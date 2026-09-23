from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

import soundfile as sf

from features.reference_removal.dsp import align_audio, process_audio
from features.reference_removal.matching import analyze_stage
from features.reference_removal.models import (
    ClipKind,
    IsolationJob,
    IsolationResult,
    ReferenceJob,
    StageAnalysis,
)
from features.reference_removal.outputs import export_tracks
from features.reference_removal.rendering import render_stage_job
from shared.audio import AudioData, conform_rate, create_pcm_audio, read_audio
from shared.jobs import OutputTracks
from shared.processing import (
    CancellationToken,
    ProcessingResult,
    ProgressCallback,
    ProgressEvent,
)
from shared.progress import report_progress

logger = logging.getLogger(__name__)

# A source this close in length to the recording is the recording's own content
# rather than a song inside it; see `_is_the_recordings_own_content`.
_WHOLE_RECORDING_TOLERANCE_SECONDS = 1.0


def _aligned_reference(
    stage: AudioData,
    reference: AudioData,
    token: CancellationToken,
    progress: ProgressCallback,
) -> AudioData:
    """The reference drift-aligned onto the stage timeline, or itself unchanged.

    Alignment failing is the one documented fallback: the reference is used
    where it lies, which is what a user who switched alignment off would get.
    """
    alignment = create_pcm_audio(reference.channels, stage.frames, stage.sample_rate)
    try:
        aligned = align_audio(
            stage.samples, reference.samples, stage.sample_rate, token, alignment.samples
        )
    except (ArithmeticError, ValueError) as error:
        alignment.cleanup()
        logger.warning("alignment failed; using original timeline: %s", error)
        report_progress(progress, 28, "align_fail")
        return reference
    except BaseException:
        alignment.cleanup()
        raise
    if aligned is not alignment.samples:
        alignment.cleanup()
        return reference
    reference.cleanup()
    return alignment


def run_reference_job(
    job: ReferenceJob,
    token: CancellationToken,
    progress: ProgressCallback = lambda _event: None,
) -> ProcessingResult:
    logger.info("starting reference job: stage=%s source=%s", job.stage, job.source)
    tracks = OutputTracks(job.tracks)
    stage = reference = processed_audio = backing_audio = None
    try:
        report_progress(progress, 0, "loading_stage")
        stage = read_audio(job.stage, token).stereo()
        report_progress(progress, 10, "loading_source")
        reference = read_audio(job.source, token).stereo()
        if reference.sample_rate != stage.sample_rate:
            report_progress(progress, 18, "resampling")
            reference = conform_rate(reference, stage.sample_rate, token)
        if job.auto_align:
            report_progress(progress, 25, "aligning")
            reference = _aligned_reference(stage, reference, token, progress)
        # The result is the stage recording with the backing taken out of it,
        # so it keeps that recording's own rate and depth rather than a fixed
        # export format: resampling it up would only make the file larger.
        processed_audio = create_pcm_audio(
            stage.channels, stage.frames, stage.sample_rate, stage.bit_depth
        )
        if tracks is not OutputTracks.VOCAL:
            backing_audio = create_pcm_audio(
                stage.channels, stage.frames, stage.sample_rate, stage.bit_depth
            )
        report_progress(progress, 32, "processing")
        process_audio(
            stage.samples,
            reference.samples,
            stage.sample_rate,
            job.strength / 100.0,
            job.sigma,
            token,
            processed_audio.samples,
            backing_audio.samples if backing_audio is not None else None,
        )
        outputs, stats = export_tracks(
            processed_audio, backing_audio, job.output, tracks, token, progress
        )
        return ProcessingResult(outputs, stats)
    finally:
        for audio in (backing_audio, processed_audio, reference, stage):
            if audio is not None:
                audio.cleanup()


def _scaled_progress(progress: ProgressCallback, low: int, high: int) -> ProgressCallback:
    """Map one pipeline's own 0..100 reporting into one band of a job's.

    Each pipeline reports the fraction of itself it has finished; a job that
    runs two of them hands each a band so the bar only ever moves forward.
    """

    def report(event: ProgressEvent) -> None:
        progress(replace(event, value=low + round((high - low) * event.value / 100)))

    return report


