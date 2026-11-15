from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from scipy.signal import correlate, find_peaks, resample_poly

from features.reference_removal.fingerprints import normalized_correlation, stage_spectra
from features.reference_removal.models import (
    ClipKind,
    IsolationJob,
    StageAnalysis,
    TimelineClip,
)
from features.reference_removal.segments import match_segments
from shared.audio import AudioData, read_audio
from shared.dsp import log_flux_bands
from shared.dsp.rate import estimate_rate
from shared.dsp.stretch import time_stretch
from shared.processing import CancellationToken, ProgressCallback
from shared.progress import report_progress

logger = logging.getLogger(__name__)

_FEATURE_RATE = 4_000
_HOP_SECONDS = 0.04
# Feature frames per second: every position the anchor search finds is in these.
_FRAMES_PER_SECOND = 1.0 / _HOP_SECONDS
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
    # Averaging straight into float64 rather than converting first: the copy
    # that would make is a whole second proxy of a recording that can run hours.
    return values.mean(axis=0, dtype=np.float64)


def _features(proxy: np.ndarray) -> np.ndarray:
    bands = log_flux_bands(
        proxy,
        min(512, proxy.size),
        max(round(_HOP_SECONDS * _FEATURE_RATE), 1),
    )
    if bands is None:
        raise ValueError("audio is too short to match sources against")
    return bands


def _match_speed(
    stage_proxy: np.ndarray,
    source_proxy: np.ndarray,
    name: str,
    token: CancellationToken,
) -> float:
    """Recover a source's tempo relative to the stage, or 1.0 when unsure.

    Every anchor search below slides a query of one fixed width, so a source
    that was uploaded at a different tempo simply does not line up anywhere.
    The ratio is estimated once per source and the proxy is stretched by it,
    which leaves the rest of the matcher exactly as it was.
    """
    estimate = estimate_rate(stage_proxy, source_proxy, _FEATURE_RATE, token)
    if estimate is None or not estimate.reliable:
        return 1.0
    logger.info(
        "source %s needs a %.4f stretch to match the stage tempo (score %.3f, improvement %.3f)",
        name,
        estimate.ratio,
        estimate.score,
        estimate.improvement,
    )
    return estimate.ratio


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


def _anchor_hits(
    anchor_index: int,
    source_start: int,
    scores: np.ndarray,
    peaks: np.ndarray,
    threshold: float,
) -> list[_Hit]:
    """Turn one anchor's correlation peaks into timeline predictions."""
    source_seconds = float(source_start / _FRAMES_PER_SECOND)
    return [
        _Hit(anchor_index, source_seconds, float(peak / _FRAMES_PER_SECOND - source_seconds), score)
        for peak in peaks
        if (score := float(scores[peak])) >= threshold
    ]


def _source_candidates(
    stage_features: np.ndarray,
    source_features: np.ndarray,
    source_duration: float,
    token: CancellationToken,
) -> list[_Candidate]:
    anchor_seconds = min(20.0, max(6.0, source_duration * 0.28))
    anchor_width = min(
        max(round(anchor_seconds * _FRAMES_PER_SECOND), 24), source_features.shape[1]
    )
    maximum_start = max(source_features.shape[1] - anchor_width, 0)
    anchor_starts = np.unique(np.linspace(0, maximum_start, _ANCHORS).astype(int))
    hits: list[_Hit] = []
    peak_distance = max(round(4.0 * _FRAMES_PER_SECOND), 1)
    stage = stage_spectra(stage_features, anchor_width)
    for anchor_index, source_start in enumerate(anchor_starts):
        token.raise_if_cancelled()
        scores = normalized_correlation(
            stage,
            source_features[:, source_start : source_start + anchor_width],
        )
        if scores.size == 0:
            continue
        peaks, _ = find_peaks(scores, distance=peak_distance)
        if peaks.size == 0:
            peaks = np.asarray([int(np.argmax(scores))])
        selected = peaks[np.argsort(scores[peaks])[-12:]]
        hits.extend(_anchor_hits(anchor_index, source_start, scores, selected, 0.08))

    return _cluster_hits(hits, source_duration, anchor_width / _FRAMES_PER_SECOND)


