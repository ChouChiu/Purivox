from __future__ import annotations

import math
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from scipy.ndimage import gaussian_filter

from shared.audio import BLOCK_FRAMES, release_mapped_pages
from shared.dsp import istft, stft
from shared.processing import CancellationToken

from .transfer import (
    TRANSFER_ORDER,
    effective_observations,
    power_transfer,
    predict_reference_spectra,
    smoothstep,
    spectral_smooth,
)

_MASK_FLOOR = 0.05
_SPECTRAL_OVERSUBTRACTION = 1.5
# A geometric mean sits at about 0.56 of the arithmetic mean for the residual's
# distribution, so the threshold is scaled up to keep the same amount of
# down-weighting as the mean-based form it replaced.
_ROBUST_SCALE = 7.0
# Frames where the reference explains most of the mixture are the ones that
# reveal how much accompaniment the transfer failed to describe.
_LEAKAGE_LOW = 0.5
_LEAKAGE_HIGH = 0.9
# Leakage cannot exceed the prediction it leaked from.
_MAX_LEAKAGE = 1.0
# A power-domain fit needs a clearly positive correlation before it is allowed
# to remove anything: unrelated music shares loudness envelopes, and this gate
# is what keeps an unrelated source from being suppressed.
_INCOHERENT_LOW = 0.15
_INCOHERENT_HIGH = 0.45
# The power-domain estimate is noisier than the coherent one, so it gets its
# own over-subtraction factor rather than borrowing the coherent path's.  It has
# not been tuned away from that value: it is kept separate because this is the
# knob to lower when the incoherent path suppresses cleanly but audibly costs
# quality, which is what it does on a badly phase-decorrelated capture.
_INCOHERENT_OVERSUBTRACTION = 1.5
# The incoherent path rides on much weaker evidence than the coherent one, so a
# single noisy cell must not be allowed to drive the mask all the way to the
# floor: that is exactly the fluctuation that is audible as musical noise.
# Capping how much of the residual power this path may claim per cell keeps
# the mask dips shallow wherever the evidence is weak, while confident cells
# still reach the same depth through the coherent stage.
_INCOHERENT_MAX_SHARE = 0.55
# Width of the single narrow smoothing pass over the finished mask, in
# (frames, bins).
_MASK_SMOOTHING = (0.75, 0.35)
# The mask ratio is formed from instantaneous per-cell powers, which forces the
# narrow Gaussian pass to absorb nearly all of their variance.  Smoothing the
# numerator and denominator in time first (sigma in frames, ~11.6 ms each at
# 44.1 kHz) removes most of that fluctuation before the ratio is taken, which
# is the dominant source of musical noise on captures whose phase has been
# destroyed.
_MASK_POWER_SMOOTH = 1.5
_SPECTRAL_CELL_BUDGET = 4_000_000
_MAX_PROCESSING_BLOCK_SECONDS = 48
_MAX_PROCESSING_WORKERS = min(5, os.cpu_count() or 1)
_MAX_PARALLEL_SPECTRAL_CELLS = 9_000_000


def _analysis_fft_size(sample_rate: int) -> int:
    target = max(0.046 * sample_rate, 1.0)
    exponent = round(math.log2(target))
    return int(np.clip(2**exponent, 512, 4096))


def _context_frames(sample_rate: int, sigma: float) -> int:
    """Frames a block must span before its smoothing context is representative."""
    return max(
        round((1.5 * float(sigma) + 4.0) * sample_rate),
        12 * sample_rate,
    )


def _processing_block_frames(
    sample_rate: int,
    sigma: float,
    spectral_cell_budget: int = _SPECTRAL_CELL_BUDGET,
) -> int:
    """Use the 2 GiB working-set budget to reduce repeated overlap analysis."""
    context_frames = _context_frames(sample_rate, sigma)
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
    context_frames = _context_frames(sample_rate, sigma)
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


