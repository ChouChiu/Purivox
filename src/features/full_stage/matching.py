from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from scipy.signal import correlate, find_peaks, resample_poly

from features.full_stage.models import (
    ClipKind,
    FullStageAnalysis,
    FullStageJob,
    TimelineClip,
)
from shared.audio import AudioData, read_audio
from shared.dsp import log_flux_bands
from shared.processing import CancellationToken, ProgressCallback
from shared.progress import report_progress

logger = logging.getLogger(__name__)

_FEATURE_RATE = 4_000
_HOP_SECONDS = 0.04
_ANCHORS = 7
# Hits this close to each other describe the same placement, not two of them.
_CLUSTER_TOLERANCE_SECONDS = 0.8


@dataclass(frozen=True, slots=True)
class _Hit:
    anchor_index: int
    source_start: float
    timeline_start: float
    score: float


@dataclass(slots=True)
class _Candidate:
    timeline_start: float
    source_duration: float
    anchor_duration: float
    hits: list[_Hit]

    @property
    def votes(self) -> int:
        return len({hit.anchor_index for hit in self.hits})

    @property
    def confidence(self) -> float:
        values = sorted((hit.score for hit in self.hits), reverse=True)
        useful = values[: max(1, self.votes)]
        return float(np.clip(np.mean(useful), 0.0, 1.0))


def _proxy(audio: AudioData, token: CancellationToken) -> np.ndarray:
    token.raise_if_cancelled()
    channels = np.asarray(audio.samples[:2], dtype=np.float32)
    divisor = math.gcd(audio.sample_rate, _FEATURE_RATE)
    values = resample_poly(
        channels,
        _FEATURE_RATE // divisor,
        audio.sample_rate // divisor,
        axis=1,
    )
    token.raise_if_cancelled()
    return np.asarray(values, dtype=np.float64).mean(axis=0)


def _features(proxy: np.ndarray) -> np.ndarray:
    bands = log_flux_bands(
        proxy,
        min(512, proxy.size),
        max(round(_HOP_SECONDS * _FEATURE_RATE), 1),
    )
    if bands is None:
        raise ValueError("audio is too short for full-stage matching")
    return bands


def _normalized_correlation(stage: np.ndarray, query: np.ndarray) -> np.ndarray:
    if query.shape[1] > stage.shape[1]:
        return np.empty(0, dtype=np.float64)
    score = np.zeros(stage.shape[1] - query.shape[1] + 1, dtype=np.float64)
    stage_energy = np.zeros_like(score)
    query_energy = float(np.sum(query * query))
    width = query.shape[1]
    for stage_band, query_band in zip(stage, query, strict=True):
        score += correlate(stage_band, query_band, mode="valid", method="fft")
        cumulative = np.concatenate(([0.0], np.cumsum(stage_band * stage_band)))
        stage_energy += cumulative[width:] - cumulative[:-width]
    return np.divide(
        score,
        np.sqrt(stage_energy * query_energy) + 1e-12,
        out=np.zeros_like(score),
    )


def _cluster_hits(
    hits: list[_Hit],
    source_duration: float,
    anchor_duration: float,
) -> list[_Candidate]:
    """Group hits that predict the same timeline position, best score first.

    Every anchor votes independently, so one real placement shows up as a spray
    of hits within a second of each other.  Merging them turns those votes into
    a single candidate whose confidence reflects how many anchors agreed.
    """
    clusters: list[_Candidate] = []
    for hit in sorted(hits, key=lambda item: item.score, reverse=True):
        cluster = next(
            (
                candidate
                for candidate in clusters
                if abs(candidate.timeline_start - hit.timeline_start) <= _CLUSTER_TOLERANCE_SECONDS
            ),
            None,
        )
        if cluster is None:
            clusters.append(_Candidate(hit.timeline_start, source_duration, anchor_duration, [hit]))
            continue
        cluster.hits.append(hit)
        cluster.timeline_start = float(np.median([item.timeline_start for item in cluster.hits]))
    return sorted(
        clusters,
        key=lambda candidate: (candidate.votes, candidate.confidence),
        reverse=True,
    )


