from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from features.reference_removal import ClipKind, IsolationJob, StageAnalysis, TimelineClip
from features.reference_removal.rendering import _alignment_quality, render_stage_job
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


def test_alignment_quality_rejects_a_shift_that_damages_an_existing_match():
    sample_rate = 8_000
    reference = _source(sample_rate, 8, 11).T
    stage = reference + np.random.default_rng(12).normal(0, 0.01, reference.shape)
    shifted = np.roll(reference, sample_rate // 20, axis=1)

    assert _alignment_quality(stage, reference, sample_rate) > _alignment_quality(
        stage, shifted, sample_rate
    )


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
