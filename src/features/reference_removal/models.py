from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from shared.audio import AudioStats
from shared.jobs import OutputTracks, planned_outputs, validate_reference_settings


@dataclass(frozen=True, slots=True)
class ReferenceJob:
    """Cancel one reference out of one recording, over the whole timeline.

    This is the fallback the isolation pipeline falls back to when a lone source
    cannot be located in the stage recording: the reference is taken as covering
    the recording, aligned by drift tracking rather than by matching.
    """

    stage: Path
    source: Path
    output: Path
    strength: int = 75
    sigma: int = 3
    auto_align: bool = True
    tracks: OutputTracks = OutputTracks.VOCAL

    def __post_init__(self) -> None:
        validate_reference_settings(self.strength, self.sigma)


class ClipKind(StrEnum):
    SONG = "song"
    FRAGMENT = "fragment"
    UNMATCHED = "unmatched"


@dataclass(frozen=True, slots=True)
class TimelineClip:
    kind: ClipKind
    stage_start: float
    stage_end: float
    source: Path | None = None
    source_index: int | None = None
    source_start: float = 0.0
    source_end: float = 0.0
    confidence: float = 0.0
    enabled: bool = True
    manual: bool = False
    speed: float = 1.0
    """Stage seconds per source second: the factor this clip's source is stretched by."""

    def __post_init__(self) -> None:
        if self.stage_start < 0 or self.stage_end <= self.stage_start:
            raise ValueError("timeline clip must have a positive duration")
        if self.kind == ClipKind.UNMATCHED:
            if self.source is not None or self.source_index is not None:
                raise ValueError("unmatched clips must not reference a source")
            object.__setattr__(self, "enabled", False)
            object.__setattr__(self, "speed", 1.0)
        elif self.source is None or self.source_index is None:
            raise ValueError("matched clips require a source")
        elif self.source_start < 0 or self.source_end <= self.source_start:
            raise ValueError("matched source range must have a positive duration")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if self.manual and self.kind == ClipKind.UNMATCHED:
            raise ValueError("unmatched clips cannot be manual")
        if not 0.25 <= self.speed <= 4.0:
            raise ValueError("speed must be within [0.25, 4]")

    @property
    def duration(self) -> float:
        return self.stage_end - self.stage_start


@dataclass(frozen=True, slots=True)
class StageAnalysis:
    """Where each source sits in the stage recording."""

    duration_seconds: float
    clips: tuple[TimelineClip, ...]
    missing_sources: tuple[Path, ...] = ()

    @property
    def matched_clips(self) -> tuple[TimelineClip, ...]:
        return tuple(
            clip for clip in self.clips if clip.kind != ClipKind.UNMATCHED and clip.enabled
        )

    @property
    def song_clips(self) -> tuple[TimelineClip, ...]:
        return tuple(clip for clip in self.clips if clip.kind == ClipKind.SONG)


@dataclass(frozen=True, slots=True)
class IsolationJob:
    """One stage recording, one or more song sources, one pair of outputs."""

    stage: Path
    sources: tuple[Path, ...]
    output: Path
    strength: int = 75
    sigma: int = 3
    auto_align: bool = True
    tracks: OutputTracks = OutputTracks.VOCAL

    def __post_init__(self) -> None:
        if not self.sources:
            raise ValueError("at least one source is required")
        validate_reference_settings(self.strength, self.sigma)
        resolved_stage = self.stage.expanduser().resolve()
        resolved_sources = tuple(source.expanduser().resolve() for source in self.sources)
        inputs = {resolved_stage, *resolved_sources}
        planned = planned_outputs(self.output, OutputTracks(self.tracks))
        if any(output.expanduser().resolve() in inputs for output in planned):
            raise ValueError("output path must not overwrite an input file")
        if resolved_stage in resolved_sources:
            raise ValueError("stage audio must not also be a source")


@dataclass(frozen=True, slots=True)
class IsolationResult:
    analysis: StageAnalysis
    outputs: tuple[Path, ...] = ()
    audio_stats: tuple[AudioStats, ...] = ()
