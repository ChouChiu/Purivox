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
        values = np.asarray(audio.samples[:, start:end], dtype=np.float32)
        peak = max(peak, float(np.max(np.abs(values), initial=0.0)))
        # A float32 sum of squares per block, accumulated in float64 across the
        # file: widening every sample to float64 first measured three times
        # slower for a statistic that is displayed to a tenth of a decibel.
        square_sum += float(np.einsum("ij,ij->", values, values))
        sample_count += values.size
    rms = math.sqrt(square_sum / sample_count)
    return AudioStats(
        duration_seconds=audio.frames / audio.sample_rate,
        sample_rate=audio.sample_rate,
        channels=audio.channels,
        bit_depth=audio.bit_depth,
        peak_dbfs=_dbfs(peak),
        rms_dbfs=_dbfs(rms),
    )


def _require_matching_formats(source: AudioData, destination: AudioData) -> None:
    """Both block loops address the two arrays with the same indices."""
    if (
        source.channels != destination.channels
        or source.frames != destination.frames
        or source.sample_rate != destination.sample_rate
    ):
        raise ValueError("source and destination audio formats must match")


def copy_audio(
    source: AudioData,
    destination: AudioData,
    token: CancellationToken | None = None,
) -> None:
    """Copy compatible mapped audio in cancellable, bounded-memory blocks."""
    _require_matching_formats(source, destination)
    token = token or CancellationToken()
    for start in range(0, source.frames, BLOCK_FRAMES):
        token.raise_if_cancelled()
        end = min(start + BLOCK_FRAMES, source.frames)
        destination.samples[:, start:end] = source.samples[:, start:end]


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
        # A synthesised stem can exceed full scale where the estimate behind it
        # is larger than the recording it came from.  libsndfile clips on write,
        # so say so rather than let a flattened peak read as a cancellation fault.
        logger.warning("%s peaks at %+.2f dBFS and will clip", destination, stats.peak_dbfs)
    report_progress(progress, saving, "saving")
    write_wav_atomic(destination, audio, token)
    return replace(stats, file_size=destination.stat().st_size)
