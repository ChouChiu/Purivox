from __future__ import annotations

import logging
import math
from functools import lru_cache

import numpy as np
import soxr
from scipy.fft import irfft, rfft
from scipy.ndimage import median_filter
from scipy.signal import correlate, correlation_lags, resample_poly

from shared.audio import BLOCK_FRAMES
from shared.dsp import log_flux_bands
from shared.dsp.rate import estimate_rate
from shared.dsp.stretch import time_stretch
from shared.processing import CancellationToken

logger = logging.getLogger(__name__)

# The proxy's bandwidth, not its sample grid, sets how precisely a local lag
# can be resolved.  Measured end to end on a drifting broadband reference,
# raising this from 2 kHz lifted cancellation depth by roughly 10 dB while
# alignment runtime stayed flat, because the tracking loop still steps once
# every 0.1 s.  Admitting more live-only content (vocals, cymbals) into the
# correlation did not offset that: the same sweep improved monotonically even
# with a loud broadband live source present only in the stage mix.
_PROXY_RATE = 16000
# The rate search works on a coarser proxy than the lag track: its grid is the
# feature hop, not the sample, and 4 kHz measured both cheaper and no less
# accurate than 16 kHz across the ratios it has to cover.
_RATE_PROXY_RATE = 4000
# The ratio is one constant per source, so the search only needs enough of it
# for the peak to stand out: the first two minutes measured the same ratios as
# the whole take, and everything past them is a longer resample and a longer
# correlation for no sharper an answer.
_RATE_SEARCH_SECONDS = 120.0
_LANCZOS_RADIUS = 3
# 8192 fractional phases keep the table's quantisation error near -80 dBFS,
# far below the residual that reference cancellation can reach in practice.
_LANCZOS_PHASES = 8192
# Below this median band scale a channel carries no usable attacks at all.
_MINIMUM_FLUX_SCALE = 1e-4


def _mono(channels: np.ndarray) -> np.ndarray:
    # `mean` accumulates in float64 without first materialising a float64 copy
    # of the input, which for a long take is the same size as the take.
    return np.asarray(channels).mean(axis=0, dtype=np.float64)


def _proxy(channels: np.ndarray, length: int, source_rate: int, target_rate: int) -> np.ndarray:
    """Create an anti-aliased low-rate proxy for long-range alignment.

    Plain strided sampling folds high-frequency vocals, cymbals and crowd noise
    into the reference band.  A high-quality resampler keeps those unrelated
    components from steering the local lag track and gives the proxy an exact
    rate, so proxy positions map back to source samples without clock error.
    soxr is the resampler the audio path already uses, and it measured about 7%
    off the alignment phase; its group delay differs from a polyphase filter's
    by a constant, which the per-bin complex transfer absorbs as a phase ramp.
    """
    # Resampling and the channel mean are both linear and act on different
    # axes, so averaging first builds the same proxy for half the work:
    # measured 1.47x faster with a maximum relative difference of 4e-7.
    mono = np.asarray(channels[:, :length], dtype=np.float32).mean(axis=0, dtype=np.float64)
    return soxr.resample(mono, source_rate, target_rate, quality="HQ")


def _normalize(values: np.ndarray) -> np.ndarray | None:
    centered = values - np.mean(values)
    scale = np.std(centered)
    if not np.isfinite(scale) or scale < 1e-8:
        return None
    return centered / scale


def _parabolic_offset(scores: np.ndarray, index: int) -> float:
    """Refine a discrete correlation peak to sub-sample resolution."""
    if not 0 < index < scores.size - 1:
        return 0.0
    left, center, right = scores[index - 1 : index + 2]
    denominator = left - 2 * center + right
    if abs(denominator) <= 1e-12:
        return 0.0
    return float(np.clip(0.5 * (left - right) / denominator, -1.0, 1.0))


def _gcc_phat_lag(mix: np.ndarray, reference: np.ndarray, max_lag: int) -> float | None:
    size = 1 << int(np.ceil(np.log2(mix.size + reference.size - 1)))
    mix_fft = rfft(mix, size)
    reference_fft = rfft(reference, size)
    cross = mix_fft * np.conj(reference_fft)
    magnitude = np.abs(cross)
    valid = magnitude > np.finfo(np.float64).eps
    if not np.any(valid):
        return None
    cross[valid] /= magnitude[valid]
    cross[~valid] = 0
    correlation = irfft(cross, size)
    correlation = np.concatenate((correlation[-max_lag:], correlation[: max_lag + 1]))
    score = np.abs(correlation)
    index = int(np.argmax(score))
    peak = float(score[index])
    if not np.isfinite(peak) or peak < 1e-5:
        return None
    return float(index - max_lag) + _parabolic_offset(score, index)