def _source_candidates(
    stage_features: np.ndarray,
    source_features: np.ndarray,
    source_duration: float,
    token: CancellationToken,
) -> list[_Candidate]:
    feature_rate = 1.0 / _HOP_SECONDS
    anchor_seconds = min(20.0, max(6.0, source_duration * 0.28))
    anchor_width = min(max(round(anchor_seconds * feature_rate), 24), source_features.shape[1])
    maximum_start = max(source_features.shape[1] - anchor_width, 0)
    anchor_starts = np.unique(np.linspace(0, maximum_start, _ANCHORS).astype(int))
    hits: list[_Hit] = []
    peak_distance = max(round(4.0 * feature_rate), 1)
    for anchor_index, source_start in enumerate(anchor_starts):
        token.raise_if_cancelled()
        scores = _normalized_correlation(
            stage_features,
            source_features[:, source_start : source_start + anchor_width],
        )
        if scores.size == 0:
            continue
        peaks, _ = find_peaks(scores, distance=peak_distance)
        if peaks.size == 0:
            peaks = np.asarray([int(np.argmax(scores))])
        selected = peaks[np.argsort(scores[peaks])[-12:]]
        for peak in selected:
            score = float(scores[peak])
            if score < 0.08:
                continue
            source_seconds = float(source_start / feature_rate)
            hits.append(
                _Hit(
                    anchor_index,
                    source_seconds,
                    float(peak / feature_rate - source_seconds),
                    score,
                )
            )

    return _cluster_hits(hits, source_duration, anchor_width / feature_rate)


def _boundary_fragment_candidates(
    stage_features: np.ndarray,
    source_features: np.ndarray,
    source_duration: float,
    token: CancellationToken,
) -> list[_Candidate]:
    """Find short promo/outro uses without letting them replace the full song."""
    feature_rate = 1.0 / _HOP_SECONDS
    width = min(round(10.0 * feature_rate), source_features.shape[1])
    step = max(round(5.0 * feature_rate), 1)
    boundary = round(75.0 * feature_rate)
    hits: list[_Hit] = []
    for anchor_index, source_start in enumerate(
        range(0, max(source_features.shape[1] - width + 1, 1), step)
    ):
        token.raise_if_cancelled()
        scores = _normalized_correlation(
            stage_features,
            source_features[:, source_start : source_start + width],
        )
        if scores.size == 0:
            continue
        boundary_indices = np.concatenate(
            (
                np.arange(min(boundary, scores.size)),
                np.arange(max(0, scores.size - boundary), scores.size),
            )
        )
        selected = boundary_indices[np.argsort(scores[boundary_indices])[-4:]]
        for peak in selected:
            score = float(scores[peak])
            if score < 0.22:
                continue
            source_seconds = float(source_start / feature_rate)
            hits.append(
                _Hit(
                    anchor_index,
                    source_seconds,
                    float(peak / feature_rate - source_seconds),
                    score,
                )
            )

    return _cluster_hits(hits, source_duration, width / feature_rate)


def _verify_boundary_candidates(
    stage_proxy: np.ndarray,
    source_proxy: np.ndarray,
    candidates: list[_Candidate],
) -> list[_Candidate]:
    verified: list[_Candidate] = []
    width = min(round(10.0 * _FEATURE_RATE), source_proxy.size)
    for candidate in candidates:
        if candidate.votes < 2:
            continue
        anchor = max(candidate.hits, key=lambda hit: hit.score)
        source_start = max(0, round(anchor.source_start * _FEATURE_RATE))
        query = np.diff(
            source_proxy[source_start : source_start + width],
            prepend=source_proxy[source_start],
        )
        query -= np.mean(query)
        predicted = candidate.timeline_start + anchor.source_start
        search_start = max(0, round((predicted - 1.0) * _FEATURE_RATE))
        search_end = min(stage_proxy.size, search_start + query.size + 2 * _FEATURE_RATE)
        search = np.diff(
            stage_proxy[search_start:search_end],
            prepend=stage_proxy[search_start],
        )
        if search.size < query.size:
            continue
        score = correlate(search, query, mode="valid", method="fft")
        cumulative = np.concatenate(([0.0], np.cumsum(search * search)))
        energy = np.sqrt(
            (cumulative[query.size :] - cumulative[: -query.size]) * float(np.sum(query * query))
        )
        normalized = np.abs(score / (energy + 1e-12))
        best = int(np.argmax(normalized))
        if float(normalized[best]) < 0.06:
            continue
        matched_stage = (search_start + best) / _FEATURE_RATE
        candidate.timeline_start = matched_stage - anchor.source_start
        verified.append(candidate)
    return verified


