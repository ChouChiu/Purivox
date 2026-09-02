import numpy as np

from shared.dsp import istft, stft


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


def test_framing_matches_the_sliding_window_it_replaces():
    """The hop-strided view must frame exactly what subsampling every offset did.

    `stft` cannot build every offset first: numpy rejects a view whose nominal
    size exceeds a pointer, and under wasm32 that is two gigabytes, which a few
    seconds of 44.1 kHz audio passes. This pins the two formulations together.
    """
    n_fft, hop = 64, 16
    signal = np.sin(np.arange(4_000) / 40.0).astype(np.float32)

    padded = np.pad(signal, (n_fft // 2, n_fft // 2), mode="reflect")
    remainder = (padded.size - n_fft) % hop
    if remainder:
        padded = np.pad(padded, (0, hop - remainder), mode="reflect")
    expected = np.lib.stride_tricks.sliding_window_view(padded, n_fft)[::hop]

    stride = padded.strides[0]
    count = (padded.size - n_fft) // hop + 1
    produced = np.lib.stride_tricks.as_strided(
        padded, shape=(count, n_fft), strides=(hop * stride, stride), writeable=False
    )

    assert produced.shape == expected.shape
    assert np.array_equal(produced, expected)
    assert stft(signal, n_fft=n_fft, hop=hop).shape[0] == count
