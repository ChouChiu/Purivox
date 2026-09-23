from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from features.reference_removal.models import (
    ClipKind,
    IsolationJob,
    ReferenceJob,
    StageAnalysis,
    TimelineClip,
)
from features.reference_removal.processing import (
    _scaled_progress,
    run_isolation_job,
    run_reference_job,
)
from shared.jobs import OutputTracks
from shared.processing import CancellationToken, ProgressEvent


def test_reference_pipeline_end_to_end(tmp_path: Path):
    sample_rate = 8_000
    time = np.arange(sample_rate) / sample_rate
    vocal = 0.3 * np.sin(2 * np.pi * 440 * time)
    reference = 0.2 * np.sin(2 * np.pi * 110 * time)
    stage = tmp_path / "stage.wav"
    source = tmp_path / "instrumental.wav"
    output = tmp_path / "vocals.wav"
    sf.write(stage, np.stack([vocal + reference] * 2, axis=1), sample_rate)
    sf.write(source, np.stack([reference] * 2, axis=1), sample_rate)
    events = []
    result = run_reference_job(
        ReferenceJob(stage, source, output, 100, 8, False),
        CancellationToken(),
        events.append,
    )
    assert result.outputs == (output.resolve(),)
    assert len(result.audio_stats) == 1
    stats = result.audio_stats[0]
    assert stats.duration_seconds == 1
    assert stats.sample_rate == sample_rate
    assert stats.channels == 2
    assert stats.bit_depth == 16
    assert stats.peak_dbfs <= 0
    assert stats.rms_dbfs < stats.peak_dbfs
    assert stats.file_size == output.stat().st_size
    assert output.is_file()
    data, rate = sf.read(output, always_2d=True)
    assert rate == sample_rate and data.shape == (sample_rate, 2)
    assert sf.info(output).subtype == "PCM_16", "a 16-bit source must not be inflated to 24"
    assert events[-1].value == 100


def test_reference_pipeline_retains_stage_duration_with_a_short_reference(tmp_path: Path):
    sample_rate = 8_000
    stage_time = np.arange(2 * sample_rate) / sample_rate
    reference_time = np.arange(sample_rate) / sample_rate
    vocal = 0.2 * np.sin(2 * np.pi * 440 * stage_time)
    reference = 0.15 * np.sin(2 * np.pi * 110 * reference_time)
    padded_reference = np.pad(reference, (0, sample_rate))
    stage = tmp_path / "long-stage.wav"
    source = tmp_path / "short-reference.wav"
    output = tmp_path / "full-length-output.wav"
    sf.write(stage, np.stack([vocal + padded_reference] * 2, axis=1), sample_rate)
    sf.write(source, np.stack([reference] * 2, axis=1), sample_rate)

    run_reference_job(
        ReferenceJob(stage, source, output, 100, 8, False),
        CancellationToken(),
    )

    data, rate = sf.read(output, always_2d=True)
    assert rate == sample_rate
    assert data.shape == (2 * sample_rate, 2)


def test_reference_job_rejects_same_stage_and_source(tmp_path: Path):
    stage = tmp_path / "stage.wav"
    with pytest.raises(ValueError, match="must not also be a source"):
        ReferenceJob(stage, stage, tmp_path / "output.wav", 100, 8, False)


def _cancellation_inputs(
    tmp_path: Path, seconds: float = 1.0, source_seconds: float | None = None
) -> tuple[Path, Path]:
    """A stage recording holding a backing track plus a voice that is not in it."""
    sample_rate = 8_000
    stage_time = np.arange(int(sample_rate * seconds)) / sample_rate
    source_time = np.arange(int(sample_rate * (source_seconds or seconds))) / sample_rate
    backing = 0.2 * np.sin(2 * np.pi * 110 * source_time)
    vocal = 0.3 * np.sin(2 * np.pi * 440 * stage_time)
    stage = tmp_path / "stage.wav"
    source = tmp_path / "instrumental.wav"
    sf.write(
        stage,
        np.stack([vocal + np.pad(backing, (0, vocal.size - backing.size))] * 2, axis=1),
        sample_rate,
        subtype="PCM_24",
    )
    sf.write(source, np.stack([backing] * 2, axis=1), sample_rate, subtype="PCM_24")
    return stage, source