def _is_credible(candidate: _Candidate) -> bool:
    return (candidate.votes >= 2 and candidate.confidence >= 0.10) or candidate.confidence >= 0.28


def _choose_songs(
    candidates: list[list[_Candidate]],
    source_paths: tuple[Path, ...],
    duration: float,
) -> tuple[list[TimelineClip], list[Path]]:
    ranked = sorted(
        (
            (candidate.votes, candidate.confidence, source_index, source, candidate)
            for source_index, (source, options) in enumerate(
                zip(source_paths, candidates, strict=True)
            )
            for candidate in options
            if _is_credible(candidate)
            and candidate.timeline_start < duration
            and candidate.timeline_start + candidate.source_duration > 0.0
        ),
        reverse=True,
        key=lambda item: (item[0], item[1]),
    )
    clips: list[TimelineClip] = []
    selected_sources: set[int] = set()
    for _votes, _confidence, source_index, source, selected in ranked:
        if source_index in selected_sources:
            continue
        start = max(0.0, selected.timeline_start)
        end = min(duration, selected.timeline_start + selected.source_duration)
        if any(min(end, clip.stage_end) - max(start, clip.stage_start) > 2.0 for clip in clips):
            continue
        source_start = max(0.0, -selected.timeline_start)
        clips.append(
            TimelineClip(
                ClipKind.SONG,
                start,
                end,
                source,
                source_index,
                source_start,
                source_start + end - start,
                selected.confidence,
            )
        )
        selected_sources.add(source_index)
    missing = [source for index, source in enumerate(source_paths) if index not in selected_sources]
    return sorted(clips, key=lambda clip: clip.stage_start), missing


def _overlaps(left: TimelineClip, start: float, end: float) -> bool:
    return min(left.stage_end, end) - max(left.stage_start, start) > 1.0


def _find_fragments(
    all_candidates: list[list[_Candidate]],
    source_paths: tuple[Path, ...],
    songs: list[TimelineClip],
    duration: float,
) -> list[TimelineClip]:
    fragments: list[TimelineClip] = []
    feature_rate = 1.0 / _HOP_SECONDS
    possible = [
        (candidate.votes, candidate.confidence, source_index, source, candidate)
        for source_index, (source, options) in enumerate(
            zip(source_paths, all_candidates, strict=True)
        )
        for candidate in options
    ]
    for _votes, _confidence, source_index, source, candidate in sorted(
        possible, reverse=True, key=lambda item: (item[0], item[1])
    ):
        source_starts = [hit.source_start for hit in candidate.hits]
        source_start = min(source_starts)
        source_end = min(
            candidate.source_duration,
            max(source_starts) + candidate.anchor_duration,
        )
        start = max(0.0, candidate.timeline_start + source_start)
        end = min(duration, candidate.timeline_start + source_end)
        if candidate.votes < 2 or candidate.confidence < 0.16:
            continue
        if end - start < max(5.0, 2.0 / feature_rate):
            continue
        if any(_overlaps(song, start, end) for song in songs):
            continue
        if any(_overlaps(fragment, start, end) for fragment in fragments):
            continue
        fragments.append(
            TimelineClip(
                ClipKind.FRAGMENT,
                start,
                end,
                source,
                source_index,
                source_start,
                source_start + end - start,
                candidate.confidence,
            )
        )
    return fragments


def _timeline(duration: float, occupied: list[TimelineClip]) -> tuple[TimelineClip, ...]:
    """Order matched clips and the unmatched gaps between them into one track."""
    gaps = _unmatched_clips(duration, occupied)
    return tuple(sorted(occupied + gaps, key=lambda clip: (clip.stage_start, clip.kind.value)))


def _rebuilt(analysis: FullStageAnalysis, occupied: list[TimelineClip]) -> FullStageAnalysis:
    """Recompute the unmatched gaps around a changed set of matched clips."""
    return replace(analysis, clips=_timeline(analysis.duration_seconds, occupied))


