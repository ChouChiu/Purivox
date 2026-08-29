from __future__ import annotations

import math
import mmap
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from scipy.ndimage import gaussian_filter, gaussian_filter1d, uniform_filter1d

from shared.dsp import fft_frequencies, istft, stft
from shared.processing import CancellationToken

_MASK_FLOOR = 0.05
_CONFIDENCE_LOW = 0.03
_CONFIDENCE_HIGH = 0.35
_SPECTRAL_OVERSUBTRACTION = 1.5
_SPECTRAL_CELL_BUDGET = 4_000_000
_MAX_TRANSFER_GAIN = 2.0
_DEFAULT_REFERENCE_TAPS = 2
_MAX_PROCESSING_BLOCK_SECONDS = 48
_MAX_PROCESSING_WORKERS = min(5, os.cpu_count() or 1)
_MAX_PARALLEL_SPECTRAL_CELLS = 9_000_000


def _release_mapped_pages(values: np.ndarray) -> None:
    base: object = values
    mapping = None
    while isinstance(base, np.ndarray):
        mapping = getattr(base, "_mmap", mapping)
        if getattr(base, "base", None) is None:
            break
        base = base.base
    if mapping is not None:
        mapping.flush()
        if hasattr(mapping, "madvise") and hasattr(mmap, "MADV_DONTNEED"):
            mapping.madvise(mmap.MADV_DONTNEED)


def _spectral_smooth(
    values: np.ndarray,
    sigma_time: float,
    sigma_frequency: float = 1.0,
) -> np.ndarray:
    """Smooth long spectral contexts in O(N) time along the frame axis."""
    if np.iscomplexobj(values):
        return _spectral_smooth(values.real, sigma_time, sigma_frequency) + 1j * _spectral_smooth(
            values.imag,
            sigma_time,
            sigma_frequency,
        )
    window = max(round(6.0 * sigma_time), 1)
    smoothed = uniform_filter1d(values, size=window, axis=0, mode="reflect")
    if sigma_frequency > 0.0:
        smoothed = gaussian_filter1d(
            smoothed,
            sigma=sigma_frequency,
            axis=1,
            mode="reflect",
        )
    return smoothed


def _weighted_smooth(
    values: np.ndarray,
    weights: np.ndarray | None,
    sigma_time: float,
    denominator: np.ndarray | None = None,
) -> np.ndarray:
    if weights is None:
        return _spectral_smooth(values, sigma_time)
    if denominator is None:
        denominator = _spectral_smooth(weights, sigma_time) + 1e-12
    numerator = _spectral_smooth(values * weights, sigma_time)
    return numerator / denominator


def _smoothstep(low: float, high: float, values: np.ndarray) -> np.ndarray:
    scaled = np.clip((values - low) / (high - low), 0.0, 1.0)
    return scaled * scaled * (3.0 - 2.0 * scaled)


