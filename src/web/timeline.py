from __future__ import annotations

from pathlib import Path
from typing import Any

from features.reference_removal import (
    ClipKind,
    StageAnalysis,
    TimelineClip,
    add_manual_clip,
    remove_manual_clip,
)
from features.reference_removal import edit_clip as edit_timeline_clip


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
        "speed": clip.speed,
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
        speed=float(data.get("speed", 1.0)),
    )


def analysis_to_dict(analysis: StageAnalysis) -> dict[str, Any]:
    return {
        "duration_seconds": analysis.duration_seconds,
        "clips": [clip_to_dict(clip) for clip in analysis.clips],
        "missing_sources": [str(path) for path in analysis.missing_sources],
    }


def analysis_from_dict(data: dict[str, Any]) -> StageAnalysis:
    return StageAnalysis(
        duration_seconds=float(data["duration_seconds"]),
        clips=tuple(clip_from_dict(clip) for clip in data["clips"]),
        missing_sources=tuple(Path(path) for path in data.get("missing_sources", ())),
    )


def add_clip(analysis_data: dict[str, Any], clip_data: dict[str, Any]) -> dict[str, Any]:
    """Insert one manually described clip and rebuild the surrounding timeline.

    The page edits a plain object, but the rules that decide what a timeline
    looks like after an edit stay in `features.reference_removal.matching` - the GUI
    reaches the very same functions through `TimelineModel`.
    """
    analysis = analysis_from_dict(analysis_data)
    return analysis_to_dict(add_manual_clip(analysis, clip_from_dict(clip_data)))


def remove_clip(analysis_data: dict[str, Any], index: int) -> dict[str, Any]:
    analysis = analysis_from_dict(analysis_data)
    return analysis_to_dict(remove_manual_clip(analysis, index))


def edit_clip(analysis_data: dict[str, Any], index: int, changes: dict[str, Any]) -> dict[str, Any]:
    """Apply one in-place cell edit to a clip and hand back the whole analysis.

    The rule is `features.reference_removal.edit_clip`, the one `TimelineModel`
    applies to the desktop table; this only reads the page's partial change.
    """
    analysis = analysis_from_dict(analysis_data)
    clip = analysis.clips[index] if 0 <= index < len(analysis.clips) else None
    stage_range = source_range = None
    if clip is not None and ("stage_start" in changes or "stage_end" in changes):
        stage_range = (
            float(changes.get("stage_start", clip.stage_start)),
            float(changes.get("stage_end", clip.stage_end)),
        )
    if clip is not None and ("source_start" in changes or "source_end" in changes):
        source_range = (
            float(changes.get("source_start", clip.source_start)),
            float(changes.get("source_end", clip.source_end)),
        )
    enabled = bool(changes["enabled"]) if "enabled" in changes else None
    return analysis_to_dict(
        edit_timeline_clip(
            analysis,
            index,
            enabled=enabled,
            stage_range=stage_range,
            source_range=source_range,
        )
    )
