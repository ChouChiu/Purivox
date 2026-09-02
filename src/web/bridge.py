from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import soundfile as sf

from app.full_stage_processing import analyze_full_stage_job, run_full_stage_job
from features.full_stage import FullStageJob
from features.reference_removal import ReferenceJob, run_reference_job
from shared.audio import AudioStats
from shared.processing import CancellationToken, ProgressEvent
from web.limits import full_stage_peak_bytes, reference_peak_bytes
from web.timeline import add_clip, analysis_from_dict, analysis_to_dict, edit_clip, remove_clip

logger = logging.getLogger(__name__)

# Everything crosses the JavaScript boundary as a JSON string.  Pyodide would
# hand a dict over as a proxy the page has to destroy by hand, and a progress
# callback fires often enough that one leaked proxy per event matters.
JsonCallback = Callable[[str], None]


def _finite(value: float) -> float | None:
    """JSON has no infinity, and a silent stem analyses to -inf dBFS."""
    return value if math.isfinite(value) else None


def _stats_to_dict(stats: AudioStats) -> dict[str, Any]:
    data = asdict(stats)
    data["peak_dbfs"] = _finite(stats.peak_dbfs)
    data["rms_dbfs"] = _finite(stats.rms_dbfs)
    return data


def _progress_callback(on_progress: JsonCallback | None) -> Callable[[ProgressEvent], None]:
    """Adapt the shared progress contract to one JSON string per update.

    The key and its placeholder values travel untranslated: this build has no Qt
    catalogue, so the page translates them against the same `.ts` sources the
    desktop compiles into `.qm`.
    """
    if on_progress is None:
        return lambda _event: None

    def report(event: ProgressEvent) -> None:
        on_progress(
            json.dumps(
                {"value": event.value, "key": event.key, "values": dict(event.values)},
                ensure_ascii=False,
            )
        )

    return report


def _dump(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def probe_audio(request: str) -> str:
    """Report an uploaded file's format from its header, without decoding it.

    libsndfile reads the header alone, so this is cheap even for a long stage
    recording, and it is the same decoder the pipeline will use.  A container
    libsndfile turns down is reported rather than raised: the page decodes those
    with the browser and hands the pipeline a WAV instead, which is the role the
    Qt Multimedia fallback plays on the desktop.
    """
    data = json.loads(request)
    path = Path(data["path"])
    try:
        with sf.SoundFile(path) as source:
            return _dump(
                {
                    "supported": True,
                    "sample_rate": source.samplerate,
                    "channels": source.channels,
                    "frames": source.frames,
                    "seconds": source.frames / source.samplerate if source.samplerate else 0.0,
                    "format": source.format,
                    "subtype": source.subtype,
                }
            )
    except sf.LibsndfileError as error:
        logger.info("libsndfile cannot open %s: %s", path, error)
        return _dump({"supported": False, "reason": str(error)})


def estimate_reference(request: str) -> str:
    """Report whether one single-song job fits in the browser's memory budget."""
    data = json.loads(request)
    estimate = reference_peak_bytes(
        int(data["sample_rate"]),
        float(data["song_seconds"]),
        float(data["accompaniment_seconds"]),
        int(data.get("file_bytes", 0)),
    )
    return _dump(
        {
            "peak_bytes": estimate.peak_bytes,
            "budget_bytes": estimate.budget_bytes,
            "fits": estimate.fits,
            "tight": estimate.tight,
            "fraction": estimate.fraction,
        }
    )


def estimate_full_stage(request: str) -> str:
    """Report whether one full-stage render fits in the browser's memory budget."""
    data = json.loads(request)
    estimate = full_stage_peak_bytes(
        int(data["sample_rate"]),
        float(data["stage_seconds"]),
        float(data["longest_source_seconds"]),
        int(data.get("file_bytes", 0)),
    )
    return _dump(
        {
            "peak_bytes": estimate.peak_bytes,
            "budget_bytes": estimate.budget_bytes,
            "fits": estimate.fits,
            "tight": estimate.tight,
            "fraction": estimate.fraction,
        }
    )


def run_reference(request: str, on_progress: JsonCallback | None = None) -> str:
    """Run one single-song cancellation over files already in the Pyodide filesystem."""
    data = json.loads(request)
    job = ReferenceJob(
        song=Path(data["song"]),
        accompaniment=Path(data["accompaniment"]),
        output=Path(data["output"]),
        strength=int(data.get("strength", 75)),
        sigma=int(data.get("sigma", 3)),
        auto_align=bool(data.get("auto_align", True)),
    )
    result = run_reference_job(job, CancellationToken(), _progress_callback(on_progress))
    return _dump(
        {
            "outputs": [str(path) for path in result.outputs],
            "audio_stats": [_stats_to_dict(stats) for stats in result.audio_stats],
        }
    )


def _full_stage_job(data: dict[str, Any]) -> FullStageJob:
    return FullStageJob(
        stage=Path(data["stage"]),
        sources=tuple(Path(source) for source in data["sources"]),
        output=Path(data["output"]),
        strength=int(data.get("strength", 75)),
        sigma=int(data.get("sigma", 3)),
        include_fragments=bool(data.get("include_fragments", True)),
        auto_align=bool(data.get("auto_align", True)),
    )


def analyze_stage(request: str, on_progress: JsonCallback | None = None) -> str:
    """Match the sources against the stage recording and return the timeline."""
    data = json.loads(request)
    result = analyze_full_stage_job(
        _full_stage_job(data), CancellationToken(), _progress_callback(on_progress)
    )
    return _dump({"analysis": analysis_to_dict(result.analysis)})


def render_stage(request: str, on_progress: JsonCallback | None = None) -> str:
    """Cancel the enabled clips of an edited timeline out of the stage recording."""
    data = json.loads(request)
    analysis = analysis_from_dict(data["analysis"])
    result = run_full_stage_job(
        _full_stage_job(data), analysis, CancellationToken(), _progress_callback(on_progress)
    )
    return _dump(
        {
            "analysis": analysis_to_dict(result.analysis),
            "outputs": [str(path) for path in result.outputs],
            "audio_stats": [_stats_to_dict(stats) for stats in result.audio_stats],
        }
    )


def add_timeline_clip(request: str) -> str:
    data = json.loads(request)
    return _dump({"analysis": add_clip(data["analysis"], data["clip"])})


def remove_timeline_clip(request: str) -> str:
    data = json.loads(request)
    return _dump({"analysis": remove_clip(data["analysis"], int(data["index"]))})


def edit_timeline_clip(request: str) -> str:
    data = json.loads(request)
    return _dump({"analysis": edit_clip(data["analysis"], int(data["index"]), data["changes"])})