def test_the_backing_track_is_the_source_the_playback_carried(tmp_path: Path):
    """The backing is rendered from the source, not from the stage less the vocal."""
    stage, source = _cancellation_inputs(tmp_path)
    output = tmp_path / "stage_vocals.wav"
    result = run_reference_job(
        ReferenceJob(stage, source, output, 100, 8, False, OutputTracks.BOTH),
        CancellationToken(),
    )
    assert result.outputs == (output.resolve(), (tmp_path / "stage_backing.wav").resolve())
    assert len(result.audio_stats) == 2
    vocal, _ = sf.read(result.outputs[0], always_2d=True)
    backing, _ = sf.read(result.outputs[1], always_2d=True)
    reference, _ = sf.read(source, always_2d=True)
    body = slice(100, -100)
    # The source's own waveform, at the level the stage carried it.
    assert np.corrcoef(backing[body].ravel(), reference[body].ravel())[0, 1] > 0.99
    assert np.isclose(
        np.sqrt(np.mean(backing[body] ** 2)),
        np.sqrt(np.mean(reference[body] ** 2)),
        rtol=0.05,
    )
    # And none of the live voice, which the source does not contain.
    live = np.sin(2 * np.pi * 440 * np.arange(vocal.shape[0]) / 8_000)
    tone = np.tile(live[body], 2)
    assert abs(float(np.dot(backing[body].ravel(), tone) / np.dot(tone, tone))) < 0.01


def test_backing_only_writes_the_named_path_and_nothing_else(tmp_path: Path):
    """`output` is whichever stem was asked for, so the CLI cannot answer elsewhere."""
    stage, source = _cancellation_inputs(tmp_path)
    output = tmp_path / "just_the_backing.wav"
    result = run_reference_job(
        ReferenceJob(stage, source, output, 100, 8, False, OutputTracks.BACKING),
        CancellationToken(),
    )
    assert result.outputs == (output.resolve(),)
    assert not (tmp_path / "just_the_backing_backing.wav").exists()
    assert not (tmp_path / "stage_vocals.wav").exists()
    backing, _ = sf.read(output, always_2d=True)
    assert np.max(np.abs(backing)) > 0.1


def test_a_derived_backing_path_may_not_overwrite_an_input(tmp_path: Path):
    stage, source = _cancellation_inputs(tmp_path)
    collision = tmp_path / "instrumental_vocals.wav"
    source.replace(tmp_path / "instrumental_backing.wav")
    with pytest.raises(ValueError):
        run_reference_job(
            ReferenceJob(
                stage,
                tmp_path / "instrumental_backing.wav",
                collision,
                100,
                8,
                False,
                OutputTracks.BOTH,
            ),
            CancellationToken(),
        )


def _unmatched(duration: float) -> StageAnalysis:
    return StageAnalysis(duration, (TimelineClip(ClipKind.UNMATCHED, 0.0, duration),))


def _matched(source: Path, duration: float) -> StageAnalysis:
    return StageAnalysis(
        duration,
        (
            TimelineClip(
                ClipKind.SONG,
                0.0,
                duration,
                source=source,
                source_index=0,
                source_start=0.0,
                source_end=duration,
                confidence=1.0,
            ),
        ),
    )


def test_a_matched_analysis_renders_its_clips(tmp_path: Path):
    """A source shorter than the recording is a song inside it, not all of it."""
    stage, source = _cancellation_inputs(tmp_path, seconds=4.0, source_seconds=1.0)
    output = tmp_path / "matched.wav"
    analysis = _matched(source, 4.0)
    events: list[ProgressEvent] = []
    result = run_isolation_job(
        IsolationJob(stage, (source,), output, 100, 8, auto_align=False),
        analysis,
        CancellationToken(),
        events.append,
    )
    assert result.analysis is analysis
    assert result.outputs == (output.resolve(),)
    assert output.is_file()
    assert next(event.key for event in events) == "stage_render_loading"


