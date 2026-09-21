"""The complementary crossover the band stems are split at.

Two independent filters do not add back up to what they were split from: a
Butterworth low-pass and a Butterworth high-pass at the same corner leave a dip
around it and a phase error between the pair, so the band stems of a song do
not reconstruct the song.  Here the low band is a Linkwitz-Riley low-pass and
every other band is a difference of low-passes, which reconstructs the input
sample for sample by construction.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfilt

from shared.audio import BLOCK_FRAMES, AudioData
from shared.processing import CancellationToken

# A Linkwitz-Riley crossover is one Butterworth section run twice, so the
# crossover slope is twice this and the two halves stay in phase: LR4.
STAGE_ORDER = 2


def lowpass_sections(sample_rate: int, cutoff_hz: float) -> np.ndarray:
    """The cascaded second-order sections of one Linkwitz-Riley low-pass."""
    nyquist = sample_rate / 2.0
    # A corner at or above Nyquist describes no filter; clamp rather than let
    # scipy raise on a rate the user never chose.
    corner = min(cutoff_hz, nyquist * 0.99)
    sections = butter(STAGE_ORDER, corner, "lowpass", fs=sample_rate, output="sos")
    return np.concatenate([sections, sections])


def lowpass(
    source: AudioData,
    destination: AudioData,
    cutoff_hz: float,
    token: CancellationToken,
) -> None:
    """Low-pass every channel of `source` into `destination`, in blocks.

    The filter state carries across the block boundary, so the result is the
    same as filtering the whole recording in one call - which is what the test
    at the mirrored path asserts - without ever holding it in memory.
    """
    sections = lowpass_sections(source.sample_rate, cutoff_hz)
    state = np.zeros((sections.shape[0], source.channels, 2))
    for start in range(0, source.frames, BLOCK_FRAMES):
        token.raise_if_cancelled()
        end = min(start + BLOCK_FRAMES, source.frames)
        block = np.asarray(source.samples[:, start:end], dtype=np.float64)
        filtered, state = sosfilt(sections, block, axis=1, zi=state)
        destination.samples[:, start:end] = filtered.astype(np.float32, copy=False)


def difference(
    destination: AudioData,
    minuend: AudioData,
    subtrahend: AudioData,
    token: CancellationToken,
) -> None:
    """Write `minuend - subtrahend` into `destination`, which may be either of them."""
    frames = min(minuend.frames, subtrahend.frames, destination.frames)
    for start in range(0, frames, BLOCK_FRAMES):
        token.raise_if_cancelled()
        end = min(start + BLOCK_FRAMES, frames)
        destination.samples[:, start:end] = (
            minuend.samples[:, start:end] - subtrahend.samples[:, start:end]
        )
