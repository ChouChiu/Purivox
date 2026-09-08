"""Estimate how much a source has been sped up or slowed down on stage.

A re-uploaded stage recording can carry its tempo shifted, and the shift is a
single constant per source.  Everything downstream - anchor matching, drift
tracking, reference cancellation - assumes the source runs at the stage's own
rate, so the ratio has to be recovered before any of it can work.

Correlating the source's attack features against the stage's at a trial ratio
finds it directly: the ratio that makes the whole source line up scores far
above every neighbouring ratio, and far above the score at ratio one.  The
trial is built by interpolating the source's own feature matrix along time
rather than by resampling the audio and transforming it again.  Both give the
same peak to within one grid step, measured on real material, and interpolating
costs a tenth as much: one source's search fell from 2.4 s to 0.23 s, which is
what makes a tempo search affordable inside an analysis the user waits for.

Measured on a real broadcast whose two sources were shifted by 1.0300 and
0.9232: the peak scores were 0.672 and 0.653 against 0.275 and 0.258 at ratio
one, and the matching step then placed both songs correctly where it had
previously swapped them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy.fft import irfft, next_fast_len, rfft

from shared.dsp.spectral import log_flux_bands
from shared.processing import CancellationToken

logger = logging.getLogger(__name__)

_RATE_MINIMUM = 0.88
_RATE_MAXIMUM = 1.15
_COARSE_STEP = 0.004
_FINE_STEP = 0.0005
_FINE_RADIUS = 0.006
# A peak below this is indistinguishable from the correlation floor of two
# signals with no common structure: measured on real material, a live section
# of one song against a different studio source reached 0.24 and music against
# noise reached 0.19, while a real match reached 0.65.
_MINIMUM_SCORE = 0.25
# The peak has to beat the best ratio outside its own neighbourhood, or a long
# correlation has simply produced a confident-looking number.
_MINIMUM_MARGIN = 1.10
# And it has to beat the unchanged hypothesis by a clear margin, which is what
# keeps a stage that already runs at the source's tempo on its existing path.
_MINIMUM_IMPROVEMENT = 0.04
# Below this the local drift tracker absorbs the difference anyway, so paying
# for a stretch would only add artefacts.
_MINIMUM_CHANGE = 0.002
_RIVAL_DISTANCE = 0.01
_HOP_SECONDS = 0.04
_MINIMUM_SECONDS = 8.0
_MINIMUM_FRAMES = 8


@dataclass(frozen=True, slots=True)
class RateEstimate:
    """What one scale search found, and how much it should be trusted.

    `ratio` is stage seconds per source second: the factor the source has to be
    stretched by to land on the stage's timeline.
    """

    ratio: float
    score: float
    rival: float
    improvement: float

    @property
    def reliable(self) -> bool:
        """Whether acting on this estimate is both safe and worth it."""
        return (
            self.score >= _MINIMUM_SCORE
            and self.score >= _MINIMUM_MARGIN * self.rival
            and self.improvement >= _MINIMUM_IMPROVEMENT
            and abs(self.ratio - 1.0) >= _MINIMUM_CHANGE
        )


@dataclass(frozen=True, slots=True)
class _Stage:
    """The stage side of a scale search, transformed once instead of per trial."""

    length: int
    size: int
    spectra: np.ndarray
    cumulative: np.ndarray


def _prepare(stage: np.ndarray, widest_query: int) -> _Stage:
    """Transform the stage once, at the length the widest trial query needs."""
    length = stage.shape[1]
    size = next_fast_len(length + min(widest_query, length) - 1, True)
    cumulative = np.concatenate(
        (np.zeros((stage.shape[0], 1)), np.cumsum(stage * stage, axis=1)), axis=1
    )
    spectra = np.stack([rfft(band, size) for band in stage])
    return _Stage(length, size, spectra, cumulative)


def _peak_score(stage: _Stage, query: np.ndarray) -> float | None:
    """Best normalized correlation of `query` anywhere along the stage."""
    width = query.shape[1]
    if width > stage.length:
        return None
    score = np.zeros(stage.length - width + 1, dtype=np.float64)
    stage_energy = np.zeros_like(score)
    query_energy = float(np.sum(query * query))
    if query_energy <= 0.0:
        return None
    pairs = zip(stage.spectra, stage.cumulative, query, strict=True)
    for band, cumulative, query_band in pairs:
        full = irfft(band * rfft(query_band[::-1], stage.size), stage.size)
        score += full[width - 1 : stage.length]
        stage_energy += cumulative[width:] - cumulative[:-width]
    normalized = score / (np.sqrt(stage_energy * query_energy) + 1e-12)
    peak = float(np.max(normalized))
    return peak if np.isfinite(peak) else None


def _trial_features(features: np.ndarray, ratio: float, max_frames: int) -> np.ndarray | None:
    """The source's features as if it had been stretched by `ratio`.

    Output frame `j` describes the stretched signal at `j` hops, which came from
    source frame `j / ratio`.  A source longer than the stage cannot be placed
    at all, and a trial ratio that makes it longer still only loses its tail, so
    every trial is trimmed to the stage's own length; that also keeps the
    unchanged hypothesis measurable when the source outruns the stage clip.
    """
    frames = features.shape[1]
    width = min(round(frames * ratio), max_frames)
    if width < _MINIMUM_FRAMES:
        return None
    positions = np.arange(width) / ratio
    lower = np.floor(positions).astype(np.int64)
    fraction = positions - lower
    upper = np.minimum(lower + 1, frames - 1)
    np.clip(lower, 0, frames - 1, out=lower)
    return features[:, lower] * (1.0 - fraction) + features[:, upper] * fraction


def estimate_rate(
    stage_proxy: np.ndarray,
    source_proxy: np.ndarray,
    feature_rate: int,
    token: CancellationToken | None = None,
) -> RateEstimate | None:
    """Find the tempo ratio between a stage recording and one source.

    Both inputs are mono proxies at `feature_rate`; the caller already builds
    one for matching.  Returns `None` when either is too short to describe, or
    when no trial ratio produces a peak worth reporting.
    """
    cancel = token or CancellationToken()
    stage = np.asarray(stage_proxy, dtype=np.float64)
    source = np.asarray(source_proxy, dtype=np.float64)
    if stage.ndim != 1 or source.ndim != 1 or feature_rate <= 0:
        raise ValueError("rate estimation needs two mono proxies and a positive feature rate")
    if (
        stage.size / feature_rate < _MINIMUM_SECONDS
        or source.size / feature_rate < _MINIMUM_SECONDS
    ):
        return None
    hop = max(round(_HOP_SECONDS * feature_rate), 1)
    stage_features = log_flux_bands(stage, min(512, stage.size), hop)
    source_features = log_flux_bands(source, min(512, source.size), hop)
    if stage_features is None or source_features is None:
        return None
    max_frames = stage_features.shape[1]
    prepared = _prepare(
        stage_features,
        round(source_features.shape[1] * _RATE_MAXIMUM),
    )

    scores: dict[float, float] = {}

    def measure(ratio: float) -> float | None:
        ratio = round(min(max(ratio, _RATE_MINIMUM), _RATE_MAXIMUM), 5)
        if ratio in scores:
            return scores[ratio]
        query = _trial_features(source_features, ratio, max_frames)
        if query is None:
            return None
        peak = _peak_score(prepared, query)
        if peak is not None:
            scores[ratio] = peak
        return peak

    baseline = measure(1.0)
    if baseline is None:
        return None
    best_ratio = 1.0
    best_score = baseline
    steps = round((_RATE_MAXIMUM - _RATE_MINIMUM) / _COARSE_STEP)
    for index in range(steps + 1):
        if index % 8 == 0:
            cancel.raise_if_cancelled()
        peak = measure(_RATE_MINIMUM + index * _COARSE_STEP)
        if peak is not None and peak > best_score:
            best_ratio, best_score = round(_RATE_MINIMUM + index * _COARSE_STEP, 5), peak
    if best_score < _MINIMUM_SCORE:
        logger.debug("rate search found no usable peak (best %.3f at %.4f)", best_score, best_ratio)
        return None
    fine_steps = round(2 * _FINE_RADIUS / _FINE_STEP)
    for index in range(fine_steps + 1):
        if index % 8 == 0:
            cancel.raise_if_cancelled()
        ratio = best_ratio - _FINE_RADIUS + index * _FINE_STEP
        peak = measure(ratio)
        if peak is not None and peak > best_score:
            best_ratio, best_score = round(min(max(ratio, _RATE_MINIMUM), _RATE_MAXIMUM), 5), peak
    rival = max(
        (value for ratio, value in scores.items() if abs(ratio - best_ratio) > _RIVAL_DISTANCE),
        default=0.0,
    )
    estimate = RateEstimate(best_ratio, best_score, rival, best_score - baseline)
    logger.debug(
        "rate search: ratio=%.4f score=%.3f rival=%.3f improvement=%.3f reliable=%s",
        estimate.ratio,
        estimate.score,
        estimate.rival,
        estimate.improvement,
        estimate.reliable,
    )
    return estimate
