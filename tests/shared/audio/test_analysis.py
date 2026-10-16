from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from shared.audio import AudioData, analyze_audio, copy_audio, create_pcm_audio, export_audio
from shared.processing import CancellationToken


def test_audio_analysis_and_copy_use_shared_contract():
    source = create_pcm_audio(2, 4, 8_000)
    destination = create_pcm_audio(2, 4, 8_000)
    try:
        source.samples[:] = [[0.0, 0.5, -1.0, 0.5], [0.0, -0.5, 1.0, -0.5]]
        copy_audio(source, destination)
        stats = analyze_audio(destination)
        assert np.array_equal(destination.samples, source.samples)
        assert stats.duration_seconds == 0.0005
        assert stats.peak_dbfs == 0.0
        assert np.isclose(stats.rms_dbfs, -4.259687, atol=1e-6)
    finally:
        destination.cleanup()
        source.cleanup()


def test_silence_measures_as_negative_infinity_rather_than_failing():
    with create_pcm_audio(2, 1_000, 8_000) as silent:
        stats = analyze_audio(silent)
    assert stats.peak_dbfs == stats.rms_dbfs == float("-inf")


def test_copying_between_different_formats_is_refused():
    with (
        create_pcm_audio(2, 100, 8_000) as source,
        create_pcm_audio(2, 100, 16_000) as target,
        pytest.raises(ValueError, match="formats must match"),
    ):
        copy_audio(source, target)


def test_an_export_reports_the_size_of_the_file_it_wrote(tmp_path: Path):
    audio = AudioData(np.full((2, 8_000), 0.25, dtype=np.float32), 8_000, bit_depth=16)
    events = []
    destination = tmp_path / "out.wav"

    stats = export_audio(audio, destination, CancellationToken(), events.append, 40, 60)

    assert stats.file_size == destination.stat().st_size
    assert sf.info(destination).subtype == "PCM_16"
    assert [(event.value, event.key) for event in events] == [
        (40, "analyzing_output"),
        (60, "saving"),
    ]
