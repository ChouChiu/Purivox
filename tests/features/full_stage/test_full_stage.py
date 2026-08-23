from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

from features.full_stage import (
    ClipKind,
    FullStageJob,
    analyze_full_stage,
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
