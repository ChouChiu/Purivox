import numpy as np

from shared.dsp import hann, istft, stft


def test_stft_round_trip_and_helpers():
    rng = np.random.default_rng(42)
    signal = rng.normal(0, 0.2, 12_345)
    spectra = stft(signal, 512, 128)
    restored = istft(spectra, 128, signal.size)
    assert spectra.shape[1] == 257
    assert np.max(np.abs(restored - signal)) < 1e-10
    assert hann(0).size == 0


def test_stft_preserves_single_precision_fast_path():
    rng = np.random.default_rng(43)
    signal = rng.normal(0, 0.2, 12_345).astype(np.float32)

    spectra = stft(signal, 512, 128)
    restored = istft(spectra, 128, signal.size)

    assert spectra.dtype == np.complex64
    assert restored.dtype == np.float32
    assert np.max(np.abs(restored - signal)) < 1e-5
