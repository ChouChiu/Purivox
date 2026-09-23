from __future__ import annotations

import logging
from contextlib import ExitStack

import numpy as np

from features.reference_removal.dsp import align_audio, process_audio
from features.reference_removal.models import (
    IsolationJob,
    IsolationResult,
    StageAnalysis,
    TimelineClip,
)
from features.reference_removal.outputs import export_tracks
from shared.audio import AudioData, conform_rate, copy_audio, create_pcm_audio, read_audio
from shared.dsp import time_stretch
from shared.jobs import OutputTracks
from shared.processing import CancellationToken, ProgressCallback
from shared.progress import report_progress

logger = logging.getLogger(__name__)


def _alignment_quality(mix: np.ndarray, reference: np.ndarray, sample_rate: int) -> float:
    """Estimate how much of the stage a time-aligned stereo reference explains.

    Matching already supplies a close source position.  A second drift
    alignment is useful for some broadcasts, but an uncertain local lag track can
    make an already-correct match worse.  Compare both candidates with small direct
    2x2 fits and keep the robust median.
    """
    length = min(mix.shape[1], reference.shape[1])
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
        mix_window = np.asarray(mix[:, int(start) : end : stride], dtype=np.float64)
        reference_window = np.asarray(reference[:, int(start) : end : stride], dtype=np.float64)
        mix_window -= np.mean(mix_window, axis=1, keepdims=True)
        reference_window -= np.mean(reference_window, axis=1, keepdims=True)
        covariance = reference_window @ reference_window.T
        regularizer = 2e-4 * float(np.trace(covariance)) / max(reference_window.shape[0], 1)
        loaded = covariance + (regularizer + epsilon) * np.eye(reference_window.shape[0])
        transfer = np.linalg.solve(loaded.T, (mix_window @ reference_window.T).T).T
        residual = mix_window - transfer @ reference_window
        energy = float(np.sum(mix_window * mix_window))
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


def _placed_source(
    stage: np.ndarray,
    source: np.ndarray,
    sample_rate: int,
    name: str,
    token: CancellationToken,
    output: np.ndarray,
) -> np.ndarray:
    """Drift-align a matched slice, unless that fits the stage worse than the match did."""
    aligned = align_audio(stage, source, sample_rate, token, output, detect_speed=False)
    raw_quality = _alignment_quality(stage, source, sample_rate)
    aligned_quality = _alignment_quality(stage, aligned, sample_rate)
    if raw_quality > aligned_quality:
        logger.info(
            "keeping matched timeline position for %s (quality %.4f > aligned %.4f)",
            name,
            raw_quality,
            aligned_quality,
        )
        return source
    logger.info(
        "using drift alignment for %s (quality %.4f >= raw %.4f)",
        name,
        aligned_quality,
        raw_quality,
    )
    return aligned


def _render_clip(
    job: IsolationJob,
    clip: TimelineClip,
    stage: AudioData,
    output: AudioData,
    backing: AudioData | None,
    token: CancellationToken,
) -> None:
    """Cancel one clip's source out of its stretch of the stage, in place."""
    rate = stage.sample_rate
    stage_start = round(clip.stage_start * rate)
    stage_end = min(stage.frames, round(clip.stage_end * rate))
    length = stage_end - stage_start
    stage_slice = stage.samples[:, stage_start:stage_end]
    with ExitStack() as owned:
        reference = conform_rate(read_audio(clip.source, token).stereo(), rate, token)
        owned.callback(reference.cleanup)
        source_start = round(clip.source_start * rate)
        source_end = min(reference.frames, round(clip.source_end * rate))
        if length <= 0 or source_end <= source_start:
            return
        source_values = reference.samples[:, source_start:source_end]
        if abs(clip.speed - 1.0) > 1e-9:
            # The analysis found this source at a different tempo, so the slice
            # comes out short or long by exactly that factor; the clip records
            # the ratio, not a stretched file, because the timeline stays in the
            # source's own clock.
            logger.info("stretching %s by %.4f", clip.source.name, clip.speed)
            source_values = time_stretch(source_values, rate, clip.speed, token)
        aligned_audio = owned.enter_context(create_pcm_audio(reference.channels, length, rate))
        aligned = source_values
        if job.auto_align:
            aligned = _placed_source(
                stage_slice, source_values, rate, clip.source.name, token, aligned_audio.samples
            )
        if aligned is not aligned_audio.samples:
            aligned_audio.samples.fill(0.0)
            common = min(length, aligned.shape[1])
            aligned_audio.samples[:, :common] = aligned[:, :common]
        processed = owned.enter_context(create_pcm_audio(stage.channels, length, rate))
        processed_backing = (
            owned.enter_context(create_pcm_audio(stage.channels, length, rate))
            if backing is not None
            else None
        )
        process_audio(
            stage_slice,
            aligned_audio.samples,
            rate,
            job.strength / 100.0,
            job.sigma,
            token,
            processed.samples,
            processed_backing.samples if processed_backing is not None else None,
        )
        _blend_segment(output.samples[:, stage_start:stage_end], processed.samples, rate)
        if processed_backing is not None:
            _blend_segment(
                backing.samples[:, stage_start:stage_end], processed_backing.samples, rate
            )


def render_stage_job(
    job: IsolationJob,
    analysis: StageAnalysis,
    token: CancellationToken,
    progress: ProgressCallback = lambda _event: None,
) -> IsolationResult:
    logger.info(
        "stage render settings: strength=%d sigma=%d auto_align=%s",
        job.strength,
        job.sigma,
        job.auto_align,
    )
    matched = analysis.matched_clips
    if not matched:
        raise ValueError("no source could be matched to the stage audio")

    tracks = OutputTracks(job.tracks)
    with ExitStack() as owned:
        report_progress(progress, 31, "stage_render_loading")
        stage = owned.enter_context(read_audio(job.stage, token).stereo())
        # The render is the stage recording with matched clips cancelled out of
        # it, so it keeps the stage's own rate and depth on the way back out.
        shape = (stage.channels, stage.frames, stage.sample_rate, stage.bit_depth)
        output = owned.enter_context(create_pcm_audio(*shape))
        copy_audio(stage, output, token)
        # The backing track is synthesised from each clip's source, so it starts
        # silent: a range no clip covers carries no estimate.
        backing = (
            owned.enter_context(create_pcm_audio(*shape))
            if tracks is not OutputTracks.VOCAL
            else None
        )
        for index, clip in enumerate(matched):
            token.raise_if_cancelled()
            report_progress(
                progress,
                35 + round(48 * index / len(matched)),
                "stage_render_clip",
                current=index + 1,
                total=len(matched),
                name=clip.source.name,
            )
            _render_clip(job, clip, stage, output, backing, token)
        outputs, stats = export_tracks(output, backing, job.output, tracks, token, progress)
        return IsolationResult(analysis, outputs, stats)
