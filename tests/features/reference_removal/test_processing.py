from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from features.reference_removal.models import ReferenceJob
from features.reference_removal.processing import run_reference_job
from shared.jobs import OutputTracks
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
    assert rate == sample_rate
    assert data.shape == (2 * sample_rate, 2)


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


def _cancellation_inputs(tmp_path: Path) -> tuple[Path, Path]:
    """A stage recording holding a backing track plus a voice that is not in it."""
    sample_rate = 8_000
    time = np.arange(sample_rate) / sample_rate
    backing = 0.2 * np.sin(2 * np.pi * 110 * time)
    vocal = 0.3 * np.sin(2 * np.pi * 440 * time)
    song = tmp_path / "stage.wav"
    accompaniment = tmp_path / "instrumental.wav"
    sf.write(song, np.stack([vocal + backing] * 2, axis=1), sample_rate, subtype="PCM_24")
    sf.write(accompaniment, np.stack([backing] * 2, axis=1), sample_rate, subtype="PCM_24")
    return song, accompaniment


def test_both_tracks_add_back_up_to_the_stage_recording(tmp_path: Path):
    """The backing track is defined as the stage less the vocal, so the two sum."""
    song, accompaniment = _cancellation_inputs(tmp_path)
    output = tmp_path / "stage_vocals.wav"
    result = run_reference_job(
        ReferenceJob(song, accompaniment, output, 100, 8, False, OutputTracks.BOTH),
        CancellationToken(),
    )
    assert result.outputs == (output.resolve(), (tmp_path / "stage_backing.wav").resolve())
    assert len(result.audio_stats) == 2
    vocal, _ = sf.read(result.outputs[0], always_2d=True)
    backing, _ = sf.read(result.outputs[1], always_2d=True)
    stage, _ = sf.read(song, always_2d=True)
    # Two 24-bit quantisations plus a float32 subtraction; nothing else may drift.
    assert np.allclose(vocal + backing, stage, atol=1e-6)


def test_backing_only_writes_the_named_path_and_nothing_else(tmp_path: Path):
    """`output` is whichever stem was asked for, so the CLI cannot answer elsewhere."""
    song, accompaniment = _cancellation_inputs(tmp_path)
    output = tmp_path / "just_the_backing.wav"
    result = run_reference_job(
        ReferenceJob(song, accompaniment, output, 100, 8, False, OutputTracks.BACKING),
        CancellationToken(),
    )
    assert result.outputs == (output.resolve(),)
    assert not (tmp_path / "just_the_backing_backing.wav").exists()
    assert not (tmp_path / "stage_vocals.wav").exists()


def test_a_derived_backing_path_may_not_overwrite_an_input(tmp_path: Path):
    song, accompaniment = _cancellation_inputs(tmp_path)
    collision = tmp_path / "instrumental_vocals.wav"
    accompaniment.replace(tmp_path / "instrumental_backing.wav")
    with pytest.raises(ValueError):
        run_reference_job(
            ReferenceJob(
                song,
                tmp_path / "instrumental_backing.wav",
                collision,
                100,
                8,
                False,
                OutputTracks.BOTH,
            ),
            CancellationToken(),
        )