def _phantom_center_enhance(
    audio: np.ndarray,
    sample_rate: int,
    amount: float,
    open_mic_focus: bool,
    token: CancellationToken,
) -> np.ndarray:
    """Apply the confirmed Audition/PhantomCenter-style vocal enhancement."""
    mix = float(np.clip(amount, 0.0, 1.0))
    if audio.shape[0] < 2 or mix <= 0.0:
        return audio
    # Match the core path's analysis size instead of a fixed 2048/512: at
    # 96 kHz the fixed size was a 21 ms window, and the true Gaussian smoother
    # then ran with a sigma near 17 frames.
    n_fft = _analysis_fft_size(sample_rate)
    hop = n_fft // 4
    spectra = [stft(audio[channel], n_fft=n_fft, hop=hop) for channel in range(2)]
    token.raise_if_cancelled()
    left, right = spectra
    epsilon = 1e-10
    # Roughly 90 ms of temporal context at every sample rate suppresses musical
    # noise while retaining syllable attacks.
    smooth = max(0.09 * sample_rate / hop, 1.0)
    left_power = _spectral_smooth(np.abs(left) ** 2, smooth)
    right_power = _spectral_smooth(np.abs(right) ** 2, smooth)
    cross = _spectral_smooth(left * np.conj(right), smooth)
    coherence = np.clip(
        np.abs(cross) ** 2 / (left_power * right_power + epsilon),
        0.0,
        1.0,
    )
    phase_delta = np.angle(cross)
    half_delta = 0.5 * np.abs(phase_delta)
    phase_overlap = np.maximum(0.0, np.cos(half_delta) - np.sin(half_delta))
    coherence_gate = _smoothstep(0.03, 0.35, coherence)
    left_amplitude = np.sqrt(left_power)
    right_amplitude = np.sqrt(right_power)
    common_amplitude = np.minimum(left_amplitude, right_amplitude) * phase_overlap * coherence_gate
    mean_power = 0.5 * (left_power + right_power)
    center_share = np.clip(common_amplitude**2 / (mean_power + epsilon), 0.0, 1.0)
    # A quiet live mic can be buried below wide backing and crowd energy. Applying
    # the fixed side floor in those bins reduced the already weak singer by up to
    # 9 dB. Use conventional Mid as a fallback center instead of fading the whole
    # spatial stage out: this keeps a buried center vocal while still suppressing
    # wide backing in sections where nobody is singing.
    center_presence = _smoothstep(0.02, 0.18, center_share)
    center = 0.5 * (
        common_amplitude / (left_amplitude + epsilon) * np.exp(-0.5j * phase_delta) * left
        + common_amplitude / (right_amplitude + epsilon) * np.exp(0.5j * phase_delta) * right
    )
    frequencies = fft_frequencies(sample_rate, n_fft)
    vocal_band = _smoothstep(80.0, 160.0, frequencies) * (
        1.0 - _smoothstep(9_000.0, 14_000.0, frequencies)
    )
    side_floor = 0.35
    center_gain = 1.25
    fallback_center = 0.5 * (left + right)
    focused = []
    for channel in spectra:
        full_target = side_floor * channel + (center_gain - side_floor) * center
        if open_mic_focus:
            full_target += (1.0 - side_floor) * (1.0 - center_presence) * fallback_center
        target = channel + mix * (full_target - channel)
        focused.append(channel + vocal_band[None, :] * (target - channel))
    token.raise_if_cancelled()
    return np.asarray(
        [istft(channel, hop=hop, length=audio.shape[1]) for channel in focused],
        dtype=np.float32,
    )


def _analysis_fft_size(sample_rate: int) -> int:
    target = max(0.046 * sample_rate, 1.0)
    exponent = round(math.log2(target))
    return int(np.clip(2**exponent, 512, 4096))


