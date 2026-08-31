from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from features.reference_removal.models import ReferenceJob
from features.reference_removal.processing import run_reference_job
from shared.audio import HI_RES_SAMPLE_RATE
from shared.processing import CancellationToken


def test_reference_pipeline_end_to_end(tmp_path: Path):
    sample_rate = 8_000
    time = np.arange(sample_rate) / sample_rate
    vocal = 0.3 * np.sin(2 * np.pi * 440 * time)
    reference = 0.2 * np.sin(2 * np.pi * 110 * time)
    song = tmp_path / "song.wav"
    accompaniment = tmp_path / "instrumental.wav"
    output = tmp_path / "vocals.wav"
    sf.write(song, np.stack([vocal + reference] * 2, axis=1), sample_rate)
    sf.write(accompaniment, np.stack([reference] * 2, axis=1), sample_rate)
    events = []
    result = run_reference_job(
        ReferenceJob(song, accompaniment, output, 100, 8, False),
        CancellationToken(),
        events.append,
    )
    assert result.outputs == (output.resolve(),)
    assert len(result.audio_stats) == 1
    stats = result.audio_stats[0]
    assert stats.duration_seconds == 1
    assert stats.sample_rate == HI_RES_SAMPLE_RATE
    assert stats.channels == 2
    assert stats.bit_depth == 24
    assert stats.peak_dbfs <= 0
    assert stats.rms_dbfs < stats.peak_dbfs
    assert stats.file_size == output.stat().st_size
    assert output.is_file()
    data, rate = sf.read(output, always_2d=True)
    assert rate == HI_RES_SAMPLE_RATE and data.shape == (HI_RES_SAMPLE_RATE, 2)
    assert sf.info(output).subtype == "PCM_24"
    assert events[-1].value == 100


def test_reference_pipeline_retains_song_duration_with_a_short_reference(tmp_path: Path):
    sample_rate = 8_000
    song_time = np.arange(2 * sample_rate) / sample_rate
    reference_time = np.arange(sample_rate) / sample_rate
    vocal = 0.2 * np.sin(2 * np.pi * 440 * song_time)
    reference = 0.15 * np.sin(2 * np.pi * 110 * reference_time)
    padded_reference = np.pad(reference, (0, sample_rate))
    song = tmp_path / "long-song.wav"
    accompaniment = tmp_path / "short-reference.wav"
    output = tmp_path / "full-length-output.wav"
    sf.write(song, np.stack([vocal + padded_reference] * 2, axis=1), sample_rate)
    sf.write(accompaniment, np.stack([reference] * 2, axis=1), sample_rate)

    run_reference_job(
        ReferenceJob(song, accompaniment, output, 100, 8, False),
        CancellationToken(),
    )

    data, rate = sf.read(output, always_2d=True)
    assert rate == HI_RES_SAMPLE_RATE
    assert data.shape == (2 * HI_RES_SAMPLE_RATE, 2)


def test_reference_pipeline_rejects_same_song_and_accompaniment(tmp_path: Path):
    song = tmp_path / "song.wav"
    song.touch()
    job = ReferenceJob(
        song,
        song,
        tmp_path / "output.wav",
        100,
        8,
        False,
    )

    with pytest.raises(ValueError, match="song and accompaniment must be different"):
        run_reference_job(job, CancellationToken())
