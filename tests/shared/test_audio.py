from contextlib import suppress
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from shared.audio import (
    AudioData,
    AudioStats,
    analyze_audio,
    copy_audio,
    create_pcm_audio,
    read_audio,
    resample_audio,
    write_wav_atomic,
)
from shared.audio.io import _read_with_qt
from shared.processing import CancellationToken, ProcessingCancelled


def test_audio_analysis_and_copy_use_shared_contract():
    source = create_pcm_audio(2, 4, 8_000)
    destination = create_pcm_audio(2, 4, 8_000)
    try:
        source.samples[:] = [[0.0, 0.5, -1.0, 0.5], [0.0, -0.5, 1.0, -0.5]]
        copy_audio(source, destination)
        stats = analyze_audio(destination)
        assert np.array_equal(destination.samples, source.samples)
        assert isinstance(stats, AudioStats)
        assert stats.duration_seconds == 0.0005
        assert stats.peak_dbfs == 0.0
        assert np.isclose(stats.rms_dbfs, -4.259687, atol=1e-6)
    finally:
        destination.cleanup()
        source.cleanup()


def test_wav_roundtrip_and_resample(tmp_path: Path):
    sample_rate = 16_000
    signal = np.sin(2 * np.pi * 440 * np.arange(sample_rate) / sample_rate).astype(np.float32) * 0.5
    source = AudioData(np.stack([signal, signal]), sample_rate)
    path = tmp_path / "test.wav"
    write_wav_atomic(path, source)
    decoded = read_audio(path)
    try:
        assert decoded.backing_path is not None and decoded.backing_path.is_file()
        assert decoded.sample_rate == sample_rate
        assert decoded.samples.shape == source.samples.shape
        assert np.max(np.abs(decoded.samples - source.samples)) < 2e-6
        resampled = resample_audio(decoded, 8_000)
        try:
            assert resampled.backing_path is not None and resampled.backing_path.is_file()
            assert resampled.sample_rate == 8_000
            assert abs(resampled.frames - 8_000) <= 1
        finally:
            resampled.cleanup()
    finally:
        backing = decoded.backing_path
        decoded.cleanup()
        assert backing is not None and not backing.exists()


@pytest.mark.parametrize("subtype, bits", [("PCM_16", 16), ("PCM_24", 24), ("FLOAT", 24)])
def test_a_source_is_written_back_out_at_its_own_rate_and_depth(
    tmp_path: Path, subtype: str, bits: int
):
    """No export floor: 8 kHz in is 8 kHz out, and a 16-bit source stays 16-bit."""
    source = tmp_path / f"source-{subtype}.wav"
    sf.write(source, np.zeros((8_000, 2), dtype=np.float32), 8_000, subtype=subtype)
    decoded = read_audio(source)
    written = tmp_path / f"written-{subtype}.wav"
    try:
        assert decoded.sample_rate == 8_000
        assert decoded.bit_depth == bits
        write_wav_atomic(written, decoded)
    finally:
        decoded.cleanup()
    info = sf.info(written)
    assert info.samplerate == 8_000
    assert info.subtype == f"PCM_{bits}"


def test_resampling_carries_the_source_depth():
    source = AudioData(np.zeros((2, 8_000), dtype=np.float32), 8_000, bit_depth=16)
    resampled = resample_audio(source, 16_000)
    try:
        assert resampled.sample_rate == 16_000
        assert resampled.bit_depth == 16
    finally:
        resampled.cleanup()


def test_temporary_pcm_is_disk_backed_and_removable():
    audio = create_pcm_audio(2, 128, 8_000)
    path = audio.backing_path
    assert path is not None and path.is_file()
    audio.samples[:] = 0.25
    audio.cleanup()
    assert not path.exists()


def test_qt_audio_decoder_signal_api(tmp_path: Path, qtbot):
    path = tmp_path / "qt-decoder.wav"
    source = np.linspace(-0.5, 0.5, 800, dtype=np.float32)
    sf.write(path, source, 8_000, subtype="FLOAT")

    decoded = _read_with_qt(path, CancellationToken())
    try:
        assert decoded.sample_rate == 8_000
        assert decoded.channels == 1
        assert decoded.frames == source.size
        assert np.max(np.abs(decoded.samples[0] - source)) < 2e-6
    finally:
        decoded.cleanup()


def test_atomic_writer_preserves_existing_file_when_the_write_is_abandoned(tmp_path: Path):
    path = tmp_path / "existing.wav"
    path.write_bytes(b"keep")
    audio = AudioData(np.ones((1, 100), dtype=np.float32), 8_000)
    cancelled = CancellationToken()
    cancelled.cancel()
    with suppress(ProcessingCancelled):
        write_wav_atomic(path, audio, cancelled)
    assert path.read_bytes() == b"keep"


def test_audio_data_rejects_a_depth_the_writer_cannot_produce():
    with pytest.raises(ValueError):
        AudioData(np.ones((1, 100), dtype=np.float32), 8_000, bit_depth=12)
