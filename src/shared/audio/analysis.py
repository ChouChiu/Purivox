from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from shared.audio.io import BLOCK_FRAMES, AudioData
from shared.processing import CancellationToken


@dataclass(frozen=True, slots=True)
class AudioStats:
    duration_seconds: float
    sample_rate: int
    channels: int
    bit_depth: int
    peak_dbfs: float
    rms_dbfs: float
    file_size: int = 0


def _dbfs(amplitude: float) -> float:
    return 20.0 * math.log10(amplitude) if amplitude > 0 else -math.inf


def analyze_audio(
    audio: AudioData,
    token: CancellationToken | None = None,
) -> AudioStats:
    """Calculate peak and RMS statistics without loading the whole file into RAM."""
    token = token or CancellationToken()
    peak = 0.0
    square_sum = 0.0
    sample_count = 0
    for start in range(0, audio.frames, BLOCK_FRAMES):
        token.raise_if_cancelled()
        end = min(start + BLOCK_FRAMES, audio.frames)
        values = np.asarray(audio.samples[:, start:end], dtype=np.float64)
        peak = max(peak, float(np.max(np.abs(values), initial=0.0)))
        square_sum += float(np.sum(values * values))
        sample_count += values.size
    rms = math.sqrt(square_sum / max(sample_count, 1))
    return AudioStats(
        duration_seconds=audio.frames / audio.sample_rate,
        sample_rate=audio.sample_rate,
        channels=audio.channels,
        bit_depth=audio.bit_depth,
        peak_dbfs=_dbfs(peak),
        rms_dbfs=_dbfs(rms),
    )


def copy_audio(
    source: AudioData,
    destination: AudioData,
    token: CancellationToken | None = None,
) -> None:
    """Copy compatible mapped audio in cancellable, bounded-memory blocks."""
    if (
        source.channels != destination.channels
        or source.frames != destination.frames
        or source.sample_rate != destination.sample_rate
    ):
        raise ValueError("source and destination audio formats must match")
    token = token or CancellationToken()
    for start in range(0, source.frames, BLOCK_FRAMES):
        token.raise_if_cancelled()
        end = min(start + BLOCK_FRAMES, source.frames)
        destination.samples[:, start:end] = source.samples[:, start:end]
