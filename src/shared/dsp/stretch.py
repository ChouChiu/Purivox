"""Pitch-preserving time stretching, for references that run at a different tempo.

A stage recording can be uploaded with its tempo shifted (a slowed or sped-up
copy), and the studio source then no longer lines up with it.  Compensating with
a plain resample would move the pitch by the same factor - 3% is 51 cents - and
reference cancellation is per-bin, so the harmonics would land in the wrong bins
and nothing would cancel.

Waveform-similarity overlap-add keeps the pitch.  It is measured, not assumed:
on a real broadcast whose tempo differs by 3%, the cancellation depth of the
shared probe was -0.05 dB with no stretch, -1.46 dB with a phase vocoder and
-2.99 dB with this, level with ffmpeg's `atempo` at -3.15 dB.  A phase vocoder
smears the transients that carry most of the coherent energy; searching each
output frame for the input position that continues the previous waveform keeps
them.  The implementation stays inside numpy and scipy because the browser build
runs the same pipeline under Pyodide, where an external binary is not an option.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import fftconvolve, get_window

from shared.processing import CancellationToken

# Window and search widths in seconds, and the widest ratio a caller may ask
# for.  A window much shorter than a bass period loses the waveform continuity
# the search depends on; a search narrower than a pitch period cannot find the
# continuation at all.
_WINDOW_SECONDS = 0.064
_SEARCH_SECONDS = 0.0075
_MINIMUM_RATIO = 0.25
_MAXIMUM_RATIO = 4.0
_IDENTITY_EPSILON = 1e-6


def _float_dtype(dtype: np.dtype) -> np.dtype:
    return dtype if dtype in (np.dtype(np.float32), np.dtype(np.float64)) else np.dtype(np.float32)


def _continuation_offset(
    values: np.ndarray,
    nominal: int,
    search: int,
    window: int,
    target: np.ndarray | None,
) -> int:
    """Pick the input position that continues `target` with the least seam.

    Every channel votes into the same offset: a stereo source whose channels
    were allowed to drift apart would lose the inter-channel coherence the
    transfer estimate needs.  One batched transform covers every channel at
    once - measured three times faster than a per-channel correlation with an
    identical answer - and the running energy is a prefix sum rather than a
    second transform.
    """
    frames = values.shape[1]
    low = max(nominal - search, 0)
    high = min(nominal + search, max(frames - window, 0))
    if high < low:
        return min(max(nominal, 0), max(frames - window, 0))
    if target is None or high == low:
        return low
    segment = np.asarray(values[:, low : high + window], dtype=np.float64)
    cross = fftconvolve(
        segment,
        np.ascontiguousarray(target[:, ::-1]),
        mode="valid",
        axes=-1,
    )
    squared = np.concatenate(
        (np.zeros((segment.shape[0], 1)), np.cumsum(segment * segment, axis=1)), axis=1
    )
    energy = np.sqrt(squared[:, window:] - squared[:, :-window])
    norms = np.linalg.norm(target, axis=1)[:, None]
    scores = np.sum(cross / (energy * norms + 1e-12), axis=0)
    return low + int(np.argmax(scores))


def time_stretch(
    channels: np.ndarray,
    sample_rate: int,
    ratio: float,
    token: CancellationToken | None = None,
) -> np.ndarray:
    """Stretch `channels` in time by `ratio` without moving its pitch.

    `channels` is a `[channels, frames]` array and the result is
    `round(frames * ratio)` long with the same layout and a float dtype.  A
    ratio of one, and audio too short to hold a window, are returned unchanged
    rather than copied.
    """
    cancel = token or CancellationToken()
    values = np.asarray(channels)
    if values.ndim != 2 or sample_rate <= 0 or not np.isfinite(ratio) or ratio <= 0.0:
        raise ValueError("time stretch needs a [channels, frames] array and a positive ratio")
    if not _MINIMUM_RATIO <= ratio <= _MAXIMUM_RATIO:
        raise ValueError(f"time stretch ratio must be within [{_MINIMUM_RATIO}, {_MAXIMUM_RATIO}]")
    frames = values.shape[1]
    window = max(round(_WINDOW_SECONDS * sample_rate), 2)
    if abs(ratio - 1.0) < _IDENTITY_EPSILON or frames < 4 * window:
        return values
    cancel.raise_if_cancelled()
    hop = window // 2
    advance = hop / ratio
    search = max(round(_SEARCH_SECONDS * sample_rate), 1)
    length = round(frames * ratio)
    # Accumulating in the input's own float width avoids a full-length cast on
    # the way out; the audio path is float32 and the matching proxy float64.
    dtype = _float_dtype(values.dtype)
    output = np.zeros((values.shape[0], length + window), dtype=dtype)
    weight = np.zeros(length + window, dtype=dtype)
    taper = get_window("hann", window).astype(dtype)
    target: np.ndarray | None = None
    position = 0.0
    index = 0
    while True:
        start = index * hop
        if start >= length:
            break
        cancel.raise_if_cancelled()
        offset = _continuation_offset(values, round(position), search, window, target)
        segment = values[:, offset : offset + window]
        output[:, start : start + window] += segment * taper
        weight[start : start + window] += taper
        following = offset + hop
        if following + window <= frames:
            # The waveform the next frame has to continue, taken from the input
            # rather than from the output so a seam is never allowed to compound.
            target = np.asarray(values[:, following : following + window], dtype=np.float64)
        position += advance
        index += 1
    valid = weight > 1e-8
    output[:, valid] /= weight[valid]
    return output[:, :length]
