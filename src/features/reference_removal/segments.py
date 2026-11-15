"""Recover piecewise source positions without dragging an offset through a cut."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import correlate, find_peaks

from features.reference_removal.fingerprints import normalized_correlation, stage_spectra
from shared.processing import CancellationToken

_WINDOW_SECONDS = 4.0
_STEP_SECONDS = 1.0
_MINIMUM_SCORE = 0.4
_SWITCH_COST = 0.8
_MAX_POSITIONS = 32


@dataclass(frozen=True, slots=True)
class Segment:
    start: float
    end: float
    offset: float
    confidence: float


def _positions(hits: list[tuple[int, float]], tolerance: int) -> list[int]:
    clusters: list[list[tuple[int, float]]] = []
    for hit in sorted(hits):
        if not clusters or hit[0] - clusters[-1][0][0] > 2 * tolerance:
            clusters.append([hit])
        else:
            clusters[-1].append(hit)
    ranked = sorted(
        (g for g in clusters if len(g) >= 2),
        key=lambda g: sum(h[1] for h in g),
        reverse=True,
    )
    return [round(float(np.median([h[0] for h in g]))) for g in ranked[:_MAX_POSITIONS]]


def _path(emissions: np.ndarray, token: CancellationToken) -> np.ndarray:
    scores = emissions[0].copy()
    back = np.empty(emissions.shape, dtype=np.int32)
    states = np.arange(scores.size)
    for index, row in enumerate(emissions[1:], 1):
        token.raise_if_cancelled()
        best = int(np.argmax(scores))
        switch = scores[best] - _SWITCH_COST
        previous = np.where(scores >= switch, states, best)
        updated = np.maximum(scores, switch)
        # A gap has no competing source position; entering it costs less than
        # jumping to another chorus, so a short dancebreak is not bridged.
        from_gap = scores[-1] - 0.1
        use_gap = from_gap > updated[:-1]
        previous[:-1] = np.where(use_gap, scores.size - 1, previous[:-1])
        updated[:-1] = np.maximum(updated[:-1], from_gap)
        previous[-1] = best if scores[best] - 0.1 > scores[-1] else scores.size - 1
        updated[-1] = max(scores[-1], scores[best] - 0.1)
        back[index] = previous
        scores = updated + row
    path = np.empty(emissions.shape[0], dtype=np.int32)
    path[-1] = int(np.argmax(scores))
    for index in range(path.size - 1, 0, -1):
        path[index - 1] = back[index, path[index]]
    return path


def _waveform_score(
    stage: np.ndarray, source: np.ndarray, start: int, source_start: int, width: int, rate: int
) -> float:
    left = np.diff(stage[max(start, 0) : min(start + width, stage.size)])
    low = max(0, source_start - round(0.12 * rate))
    high = min(source.size, source_start + width + round(0.12 * rate))
    right = np.diff(source[low:high])
    if left.size < rate // 4 or right.size < left.size:
        return 0.0
    cross = correlate(right, left, mode="valid", method="fft")
    cumulative = np.concatenate(([0.0], np.cumsum(right * right)))
    energy = np.sqrt(
        np.maximum(cumulative[left.size :] - cumulative[: -left.size], 0.0)
        * float(np.sum(left * left))
    )
    return float(np.max(np.abs(cross) / (energy + 1e-12), initial=0.0))


def _local_scores(
    stage: np.ndarray,
    source: np.ndarray,
    offset: int,
    fps: float,
    stage_proxy: np.ndarray,
    source_proxy: np.ndarray,
    rate: int,
    low: int,
    high: int,
    minimum_score: float,
) -> np.ndarray:
    score = np.full(high - low, -minimum_score)
    start, end = max(low, offset, 0), min(high, stage.shape[1], source.shape[1] + offset)
    if end <= start:
        return score
    left, right = stage[:, start:end], source[:, start - offset : end - offset]
    cross = np.sum(left * right, axis=0)
    energy = np.sqrt(np.sum(left * left, axis=0) * np.sum(right * right, axis=0))
    width = max(round(fps), 1)
    cross = uniform_filter1d(cross, width, mode="nearest")
    energy = uniform_filter1d(energy, width, mode="nearest")
    values = cross / (energy + 1e-12) - minimum_score
    for index, frame in enumerate(range(start, end)):
        at = round((frame / fps - 0.5) * rate)
        similarity = _waveform_score(
            stage_proxy, source_proxy, at, at - round(offset / fps * rate), rate, rate
        )
        if similarity < 0.12:
            values[index] = min(values[index], similarity - 0.12)
        else:
            values[index] = 0.5 * values[index] + similarity - 0.12
    score[start - low : end - low] = values
    return score


def match_segments(
    stage: np.ndarray,
    source: np.ndarray,
    fps: float,
    duration: float,
    source_duration: float,
    token: CancellationToken,
    stage_proxy: np.ndarray,
    source_proxy: np.ndarray,
    proxy_rate: int,
    preferred_offset: float | None = None,
    minimum_score: float = _MINIMUM_SCORE,
) -> list[Segment]:
    """Find persistent positions, then split where the evidence changes position.

    An unmatched state competes with source positions. A switching cost keeps
    repeated choruses from pulling the path away from a continuous placement.
    Only the small feature track and one correlation curve are held at a time.
    """
    width = round(_WINDOW_SECONDS * fps)
    step = round(_STEP_SECONDS * fps)
    if min(stage.shape[1], source.shape[1]) < width + step:
        return []
    starts = np.arange(0, stage.shape[1] - width + 1, step)
    prepared = stage_spectra(source, width)
    hits: list[tuple[int, float]] = []
    for start in starts:
        token.raise_if_cancelled()
        scores = normalized_correlation(prepared, stage[:, start : start + width])
        peaks, _ = find_peaks(scores, distance=max(round(0.48 * fps), 1))
        peaks = np.unique(np.append(peaks, np.argmax(scores)))
        for peak in peaks[np.argsort(scores[peaks])[-3:]]:
            if scores[peak] >= minimum_score:
                hits.append((int(start - peak), float(scores[peak])))
    offsets = _positions(hits, max(round(0.12 * fps), 1))
    if not offsets:
        return []
    emissions = np.zeros((starts.size, len(offsets) + 1))
    for index, start in enumerate(starts):
        token.raise_if_cancelled()
        scores = normalized_correlation(prepared, stage[:, start : start + width])
        for position, offset in enumerate(offsets):
            at = start - offset
            emissions[index, position] = (
                float(np.max(scores[max(at - 1, 0) : min(at + 2, scores.size)])) - minimum_score
                if 0 <= at < scores.size
                else -1.0
            )
    for index, start in enumerate(starts):
        token.raise_if_cancelled()
        at = round(start / fps * proxy_rate)
        for position, offset in enumerate(offsets):
            if emissions[index, position] <= -0.5 * minimum_score:
                continue
            similarity = _waveform_score(
                stage_proxy,
                source_proxy,
                at,
                round((start - offset) / fps * proxy_rate),
                round(_WINDOW_SECONDS * proxy_rate),
                proxy_rate,
            )
            if similarity < 0.06:
                emissions[index, position] = -minimum_score
            else:
                emissions[index, position] = max(emissions[index, position], similarity - 0.12)
    bonuses = np.zeros(len(offsets) + 1)
    if preferred_offset is not None:
        for position, offset in enumerate(offsets):
            if abs(offset / fps - preferred_offset) <= 0.16:
                bonuses[position] = 0.15 * minimum_score
    emissions += bonuses
    path = _path(emissions, token)
    changes = np.flatnonzero(np.diff(path)) + 1
    boundaries = [0]
    for change in changes:
        token.raise_if_cancelled()
        left, right = int(path[change - 1]), int(path[change])
        center = int((starts[change - 1] + starts[change] + width) // 2)
        low = max(boundaries[-1], center - width // 2)
        high = min(stage.shape[1], center + width // 2)
        curves = []
        for state in (left, right):
            curves.append(
                _local_scores(
                    stage,
                    source,
                    offsets[state],
                    fps,
                    stage_proxy,
                    source_proxy,
                    proxy_rate,
                    low,
                    high,
                    minimum_score,
                )
                if state < len(offsets)
                else np.zeros(high - low)
            )
        advantage = np.concatenate(([0.0], np.cumsum(curves[0] - curves[1])))
        boundaries.append(low + int(np.argmax(advantage)))
    boundaries.append(stage.shape[1])
    segments = []
    for first, last, low, high in zip(
        np.r_[0, changes], np.r_[changes, path.size], boundaries[:-1], boundaries[1:], strict=True
    ):
        state = int(path[first])
        if state == len(offsets):
            continue
        offset = offsets[state] / fps
        start = max(low / fps, offset, 0.0)
        end = min(high / fps, offset + source_duration, duration)
        if end - start < _WINDOW_SECONDS:
            continue
        # Window searches can vote for music beyond a boundary. Validate both
        # ends locally so a partial window cannot turn nearby noise into a clip.
        edge = width // 2
        first_frame, last_frame = round(start * fps), round(end * fps)
        head_end = min(first_frame + edge, last_frame)
        tail_start = max(first_frame, last_frame - edge)
        head = _local_scores(
            stage,
            source,
            offsets[state],
            fps,
            stage_proxy,
            source_proxy,
            proxy_rate,
            first_frame,
            head_end,
            minimum_score,
        )
        tail = _local_scores(
            stage,
            source,
            offsets[state],
            fps,
            stage_proxy,
            source_proxy,
            proxy_rate,
            tail_start,
            last_frame,
            minimum_score,
        )
        supported_head = np.flatnonzero(head > 0.0)
        supported_tail = np.flatnonzero(tail > 0.0)
        start = max(
            start,
            (first_frame + int(supported_head[0])) / fps if supported_head.size else head_end / fps,
        )
        end = min(
            end,
            (tail_start + int(supported_tail[-1]) + 1) / fps
            if supported_tail.size
            else tail_start / fps,
        )
        if end - start < _WINDOW_SECONDS:
            continue
        confidence = float(
            np.clip(np.median(emissions[first:last, state]) + minimum_score - bonuses[state], 0, 1)
        )
        segments.append(Segment(start, end, offset, confidence))
    return segments
