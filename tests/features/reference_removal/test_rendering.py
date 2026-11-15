from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from features.reference_removal import ClipKind, IsolationJob, StageAnalysis, TimelineClip
from features.reference_removal.rendering import render_stage_job
from shared.audio import AudioData
from shared.jobs import OutputTracks
from shared.processing import CancellationToken


def _source(sample_rate: int, seconds: int, seed: int) -> np.ndarray:
    random = np.random.default_rng(seed)
    frames = sample_rate * seconds
    time = np.arange(frames) / sample_rate
    signal = np.zeros(frames)
    for frequency in (103 + seed * 7, 211 + seed * 11, 367 + seed * 13):
        envelope = np.repeat(random.uniform(0.1, 1.0, seconds * 8), sample_rate // 8)
        signal += envelope[:frames] * np.sin(
            2 * np.pi * frequency * time + random.uniform(0, 2 * np.pi)
        )
    signal /= 8
    return np.stack([signal, signal], axis=1).astype(np.float32)


def test_render_keeps_unmatched_audio_and_processes_the_matched_span(tmp_path: Path):
    sample_rate = 8_000
    reference = _source(sample_rate, 4, 7)
    stage = np.random.default_rng(8).normal(0, 0.01, (8 * sample_rate, 2)).astype(np.float32)
    stage[2 * sample_rate : 6 * sample_rate] += reference
    stage_path = tmp_path / "stage.wav"
    source_path = tmp_path / "source.wav"
    output_path = tmp_path / "output.wav"
    sf.write(stage_path, stage, sample_rate)
    sf.write(source_path, reference, sample_rate)
    analysis = StageAnalysis(
        8.0,
        (
            TimelineClip(ClipKind.UNMATCHED, 0.0, 2.0),
            TimelineClip(
                ClipKind.FRAGMENT,
                0.5,
                1.5,
                source_path.resolve(),
                0,
                0.0,
                1.0,
                0.8,
                False,
            ),
            TimelineClip(
                ClipKind.SONG,
                2.0,
                6.0,
                source_path.resolve(),
                0,
                0.0,
                4.0,
                1.0,
            ),
            TimelineClip(ClipKind.UNMATCHED, 6.0, 8.0),
        ),
    )
    job = IsolationJob(
        stage_path,
        (source_path,),
        output_path,
        strength=100,
        sigma=1,
    )

    result = render_stage_job(job, analysis, CancellationToken())

    rendered, rendered_rate = sf.read(output_path, always_2d=True, dtype="float32")
    original, _ = sf.read(stage_path, always_2d=True, dtype="float32")
    expected_audio = AudioData(original.T.copy(), sample_rate)
    try:
        expected = expected_audio.samples.T
        assert rendered_rate == sample_rate
        assert rendered.shape == expected.shape
        assert np.allclose(rendered[:sample_rate], expected[:sample_rate], atol=2e-6)
        assert np.allclose(rendered[-sample_rate:], expected[-sample_rate:], atol=2e-6)
        assert np.sqrt(np.mean(rendered[3 * sample_rate : 5 * sample_rate] ** 2)) < 0.5 * np.sqrt(
            np.mean(expected[3 * sample_rate : 5 * sample_rate] ** 2)
        )
    finally:
        expected_audio.cleanup()
    assert sf.info(output_path).subtype == "PCM_16", "the stage's own depth must survive"
    assert result.outputs == (output_path.resolve(),)
    assert result.audio_stats[0].sample_rate == sample_rate
    assert result.audio_stats[0].bit_depth == 16
    assert result.audio_stats[0].duration_seconds == 8
    assert result.analysis is analysis


def test_backing_export_is_silent_where_nothing_was_cancelled(tmp_path: Path):
    """The backing is synthesised per clip, so a range no clip covers has none."""
    sample_rate = 8_000
    reference = _source(sample_rate, 4, 7)
    stage = np.random.default_rng(8).normal(0, 0.01, (8 * sample_rate, 2)).astype(np.float32)
    stage[2 * sample_rate : 6 * sample_rate] += reference
    stage_path = tmp_path / "stage.wav"
    source_path = tmp_path / "source.wav"
    output_path = tmp_path / "stage_vocals.wav"
    sf.write(stage_path, stage, sample_rate, subtype="PCM_24")
    sf.write(source_path, reference, sample_rate, subtype="PCM_24")
    analysis = StageAnalysis(
        8.0,
        (
            TimelineClip(ClipKind.UNMATCHED, 0.0, 2.0),
            TimelineClip(ClipKind.SONG, 2.0, 6.0, source_path.resolve(), 0, 0.0, 4.0, 1.0),
            TimelineClip(ClipKind.UNMATCHED, 6.0, 8.0),
        ),
    )
    job = IsolationJob(
        stage_path,
        (source_path,),
        output_path,
        strength=100,
        sigma=1,
        tracks=OutputTracks.BOTH,
    )

    result = render_stage_job(job, analysis, CancellationToken())

    backing_output = tmp_path / "stage_backing.wav"
    assert result.outputs == (output_path.resolve(), backing_output.resolve())
    assert len(result.audio_stats) == 2
    backing, _ = sf.read(backing_output, always_2d=True, dtype="float32")
    # Nothing was cancelled out of the unmatched head and tail.
    assert np.max(np.abs(backing[: 2 * sample_rate])) < 1e-6
    assert np.max(np.abs(backing[6 * sample_rate :])) < 1e-6
    # The song range is where the backing track actually lives, and it is the
    # source's own waveform rather than what the stage carried of it.  The clip
    # maps stage 2-6 s onto the source's own 0-4 s.
    song = slice(3 * sample_rate, 5 * sample_rate)
    source_song = slice(sample_rate, 3 * sample_rate)
    assert np.max(np.abs(backing[song])) > 0.01
    assert np.corrcoef(backing[song].ravel(), reference[source_song].ravel())[0, 1] > 0.99


def _layered_clips(tmp_path: Path) -> tuple[Path, Path, Path, StageAnalysis]:
    """Four seconds of stage carrying two sources over the same stretch."""
    sample_rate = 8_000
    first = _source(sample_rate, 4, 7)
    second = _source(sample_rate, 4, 11)
    stage_path = tmp_path / "stage.wav"
    first_path = tmp_path / "first.wav"
    second_path = tmp_path / "second.wav"
    sf.write(stage_path, first + second, sample_rate, subtype="PCM_24")
    sf.write(first_path, first, sample_rate, subtype="PCM_24")
    sf.write(second_path, second, sample_rate, subtype="PCM_24")
    analysis = StageAnalysis(
        4.0,
        (
            TimelineClip(ClipKind.SONG, 0.0, 4.0, first_path.resolve(), 0, 0.0, 4.0, 0.9),
            TimelineClip(ClipKind.SONG, 0.0, 4.0, second_path.resolve(), 1, 0.0, 4.0, 0.8),
        ),
    )
    return stage_path, first_path, second_path, analysis


def test_stacked_clips_are_cancelled_out_of_what_the_others_left(tmp_path: Path):
    """Two layers over one stretch: the second cancels the first's residual."""
    stage_path, first_path, second_path, analysis = _layered_clips(tmp_path)
    rendered: dict[bool, np.ndarray] = {}
    for stack in (False, True):
        output = tmp_path / f"stacked-{stack}.wav"
        render_stage_job(
            IsolationJob(stage_path, (first_path, second_path), output, 100, 1, stack=stack),
            analysis,
            CancellationToken(),
        )
        rendered[stack], _ = sf.read(output, always_2d=True, dtype="float32")
    body = slice(1_000, -1_000)
    plain = float(np.mean(rendered[False][body] ** 2))
    stacked = float(np.mean(rendered[True][body] ** 2))
    assert stacked < 0.35 * plain, f"stacking left {stacked / plain:.2f} of the one-source residual"


def test_a_stacked_backing_carries_every_source_it_cancelled(tmp_path: Path):
    """The playback carried both layers, so both belong in the backing stem."""
    stage_path, first_path, second_path, analysis = _layered_clips(tmp_path)
    output = tmp_path / "stage_vocals.wav"
    result = render_stage_job(
        IsolationJob(
            stage_path,
            (first_path, second_path),
            output,
            100,
            1,
            tracks=OutputTracks.BOTH,
            stack=True,
        ),
        analysis,
        CancellationToken(),
    )
    backing, _ = sf.read(result.outputs[1], always_2d=True, dtype="float32")
    body = slice(1_000, -1_000)
    for path in (first_path, second_path):
        source, _ = sf.read(path, always_2d=True, dtype="float32")
        correlation = np.corrcoef(backing[body].ravel(), source[body].ravel())[0, 1]
        assert correlation > 0.5, f"{path.name} is missing from the backing: {correlation:.2f}"
