from __future__ import annotations

import logging
from pathlib import Path

from shared.audio import AudioData, AudioStats, export_audio
from shared.jobs import OutputTracks, planned_outputs
from shared.processing import CancellationToken, ProgressCallback
from shared.progress import report_progress

logger = logging.getLogger(__name__)

# Where each written stem's analysis and save land on the job's progress bar.
_STEM_PROGRESS = ((86, 89), (93, 96))


def export_tracks(
    vocal: AudioData,
    backing: AudioData | None,
    output: Path,
    tracks: OutputTracks,
    token: CancellationToken,
    progress: ProgressCallback,
) -> tuple[tuple[Path, ...], tuple[AudioStats, ...]]:
    """Write the stems `tracks` asks for, where `planned_outputs` names them.

    Both engines finish the same way, so the order, the names and the progress
    of the export are decided here once.  `backing` is only rendered when the
    job exports it.
    """
    stems = {
        OutputTracks.VOCAL: (vocal,),
        OutputTracks.BACKING: (backing,),
        OutputTracks.BOTH: (vocal, backing),
    }[tracks]
    outputs: list[Path] = []
    stats: list[AudioStats] = []
    for audio, path, (analysing, saving) in zip(
        stems, planned_outputs(output, tracks), _STEM_PROGRESS, strict=False
    ):
        stats.append(export_audio(audio, path, token, progress, analysing, saving))
        audio.release_pages()
        outputs.append(path.resolve())
    report_progress(progress, 100, "done_status", path=outputs[0])
    logger.info("wrote %s", ", ".join(str(path) for path in outputs))
    return tuple(outputs), tuple(stats)
