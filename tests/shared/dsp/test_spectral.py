import tracemalloc

import numpy as np
from scipy.signal import get_window
from scipy.signal import stft as scipy_stft

from shared.dsp import istft, log_flux_bands, stft


def test_stft_round_trip_and_helpers():
    rng = np.random.default_rng(42)
    signal = rng.normal(0, 0.2, 12_345)
    spectra = stft(signal, 512, 128)
    restored = istft(spectra, 128, signal.size)
    assert spectra.shape[1] == 257
    assert np.max(np.abs(restored - signal)) < 1e-10


def test_stft_preserves_single_precision_fast_path():
    rng = np.random.default_rng(43)
    signal = rng.normal(0, 0.2, 12_345).astype(np.float32)

    spectra = stft(signal, 512, 128)
    restored = istft(spectra, 128, signal.size)

    assert spectra.dtype == np.complex64
    assert restored.dtype == np.float32
    assert np.max(np.abs(restored - signal)) < 1e-5


def test_stft_frames_the_signal_the_way_librosa_centres_it():
    """Each frame is the hop-strided, reflect-padded window, transformed.

    `stft` strides straight to the hop positions instead of framing every
    offset first: numpy rejects a view whose nominal size exceeds a pointer,
    and under wasm32 that is two gigabytes, which a few seconds of 44.1 kHz
    audio passes.  This holds the shortcut to the plain formulation.
    """
    n_fft, hop = 64, 16
    signal = np.sin(np.arange(4_000) / 40.0)

    padded = np.pad(signal, (n_fft // 2, n_fft // 2), mode="reflect")
    remainder = (padded.size - n_fft) % hop
    if remainder:
        padded = np.pad(padded, (0, hop - remainder), mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(padded, n_fft)[::hop]
    expected = np.fft.rfft(frames * get_window("hann", n_fft, fftbins=True), axis=1)

    np.testing.assert_allclose(stft(signal, n_fft=n_fft, hop=hop), expected, atol=1e-12)


def _scipy_log_flux_bands(signal: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
    """`log_flux_bands` written the way scipy's own stft spells it."""
    _, _, spectrum = scipy_stft(
        signal, nperseg=n_fft, noverlap=max(n_fft - hop, 0), boundary=None, padded=False
    )
    magnitude = np.log1p(20.0 * np.abs(spectrum))
    flux = np.maximum(np.diff(magnitude, axis=1, prepend=magnitude[:, :1]), 0.0)
    edges = np.unique(np.geomspace(2, magnitude.shape[0], 13).astype(int))
    bands = np.stack(
        [np.mean(flux[edges[index] : edges[index + 1]], axis=0) for index in range(edges.size - 1)]
    )
    bands -= np.median(bands, axis=1, keepdims=True)
    scale = np.median(np.abs(bands), axis=1, keepdims=True)
    return np.clip(bands / (scale + 1e-6), -8.0, 8.0)


def test_log_flux_bands_match_the_scipy_formulation_they_replace():
    rng = np.random.default_rng(11)
    for dtype in (np.float64, np.float32):
        samples = np.arange(4_000 * 20)
        signal = (rng.normal(0, 0.3, samples.size) * (1 + np.sin(samples / 500))).astype(dtype)

        produced = log_flux_bands(signal, 512, 160)

        assert produced.dtype == dtype
        np.testing.assert_allclose(produced, _scipy_log_flux_bands(signal, 512, 160), atol=1e-9)


def test_log_flux_bands_keep_their_working_set_off_the_signal_length():
    """Blocking is what lets the browser build analyse more than two minutes.

    scipy frames every offset before subsampling, and numpy refuses a view whose
    nominal size does not fit a pointer: under wasm32 that is two gigabytes,
    which 131 seconds of the 4 kHz matching proxy already passes. Reducing each
    block to its bands keeps the magnitude matrix - `n_fft // 2` times the audio
    it describes - off the heap as well.
    """
    signal = np.sin(np.arange(4_000 * 600) / 37.0)
    frames = (signal.size - 512) // 160 + 1
    whole_spectrum = frames * 257 * np.dtype(np.complex128).itemsize

    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    bands = log_flux_bands(signal, 512, 160)
    peak = tracemalloc.get_traced_memory()[1] - before
    tracemalloc.stop()

    assert bands.shape[1] == frames
    assert peak < whole_spectrum / 3
