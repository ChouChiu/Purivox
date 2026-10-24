from __future__ import annotations

import logging
import math
from functools import lru_cache

import numpy as np
import soxr
from scipy.fft import irfft, rfft
from scipy.ndimage import correlate1d, median_filter
from scipy.signal import correlate, correlation_lags, resample_poly

from shared.audio import BLOCK_FRAMES
from shared.dsp import log_flux_bands, stft
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
# A window whose best normalised correlation is below this found nothing.
_TRACK_MINIMUM_CORRELATION = 0.08
# Gaussian width of the fit through the track's sub-sample peaks.  A device
# clock moves the lag by microseconds per second, so a wide fit loses nothing;
# measured on 0-150 ppm drift at 44.1 kHz, 3 s beat 1.5 s above 4 kHz.
_TRACK_SMOOTHING_SECONDS = 3.0
_TRACK_ROBUST_PASSES = 3
# The narrowband score's excerpts: long enough for a per-bin fit to average
# over phrases, few enough that scoring a candidate stays a few milliseconds.
_SCORE_EXCERPT_SECONDS = 6.0
_SCORE_EXCERPTS = 8
# Shorter than the canceller's ~46 ms window, so the score also prefers the
# lag that centres two arrivals in it.  Measured on a two-path fancam: at 64 ms
# the line settled on the stronger path and left 1-2.7 dB more backing above
# 2 kHz than at 32 ms, where it sat between them; 16 ms bought nothing more.
_SCORE_FFT_SECONDS = 0.032
# The line candidate searches each excerpt this far either side of the track.
# Its step is half the score's hop, ~4 ms: the score falls off over tens of
# milliseconds, so the step only has to land on the slope of its peak for the
# parabola to find it.
_LINE_SEARCH_SECONDS = 0.048
_LINE_EXCERPT_SPACING_SECONDS = 10.0
# A line is two numbers; past a dozen points a longer take only costs time.
_LINE_MAXIMUM_EXCERPTS = 12
_LINE_MINIMUM_EXCERPTS = 3
# The track stays unless the line explains clearly more: on a clean broadcast
# the two score within a few percent of each other, and the track is what
# follows a clock that wanders.
_LINE_RELATIVE_MARGIN = 1.02
_LINE_ABSOLUTE_MARGIN = 0.002


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


