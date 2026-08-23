from contextlib import suppress
from pathlib import Path

import numpy as np
import soundfile as sf

from shared.audio import (
    HI_RES_BIT_DEPTH,
    HI_RES_SAMPLE_RATE,
    AudioData,
    AudioStats,
    analyze_audio,
    copy_audio,
    create_pcm_audio,
    prepare_hi_res_output,
    read_audio,
    resample_audio,
    write_wav_atomic,
)
from shared.audio.io import _read_with_qt
from shared.processing import CancellationToken


def test_audio_analysis_and_copy_use_shared_contract():
    source = create_pcm_audio(2, 4, 8_000)
    destination = create_pcm_audio(2, 4, 8_000)
    try:
        source.samples[:] = [[0.0, 0.5, -1.0, 0.5], [0.0, -0.5, 1.0, -0.5]]
        copy_audio(source, destination)
        stats = analyze_audio(destination, 24)
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
    write_wav_atomic(path, source, 24)
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


def test_hi_res_output_uses_96_khz_24_bit_floor(tmp_path: Path):
    source = AudioData(np.zeros((2, 8_000), dtype=np.float32), 8_000)
    prepared = prepare_hi_res_output(source)
    path = tmp_path / "hi-res.wav"
    try:
        assert prepared.sample_rate == HI_RES_SAMPLE_RATE
        assert prepared.frames == HI_RES_SAMPLE_RATE
        write_wav_atomic(path, prepared, HI_RES_BIT_DEPTH)
        info = sf.info(path)
        assert info.samplerate == HI_RES_SAMPLE_RATE
        assert info.subtype == "PCM_24"
    finally:
        prepared.cleanup()

    higher_rate = AudioData(np.zeros((2, 192), dtype=np.float32), 192_000)
    assert prepare_hi_res_output(higher_rate) is higher_rate


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


def test_atomic_writer_preserves_existing_file_on_invalid_input(tmp_path: Path):
    path = tmp_path / "existing.wav"
    path.write_bytes(b"keep")
    audio = AudioData(np.ones((1, 100), dtype=np.float32), 8_000)
    with suppress(ValueError):
        write_wav_atomic(path, audio, 12)
    assert path.read_bytes() == b"keep"
