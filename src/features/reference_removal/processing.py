from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from features.reference_removal.dsp import align_audio, process_audio
from features.reference_removal.models import ReferenceJob
from shared.audio import (
    HI_RES_BIT_DEPTH,
    analyze_audio,
    create_pcm_audio,
    prepare_hi_res_output,
    read_audio,
    resample_audio,
    write_wav_atomic,
)
from shared.processing import CancellationToken, ProcessingResult, ProgressCallback
from shared.progress import report_progress

logger = logging.getLogger(__name__)


def _validate_reference_paths(song: Path, accompaniment: Path, output: Path) -> None:
    resolved_song = song.expanduser().resolve()
    resolved_accompaniment = accompaniment.expanduser().resolve()
    resolved_output = output.expanduser().resolve()
    if resolved_song == resolved_accompaniment:
        raise ValueError("song and accompaniment must be different files")
    if resolved_output in {resolved_song, resolved_accompaniment}:
        raise ValueError("output path must not overwrite an input file")


def run_reference_job(
    job: ReferenceJob,
    token: CancellationToken,
    progress: ProgressCallback = lambda _event: None,
) -> ProcessingResult:
    logger.info(
        "starting reference job: song=%s accompaniment=%s center=%s protection=%s",
        job.song,
        job.accompaniment,
        job.center_extraction,
        job.weak_vocal_protection,
    )
    _validate_reference_paths(job.song, job.accompaniment, job.output)
    song = reference = processed_audio = hi_res_audio = None
    try:
        report_progress(progress, 0, job.language, "loading_song")
        song = read_audio(job.song, token).stereo()
        token.raise_if_cancelled()
        report_progress(progress, 10, job.language, "loading_acc")
        reference = read_audio(job.accompaniment, token).stereo()
        if reference.sample_rate != song.sample_rate:
            report_progress(progress, 18, job.language, "resampling")
            resampled = resample_audio(reference, song.sample_rate, token)
            reference.cleanup()
            reference = resampled
        token.raise_if_cancelled()
        if job.auto_align:
            report_progress(progress, 25, job.language, "aligning")
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
                report_progress(progress, 28, job.language, "align_fail")
            except BaseException:
                alignment.cleanup()
                raise
        length = song.frames
        processed_audio = create_pcm_audio(song.channels, length, song.sample_rate)
        report_progress(progress, 32, job.language, "processing")
        process_audio(
            song.samples,
            reference.samples,
            song.sample_rate,
            job.strength / 100.0,
            job.sigma,
            token,
            processed_audio.samples,
            center_extraction=job.center_extraction,
            weak_vocal_protection=job.weak_vocal_protection,
        )
        report_progress(progress, 84, job.language, "preparing_hi_res")
        hi_res_audio = prepare_hi_res_output(processed_audio, token)
        bit_depth = HI_RES_BIT_DEPTH
        report_progress(progress, 86, job.language, "analyzing_output")
        stats = analyze_audio(hi_res_audio, bit_depth, token)
        report_progress(progress, 90, job.language, "saving")
        write_wav_atomic(job.output, hi_res_audio, bit_depth, token)
        stats = replace(stats, file_size=job.output.stat().st_size)
        report_progress(progress, 100, job.language, "done_status", path=job.output)
        logger.info("reference job completed: %s", job.output.resolve())
        return ProcessingResult((job.output.resolve(),), (stats,))
    finally:
        if hi_res_audio is processed_audio:
            hi_res_audio = None
        for audio in (hi_res_audio, processed_audio, reference, song):
            if audio is not None:
                audio.cleanup()
