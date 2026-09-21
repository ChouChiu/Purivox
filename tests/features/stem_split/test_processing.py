from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from features.stem_split import (
    StemKind,
    StemLayout,
    StemSplitJob,
    layout_stems,
    run_stem_split_job,
)
from shared.processing import CancellationToken, ProcessingCancelled, ProgressEvent

RATE = 16_000
SECONDS = 2.0


def _write(path: Path, channels: int, subtype: str = "PCM_24") -> Path:
    time = np.arange(int(RATE * SECONDS)) / RATE
    generator = np.random.default_rng(11)
    tones = [
        0.3 * np.sin(2 * np.pi * (80.0 + 130.0 * index) * time) for index in range(max(channels, 1))
    ]
    samples = np.stack(tones, axis=1) + generator.normal(0.0, 0.01, (time.size, channels))
    sf.write(path, samples.astype(np.float32), RATE, subtype=subtype)
    return path


def _run(path: Path, output_dir: Path) -> tuple[list[ProgressEvent], object]:
    events: list[ProgressEvent] = []
    job = StemSplitJob(source=path, output_dir=output_dir)
    return events, run_stem_split_job(job, CancellationToken(), events.append)


@pytest.mark.parametrize(
    ("channels", "layout"),
    [(6, StemLayout.SURROUND), (2, StemLayout.STEREO), (1, StemLayout.MONO)],
)
def test_each_channel_layout_writes_its_own_stems(
    tmp_path: Path, channels: int, layout: StemLayout
):
    source = _write(tmp_path / "mix.wav", channels)

    events, result = _run(source, tmp_path / "stems")

    assert result.layout is layout
    assert result.kinds == layout_stems(layout)
    assert [path.name for path in result.outputs] == [
        f"mix_{kind.value}.wav" for kind in layout_stems(layout)
    ]
    assert all(path.is_file() for path in result.outputs)
    values = [event.value for event in events]
    assert values == sorted(values)
    assert values[0] == 0
    assert values[-1] == 100


def test_an_export_keeps_the_rate_and_the_depth_of_its_source(tmp_path: Path):
    """There is no export floor: a 16-bit recording comes back 16-bit."""
    source = _write(tmp_path / "mix.wav", 2, subtype="PCM_16")

    _events, result = _run(source, tmp_path / "stems")

    assert all(stats.sample_rate == RATE for stats in result.audio_stats)
    assert all(stats.bit_depth == 16 for stats in result.audio_stats)
    assert all(stats.peak_dbfs <= 0.0 for stats in result.audio_stats)


def test_the_band_stems_add_back_up_to_the_recording(tmp_path: Path):
    source = _write(tmp_path / "mix.wav", 2)

    _events, result = _run(source, tmp_path / "stems")

    outputs = dict(zip(result.kinds, result.outputs, strict=True))
    low, _ = sf.read(outputs[StemKind.LOW], dtype="float32", always_2d=True)
    high, _ = sf.read(outputs[StemKind.HIGH], dtype="float32", always_2d=True)
    mix, _ = sf.read(source, dtype="float32", always_2d=True)
    # One shared gain may hold the pair under full scale, so the sum is the
    # recording up to a single scalar rather than sample for sample.
    summed = low + high
    scale = float(np.dot(summed.ravel(), mix.ravel()) / np.dot(mix.ravel(), mix.ravel()))
    assert 0.5 <= scale <= 1.0
    assert np.allclose(summed, scale * mix, atol=2e-4)


def test_the_mono_bands_add_back_up_to_the_recording(tmp_path: Path):
    source = _write(tmp_path / "mix.wav", 1)

    _events, result = _run(source, tmp_path / "stems")

    bands = [sf.read(path, dtype="float32", always_2d=True)[0] for path in result.outputs]
    mix, _ = sf.read(source, dtype="float32", always_2d=True)
    assert np.allclose(sum(bands), mix, atol=2e-4)


def test_cancelling_a_split_stops_it(tmp_path: Path):
    source = _write(tmp_path / "mix.wav", 2)
    token = CancellationToken()
    job = StemSplitJob(source=source, output_dir=tmp_path / "stems")

    with pytest.raises(ProcessingCancelled):
        run_stem_split_job(job, token, lambda _event: token.cancel())
