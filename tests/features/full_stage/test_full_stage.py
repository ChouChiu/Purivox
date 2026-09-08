from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from features.full_stage import (
    ClipKind,
    FullStageAnalysis,
    FullStageJob,
    TimelineClip,
    add_manual_clip,
    analyze_full_stage,
    remove_manual_clip,
)
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


def test_full_stage_matches_sources_in_order_and_preserves_gaps(tmp_path: Path):
    sample_rate = 8_000
    first = _source(sample_rate, 8, 1)
    second = _source(sample_rate, 9, 2)
    stage = np.zeros((25 * sample_rate, 2), dtype=np.float32)
    stage[2 * sample_rate : 10 * sample_rate] = first
    stage[13 * sample_rate : 22 * sample_rate] = second
    stage += np.random.default_rng(4).normal(0, 0.01, stage.shape).astype(np.float32)
    stage_path = tmp_path / "stage.wav"
    first_path = tmp_path / "first.wav"
    second_path = tmp_path / "second.wav"
    sf.write(stage_path, stage, sample_rate)
    sf.write(first_path, first, sample_rate)
    sf.write(second_path, second, sample_rate)

    analysis = analyze_full_stage(
        FullStageJob(stage_path, (second_path, first_path), tmp_path / "output.wav"),
        CancellationToken(),
    )

    assert not analysis.missing_sources
    assert [clip.source for clip in analysis.song_clips] == [
        first_path.resolve(),
        second_path.resolve(),
    ]
    assert [clip.stage_start for clip in analysis.song_clips] == [2.0, 13.0]
    gaps = [clip for clip in analysis.clips if clip.kind == ClipKind.UNMATCHED]
    assert [(clip.stage_start, clip.stage_end) for clip in gaps] == [
        (0.0, 2.0),
        (10.0, 13.0),
        (22.0, 25.0),
    ]


def test_manual_clip_is_inserted_and_gaps_are_recomputed(tmp_path: Path):
    """A spliced backing reuses a source in an order no anchor search finds."""
    source = (tmp_path / "song.wav").resolve()
    analysis = FullStageAnalysis(
        60.0,
        (
            TimelineClip(ClipKind.SONG, 0.0, 20.0, source, 0, 0.0, 20.0, 0.9),
            TimelineClip(ClipKind.UNMATCHED, 20.0, 60.0),
        ),
    )

    updated = add_manual_clip(
        analysis,
        TimelineClip(ClipKind.SONG, 30.0, 45.0, source, 0, 60.0, 75.0, manual=True),
    )

    kinds = [(clip.kind, clip.stage_start, clip.stage_end) for clip in updated.clips]
    assert kinds == [
        (ClipKind.SONG, 0.0, 20.0),
        (ClipKind.UNMATCHED, 20.0, 30.0),
        (ClipKind.SONG, 30.0, 45.0),
        (ClipKind.UNMATCHED, 45.0, 60.0),
    ]
    # Rendering gates fragments behind a switch, so an explicit addition has to
    # be a song or it would be silently skipped.
    manual = updated.clips[2]
    assert manual.manual and manual.kind == ClipKind.SONG
    assert manual in updated.matched_clips


def test_manual_clip_removal_only_applies_to_manual_entries(tmp_path: Path):
    source = (tmp_path / "song.wav").resolve()
    analysis = FullStageAnalysis(
        40.0,
        (TimelineClip(ClipKind.SONG, 0.0, 20.0, source, 0, 0.0, 20.0, 0.9),),
    )
    added = add_manual_clip(
        analysis,
        TimelineClip(ClipKind.SONG, 25.0, 35.0, source, 0, 0.0, 10.0, manual=True),
    )
    manual_index = next(index for index, clip in enumerate(added.clips) if clip.manual)

    with pytest.raises(ValueError):
        remove_manual_clip(added, 0)

    restored = remove_manual_clip(added, manual_index)
    assert not any(clip.manual for clip in restored.clips)
    assert [clip.kind for clip in restored.clips] == [ClipKind.SONG, ClipKind.UNMATCHED]


def test_manual_clip_rejects_a_range_past_the_stage(tmp_path: Path):
    source = (tmp_path / "song.wav").resolve()
    analysis = FullStageAnalysis(10.0, (TimelineClip(ClipKind.UNMATCHED, 0.0, 10.0),))

    with pytest.raises(ValueError):
        add_manual_clip(
            analysis,
            TimelineClip(ClipKind.SONG, 5.0, 20.0, source, 0, 0.0, 15.0, manual=True),
        )


def test_a_source_played_at_a_different_tempo_is_matched_and_stretched(tmp_path: Path):
    """The stage plays the song 4% slower; the clip has to say so."""
    from shared.dsp import time_stretch

    sample_rate = 8_000
    source = _source(sample_rate, 12, 5)
    stage_song = time_stretch(source.T.astype(np.float32), sample_rate, 1.04).T
    stage = np.random.default_rng(9).normal(0, 0.01, (20 * sample_rate, 2)).astype(np.float32)
    stage[3 * sample_rate : 3 * sample_rate + stage_song.shape[0]] = stage_song
    stage_path = tmp_path / "stage.wav"
    source_path = tmp_path / "source.wav"
    sf.write(stage_path, stage, sample_rate)
    sf.write(source_path, source, sample_rate)

    analysis = analyze_full_stage(
        FullStageJob(stage_path, (source_path,), tmp_path / "output.wav"),
        CancellationToken(),
    )

    assert not analysis.missing_sources
    (clip,) = analysis.song_clips
    assert clip.stage_start == pytest.approx(3.0, abs=0.2)
    assert clip.speed == pytest.approx(1.04, abs=0.004)
    assert clip.source_start == pytest.approx(0.0, abs=0.05)
    assert clip.source_end == pytest.approx(12.0, abs=0.2)
    assert clip.duration == pytest.approx(12.0 * clip.speed, abs=0.2)