def _reference_cancel(
    song: np.ndarray,
    reference: np.ndarray,
    sample_rate: int,
    strength: float,
    sigma: float,
    token: CancellationToken,
) -> np.ndarray:
    """Cancel reference-correlated content coherently, then suppress what is left.

    A real mask can only attenuate a whole time-frequency cell.  Where a live
    voice and the accompaniment share a cell - which in the vocal range is the
    normal case, not the exception - the mask has to choose between removing
    both and keeping both, so depth is always paid for with the voice.  The
    transfer estimate is a complex vector, and subtracting it removes the
    accompaniment vector from inside the cell while the live vector survives.

    This is the linear-canceller-then-residual-suppressor arrangement acoustic
    echo cancellers use.  It is not the direct residual this project removed
    earlier: that one subtracted a broadband real 2x2 matrix in the time domain
    with no per-bin projection, no confidence and no bound on the result, which
    is why a word present only in the reference ended up inverted in the output.
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

    predicted, _explained = predict_reference_spectra(
        song_spectra,
        reference_spectra,
        sigma_frames,
        token,
    )
    residual_power = np.zeros(song_spectra[0].shape, dtype=np.float32)
    for mixture_channel, predicted_channel in zip(song_spectra, predicted, strict=True):
        residual_power += np.abs(mixture_channel - predicted_channel) ** 2
    # The scale the outliers are judged against has to be one they cannot lift
    # themselves.  A smoothed arithmetic mean is dragged up by the very live
    # transients it is meant to down-weight, so take the geometric mean: the
    # same O(N) smoother, read in the log domain.
    residual_floor = 1e-10 * float(np.mean(residual_power)) + 1e-30
    local_residual = np.exp(spectral_smooth(np.log(residual_power + residual_floor), sigma_frames))
    robust_weights = np.minimum(
        1.0, _ROBUST_SCALE * local_residual / (residual_power + 1e-12)
    ).astype(np.float32)
    del residual_power, local_residual, predicted
    predicted, explained = predict_reference_spectra(
        song_spectra,
        reference_spectra,
        sigma_frames,
        token,
        robust_weights,
    )
    del robust_weights
    token.raise_if_cancelled()

    # How much of the prediction to subtract is not a free parameter.  The
    # transfer is estimated from a finite window, so its error variance is
    # about order/observations of the unexplained power, and the shrinkage that
    # minimises the mean square error of the subtraction follows from that
    # alone.  It reaches zero for a reference that explains nothing, which is
    # what keeps an unrelated reference from being subtracted at all.
    variance_ratio = TRANSFER_ORDER / effective_observations(sigma_frames, song_spectra[0].shape[0])
    alignment = np.zeros(song_spectra[0].shape, dtype=np.float32)
    predicted_power = np.zeros_like(alignment)
    for mixture_channel, predicted_channel, confidence in zip(
        song_spectra, predicted, explained, strict=True
    ):
        predicted_channel *= confidence / (confidence + variance_ratio * (1.0 - confidence) + 1e-12)
        alignment += (mixture_channel * np.conj(predicted_channel)).real
        predicted_power += np.abs(predicted_channel) ** 2
    # The linear stage may only take energy out.  Solving |y - t*d| <= |y| for t
    # gives 2*Re(y conj(d))/|d|^2 exactly, so this is the largest step that
    # cannot amplify - and because it reads the phase, it also falls to zero
    # where the prediction is orthogonal to the mixture in a cell.  Bounding
    # |e| by |y| instead leaves the residual pointing wherever the bad
    # prediction put it, merely rescaled.  The step is linked across channels
    # like the mask that follows it.
    step = np.clip(2.0 * alignment / (predicted_power + 1e-20), 0.0, 1.0).astype(np.float32)
    del alignment, predicted_power
    removable_power = np.zeros(song_spectra[0].shape, dtype=np.float32)
    residual_spectra: list[np.ndarray] = []
    for mixture_channel, predicted_channel in zip(song_spectra, predicted, strict=True):
        removed = step * predicted_channel
        residual_spectra.append(mixture_channel - removed)
        removable_power += np.abs(removed) ** 2
    del predicted, step
    token.raise_if_cancelled()

    # What survives the subtraction is not only the live source: reverberation
    # ringing past the analysis window, residual misalignment and level moves
    # all leave accompaniment behind that the narrowband transfer could not
    # describe.  Its size is measured per bin over the frames the reference
    # dominates - a stage recording supplies plenty of those between vocal
    # phrases - and the mask is asked to remove that much and no more.
    residual_power = np.zeros_like(removable_power)
    for residual in residual_spectra:
        residual_power += np.abs(residual) ** 2
    dominant = smoothstep(_LEAKAGE_LOW, _LEAKAGE_HIGH, sum(explained) / len(explained))
    leakage = np.sum(dominant * residual_power, axis=0) / (
        np.sum(dominant * removable_power, axis=0) + 1e-12
    )
    leakage = np.clip(leakage, 0.0, _MAX_LEAKAGE).astype(np.float32)
    del dominant, explained

    # Where the capture path destroyed phase, the coherent stage has nothing to
    # subtract and `removable_power` is far smaller than the accompaniment that
    # is actually present.  The power-domain fit sees that content, so the mask
    # removes whichever of the two explains more, minus what has already gone.
    reference_power = np.zeros_like(residual_power)
    for reference_channel in reference_spectra:
        reference_power += np.abs(reference_channel) ** 2
    mixture_power = np.zeros_like(residual_power)
    for mixture_channel in song_spectra:
        mixture_power += np.abs(mixture_channel) ** 2
    incoherent_power, incoherent_confidence = power_transfer(
        mixture_power, reference_power, sigma_frames
    )
    del reference_power, mixture_power, reference_spectra
    incoherent_power *= smoothstep(_INCOHERENT_LOW, _INCOHERENT_HIGH, incoherent_confidence)
    incoherent_power = np.maximum(incoherent_power - removable_power, 0.0)
    del incoherent_confidence
    # Bound the weak-evidence path so one noisy cell cannot drive the mask to
    # the floor: deep, isolated mask dips are what musical noise sounds like.
    incoherent_power = np.minimum(incoherent_power, _INCOHERENT_MAX_SHARE * residual_power)

    remaining_power = np.maximum(
        residual_power
        - _SPECTRAL_OVERSUBTRACTION * leakage[None, :] * removable_power
        - _INCOHERENT_OVERSUBTRACTION * incoherent_power,
        (_MASK_FLOOR**2) * residual_power,
    )
    del incoherent_power
    # Form the mask from powers smoothed in time rather than from instantaneous
    # per-cell powers: most of the ratio's variance is removed before it
    # reaches the mask, and the Gaussian pass below only has to catch what is
    # left.  This is what tamed the musical noise on phase-decorrelated
    # captures; the floor still bounds the ratio from below.
    mask_remaining = spectral_smooth(remaining_power, _MASK_POWER_SMOOTH, 0.0)
    mask_residual = spectral_smooth(residual_power, _MASK_POWER_SMOOTH, 0.0)
    mask = np.sqrt(np.clip(mask_remaining / (mask_residual + 1e-12), _MASK_FLOOR**2, 1.0))
    del mask_remaining, mask_residual, remaining_power, removable_power, residual_power
    # The narrow Gaussian pass catches what the power-domain smoothing left:
    # isolated-bin musical noise, without refilling tonal notches from
    # untouched neighbours.  Berouti-style signal-dependent over-subtraction, an
    # Ephraim-Malah decision-directed Wiener gain and Breithaupt cepstral gain
    # smoothing were all measured here against this line: each bought a few dB
    # on short reverberation but roughly halved fidelity on a quiet live vocal,
    # so none of them replaced it.
    mask = gaussian_filter(mask, sigma=_MASK_SMOOTHING, mode="reflect")
    np.clip(mask, _MASK_FLOOR, 1.0, out=mask)
    token.raise_if_cancelled()
    # Strength interpolates towards the fully processed spectrum.  With nothing
    # subtracted this is exactly the mask blend it replaces, 1 - a(1 - M), so
    # bypass at zero and monotonicity are unchanged.
    for index, (mixture_channel, residual) in enumerate(
        zip(song_spectra, residual_spectra, strict=True)
    ):
        residual_spectra[index] = mixture_channel + strength * (mask * residual - mixture_channel)
    del song_spectra, mask
    return np.asarray(
        [istft(channel, hop=hop, length=length) for channel in residual_spectra],
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
) -> np.ndarray:
    cancel = token or CancellationToken()
    mix = np.asarray(song, dtype=np.float32)
    accompaniment = np.asarray(reference, dtype=np.float32)
    if mix.ndim != 2 or accompaniment.ndim != 2 or sample_rate <= 0:
        raise ValueError("audio must have shape [channels, frames] and a positive sample rate")
    strength = float(np.clip(strength, 0.0, 1.0))
    length = mix.shape[1]
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
        if reference_end < end:
            # The reference ran out inside this block: pad the rest with silence.
            reference_block = np.zeros((accompaniment.shape[0], end - start), dtype=np.float32)
            if start < reference_end:
                reference_block[:, : reference_end - start] = accompaniment[:, start:reference_end]
        else:
            reference_block = accompaniment[:, start:end]
        processed = _reference_cancel(
            mix[:, start:end],
            reference_block,
            sample_rate,
            strength,
            sigma,
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
            release_mapped_pages(mix)
            release_mapped_pages(accompaniment)
            release_mapped_pages(result)
    peak = 0.0
    cleanup_block = BLOCK_FRAMES
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