def _processing_block_frames(
    sample_rate: int,
    sigma: float,
    spectral_cell_budget: int = _SPECTRAL_CELL_BUDGET,
) -> int:
    """Use the 2 GiB working-set budget to reduce repeated overlap analysis."""
    context_frames = max(
        round((1.5 * float(sigma) + 4.0) * sample_rate),
        12 * sample_rate,
    )
    n_fft = _analysis_fft_size(sample_rate)
    hop = n_fft // 4
    bins = n_fft // 2 + 1
    # A spectral cell expands into several complex and real work arrays.  Four
    # million cells keeps measured peak RSS below 2 GiB while allowing roughly
    # 45 seconds per block at 44.1 kHz instead of the previous 16 seconds.
    budget_stft_frames = max(spectral_cell_budget // bins, 2)
    budget_audio_frames = max((budget_stft_frames - 2) * hop, 1)
    throughput_frames = min(
        _MAX_PROCESSING_BLOCK_SECONDS * sample_rate,
        budget_audio_frames,
    )
    return max(context_frames, throughput_frames)


def _processing_workers(sample_rate: int, sigma: float, length: int) -> int:
    context_frames = max(
        round((1.5 * float(sigma) + 4.0) * sample_rate),
        12 * sample_rate,
    )
    n_fft = _analysis_fft_size(sample_rate)
    context_stft_frames = math.ceil(context_frames / (n_fft // 4)) + 2
    context_cells = context_stft_frames * (n_fft // 2 + 1)
    if length < 2 * context_frames:
        return 1
    memory_limited_workers = _MAX_PARALLEL_SPECTRAL_CELLS // context_cells
    return max(1, min(_MAX_PROCESSING_WORKERS, memory_limited_workers))


def _processing_layout(sample_rate: int, sigma: float, length: int) -> tuple[int, int]:
    workers = _processing_workers(sample_rate, sigma, length)
    block = _processing_block_frames(sample_rate, sigma, _SPECTRAL_CELL_BUDGET // workers)
    return block, workers


def _solve_hermitian(
    covariance: list[list[np.ndarray]],
    cross: list[np.ndarray],
) -> list[np.ndarray]:
    """Solve the Hermitian system R h = c for every time-frequency cell.

    `covariance` holds the lower triangle as whole [frames, bins] spectra.
    Stacking the cells into one [frames, bins, order, order] tensor and calling
    `numpy.linalg.solve` makes LAPACK run once per cell, which measured about
    seven times slower.  An LDL^H factorisation written out over the spectra
    keeps every step a single vectorised array operation and needs no square
    roots.
    """
    order = len(cross)
    lower: list[list[np.ndarray | None]] = [[None] * order for _ in range(order)]
    pivot: list[np.ndarray] = []
    for column in range(order):
        value = covariance[column][column].real.copy()
        for index in range(column):
            factor = lower[column][index]
            value -= (factor.real**2 + factor.imag**2) * pivot[index]
        pivot.append(np.maximum(value, 1e-20))
        for row in range(column + 1, order):
            entry = covariance[row][column].copy()
            for index in range(column):
                entry -= lower[row][index] * np.conj(lower[column][index]) * pivot[index]
            lower[row][column] = entry / pivot[column]
    forward: list[np.ndarray] = []
    for row in range(order):
        value = cross[row].copy()
        for index in range(row):
            value -= lower[row][index] * forward[index]
        forward.append(value)
    transfer: list[np.ndarray | None] = [None] * order
    for row in reversed(range(order)):
        value = forward[row] / pivot[row]
        for index in range(row + 1, order):
            value = value - np.conj(lower[index][row]) * transfer[index]
        transfer[row] = value
    return transfer


def _predict_reference_spectra(
    song_spectra: list[np.ndarray],
    reference_spectra: list[np.ndarray],
    sigma_frames: float,
    token: CancellationToken,
    weights: np.ndarray | None = None,
) -> list[np.ndarray]:
    """Predict reference-correlated spectra without subtracting them from the mix.

    One reference frame per channel is the multiplicative narrowband model.
    Spanning several frames instead, as a convolutive transfer function, was
    measured and removed again: it only helped for room responses shorter than
    a few hundred milliseconds, and at the 0.8-2 s a real venue rings it was
    worth nothing or slightly negative while costing 4.5-5.2x the runtime.
    """
    epsilon = 1e-12
    order = len(reference_spectra)
    denominator = None
    if weights is not None:
        denominator = _spectral_smooth(weights, sigma_frames) + 1e-12
    # The normal equations for y ~ sum_k h_k x_k are R h = c with
    # R[j][k] = E[x_k conj(x_j)] and c[j] = E[y conj(x_j)].  Filling R[j][k]
    # with E[x_j conj(x_k)] instead transposes the system and silently solves
    # for a different transfer, so only the lower triangle is built here and
    # the upper one is never needed.
    covariance: list[list[np.ndarray | None]] = [[None] * order for _ in range(order)]
    for row in range(order):
        for column in range(row + 1):
            covariance[row][column] = _weighted_smooth(
                reference_spectra[column] * np.conj(reference_spectra[row]),
                weights,
                sigma_frames,
                denominator,
            )
    loading = covariance[0][0].real.copy()
    for index in range(1, order):
        loading += covariance[index][index].real
    loading *= 2e-4 / order
    loading += epsilon
    for index in range(order):
        covariance[index][index] = covariance[index][index] + loading
    predicted: list[np.ndarray] = []
    for channel in song_spectra:
        token.raise_if_cancelled()
        cross = [
            _weighted_smooth(channel * np.conj(reference), weights, sigma_frames, denominator)
            for reference in reference_spectra
        ]
        transfer = _solve_hermitian(covariance, cross)
        row_gain = np.abs(transfer[0])
        for index in range(1, order):
            row_gain = row_gain + np.abs(transfer[index])
        gain_scale = np.minimum(1.0, _MAX_TRANSFER_GAIN / (row_gain + epsilon))
        combined = transfer[0] * reference_spectra[0]
        for index in range(1, order):
            combined = combined + transfer[index] * reference_spectra[index]
        predicted.append((gain_scale * combined).astype(np.complex64))
    return predicted


def _reference_mask_cancel(
    song: np.ndarray,
    reference: np.ndarray,
    sample_rate: int,
    strength: float,
    sigma: float,
    token: CancellationToken,
) -> np.ndarray:
    """Cancel reference-correlated content with a confidence-weighted soft mask.

    The estimated complex reference transfer is used only to model accompaniment
    power. Reconstruction always multiplies the original mixture spectra by a
    linked real mask, so this path performs no waveform or complex-spectrum
    polarity subtraction.
    """
    length = min(song.shape[1], reference.shape[1])
    mix = np.asarray(song[:, :length], dtype=np.float32)
    accompaniment = np.asarray(reference[:, :length], dtype=np.float32)
    n_fft = _analysis_fft_size(sample_rate)
    hop = n_fft // 4
    song_spectra = [stft(channel, n_fft=n_fft, hop=hop) for channel in mix]
    token.raise_if_cancelled()
    reference_spectra = [stft(channel, n_fft=n_fft, hop=hop) for channel in accompaniment[:2]]
    if not reference_spectra:
        return mix.copy()
    if len(reference_spectra) == 1:
        reference_spectra.append(reference_spectra[0])
    sigma_frames = max(float(sigma) * sample_rate / hop / 6.0, 1.0)

    predicted = _predict_reference_spectra(
        song_spectra,
        reference_spectra,
        sigma_frames,
        token,
    )
    residual_power = np.zeros(song_spectra[0].shape, dtype=np.float32)
    for mixture_channel, predicted_channel in zip(song_spectra, predicted, strict=True):
        residual_power += np.abs(mixture_channel - predicted_channel) ** 2
    local_residual = _spectral_smooth(residual_power, sigma_frames)
    robust_weights = np.minimum(1.0, 4.0 * local_residual / (residual_power + 1e-12)).astype(
        np.float32
    )
    predicted = _predict_reference_spectra(
        song_spectra,
        reference_spectra,
        sigma_frames,
        token,
        robust_weights,
    )
    token.raise_if_cancelled()

    mixture_power = np.zeros(song_spectra[0].shape, dtype=np.float32)
    removable_power = np.zeros_like(mixture_power)
    confidence_sigma = max(sigma_frames / 2.0, 1.0)
    for mixture_channel, predicted_channel in zip(song_spectra, predicted, strict=True):
        channel_power = np.abs(mixture_channel) ** 2
        reference_power = np.abs(predicted_channel) ** 2
        smoothed_mix = _spectral_smooth(channel_power, confidence_sigma)
        smoothed_reference = _spectral_smooth(reference_power, confidence_sigma)
        cross = _spectral_smooth(
            mixture_channel * np.conj(predicted_channel),
            confidence_sigma,
        )
        coherence = np.clip(
            np.abs(cross) ** 2 / (smoothed_mix * smoothed_reference + 1e-12),
            0.0,
            1.0,
        )
        confidence = _smoothstep(_CONFIDENCE_LOW, _CONFIDENCE_HIGH, coherence)
        mixture_power += channel_power
        removable_power += confidence * reference_power

    remaining_power = np.maximum(
        mixture_power - _SPECTRAL_OVERSUBTRACTION * removable_power,
        (_MASK_FLOOR**2) * mixture_power,
    )
    mask = np.sqrt(np.clip(remaining_power / (mixture_power + 1e-12), _MASK_FLOOR**2, 1.0))
    # A single narrow smoothing pass prevents isolated-bin musical noise without
    # refilling tonal notches from untouched neighbours.  Berouti-style
    # signal-dependent over-subtraction, an Ephraim-Malah decision-directed
    # Wiener gain and Breithaupt cepstral gain smoothing were all measured here
    # against this line: each bought a few dB on short reverberation but roughly
    # halved fidelity on a quiet live vocal, so none of them replaced it.
    mask = gaussian_filter(mask, sigma=(0.75, 0.35), mode="reflect")
    effective_mask = 1.0 - strength * (1.0 - np.clip(mask, _MASK_FLOOR, 1.0))
    token.raise_if_cancelled()
    return np.asarray(
        [istft(channel * effective_mask, hop=hop, length=length) for channel in song_spectra],
        dtype=np.float32,
    )


def process_audio(
    song: np.ndarray,
    reference: np.ndarray,
    sample_rate: int,
    strength: float,
    sigma: float,
    token: CancellationToken | None = None,
    output: np.ndarray | None = None,
    *,
    center_extraction: bool = False,
    open_mic_focus: bool = False,
) -> np.ndarray:
    cancel = token or CancellationToken()
    mix = np.asarray(song, dtype=np.float32)
    accompaniment = np.asarray(reference, dtype=np.float32)
    if mix.ndim != 2 or accompaniment.ndim != 2 or sample_rate <= 0:
        raise ValueError("audio must have shape [channels, frames] and a positive sample rate")
    strength = float(np.clip(strength, 0.0, 1.0))
    length = mix.shape[1]
    mix = mix[:, :length]
    if output is None:
        result = np.empty((mix.shape[0], length), dtype=np.float32)
    else:
        if output.shape != (mix.shape[0], length) or output.dtype != np.float32:
            raise ValueError("output must be a float32 [channels, frames] array")
        result = output
    if strength == 0:
        result[:] = mix
        return result
    # Long recordings scale across independent spectral workers.  The layout
    # divides the working-set budget; large contexts automatically use fewer.
    block, workers = _processing_layout(sample_rate, sigma, length)
    overlap = min(
        max(round(0.5 * float(sigma) * sample_rate), 2 * sample_rate),
        block // 3,
    )
    step = block - overlap
    starts = list(range(0, length, step))

    def process_block(index: int, start: int) -> tuple[int, int, int, np.ndarray]:
        cancel.raise_if_cancelled()
        end = min(start + block, length)
        reference_end = min(end, accompaniment.shape[1])
        if start >= reference_end:
            reference_block = np.zeros(
                (accompaniment.shape[0], end - start),
                dtype=np.float32,
            )
        elif reference_end < end:
            reference_block = np.zeros(
                (accompaniment.shape[0], end - start),
                dtype=np.float32,
            )
            reference_block[:, : reference_end - start] = accompaniment[:, start:reference_end]
        else:
            reference_block = accompaniment[:, start:end]
        processed = _reference_mask_cancel(
            mix[:, start:end],
            reference_block,
            sample_rate,
            strength,
            sigma,
            cancel,
        )
        if center_extraction:
            # Preserve the confirmed 75% enhancement sound while making the
            # strength slider continuous near bypass. Above 75%, only the core
            # extractor becomes stronger instead of narrowing the image further.
            center_amount = min(strength / 0.75, 1.0)
            processed = _phantom_center_enhance(
                processed,
                sample_rate,
                center_amount,
                open_mic_focus,
                cancel,
            )
        return index, start, end, processed

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="purivox-dsp") as executor:
        indexed_starts = list(enumerate(starts))
        for batch_start in range(0, len(indexed_starts), workers):
            batch = indexed_starts[batch_start : batch_start + workers]
            futures = [executor.submit(process_block, index, start) for index, start in batch]
            for future in futures:
                index, start, end, processed = future.result()
                fade = min(overlap, end - start) if index > 0 else 0
                if fade:
                    phase = np.linspace(0, np.pi / 2, fade, dtype=np.float32)
                    old_weight = np.cos(phase) ** 2
                    new_weight = np.sin(phase) ** 2
                    result[:, start : start + fade] = (
                        result[:, start : start + fade] * old_weight
                        + processed[:, :fade] * new_weight
                    )
                result[:, start + fade : end] = processed[:, fade : end - start]
            _release_mapped_pages(mix)
            _release_mapped_pages(accompaniment)
            _release_mapped_pages(result)
    peak = 0.0
    cleanup_block = 262_144
    for start in range(0, length, cleanup_block):
        view = result[:, start : start + cleanup_block]
        np.nan_to_num(view, copy=False)
        peak = max(peak, float(np.max(np.abs(view), initial=0.0)))
    peak_ceiling = 10 ** (-1.0 / 20.0)
    if peak > peak_ceiling:
        scale = peak_ceiling / peak
        for start in range(0, length, cleanup_block):
            result[:, start : start + cleanup_block] *= scale
    return result
