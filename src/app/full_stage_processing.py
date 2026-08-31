from __future__ import annotations

import logging
from dataclasses import replace

import numpy as np

from features.full_stage import (
    ClipKind,
    FullStageAnalysis,
    FullStageJob,
    FullStageResult,
    analyze_full_stage,
)
from features.reference_removal.dsp import align_audio, process_audio
from shared.audio import (
    HI_RES_BIT_DEPTH,
    analyze_audio,
    copy_audio,
    create_pcm_audio,
    prepare_hi_res_output,
    read_audio,
    resample_audio,
    write_wav_atomic,
)
from shared.processing import CancellationToken, ProgressCallback
from shared.progress import report_progress

logger = logging.getLogger(__name__)


def analyze_full_stage_job(
    job: FullStageJob,
    token: CancellationToken,
    progress: ProgressCallback = lambda _event: None,
) -> FullStageResult:
    return FullStageResult(analyze_full_stage(job, token, progress))


def _alignment_quality(song: np.ndarray, reference: np.ndarray, sample_rate: int) -> float:
    """Estimate how much of the stage a time-aligned stereo reference explains.

    Full-stage matching already supplies a close source position.  A second drift
    alignment is useful for some broadcasts, but an uncertain local lag track can
    make an already-correct match worse.  Compare both candidates with small direct
    2x2 fits and keep the robust median.
    """
    length = min(song.shape[1], reference.shape[1])
    window = min(max(4 * sample_rate, 4096), length)
    if window < 64:
        return 0.0
    count = min(10, max(length // window, 1))
    starts = np.linspace(0, max(length - window, 0), count, dtype=np.int64)
    stride = max(window // 65_536, 1)
    scores: list[float] = []
    epsilon = 1e-12
    for start in starts:
        end = int(start) + window
        mix = np.asarray(song[:, int(start) : end : stride], dtype=np.float64)
        accompaniment = np.asarray(reference[:, int(start) : end : stride], dtype=np.float64)
        mix -= np.mean(mix, axis=1, keepdims=True)
        accompaniment -= np.mean(accompaniment, axis=1, keepdims=True)
        covariance = accompaniment @ accompaniment.T
        regularizer = 2e-4 * float(np.trace(covariance)) / max(accompaniment.shape[0], 1)
        loaded = covariance + (regularizer + epsilon) * np.eye(accompaniment.shape[0])
        transfer = np.linalg.solve(loaded.T, (mix @ accompaniment.T).T).T
        residual = mix - transfer @ accompaniment
        energy = float(np.sum(mix * mix))
        scores.append(1.0 - float(np.sum(residual * residual)) / max(energy, epsilon))
    return float(np.median(scores))


def _blend_segment(destination: np.ndarray, processed: np.ndarray, sample_rate: int) -> None:
    length = destination.shape[1]
    fade = min(max(round(0.05 * sample_rate), 1), length // 2)
    if fade <= 0:
        destination[:] = processed
        return
    weight = np.ones(length, dtype=np.float32)
    weight[:fade] = np.linspace(0.0, 1.0, fade, endpoint=False, dtype=np.float32)
    weight[-fade:] = np.linspace(1.0, 0.0, fade, endpoint=False, dtype=np.float32)
    destination *= 1.0 - weight
    destination += processed * weight


def run_full_stage_job(
    job: FullStageJob,
    analysis: FullStageAnalysis,
    token: CancellationToken,
    progress: ProgressCallback = lambda _event: None,
) -> FullStageResult:
    logger.info(
        "full-stage render settings: strength=%d sigma=%d auto_align=%s include_fragments=%s",
        job.strength,
        job.sigma,
        job.auto_align,
        job.include_fragments,
    )
    matched = tuple(
        clip
        for clip in analysis.matched_clips
        if clip.kind == ClipKind.SONG or job.include_fragments
    )
    if not matched:
        raise ValueError("no source could be matched to the stage audio")

    stage = output = hi_res_output = None
    try:
        report_progress(progress, 31, "stage_render_loading")
        stage = read_audio(job.stage, token).stereo()
        output = create_pcm_audio(stage.channels, stage.frames, stage.sample_rate)
        copy_audio(stage, output, token)
        for index, clip in enumerate(matched):
            token.raise_if_cancelled()
            report_progress(
                progress,
                35 + round(48 * index / max(len(matched), 1)),
                "stage_render_clip",
                current=index + 1,
                total=len(matched),
                name=clip.source.name if clip.source else "",
            )
            reference = aligned_audio = processed_audio = None
            try:
                reference = read_audio(clip.source, token).stereo()
                if reference.sample_rate != stage.sample_rate:
                    resampled = resample_audio(reference, stage.sample_rate, token)
                    reference.cleanup()
                    reference = resampled

                stage_start = max(0, round(clip.stage_start * stage.sample_rate))
                stage_end = min(stage.frames, round(clip.stage_end * stage.sample_rate))
                source_start = max(0, round(clip.source_start * stage.sample_rate))
                source_end = min(reference.frames, round(clip.source_end * stage.sample_rate))
                length = stage_end - stage_start
                if length <= 0 or source_end <= source_start:
                    continue
                aligned_audio = create_pcm_audio(reference.channels, length, stage.sample_rate)
                source_values = reference.samples[:, source_start:source_end]
                if job.auto_align:
                    aligned = align_audio(
                        stage.samples[:, stage_start:stage_end],
                        source_values,
                        stage.sample_rate,
                        token,
                        aligned_audio.samples,
                    )
                    raw_quality = _alignment_quality(
                        stage.samples[:, stage_start:stage_end],
                        source_values,
                        stage.sample_rate,
                    )
                    aligned_quality = _alignment_quality(
                        stage.samples[:, stage_start:stage_end],
                        aligned,
                        stage.sample_rate,
                    )
                    if raw_quality > aligned_quality:
                        logger.info(
                            "keeping matched timeline position for %s "
                            "(quality %.4f > aligned %.4f)",
                            clip.source.name,
                            raw_quality,
                            aligned_quality,
                        )
                        aligned = source_values
                    else:
                        logger.info(
                            "using drift alignment for %s (quality %.4f >= raw %.4f)",
                            clip.source.name,
                            aligned_quality,
                            raw_quality,
                        )
                else:
                    aligned = source_values
                if aligned is not aligned_audio.samples:
                    aligned_audio.samples.fill(0.0)
                    common = min(length, aligned.shape[1])
                    aligned_audio.samples[:, :common] = aligned[:, :common]
                processed_audio = create_pcm_audio(stage.channels, length, stage.sample_rate)
                process_audio(
                    stage.samples[:, stage_start:stage_end],
                    aligned_audio.samples,
                    stage.sample_rate,
                    job.strength / 100.0,
                    job.sigma,
                    token,
                    processed_audio.samples,
                )
                _blend_segment(
                    output.samples[:, stage_start:stage_end],
                    processed_audio.samples,
                    stage.sample_rate,
                )
            finally:
                for audio in (processed_audio, aligned_audio, reference):
                    if audio is not None:
                        audio.cleanup()

        report_progress(progress, 84, "preparing_hi_res")
        hi_res_output = prepare_hi_res_output(output, token)
        report_progress(progress, 86, "analyzing_output")
        stats = analyze_audio(hi_res_output, HI_RES_BIT_DEPTH, token)
        output.release_pages()
        report_progress(progress, 91, "saving")
        write_wav_atomic(job.output, hi_res_output, HI_RES_BIT_DEPTH, token)
        stats = replace(stats, file_size=job.output.stat().st_size)
        report_progress(progress, 100, "done_status", path=job.output)
        logger.info("full-stage render completed: %s", job.output.resolve())
        return FullStageResult(analysis, (job.output.resolve(),), (stats,))
    finally:
        if hi_res_output is output:
            hi_res_output = None
        for audio in (hi_res_output, output, stage):
            if audio is not None:
                audio.cleanup()