def test_a_lone_source_that_cannot_be_matched_is_cancelled_as_a_whole(tmp_path: Path):
    """The fallback is the whole-file path, announced so the bar explains itself."""
    stage, source = _cancellation_inputs(tmp_path, seconds=4.0, source_seconds=1.0)
    output = tmp_path / "fallback.wav"
    events: list[ProgressEvent] = []
    result = run_isolation_job(
        IsolationJob(stage, (source,), output, 100, 8, auto_align=False),
        _unmatched(4.0),
        CancellationToken(),
        events.append,
    )
    assert result.outputs == (output.resolve(),)
    assert output.is_file()
    assert next(event.key for event in events) == "stage_match_fallback"
    assert events[-1].value == 100


def test_a_lone_source_as_long_as_the_recording_is_cancelled_as_one_take(tmp_path: Path):
    """The single-song case keeps the whole-file path, clock correction and all."""
    stage, source = _cancellation_inputs(tmp_path)
    output = tmp_path / "one_take.wav"
    events: list[ProgressEvent] = []
    result = run_isolation_job(
        IsolationJob(stage, (source,), output, 100, 8, auto_align=False),
        _matched(source, 1.0),
        CancellationToken(),
        events.append,
    )
    assert result.outputs == (output.resolve(),)
    assert output.is_file()
    assert next(event.key for event in events) == "stage_whole_recording"


def test_an_edited_timeline_decides_the_engine_itself(tmp_path: Path):
    """A timeline the user touched is a decision, not a hint."""
    stage, source = _cancellation_inputs(tmp_path)
    output = tmp_path / "edited.wav"
    events: list[ProgressEvent] = []
    analysis = StageAnalysis(
        1.0,
        (
            TimelineClip(
                ClipKind.SONG,
                0.0,
                1.0,
                source=source,
                source_index=0,
                source_start=0.0,
                source_end=1.0,
                confidence=1.0,
                manual=True,
            ),
        ),
    )
    result = run_isolation_job(
        IsolationJob(stage, (source,), output, 100, 8, auto_align=False),
        analysis,
        CancellationToken(),
        events.append,
    )
    assert result.outputs == (output.resolve(),)
    assert next(event.key for event in events) == "stage_render_loading"


def test_a_timeline_with_every_clip_disabled_renders_nothing(tmp_path: Path):
    stage, source = _cancellation_inputs(tmp_path)
    analysis = StageAnalysis(
        1.0,
        (
            TimelineClip(
                ClipKind.SONG,
                0.0,
                1.0,
                source=source,
                source_index=0,
                source_start=0.0,
                source_end=1.0,
                confidence=1.0,
                enabled=False,
            ),
        ),
    )
    with pytest.raises(ValueError, match="no source could be matched"):
        run_isolation_job(
            IsolationJob(stage, (source,), tmp_path / "out.wav", 100, 8, auto_align=False),
            analysis,
            CancellationToken(),
        )


def test_several_sources_that_cannot_be_matched_are_refused(tmp_path: Path):
    """Cancelling a whole show against one song would remove the wrong content."""
    stage, source = _cancellation_inputs(tmp_path)
    other = tmp_path / "other.wav"
    other.write_bytes(source.read_bytes())
    with pytest.raises(ValueError, match="no source could be matched"):
        run_isolation_job(
            IsolationJob(stage, (source, other), tmp_path / "out.wav", 100, 8, auto_align=False),
            _unmatched(1.0),
            CancellationToken(),
        )


def test_each_pipeline_reports_into_its_own_band_of_the_bar():
    seen: list[ProgressEvent] = []
    report = _scaled_progress(seen.append, 25, 100)
    report(ProgressEvent(0, "start"))
    report(ProgressEvent(50, "half"))
    report(ProgressEvent(100, "done"))
    assert [event.value for event in seen] == [25, 63, 100]
    assert [event.message for event in seen] == ["start", "half", "done"]
