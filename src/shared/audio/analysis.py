from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from shared.audio.io import BLOCK_FRAMES, AudioData, write_wav_atomic
from shared.processing import CancellationToken, ProgressCallback
from shared.progress import report_progress

logger = logging.getLogger(__name__)


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


def subtract_into(
    minuend: AudioData,
    target: AudioData,
    token: CancellationToken | None = None,
) -> None:
    """Replace `target` with `minuend - target`, in cancellable blocks.

    The difference overwrites the subtrahend rather than filling a third buffer:
    both callers want what is left of a mix once a stem they already wrote out
    is taken away, and under Emscripten a second full-length buffer is resident
    heap rather than a mapped file.
    """
    if (
        minuend.channels != target.channels
        or minuend.frames != target.frames
        or minuend.sample_rate != target.sample_rate
    ):
        raise ValueError("source and destination audio formats must match")
    token = token or CancellationToken()
    for start in range(0, minuend.frames, BLOCK_FRAMES):
        token.raise_if_cancelled()
        end = min(start + BLOCK_FRAMES, minuend.frames)
        target.samples[:, start:end] = minuend.samples[:, start:end] - target.samples[:, start:end]


def export_audio(
    audio: AudioData,
    destination: Path,
    token: CancellationToken,
    progress: ProgressCallback,
    analysing: int,
    saving: int,
) -> AudioStats:
    """Measure one stem, report both steps, and write it where it was asked for."""
    report_progress(progress, analysing, "analyzing_output")
    stats = analyze_audio(audio, token)
    if stats.peak_dbfs > 0.0:
        # A stem formed by subtraction can exceed full scale where the one taken
        # out of it was scaled to the output ceiling.  libsndfile clips on write,
        # so say so rather than let a flattened peak read as a cancellation fault.
        logger.warning("%s peaks at %+.2f dBFS and will clip", destination, stats.peak_dbfs)
    report_progress(progress, saving, "saving")
    write_wav_atomic(destination, audio, token)
    return replace(stats, file_size=destination.stat().st_size)