def _source_seconds(path: Path) -> float | None:
    """How long a source is, from its header alone; `None` when unreadable."""
    try:
        info = sf.info(str(path))
    except (OSError, RuntimeError):
        return None
    return info.frames / info.samplerate if info.samplerate else None


def _is_the_recordings_own_content(job: IsolationJob, analysis: StageAnalysis) -> bool:
    """Whether a lone source is the recording itself rather than a song inside it.

    A source about as long as the recording is the single-song case this project
    shipped first: the whole-file path aligns the two directly and corrects a
    clock difference between them.  Matching cannot stand in for that - a
    capture running at a different tempo is exactly what stops it placing the
    source, so it would hand the renderer a clip a few seconds out and lose
    depth the whole-file path keeps.  A source much shorter than the recording
    is a song located inside a longer take, which only the matched clips handle.
    """
    if len(job.sources) != 1:
        return False
    seconds = _source_seconds(job.sources[0])
    if seconds is None:
        return False
    return seconds >= analysis.duration_seconds - _WHOLE_RECORDING_TOLERANCE_SECONDS


def _timeline_was_edited(analysis: StageAnalysis) -> bool:
    """Whether the analysis carries a decision the user made, not just matches."""
    return any(clip.manual for clip in analysis.clips) or any(
        clip.kind is not ClipKind.UNMATCHED and not clip.enabled for clip in analysis.clips
    )


def _cancel_as_a_whole(
    job: IsolationJob,
    analysis: StageAnalysis,
    token: CancellationToken,
    progress: ProgressCallback,
    key: str,
) -> IsolationResult:
    """Run the whole-file path over a lone source and keep the analysis it had."""
    report_progress(progress, 25, key)
    result = run_reference_job(
        ReferenceJob(
            stage=job.stage,
            source=job.sources[0],
            output=job.output,
            strength=job.strength,
            sigma=job.sigma,
            auto_align=job.auto_align,
            tracks=job.tracks,
        ),
        token,
        _scaled_progress(progress, 25, 100),
    )
    return IsolationResult(analysis, result.outputs, result.audio_stats)


def run_isolation_job(
    job: IsolationJob,
    analysis: StageAnalysis | None,
    token: CancellationToken,
    progress: ProgressCallback = lambda _event: None,
) -> IsolationResult:
    """Cancel the sources out of the stage recording, matching them first.

    One entry point for one source or many.  Each source is located in the
    recording and cancelled out of its own stretch of it, which is what keeps a
    song that starts halfway through and a show of many songs from being two
    separate jobs.

    Which engine runs is a question of geometry, not of match quality.  A lone
    source as long as the recording is the recording's own content, and the
    whole-file path - which aligns the two over their whole length and corrects
    a clock difference between them - is the tool for it.  Anything else is a
    song located inside a longer take, which only the matched clips handle.  A
    lone source the matcher cannot place falls back to the whole-file path too:
    a canceller that finds no correlation leaves the recording alone, so the
    fallback cannot damage what it fails to explain.

    `analysis` is the timeline the user checked.  It is rendered as it stands,
    because a timeline they edited is a decision: only an untouched one leaves
    the choice of engine to the geometry above.
    """
    if analysis is None:
        analysis = analyze_stage(job, token, _scaled_progress(progress, 0, 25))
    edited = _timeline_was_edited(analysis)
    if analysis.matched_clips:
        if not edited and _is_the_recordings_own_content(job, analysis):
            logger.info("%s is the whole recording; cancelling it as one take", job.sources[0])
            return _cancel_as_a_whole(job, analysis, token, progress, "stage_whole_recording")
        return render_stage_job(job, analysis, token, progress)
    if len(job.sources) > 1 or edited:
        # Several songs against one recording, or a timeline the user emptied,
        # is a request this pipeline cannot answer by cancelling everything.
        raise ValueError("no source could be matched to the stage audio")
    logger.info("no source matched %s; cancelling the recording as a whole", job.stage)
    return _cancel_as_a_whole(job, analysis, token, progress, "stage_match_fallback")