def _boundary_fragment_candidates(
    stage_features: np.ndarray,
    source_features: np.ndarray,
    source_duration: float,
    token: CancellationToken,
) -> list[_Candidate]:
    """Find short promo/outro uses without letting them replace the full song."""
    width = min(round(10.0 * _FRAMES_PER_SECOND), source_features.shape[1])
    step = max(round(5.0 * _FRAMES_PER_SECOND), 1)
    boundary = round(75.0 * _FRAMES_PER_SECOND)
    hits: list[_Hit] = []
    stage = stage_spectra(stage_features, width)
    for anchor_index, source_start in enumerate(
        range(0, max(source_features.shape[1] - width + 1, 1), step)
    ):
        token.raise_if_cancelled()
        scores = normalized_correlation(
            stage,
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
        hits.extend(_anchor_hits(anchor_index, source_start, scores, selected, 0.22))

    return _cluster_hits(hits, source_duration, width / _FRAMES_PER_SECOND)


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


def _placement(
    candidate: _Candidate,
    source: Path,
    source_index: int,
    speed: float,
    duration: float,
) -> TimelineClip:
    """Turn one credible candidate into the clip a renderer can cancel."""
    start = max(0.0, candidate.timeline_start)
    end = min(duration, candidate.timeline_start + candidate.source_duration)
    # Positions found on the stretched proxy are stage-clock seconds; the clip
    # records where the source itself starts, and the render stretches the slice
    # it reads from there.
    source_start = max(0.0, -candidate.timeline_start) / speed
    return TimelineClip(
        ClipKind.SONG,
        start,
        end,
        source,
        source_index,
        source_start,
        source_start + (end - start) / speed,
        candidate.confidence,
        speed=speed,
    )


def _choose_songs(
    candidates: list[list[_Candidate]],
    source_paths: tuple[Path, ...],
    speeds: tuple[float, ...],
    duration: float,
    stack: bool,
) -> tuple[list[TimelineClip], list[Path]]:
    """Pick the clips to cancel: one placement per source, or all of them.

    One source over a stretch is the default.  Files that all match the same
    minute of a recording describe one playback unless the stage really layered
    them, so the best-scoring one is taken and the rest wait for another
    stretch.  A stage that did layer them - several backing tracks at once -
    needs every placement instead, which is what `stack` asks for: the stretches
    then overlap on purpose and the render takes each source out of what the
    previous ones left.
    """
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
    placed: dict[int, list[TimelineClip]] = {}
    for _votes, _confidence, source_index, source, selected in ranked:
        if not stack and source_index in placed:
            continue
        start = max(0.0, selected.timeline_start)
        end = min(duration, selected.timeline_start + selected.source_duration)
        if end <= start:
            continue
        # Two candidates of one source over the same stretch are one placement
        # found twice, whatever stacking says about the rest.
        if any(_covered(clip, start, end) for clip in placed.get(source_index, ())):
            continue
        if not stack and any(_covered(clip, start, end) for clip in clips):
            continue
        clip = _placement(selected, source, source_index, speeds[source_index], duration)
        clips.append(clip)
        placed.setdefault(source_index, []).append(clip)
    missing = [source for index, source in enumerate(source_paths) if index not in placed]
    return sorted(clips, key=lambda clip: clip.stage_start), missing


def _overlaps(left: TimelineClip, start: float, end: float) -> bool:
    """Whether two ranges share more than a moment of the stage timeline."""
    return min(left.stage_end, end) - max(left.stage_start, start) > 1.0


def _covered(left: TimelineClip, start: float, end: float) -> bool:
    """Whether a candidate is a placement the timeline already holds.

    The threshold is the one the one-per-stretch rule has always used: two
    ranges this far into each other describe the same content, not two.
    """
    return min(left.stage_end, end) - max(left.stage_start, start) > 2.0


def _suppressed(left: TimelineClip, start: float, end: float, source: Path, stack: bool) -> bool:
    """Whether an already placed clip keeps this candidate off the timeline.

    A stretch is normally explained by one source, so any overlap costs the
    candidate its place.  Stacking suppresses only the source's own coverage:
    another source over the same stretch is one more layer to cancel.
    """
    if not _overlaps(left, start, end):
        return False
    return not stack or left.source == source


def _find_fragments(
    all_candidates: list[list[_Candidate]],
    source_paths: tuple[Path, ...],
    speeds: tuple[float, ...],
    songs: list[TimelineClip],
    duration: float,
    stack: bool,
) -> list[TimelineClip]:
    """Place the short reuses a source has that no song placement covers.

    Without stacking a fragment has to stay clear of every song, because a
    stretch is explained by one source.  With stacking the same short reuse of
    another source is one more layer to cancel, so only the source's own
    coverage suppresses it.
    """
    fragments: list[TimelineClip] = []
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
        if end - start < max(5.0, 2.0 / _FRAMES_PER_SECOND):
            continue
        if any(_suppressed(song, start, end, source, stack) for song in songs):
            continue
        if any(_suppressed(fragment, start, end, source, stack) for fragment in fragments):
            continue
        speed = speeds[source_index]
        fragments.append(
            TimelineClip(
                ClipKind.FRAGMENT,
                start,
                end,
                source,
                source_index,
                source_start / speed,
                source_start / speed + (end - start) / speed,
                candidate.confidence,
                speed=speed,
            )
        )
    return fragments


def _timeline(duration: float, occupied: list[TimelineClip]) -> tuple[TimelineClip, ...]:
    """Order matched clips and the unmatched gaps between them into one track."""
    gaps = _unmatched_clips(duration, occupied)
    return tuple(sorted(occupied + gaps, key=lambda clip: (clip.stage_start, clip.kind.value)))


def _rebuilt(analysis: StageAnalysis, occupied: list[TimelineClip]) -> StageAnalysis:
    """Recompute the unmatched gaps around a changed set of matched clips."""
    return replace(analysis, clips=_timeline(analysis.duration_seconds, occupied))


def add_manual_clip(analysis: StageAnalysis, clip: TimelineClip) -> StageAnalysis:
    """Insert a user-supplied clip the matcher could not find on its own.

    A spliced backing track reuses parts of a source in an order no anchor
    search will reconstruct, so the timeline has to accept ranges the user
    knows about.  The clip is a full song rather than a fragment: a fragment is
    what the matcher found on its own, and a range the user typed in is not one.
    """
    if clip.kind == ClipKind.UNMATCHED:
        raise ValueError("a manual clip must reference a source")
    if clip.stage_end > analysis.duration_seconds:
        raise ValueError("manual clip exceeds the stage duration")
    occupied = [existing for existing in analysis.clips if existing.kind != ClipKind.UNMATCHED]
    occupied.append(clip)
    return _rebuilt(analysis, occupied)


def remove_manual_clip(analysis: StageAnalysis, index: int) -> StageAnalysis:
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


def edit_clip(
    analysis: StageAnalysis,
    index: int,
    *,
    enabled: bool | None = None,
    stage_range: tuple[float, float] | None = None,
    source_range: tuple[float, float] | None = None,
) -> StageAnalysis:
    """Apply one in-place edit to a clip, or raise if the timeline cannot hold it.

    Enabling and the two ranges change the clip itself; inserting and removing
    go through `add_manual_clip`/`remove_manual_clip` because those rebuild the
    gaps around the change.  `TimelineClip` validates its own ranges, so an
    empty or reversed one raises from `replace`.
    """
    if not 0 <= index < len(analysis.clips):
        raise IndexError("timeline index out of range")
    clip = analysis.clips[index]
    unmatched = clip.kind == ClipKind.UNMATCHED
    fields: dict[str, object] = {}
    if enabled is not None:
        if unmatched:
            raise ValueError("an unmatched clip cannot be enabled")
        fields["enabled"] = enabled
    if stage_range is not None:
        if stage_range[1] > analysis.duration_seconds:
            raise ValueError("stage range exceeds duration")
        fields["stage_start"], fields["stage_end"] = stage_range
    if source_range is not None:
        if unmatched:
            raise ValueError("an unmatched clip has no source range")
        fields["source_start"], fields["source_end"] = source_range
    if not fields:
        return analysis
    clips = list(analysis.clips)
    clips[index] = replace(clip, **fields)
    return replace(analysis, clips=tuple(clips))


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


def analyze_stage(
    job: IsolationJob,
    token: CancellationToken,
    progress: ProgressCallback = lambda _event: None,
) -> StageAnalysis:
    report_progress(progress, 0, "stage_loading")
    with read_audio(job.stage, token) as stage_audio:
        duration = stage_audio.frames / stage_audio.sample_rate
        report_progress(progress, 8, "stage_fingerprinting")
        stage_proxy = _proxy(stage_audio, token)
    stage_features = _features(stage_proxy)

    source_paths = tuple(source.expanduser().resolve() for source in job.sources)
    candidate_groups: list[list[_Candidate]] = []
    fragment_candidate_groups: list[list[_Candidate]] = []
    speeds: list[float] = []
    segment_groups: list[list[TimelineClip]] = []
    for index, source in enumerate(source_paths):
        token.raise_if_cancelled()
        report_progress(
            progress,
            12 + round(70 * index / len(source_paths)),
            "stage_matching_source",
            current=index + 1,
            total=len(source_paths),
            name=source.name,
        )
        with read_audio(source, token) as source_audio:
            source_duration = source_audio.frames / source_audio.sample_rate
            source_proxy = _proxy(source_audio, token)
        speed = _match_speed(stage_proxy, source_proxy, source.name, token)
        match_proxy = source_proxy
        if speed != 1.0:
            match_proxy = time_stretch(source_proxy[None, :], _FEATURE_RATE, speed, token)[0]
        source_features = _features(match_proxy)
        # The candidates below describe positions on the stretched proxy,
        # which is the stage's own clock; `speeds` converts them back.
        match_duration = source_duration * speed
        speeds.append(speed)
        candidate_groups.append(
            _source_candidates(stage_features, source_features, match_duration, token)
        )
        segments = match_segments(
            stage_features,
            source_features,
            _FRAMES_PER_SECOND,
            duration,
            match_duration,
            token,
            stage_proxy,
            match_proxy,
            _FEATURE_RATE,
            candidate_groups[-1][0].timeline_start if candidate_groups[-1] else None,
            min(0.4, max(0.12, 0.65 * candidate_groups[-1][0].confidence))
            if candidate_groups[-1]
            else 0.4,
        )
        segment_groups.append(
            [
                TimelineClip(
                    ClipKind.SONG,
                    segment.start,
                    segment.end,
                    source,
                    index,
                    max(0.0, (segment.start - segment.offset) / speed),
                    min(source_duration, (segment.end - segment.offset) / speed),
                    segment.confidence,
                    speed=speed,
                )
                for segment in segments
            ]
        )
        fragment_candidate_groups.append(
            _verify_boundary_candidates(
                stage_proxy,
                match_proxy,
                _boundary_fragment_candidates(
                    stage_features, source_features, match_duration, token
                ),
            )
        )

    songs, missing = _choose_songs(
        candidate_groups, source_paths, tuple(speeds), duration, job.stack
    )
    for source, segments in zip(source_paths, segment_groups, strict=True):
        if len(segments) < 2:
            continue
        others = [clip for clip in songs if clip.source != source]
        # A segment path says where this source actually went; another source
        # over the same stretch only competes with it when a stretch is meant to
        # be explained by one source.
        if not job.stack and any(
            _overlaps(other, segment.stage_start, segment.stage_end)
            for other in others
            for segment in segments
        ):
            continue
        songs = others + segments
        missing = [path for path in missing if path != source]
        logger.info("matched %s in %d continuous segments", source.name, len(segments))
    songs.sort(key=lambda clip: clip.stage_start)
    fragments = _find_fragments(
        [
            full_candidates + boundary_candidates
            for full_candidates, boundary_candidates in zip(
                candidate_groups, fragment_candidate_groups, strict=True
            )
        ],
        source_paths,
        tuple(speeds),
        songs,
        duration,
        job.stack,
    )
    clips = _timeline(duration, songs + fragments)
    report_progress(progress, 100, "stage_analysis_done", count=len(songs))
    logger.info(
        "stage analysis completed: stage=%s songs=%d fragments=%d missing=%d",
        job.stage,
        len(songs),
        len(fragments),
        len(missing),
    )
    return StageAnalysis(duration, clips, tuple(missing))