def add_manual_clip(analysis: FullStageAnalysis, clip: TimelineClip) -> FullStageAnalysis:
    """Insert a user-supplied clip the matcher could not find on its own.

    A spliced backing track reuses parts of a source in an order no anchor
    search will reconstruct, so the timeline has to accept ranges the user
    knows about.  The clip is a full song rather than a fragment because
    rendering gates fragments behind a switch, and an explicit addition should
    not be silently skipped by it.
    """
    if clip.kind == ClipKind.UNMATCHED:
        raise ValueError("a manual clip must reference a source")
    if clip.stage_end > analysis.duration_seconds:
        raise ValueError("manual clip exceeds the stage duration")
    occupied = [existing for existing in analysis.clips if existing.kind != ClipKind.UNMATCHED]
    occupied.append(clip)
    return _rebuilt(analysis, occupied)


def remove_manual_clip(analysis: FullStageAnalysis, index: int) -> FullStageAnalysis:
    """Drop a manually added clip. Detected clips are disabled, never removed."""
    if not 0 <= index < len(analysis.clips):
        raise IndexError("timeline index out of range")
    target = analysis.clips[index]
    if not target.manual:
        raise ValueError("only manually added clips can be removed")
    occupied = [
        existing
        for position, existing in enumerate(analysis.clips)
        if existing.kind != ClipKind.UNMATCHED and position != index
    ]
    return _rebuilt(analysis, occupied)


def _unmatched_clips(duration: float, occupied: list[TimelineClip]) -> list[TimelineClip]:
    minimum_gap = 0.25
    merged: list[tuple[float, float]] = []
    for clip in sorted(occupied, key=lambda item: item.stage_start):
        if merged and clip.stage_start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], clip.stage_end))
        else:
            merged.append((clip.stage_start, clip.stage_end))
    gaps: list[TimelineClip] = []
    cursor = 0.0
    for start, end in merged:
        if start - cursor >= minimum_gap:
            gaps.append(TimelineClip(ClipKind.UNMATCHED, cursor, start))
        cursor = max(cursor, end)
    if duration - cursor >= minimum_gap:
        gaps.append(TimelineClip(ClipKind.UNMATCHED, cursor, duration))
    return gaps


def analyze_full_stage(
    job: FullStageJob,
    token: CancellationToken,
    progress: ProgressCallback = lambda _event: None,
) -> FullStageAnalysis:
    stage_audio = None
    try:
        report_progress(progress, 0, job.language, "stage_loading")
        stage_audio = read_audio(job.stage, token)
        duration = stage_audio.frames / stage_audio.sample_rate
        report_progress(progress, 8, job.language, "stage_fingerprinting")
        stage_proxy = _proxy(stage_audio, token)
        stage_features = _features(stage_proxy)
        stage_audio.cleanup()
        stage_audio = None

        source_paths = tuple(source.expanduser().resolve() for source in job.sources)
        candidate_groups: list[list[_Candidate]] = []
        fragment_candidate_groups: list[list[_Candidate]] = []
        for index, source in enumerate(source_paths):
            token.raise_if_cancelled()
            value = 12 + round(70 * index / max(len(source_paths), 1))
            report_progress(
                progress,
                value,
                job.language,
                "stage_matching_source",
                current=index + 1,
                total=len(source_paths),
                name=source.name,
            )
            source_audio = read_audio(source, token)
            try:
                source_duration = source_audio.frames / source_audio.sample_rate
                source_proxy = _proxy(source_audio, token)
                source_features = _features(source_proxy)
            finally:
                source_audio.cleanup()
            candidate_groups.append(
                _source_candidates(stage_features, source_features, source_duration, token)
            )
            fragment_candidate_groups.append(
                _verify_boundary_candidates(
                    stage_proxy,
                    source_proxy,
                    _boundary_fragment_candidates(
                        stage_features, source_features, source_duration, token
                    ),
                )
            )

        songs, missing = _choose_songs(candidate_groups, source_paths, duration)
        fragments = _find_fragments(
            [
                full_candidates + boundary_candidates
                for full_candidates, boundary_candidates in zip(
                    candidate_groups, fragment_candidate_groups, strict=True
                )
            ],
            source_paths,
            songs,
            duration,
        )
        clips = _timeline(duration, songs + fragments)
        report_progress(progress, 100, job.language, "stage_analysis_done", count=len(songs))
        logger.info(
            "full-stage analysis completed: stage=%s songs=%d fragments=%d missing=%d",
            job.stage,
            len(songs),
            len(fragments),
            len(missing),
        )
        return FullStageAnalysis(duration, clips, tuple(missing))
    finally:
        if stage_audio is not None:
            stage_audio.cleanup()