def _raw_lag(mix: np.ndarray, reference: np.ndarray, max_lag: int) -> float | None:
    raw = correlate(mix, reference, mode="full", method="fft")
    lags = correlation_lags(mix.size, reference.size)
    valid = np.abs(lags) <= max_lag
    score = np.abs(raw)
    if not np.any(valid) or np.max(score[valid]) <= 1e-5:
        return None
    indices = np.flatnonzero(valid)
    index = int(indices[np.argmax(score[valid])])
    return float(lags[index]) + _parabolic_offset(score, index)


def _spectral_flux_lag(
    mix: np.ndarray,
    reference: np.ndarray,
    sample_rate: int,
    max_lag_seconds: float = 20.0,
) -> float | None:
    """Estimate musical offset when two masters have weak waveform coherence.

    Live camera audio and the released master can share note attacks while their
    waveforms, EQ, compression, vocals and ambience are substantially different.
    Positive log-spectral flux retains those common attacks and ignores polarity.
    A separated runner-up check prevents an unrelated reference from producing a
    confident-looking offset merely because a long correlation was searched.
    """
    feature_rate = min(8000, sample_rate)
    common = min(mix.shape[1], reference.shape[1], sample_rate * 60)
    if common < max(sample_rate // 2, 2048):
        return None

    def extract(channels: np.ndarray) -> np.ndarray | None:
        divisor = math.gcd(sample_rate, feature_rate)
        values = resample_poly(
            np.asarray(channels[:, :common], dtype=np.float32),
            feature_rate // divisor,
            sample_rate // divisor,
            axis=1,
        )
        n_fft = min(1024, values.shape[1])
        hop = max(round(0.02 * feature_rate), 1)
        channel_features: list[np.ndarray] = []
        for channel in values[:2]:
            # A featureless channel would scale numerical noise up to full range
            # and invent attacks, so a flat band set rejects the whole estimate.
            bands = log_flux_bands(channel, n_fft, hop, minimum_scale=_MINIMUM_FLUX_SCALE)
            if bands is None:
                return None
            channel_features.append(bands)
        return np.concatenate(channel_features, axis=0)

    mix_features = extract(mix)
    reference_features = extract(reference)
    if mix_features is None or reference_features is None:
        return None
    scores = None
    for mix_band, reference_band in zip(mix_features, reference_features, strict=True):
        correlation = correlate(mix_band, reference_band, mode="full", method="fft")
        scores = correlation if scores is None else scores + correlation
    lags = correlation_lags(mix_features.shape[1], reference_features.shape[1])
    hop_seconds = max(round(0.02 * feature_rate), 1) / feature_rate
    valid = np.abs(lags) <= round(max_lag_seconds / hop_seconds)
    valid_lags = lags[valid]
    valid_scores = scores[valid]
    best = int(np.argmax(valid_scores))
    peak = float(valid_scores[best])
    separation = max(round(0.4 / hop_seconds), 1)
    competing = np.abs(valid_lags - valid_lags[best]) > separation
    runner_up = float(np.max(valid_scores[competing], initial=0.0))
    if not np.isfinite(peak) or peak <= 0.0 or peak < 1.08 * max(runner_up, 1e-12):
        return None
    return float(valid_lags[best] * hop_seconds * sample_rate)


def _sliding_energy(values: np.ndarray, window: int) -> np.ndarray:
    """Energy of every length-`window` slice, in O(N) instead of O(N*window)."""
    cumulative = np.cumsum(np.concatenate(([0.0], values * values)))
    return cumulative[window:] - cumulative[:-window]


def _local_track(mix: np.ndarray, reference: np.ndarray, rate: int, initial: float):
    step = max(rate // 10, 1)
    half_window = max(rate // 20, 1)
    search = max(rate // 16, 2)
    positions = [0.0]
    lags = [initial]
    predicted = initial
    for center in range(half_window, min(mix.size, reference.size), step):
        begin = max(center - half_window, 0)
        end = min(center + half_window, mix.size)
        segment = mix[begin:end]
        low = max(0, round(begin - predicted - search))
        high = min(reference.size, round(end - predicted + search))
        candidate = reference[low:high]
        if segment.size < 64 or candidate.size < segment.size:
            continue
        scores = correlate(candidate, segment, mode="valid", method="fft")
        denominator = np.linalg.norm(segment) * np.sqrt(_sliding_energy(candidate, segment.size))
        similarities = np.abs(np.divide(scores, denominator + 1e-12))
        candidate_lags = begin - (low + np.arange(scores.size))
        ranked = similarities - 0.25 * np.abs(candidate_lags - predicted) / max(search, 1)
        best = int(np.argmax(ranked))
        best_corr = float(similarities[best])
        # The lag deliberately stays on the proxy grid.  Refining it to
        # sub-sample resolution was measured to *reduce* cancellation depth: a
        # constant fractional delay is already absorbed by the per-bin complex
        # transfer as a phase ramp, so the refinement adds per-window noise to
        # the lag curve without removing any error the mask cares about.
        lag = float(candidate_lags[best])
        predicted_index = int(np.argmin(np.abs(candidate_lags - predicted)))
        predicted_corr = float(similarities[predicted_index])
        if best_corr < 0.08 or best_corr < predicted_corr + 0.02:
            lag = predicted
        max_change = max(2.0, 0.02 * (center - positions[-1]))
        lag = float(np.clip(lag, predicted - max_change, predicted + max_change))
        positions.append(float(center))
        lags.append(lag)
        predicted = lag
    if len(lags) >= 3:
        lags = median_filter(np.asarray(lags), size=3, mode="nearest").tolist()
    positions.append(float(mix.size - 1))
    lags.append(lags[-1])
    return np.asarray(positions), np.asarray(lags)


@lru_cache(maxsize=4)
def _lanczos_table(radius: int, phases: int) -> tuple[np.ndarray, np.ndarray]:
    """Precompute Lanczos taps for every fractional phase, and what they sum to.

    The kernel depends only on the fractional part of the source position, so
    evaluating `sinc` per output sample repeats the same few thousand values
    millions of times over a long recording.  The per-phase weight sum travels
    with the taps because the interior path divides by it directly instead of
    reducing a masked copy of the whole block.
    """
    offsets = np.arange(-radius + 1, radius + 1, dtype=np.float64)
    fractions = np.arange(phases, dtype=np.float64) / phases
    distance = fractions[:, None] - offsets[None, :]
    weights = np.sinc(distance) * np.sinc(distance / radius)
    weights[np.abs(distance) >= radius] = 0.0
    return weights, weights.sum(axis=1)


@lru_cache(maxsize=4)
def _lanczos_single(radius: int, phases: int) -> tuple[np.ndarray, np.ndarray]:
    """The same taps in single precision, for the interior of a block.

    The interior accumulates six taps of a float32 recording, so carrying the
    arithmetic in float64 there spends twice the memory traffic on precision
    the source never had.  Measured 8.4 -> 6.5 ms per block with a maximum
    difference of 7.3e-7, about 40 dB below the -80 dBFS the phase table
    itself is quantised to.  The boundary path keeps the float64 table.
    """
    weights, row_sums = _lanczos_table(radius, phases)
    return weights.astype(np.float32), row_sums.astype(np.float32)


def _lanczos(values: np.ndarray, source: np.ndarray, radius: int = _LANCZOS_RADIUS) -> np.ndarray:
    base = np.floor(source)
    phase = np.minimum(
        ((source - base) * _LANCZOS_PHASES).astype(np.int64),
        _LANCZOS_PHASES - 1,
    )
    base_index = base.astype(np.int64)
    taps = np.arange(-radius + 1, radius + 1)
    # A block whose every sample sits at least `radius` from either end of the
    # recording needs no boundary handling at all.  The masked formulation
    # below builds a [samples, taps] index matrix, masks it, clips it and
    # reduces it; accumulating one tap at a time over the interior measured
    # about twice as fast, and the interior is where nearly every block is.
    interior = (base_index >= radius - 1) & (base_index <= values.size - 1 - radius)
    if interior.all():
        table, row_sums = _lanczos_single(radius, _LANCZOS_PHASES)
        numerator = np.zeros(source.size, dtype=np.float32)
        for tap in taps:
            numerator += values[base_index + tap] * table[phase, tap + radius - 1]
        denominator = row_sums[phase]
        return np.divide(
            numerator,
            denominator,
            out=np.zeros(source.size, dtype=np.float64),
            where=np.abs(denominator) > 1e-12,
        )
    table, _row_sums = _lanczos_table(radius, _LANCZOS_PHASES)
    weights = table[phase]
    indices = base_index[:, None] + taps
    weights = weights * ((indices >= 0) & (indices < values.size))
    safe_indices = np.clip(indices, 0, max(values.size - 1, 0))
    denominator = np.sum(weights, axis=1)
    return np.divide(
        np.sum(values[safe_indices] * weights, axis=1),
        denominator,
        out=np.zeros(source.size, dtype=np.float64),
        where=np.abs(denominator) > 1e-12,
    )


def _warp(
    reference: np.ndarray,
    positions: np.ndarray,
    lags: np.ndarray,
    length: int,
    token: CancellationToken,
    output: np.ndarray | None,
):
    result = output if output is not None else np.empty((reference.shape[0], length), np.float32)
    if result.shape != (reference.shape[0], length) or result.dtype != np.float32:
        raise ValueError("alignment output must be a float32 [channels, frames] array")
    block_size = BLOCK_FRAMES
    for start in range(0, length, block_size):
        token.raise_if_cancelled()
        end = min(start + block_size, length)
        destination = np.arange(start, end, dtype=np.float64)
        lag_curve = np.interp(destination, positions, lags)
        source = destination - lag_curve
        for channel, values in enumerate(reference):
            result[channel, start:end] = _lanczos(values, source)
    return result


def _rate_corrected(
    mix: np.ndarray,
    reference_audio: np.ndarray,
    sample_rate: int,
    token: CancellationToken,
) -> np.ndarray:
    """Stretch the reference onto the stage recording's tempo when it was uploaded shifted.

    A stage recording whose playback speed was changed carries the same music at
    a different tempo and an unchanged pitch, which the local drift tracker
    cannot follow: its step limit is 2% of elapsed time, so a 3% shift leaves it
    behind for the whole take.  Recovering the ratio once and stretching the
    reference removes the part that is a constant before the tracker sees it.
    """
    common = min(mix.shape[1], reference_audio.shape[1], round(sample_rate * _RATE_SEARCH_SECONDS))
    rate_proxy = min(_RATE_PROXY_RATE, sample_rate)
    estimate = estimate_rate(
        _proxy(mix, common, sample_rate, rate_proxy),
        _proxy(reference_audio, common, sample_rate, rate_proxy),
        rate_proxy,
        token,
    )
    if estimate is None or not estimate.reliable:
        return reference_audio
    logger.info(
        "stretching the reference by %.4f to match the stage tempo (score %.3f, improvement %.3f)",
        estimate.ratio,
        estimate.score,
        estimate.improvement,
    )
    return time_stretch(reference_audio, sample_rate, estimate.ratio, token)


def align_audio(
    mix: np.ndarray,
    reference: np.ndarray,
    sample_rate: int,
    token: CancellationToken | None = None,
    output: np.ndarray | None = None,
    detect_speed: bool = True,
) -> np.ndarray:
    cancel = token or CancellationToken()
    mix = np.asarray(mix, dtype=np.float32)
    reference_audio = np.asarray(reference, dtype=np.float32)
    if mix.ndim != 2 or reference_audio.ndim != 2 or sample_rate <= 0:
        return reference_audio
    cancel.raise_if_cancelled()
    common = min(mix.shape[1], reference_audio.shape[1])
    if common < 64:
        return reference_audio
    if detect_speed:
        reference_audio = _rate_corrected(mix, reference_audio, sample_rate, cancel)
        common = min(mix.shape[1], reference_audio.shape[1])
        if common < 64:
            return reference_audio
    proxy_rate = min(_PROXY_RATE, sample_rate)
    mix_proxy = _proxy(mix, common, sample_rate, proxy_rate)
    ref_proxy = _proxy(reference_audio, common, sample_rate, proxy_rate)
    mix_norm = _normalize(mix_proxy)
    ref_norm = _normalize(ref_proxy)
    if mix_norm is None or ref_norm is None:
        return reference_audio
    full_check = min(common, sample_rate * 8)
    full_mix = _normalize(_mono(mix[:, :full_check]))
    full_reference = _normalize(_mono(reference_audio[:, :full_check]))
    if full_mix is None or full_reference is None:
        return reference_audio
    max_lag = min(sample_rate * 20, full_check - 1)
    near_limit = min(sample_rate // 2, max_lag)
    lag_samples = _spectral_flux_lag(mix, reference_audio, sample_rate)
    if lag_samples is not None:
        logger.info(
            "spectral-flux coarse alignment selected %.1f samples (%.3f s)",
            lag_samples,
            lag_samples / sample_rate,
        )
    else:
        lag_samples = _gcc_phat_lag(full_mix[:full_check], full_reference[:full_check], near_limit)
        if lag_samples is not None and abs(lag_samples) >= 0.95 * near_limit:
            lag_samples = _gcc_phat_lag(full_mix[:full_check], full_reference[:full_check], max_lag)
    if lag_samples is None:
        lag_samples = _raw_lag(full_mix[:full_check], full_reference[:full_check], max_lag)
    if lag_samples is None:
        return reference_audio
    scale = sample_rate / proxy_rate
    positions, lags = _local_track(mix_norm, ref_norm, proxy_rate, lag_samples / scale)
    logger.info(
        "local alignment tracked %.3f to %.3f s (median %.3f s)",
        float(lags[0] / proxy_rate),
        float(lags[-1] / proxy_rate),
        float(np.median(lags) / proxy_rate),
    )
    cancel.raise_if_cancelled()
    return _warp(
        reference_audio,
        positions * scale,
        lags * scale,
        mix.shape[1],
        cancel,
        output,
    )
