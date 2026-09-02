from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from features.full_stage import (
    ClipKind,
    FullStageAnalysis,
    TimelineClip,
    add_manual_clip,
    remove_manual_clip,
)


def clip_to_dict(clip: TimelineClip) -> dict[str, Any]:
    return {
        "kind": str(clip.kind),
        "stage_start": clip.stage_start,
        "stage_end": clip.stage_end,
        "source": str(clip.source) if clip.source is not None else None,
        "source_index": clip.source_index,
        "source_start": clip.source_start,
        "source_end": clip.source_end,
        "confidence": clip.confidence,
        "enabled": clip.enabled,
        "manual": clip.manual,
    }


def clip_from_dict(data: dict[str, Any]) -> TimelineClip:
    source = data.get("source")
    return TimelineClip(
        kind=ClipKind(data["kind"]),
        stage_start=float(data["stage_start"]),
        stage_end=float(data["stage_end"]),
        source=Path(source) if source else None,
        source_index=data.get("source_index"),
        source_start=float(data.get("source_start", 0.0)),
        source_end=float(data.get("source_end", 0.0)),
        confidence=float(data.get("confidence", 0.0)),
        enabled=bool(data.get("enabled", True)),
        manual=bool(data.get("manual", False)),
    )


def analysis_to_dict(analysis: FullStageAnalysis) -> dict[str, Any]:
    return {
        "duration_seconds": analysis.duration_seconds,
        "clips": [clip_to_dict(clip) for clip in analysis.clips],
        "missing_sources": [str(path) for path in analysis.missing_sources],
    }


def analysis_from_dict(data: dict[str, Any]) -> FullStageAnalysis:
    return FullStageAnalysis(
        duration_seconds=float(data["duration_seconds"]),
        clips=tuple(clip_from_dict(clip) for clip in data["clips"]),
        missing_sources=tuple(Path(path) for path in data.get("missing_sources", ())),
    )


def add_clip(analysis_data: dict[str, Any], clip_data: dict[str, Any]) -> dict[str, Any]:
    """Insert one manually described clip and rebuild the surrounding timeline.

    The page edits a plain object, but the rules that decide what a timeline
    looks like after an edit stay in `features.full_stage.matching` - the GUI
    reaches the very same functions through `TimelineModel`.
    """
    analysis = analysis_from_dict(analysis_data)
    return analysis_to_dict(add_manual_clip(analysis, clip_from_dict(clip_data)))


def remove_clip(analysis_data: dict[str, Any], index: int) -> dict[str, Any]:
    analysis = analysis_from_dict(analysis_data)
    return analysis_to_dict(remove_manual_clip(analysis, index))


def edit_clip(analysis_data: dict[str, Any], index: int, changes: dict[str, Any]) -> dict[str, Any]:
    """Apply one in-place cell edit to a clip and hand back the whole analysis.

    This mirrors `TimelineModel._edited`: enabling, the stage range and the
    source range are edited on the clip itself, while inserting and removing go
    through `matching` because those rebuild the gaps around the change.
    """
    analysis = analysis_from_dict(analysis_data)
    if not 0 <= index < len(analysis.clips):
        raise IndexError("clip index out of range")
    clip = analysis.clips[index]
    unmatched = clip.kind == ClipKind.UNMATCHED
    fields: dict[str, Any] = {}
    if "enabled" in changes:
        if unmatched:
            raise ValueError("an unmatched clip cannot be enabled")
        fields["enabled"] = bool(changes["enabled"])
    if "stage_start" in changes or "stage_end" in changes:
        start = float(changes.get("stage_start", clip.stage_start))
        end = float(changes.get("stage_end", clip.stage_end))
        if end > analysis.duration_seconds:
            raise ValueError("stage range exceeds duration")
        fields["stage_start"], fields["stage_end"] = start, end
    if "source_start" in changes or "source_end" in changes:
        if unmatched:
            raise ValueError("an unmatched clip has no source range")
        fields["source_start"] = float(changes.get("source_start", clip.source_start))
        fields["source_end"] = float(changes.get("source_end", clip.source_end))
    if not fields:
        return analysis_to_dict(analysis)
    clips = list(analysis.clips)
    # TimelineClip validates its own ranges, so an invalid edit raises here.
    clips[index] = replace(clip, **fields)
    return analysis_to_dict(replace(analysis, clips=tuple(clips)))
