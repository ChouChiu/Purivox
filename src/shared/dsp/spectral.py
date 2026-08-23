from __future__ import annotations

from functools import lru_cache

import numpy as np
from scipy.fft import irfft, rfft
from scipy.signal import get_window


@lru_cache(maxsize=16)
def _hann_window(size: int, dtype_string: str) -> np.ndarray:
    return get_window("hann", size, fftbins=True).astype(np.dtype(dtype_string))


def hann(size: int) -> np.ndarray:
    if size <= 0:
        return np.empty(0, dtype=np.float64)
    return _hann_window(size, np.dtype(np.float64).str).copy()


def stft(signal: np.ndarray, n_fft: int = 2048, hop: int = 512) -> np.ndarray:
    """librosa-compatible centered STFT returned as [frames, bins]."""
    source = np.asarray(signal)
    real_dtype = np.dtype(np.float32 if source.dtype == np.float32 else np.float64)
    complex_dtype = np.dtype(np.complex64 if real_dtype == np.float32 else np.complex128)
    values = np.asarray(source, dtype=real_dtype)
    if values.ndim != 1 or values.size == 0 or n_fft <= 0 or n_fft % 2 or hop <= 0:
        return np.empty((0, 0), dtype=complex_dtype)
    if values.size == 1:
        padded = np.pad(values, (n_fft // 2, n_fft // 2), mode="edge")
    else:
        padded = np.pad(values, (n_fft // 2, n_fft // 2), mode="reflect")
    remainder = (padded.size - n_fft) % hop
    if remainder:
        padded = np.pad(padded, (0, hop - remainder), mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(padded, n_fft)[::hop]
    window = _hann_window(n_fft, real_dtype.str)
    return rfft(frames * window, axis=1)


def istft(spectra: np.ndarray, hop: int = 512, length: int | None = None) -> np.ndarray:
    source = np.asarray(spectra)
    complex_dtype = np.dtype(np.complex64 if source.dtype == np.complex64 else np.complex128)
    real_dtype = np.dtype(np.float32 if complex_dtype == np.complex64 else np.float64)
    frames = np.asarray(source, dtype=complex_dtype)
    if frames.ndim != 2 or frames.shape[0] == 0 or frames.shape[1] < 2 or hop <= 0:
        return np.empty(0, dtype=real_dtype)
    n_fft = 2 * (frames.shape[1] - 1)
    window = _hann_window(n_fft, real_dtype.str)
    output_size = hop * (frames.shape[0] - 1) + n_fft
    output = np.zeros(output_size, dtype=real_dtype)
    normalizer = np.zeros(output_size, dtype=real_dtype)
    time_frames = irfft(frames, n=n_fft, axis=1) * window
    squared = window * window
    for frame_index, frame in enumerate(time_frames):
        start = frame_index * hop
        output[start : start + n_fft] += frame
        normalizer[start : start + n_fft] += squared
    valid = normalizer > np.finfo(real_dtype).eps
    output[valid] /= normalizer[valid]
    output = output[n_fft // 2 :]
    if length is None:
        return output[: hop * (frames.shape[0] - 1)]
    if output.size < length:
        output = np.pad(output, (0, length - output.size))
    return output[:length]


def fft_frequencies(sample_rate: int, n_fft: int) -> np.ndarray:
    if sample_rate <= 0 or n_fft <= 0:
        return np.empty(0, dtype=np.float64)
    return np.fft.rfftfreq(n_fft, 1.0 / sample_rate)
