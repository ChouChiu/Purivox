from __future__ import annotations

import logging
from pathlib import Path

from features.reference_removal.dsp import align_audio, process_audio
from features.reference_removal.models import ReferenceJob
from shared.audio import (
    AudioStats,
    create_pcm_audio,
    export_audio,
    read_audio,
    resample_audio,
    subtract_into,
)
from shared.jobs import OutputTracks, planned_outputs
from shared.processing import CancellationToken, ProcessingResult, ProgressCallback
from shared.progress import report_progress

logger = logging.getLogger(__name__)


def _validate_reference_paths(song: Path, accompaniment: Path, outputs: tuple[Path, ...]) -> None:
    resolved_song = song.expanduser().resolve()
    resolved_accompaniment = accompaniment.expanduser().resolve()
    if resolved_song == resolved_accompaniment:
        raise ValueError("song and accompaniment must be different files")
    inputs = {resolved_song, resolved_accompaniment}
    if any(output.expanduser().resolve() in inputs for output in outputs):
        raise ValueError("output path must not overwrite an input file")


def run_reference_job(
    job: ReferenceJob,
    token: CancellationToken,
    progress: ProgressCallback = lambda _event: None,
) -> ProcessingResult:
    logger.info(
        "starting reference job: song=%s accompaniment=%s",
        job.song,
        job.accompaniment,
    )
    tracks = OutputTracks(job.tracks)
    planned = planned_outputs(job.output, tracks)
    _validate_reference_paths(job.song, job.accompaniment, planned)
    song = reference = processed_audio = None
    try:
        report_progress(progress, 0, "loading_song")
        song = read_audio(job.song, token).stereo()
        token.raise_if_cancelled()
        report_progress(progress, 10, "loading_acc")
        reference = read_audio(job.accompaniment, token).stereo()
        if reference.sample_rate != song.sample_rate:
            report_progress(progress, 18, "resampling")
            resampled = resample_audio(reference, song.sample_rate, token)
            reference.cleanup()
            reference = resampled
        token.raise_if_cancelled()
        if job.auto_align:
            report_progress(progress, 25, "aligning")
            alignment = create_pcm_audio(reference.channels, song.frames, song.sample_rate)
            try:
                aligned = align_audio(
                    song.samples,
                    reference.samples,
                    song.sample_rate,
                    token,
                    alignment.samples,
                )
                if aligned is alignment.samples:
                    reference.cleanup()
                    reference = alignment
                else:
                    alignment.cleanup()
            except (ArithmeticError, ValueError) as error:
                alignment.cleanup()
                logger.warning("alignment failed; using original timeline: %s", error)
                report_progress(progress, 28, "align_fail")
            except BaseException:
                alignment.cleanup()
                raise
        length = song.frames
        # The result is the song with the accompaniment taken out of it, so it
        # is exported at the song's own rate and depth rather than at a fixed
        # export format: resampling it up would only make the file larger.
        processed_audio = create_pcm_audio(song.channels, length, song.sample_rate, song.bit_depth)
        report_progress(progress, 32, "processing")
        process_audio(
            song.samples,
            reference.samples,
            song.sample_rate,
            job.strength / 100.0,
            job.sigma,
            token,
            processed_audio.samples,
        )
        outputs: list[Path] = []
        stats: list[AudioStats] = []
        if tracks is not OutputTracks.BACKING:
            stats.append(export_audio(processed_audio, job.output, token, progress, 86, 89))
            outputs.append(job.output.resolve())
        if tracks is not OutputTracks.VOCAL:
            # The backing track is what cancellation took out, so it is the stage
            # recording less the vocal - which also gives it the level the
            # accompaniment actually had on stage.  The vocal is already on disk
            # (or was never asked for), so the difference overwrites it in place.
            subtract_into(song, processed_audio, token)
            backing = planned[-1]
            stats.append(export_audio(processed_audio, backing, token, progress, 93, 96))
            outputs.append(backing.resolve())
        report_progress(progress, 100, "done_status", path=outputs[0])
        logger.info("reference job completed: %s", ", ".join(str(path) for path in outputs))
        return ProcessingResult(tuple(outputs), tuple(stats))
    finally:
        for audio in (processed_audio, reference, song):
            if audio is not None:
                audio.cleanup()
