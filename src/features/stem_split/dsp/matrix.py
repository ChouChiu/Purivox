"""The channel matrices a split is built from: M/S, discrete channels, downmix.

Every function here writes one stem into a buffer the caller owns, in blocks,
so a long recording never becomes a resident array.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence

import numpy as np

from shared.audio import BLOCK_FRAMES, AudioData
from shared.processing import CancellationToken

logger = logging.getLogger(__name__)

# WAVE_FORMAT_EXTENSIBLE orders a 5.1 master this way, and so does every
# container libsndfile hands back with six channels.
FRONT_LEFT, FRONT_RIGHT, FRONT_CENTER, LOW_FREQUENCY, SIDE_LEFT, SIDE_RIGHT = range(6)
# ITU-R BS.775 folds the centre and the surrounds in at -3 dB.
DOWNMIX_COEFFICIENT = 0.70710678
# The level a stem is held under, so a stem that would pass full scale is
# attenuated rather than clipped by the writer.
CEILING = 0.999


def channel_peaks(source: AudioData, token: CancellationToken) -> np.ndarray:
    """The absolute peak of each channel, in one streaming pass."""
    peaks = np.zeros(source.channels, dtype=np.float64)
    for start in range(0, source.frames, BLOCK_FRAMES):
        token.raise_if_cancelled()
        end = min(start + BLOCK_FRAMES, source.frames)
        block = np.abs(np.asarray(source.samples[:, start:end], dtype=np.float32))
        np.maximum(peaks, block.max(axis=1), out=peaks)
    return peaks


def downmix_gain(peaks: np.ndarray) -> float:
    """How far a BS.775 fold-down of these channels has to come down to fit.

    The three stems the downmix feeds all carry this one factor, so their
    levels stay in the relation the fold-down gave them; a stem normalised on
    its own would lose that.  A fold-down that already fits is left alone.
    """
    left = peaks[FRONT_LEFT] + DOWNMIX_COEFFICIENT * (peaks[FRONT_CENTER] + peaks[SIDE_LEFT])
    right = peaks[FRONT_RIGHT] + DOWNMIX_COEFFICIENT * (peaks[FRONT_CENTER] + peaks[SIDE_RIGHT])
    bound = float(max(left, right))
    return min(1.0, CEILING / bound) if bound > CEILING else 1.0


def apply_gain(audio: AudioData, gain: float, token: CancellationToken) -> None:
    """Scale a stem in place, in blocks."""
    for start in range(0, audio.frames, BLOCK_FRAMES):
        token.raise_if_cancelled()
        end = min(start + BLOCK_FRAMES, audio.frames)
        audio.samples[:, start:end] *= gain


def fit_group(stems: Sequence[AudioData], token: CancellationToken) -> float:
    """Hold a group of stems that add back up to one signal under full scale.

    Atome normalises every stem on its own, which is the one thing that makes
    a set of stems stop being a decomposition: each file comes back at a level
    of its own, and adding them no longer returns the mix.  A group is scaled
    by one factor or not at all, so the sum still holds, and a stem that is
    nobody's summand is left at unity with the writer's clipping warning behind
    it.
    """
    peak = max(float(channel_peaks(stem, token).max()) for stem in stems)
    if peak <= CEILING:
        return 1.0
    gain = CEILING / peak
    logger.info("holding %d stems %.2f dB down to fit", len(stems), 20.0 * math.log10(gain))
    for stem in stems:
        apply_gain(stem, gain, token)
    return gain


def copy_channels_into(
    destination: AudioData,
    source: AudioData,
    indices: tuple[int, ...],
    token: CancellationToken,
) -> None:
    """Take discrete channels out of a surround master, in the order given."""
    for start in range(0, destination.frames, BLOCK_FRAMES):
        token.raise_if_cancelled()
        end = min(start + BLOCK_FRAMES, destination.frames)
        for row, index in enumerate(indices):
            destination.samples[row, start:end] = source.samples[index, start:end]


def surround_into(destination: AudioData, source: AudioData, token: CancellationToken) -> None:
    """The surround pair, which is where a stage mix puts its ambience and backing vocals."""
    copy_channels_into(destination, source, (SIDE_LEFT, SIDE_RIGHT), token)


def mid_into(destination: AudioData, stereo: AudioData, token: CancellationToken) -> None:
    """(L + R) / 2: the centred content, as a mono stem rather than a doubled one."""
    for start in range(0, destination.frames, BLOCK_FRAMES):
        token.raise_if_cancelled()
        end = min(start + BLOCK_FRAMES, destination.frames)
        block = stereo.samples[:2, start:end]
        destination.samples[0, start:end] = 0.5 * (block[0] + block[1])


def side_into(destination: AudioData, stereo: AudioData, token: CancellationToken) -> None:
    """(L - R) / 2, written as the mono signal it is.

    Atome writes this as `[side, -side]`, which is two channels in opposite
    phase: it collapses to silence the moment anything folds it to mono, and it
    is not a stereo image, it is one signal played against itself.
    """
    for start in range(0, destination.frames, BLOCK_FRAMES):
        token.raise_if_cancelled()
        end = min(start + BLOCK_FRAMES, destination.frames)
        block = stereo.samples[:2, start:end]
        destination.samples[0, start:end] = 0.5 * (block[0] - block[1])


def downmix_into(
    destination: AudioData,
    source: AudioData,
    gain: float,
    token: CancellationToken,
) -> None:
    """Fold a surround master to stereo the way ITU-R BS.775 does.

    The LFE stays out of it: it is a separate stem here, and a broadcast
    fold-down leaves it out for the same reason - it is not programme content
    a stereo reference should carry.
    """
    for start in range(0, destination.frames, BLOCK_FRAMES):
        token.raise_if_cancelled()
        end = min(start + BLOCK_FRAMES, destination.frames)
        block = source.samples[:, start:end]
        centre = DOWNMIX_COEFFICIENT * block[FRONT_CENTER]
        destination.samples[0, start:end] = gain * (
            block[FRONT_LEFT] + centre + DOWNMIX_COEFFICIENT * block[SIDE_LEFT]
        )
        destination.samples[1, start:end] = gain * (
            block[FRONT_RIGHT] + centre + DOWNMIX_COEFFICIENT * block[SIDE_RIGHT]
        )