def _local_linear(
    values: np.ndarray, weights: np.ndarray, width: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Weighted Gaussian local-linear fit on a uniform grid: level, slope, support.

    The moments about every point are correlations with the kernel times a power
    of the offset, so the fit is five filter passes instead of one regression
    per point.
    """
    radius = max(round(4.0 * width), 1)
    offsets = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (offsets / width) ** 2)

    def moment(signal: np.ndarray, power: int) -> np.ndarray:
        return correlate1d(signal, kernel * offsets**power, mode="constant")

    weighted = weights * values
    s0, s1, s2 = (moment(weights, power) for power in range(3))
    b0, b1 = moment(weighted, 0), moment(weighted, 1)
    supported = s0 > 1e-3
    determinant = s0 * s2 - s1 * s1
    # One-sided or single-point support has no slope to fit: hold the level.
    linear = supported & (determinant > 1e-6 * s0 * s2)
    safe_determinant = np.where(linear, determinant, 1.0)
    safe_s0 = np.where(supported, s0, 1.0)
    level = np.where(linear, (s2 * b0 - s1 * b1) / safe_determinant, b0 / safe_s0)
    slope = np.where(linear, (s0 * b1 - s1 * b0) / safe_determinant, 0.0)
    return level, slope, supported


def _fit_track(
    peaks: np.ndarray, confidence: np.ndarray, width: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fit a smooth lag curve through per-window peaks, ignoring the ones that jumped.

    Bisquare passes, as in LOWESS: a window of tonal content can lock onto a
    periodic peak a whole pitch period away, and the fit must not bend to it.
    """
    weights = confidence.copy()
    trusted = confidence > 0.0
    for _ in range(_TRACK_ROBUST_PASSES):
        level, _slope, supported = _local_linear(peaks, weights, width)
        residual = peaks - level
        judged = trusted & supported
        if not judged.any():
            break
        scale = max(6.0 * float(np.median(np.abs(residual[judged]))), 1.0)
        bounded = np.clip(residual / scale, -1.0, 1.0)
        weights = confidence * (1.0 - bounded * bounded) ** 2
    return _local_linear(peaks, weights, width)


def _local_track(mix: np.ndarray, reference: np.ndarray, rate: int, initial: float):
    """Track the lag every 0.1 s, then fit a sub-sample curve through the peaks.

    The search runs on the proxy grid and only has to find the peak.  The curve
    the warp follows comes from those peaks' sub-sample positions instead: a
    device clock moves the lag by a fraction of a proxy sample per second, which
    the grid follows in whole-sample steps that the hysteresis below holds back
    until the next sample is clearly better - measured at 8-14 samples of lag
    error at 44.1 kHz.  One window's refinement is noise on its own, which is
    why refining the grid in place measured worse than the grid; the fit
    averages that noise away.  It also recovers the opening, where the slew
    limit holds the grid back from a coarse lag that is one feature hop out
    while the windows already see the right peak.
    """
    step = max(rate // 10, 1)
    half_window = max(rate // 20, 1)
    search = max(rate // 16, 2)
    centers = range(half_window, min(mix.size, reference.size), step)
    peaks = np.zeros(len(centers))
    confidence = np.zeros(len(centers))
    tracked: list[int] = []
    positions = [0.0]
    lags = [initial]
    predicted = initial
    for index, center in enumerate(centers):
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
        lag = float(candidate_lags[best])
        # Candidate lags fall as the index rises, hence the minus.
        peaks[index] = lag - _parabolic_offset(similarities, best)
        if best_corr >= _TRACK_MINIMUM_CORRELATION:
            confidence[index] = best_corr * best_corr
        predicted_index = int(np.argmin(np.abs(candidate_lags - predicted)))
        predicted_corr = float(similarities[predicted_index])
        if best_corr < _TRACK_MINIMUM_CORRELATION or best_corr < predicted_corr + 0.02:
            lag = predicted
        max_change = max(2.0, 0.02 * (center - positions[-1]))
        lag = float(np.clip(lag, predicted - max_change, predicted + max_change))
        positions.append(float(center))
        lags.append(lag)
        tracked.append(index)
        predicted = lag
    if len(lags) >= 3:
        lags = median_filter(np.asarray(lags), size=3, mode="nearest").tolist()
    positions.append(float(mix.size - 1))
    lags.append(lags[-1])
    if len(tracked) >= 4:
        width = _TRACK_SMOOTHING_SECONDS * rate / step
        level, slope, supported = _fit_track(peaks, confidence, width)
        # The two ends lie off the grid and take the fit's local slope out to them.
        at = np.asarray([0, *tracked, tracked[-1]])
        offset = np.zeros(at.size)
        offset[0] = -half_window / step
        offset[-1] = (positions[-1] - centers[tracked[-1]]) / step
        fitted = level[at] + slope[at] * offset
        lags = np.where(supported[at], fitted, lags).tolist()
    return np.asarray(positions), np.asarray(lags)


def _explained_share(
    mix: np.ndarray,
    reference: np.ndarray,
    rate: int,
    track: tuple[np.ndarray, np.ndarray] | None = None,
) -> float:
    """Share of a mono proxy that one complex gain per bin explains, per excerpt.

    This is what the canceller can take: it fits a transfer per bin over a
    window of frames, so a constant lag error well inside the analysis window
    only costs it a phase ramp, while a lag that moves inside the window costs
    it the coherence itself.  A broadband time-domain fit cannot tell the two
    apart - on a fancam whose playback arrived over two PA paths it scored the
    wandering track and the matcher's position at 0.0007 and 0.0011 - and
    neither can a short correlation window, which is what wandered.
    """
    length = min(mix.size, reference.size)
    n_fft = 1 << max(round(math.log2(_SCORE_FFT_SECONDS * rate)), 6)
    excerpt = min(round(_SCORE_EXCERPT_SECONDS * rate), length)
    if excerpt < 2 * n_fft:
        return 0.0
    count = min(_SCORE_EXCERPTS, max(length // excerpt, 1))
    scores = []
    for start in np.linspace(0, length - excerpt, count, dtype=np.int64):
        if track is None:
            placed = reference[start : start + excerpt]
        else:
            # Only the excerpts are scored, so only they are warped: the whole
            # proxy twice over measured 0.23 s of a 180 s take.
            destination = np.arange(start, start + excerpt, dtype=np.float64)
            placed = _lanczos(reference, destination - np.interp(destination, *track))
        scores.append(_excerpt_share(mix[start : start + excerpt], placed, n_fft))
    return float(np.median(scores))


def _excerpt_share(mix: np.ndarray, reference: np.ndarray, n_fft: int) -> float:
    hop = n_fft // 4
    return _spectral_share(
        stft(np.asarray(mix, dtype=np.float64), n_fft=n_fft, hop=hop),
        stft(np.asarray(reference, dtype=np.float64), n_fft=n_fft, hop=hop),
    )


def _spectral_share(mix_spectrum: np.ndarray, reference_spectrum: np.ndarray) -> float:
    return _share(
        np.einsum("fb,fb->b", np.conj(mix_spectrum), reference_spectrum),
        np.sum(reference_spectrum.real**2 + reference_spectrum.imag**2, axis=0),
        float(np.vdot(mix_spectrum, mix_spectrum).real),
    )


def _share(cross: np.ndarray, reference_power: np.ndarray, mix_energy: float) -> float:
    """Explained power over mixture power, from one excerpt's per-bin sums."""
    if mix_energy <= 1e-20:
        return 0.0
    # The same relative loading the transfer solve uses, so a bin where the
    # reference is silent cannot claim the mixture through a huge gain.
    loading = 2e-4 * float(np.mean(reference_power)) + 1e-20
    return float(np.sum(np.abs(cross) ** 2 / (reference_power + loading)) / mix_energy)


def alignment_score(mix: np.ndarray, reference: np.ndarray, sample_rate: int) -> float:
    """How much of the stage an aligned stereo reference explains, bin by bin."""
    length = min(mix.shape[1], reference.shape[1])
    rate = min(_PROXY_RATE, sample_rate)
    if length < 64:
        return 0.0
    return _explained_share(
        _proxy(mix, length, sample_rate, rate), _proxy(reference, length, sample_rate, rate), rate
    )


def _line_track(
    mix: np.ndarray, reference: np.ndarray, rate: int, positions: np.ndarray, lags: np.ndarray
) -> tuple[np.ndarray, np.ndarray] | None:
    """An offset and a clock drift, fitted through the lag each excerpt scores best at.

    A capture can hear the playback over more than one path - a fancam two PA
    arrays apart received it twice, 8 ms apart and inverted - and the 0.1 s
    track then hops between the two peaks, or wanders off both where the live
    content buries them.  Every hop is a phase jump the per-bin transfer has
    to re-learn.  One complex gain per bin describes both paths at once as long
    as they share its window, so a lag that holds still between them is what
    the canceller wants, and the narrowband score finds it directly.  Each
    excerpt searches around the track and the line goes through the peaks,
    robustly, because a clock moves the lag by microseconds per second.
    """
    length = min(mix.size, reference.size)
    excerpt = round(_SCORE_EXCERPT_SECONDS * rate)
    n_fft = 1 << max(round(math.log2(_SCORE_FFT_SECONDS * rate)), 6)
    hop = n_fft // 4
    # Shifting the reference by half a hop moves it by exactly one frame of an
    # STFT taken at that half hop, so each excerpt transforms its reference
    # span once and every candidate lag is a strided slice of it: measured
    # 0.21 s on a 180 s take against 1.06 s for transforming each candidate.
    step = hop // 2
    reach = round(_LINE_SEARCH_SECONDS * rate / step) * step
    count = min(
        round(length / (_LINE_EXCERPT_SPACING_SECONDS * rate)),
        (length - 2 * reach) // excerpt,
        _LINE_MAXIMUM_EXCERPTS,
    )
    if count < _LINE_MINIMUM_EXCERPTS:
        return None
    offsets = np.arange(-reach, reach + 1, step)
    centers: list[float] = []
    peaks: list[float] = []
    weights: list[float] = []
    for start in np.linspace(reach, length - excerpt - reach, count, dtype=np.int64):
        center = round(float(np.interp(start + excerpt / 2, positions, lags)))
        # The lowest source position belongs to the largest offset.
        base = int(start) - center - reach
        if base < 0 or base + excerpt + 2 * reach > reference.size:
            continue
        mix_spectrum = stft(np.asarray(mix[start : start + excerpt], dtype=np.float64), n_fft, hop)
        span = stft(
            np.asarray(reference[base : base + excerpt + 2 * reach], dtype=np.float64), n_fft, step
        )
        frames = min(mix_spectrum.shape[0], (span.shape[0] - 1 - 2 * reach // step) // 2 + 1)
        # sum(y conj(x)) is the conjugate of sum(conj(y) x), and only its
        # magnitude is read, so conjugating the mixture once spares every
        # candidate a conjugated copy of its slice.
        mix_conjugate = np.conj(mix_spectrum[:frames])
        mix_energy = float(np.vdot(mix_conjugate, mix_conjugate).real)
        span_power = span.real**2 + span.imag**2
        scores = np.zeros(offsets.size)
        for index, offset in enumerate(offsets):
            rows = slice((reach - offset) // step, None)
            cross = np.einsum("fb,fb->b", mix_conjugate, span[rows][: 2 * frames : 2])
            power = np.sum(span_power[rows][: 2 * frames : 2], axis=0)
            scores[index] = _share(cross, power, mix_energy)
        best = int(np.argmax(scores))
        if scores[best] <= 0.0:
            continue
        centers.append(float(start + excerpt / 2))
        peaks.append(center + float(offsets[best]) + step * _parabolic_offset(scores, best))
        weights.append(float(scores[best]))
    if len(centers) < _LINE_MINIMUM_EXCERPTS:
        return None
    times = np.asarray(centers) / rate
    values = np.asarray(peaks)
    confidence = np.asarray(weights)
    design = np.stack([np.ones_like(times), times], axis=1)
    weight = confidence
    for _ in range(_TRACK_ROBUST_PASSES + 1):
        root = np.sqrt(weight)
        coefficients = np.linalg.lstsq(design * root[:, None], values * root, rcond=None)[0]
        residual = values - design @ coefficients
        scale = max(6.0 * float(np.median(np.abs(residual))), 1.0)
        bounded = np.clip(residual / scale, -1.0, 1.0)
        weight = confidence * (1.0 - bounded * bounded) ** 2
        if not np.any(weight > 0.0):
            return None
    ends = np.asarray([0.0, float(mix.size - 1)])
    return ends, coefficients[0] + coefficients[1] * ends / rate


def _chosen_track(
    mix: np.ndarray,
    reference: np.ndarray,
    rate: int,
    positions: np.ndarray,
    lags: np.ndarray,
    token: CancellationToken,
) -> tuple[np.ndarray, np.ndarray]:
    """The track, or the line through it where the line explains clearly more."""
    line = _line_track(mix, reference, rate, positions, lags)
    if line is None:
        return positions, lags
    token.raise_if_cancelled()
    track_score = _explained_share(mix, reference, rate, (positions, lags))
    line_score = _explained_share(mix, reference, rate, line)
    chosen = line_score > _LINE_RELATIVE_MARGIN * track_score + _LINE_ABSOLUTE_MARGIN
    logger.info(
        "alignment %s: line %.3f to %.3f s scores %.4f, track scores %.4f",
        "follows the line" if chosen else "keeps the track",
        float(line[1][0] / rate),
        float(line[1][-1] / rate),
        line_score,
        track_score,
    )
    return line if chosen else (positions, lags)


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
    positions, lags = _chosen_track(mix_norm, ref_norm, proxy_rate, positions, lags, cancel)
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
