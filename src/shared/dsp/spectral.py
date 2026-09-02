from __future__ import annotations

from functools import lru_cache

import numpy as np
from scipy.fft import irfft, rfft
from scipy.signal import get_window
from scipy.signal import stft as scipy_stft


@lru_cache(maxsize=16)
def _hann_window(size: int, dtype_string: str) -> np.ndarray:
    return get_window("hann", size, fftbins=True).astype(np.dtype(dtype_string))


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
    # Stride straight to the hop positions.  Framing every offset and keeping
    # every `hop`-th row afterwards is the same result, but the intermediate is
    # `hop` times taller, and numpy refuses a view whose nominal size does not
    # fit a pointer.  Under wasm32 that ceiling is two gigabytes, which a few
    # seconds of 44.1 kHz audio already describes past.
    stride = padded.strides[0]
    count = (padded.size - n_fft) // hop + 1
    frames = np.lib.stride_tricks.as_strided(
        padded, shape=(count, n_fft), strides=(hop * stride, stride), writeable=False
    )
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


def log_flux_bands(
    signal: np.ndarray,
    n_fft: int,
    hop: int,
    band_count: int = 12,
    minimum_scale: float = 0.0,
) -> np.ndarray | None:
    """Summarise positive log-spectral flux in geometrically spaced bands.

    Two masters of the same music can share note attacks while their waveforms,
    EQ, compression, vocals and ambience differ, so both full-stage matching and
    coarse alignment compare this feature instead of the raw waveform.  Returns
    `None` when the input is too short or too flat to describe.
    """
    values = np.asarray(signal)
    if values.ndim != 1 or n_fft < 128 or hop <= 0:
        return None
    _, _, spectrum = scipy_stft(
        values,
        nperseg=n_fft,
        noverlap=max(n_fft - hop, 0),
        boundary=None,
        padded=False,
    )
    magnitude = np.log1p(20.0 * np.abs(spectrum))
    flux = np.maximum(np.diff(magnitude, axis=1, prepend=magnitude[:, :1]), 0.0)
    edges = np.unique(np.geomspace(2, magnitude.shape[0], band_count + 1).astype(int))
    if edges.size < 3:
        return None
    bands = np.stack(
        [np.mean(flux[edges[index] : edges[index + 1]], axis=0) for index in range(edges.size - 1)]
    )
    bands -= np.median(bands, axis=1, keepdims=True)
    raw_scale = np.median(np.abs(bands), axis=1, keepdims=True)
    if float(np.median(raw_scale)) < minimum_scale:
        return None
    return np.clip(bands / (raw_scale + 1e-6), -8.0, 8.0)
