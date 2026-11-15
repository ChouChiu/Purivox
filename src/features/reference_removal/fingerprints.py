from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.fft import irfft, next_fast_len, rfft


@dataclass(frozen=True, slots=True)
class StageSpectra:
    """The stage side of an anchor search, computed once instead of per anchor.

    Every anchor of one search slides a query of the same width over the whole
    stage track, so the stage's transform and its running energy do not change
    between them.  Recomputing both per anchor was the bulk of an analysis: a
    four-minute source asks for seven of them looking for the whole song and
    another forty-six looking for short reuses.
    """

    length: int
    size: int
    spectra: np.ndarray
    cumulative: np.ndarray


def stage_spectra(stage: np.ndarray, width: int) -> StageSpectra:
    """Prepare `stage` for correlating against any query of `width` frames.

    The transform length is the one `scipy.signal.correlate` would have chosen
    for this pair, so the scores below are the ones it would have returned.
    """
    length = stage.shape[1]
    size = next_fast_len(length + width - 1, True)
    cumulative = np.concatenate(
        (np.zeros((stage.shape[0], 1)), np.cumsum(stage * stage, axis=1)),
        axis=1,
    )
    # One band at a time, not one batched transform: pocketfft chooses a
    # different vectorisation for a stack than for a single row, and the last
    # digit of a score would then depend on how the bands were handed to it.
    spectra = np.stack([rfft(band, size) for band in stage])
    return StageSpectra(length, size, spectra, cumulative)


def normalized_correlation(stage: StageSpectra, query: np.ndarray) -> np.ndarray:
    width = query.shape[1]
    if width > stage.length:
        return np.empty(0, dtype=np.float64)
    score = np.zeros(stage.length - width + 1, dtype=np.float64)
    stage_energy = np.zeros_like(score)
    query_energy = float(np.sum(query * query))
    for band, cumulative, query_band in zip(stage.spectra, stage.cumulative, query, strict=True):
        # `correlate(a, b, "valid", "fft")` is this transform of `a` times the
        # transform of the reversed `b`, sliced to the fully overlapping part.
        full = irfft(band * rfft(query_band[::-1], stage.size), stage.size)
        score += full[width - 1 : stage.length]
        stage_energy += cumulative[width:] - cumulative[:-width]
    return np.divide(
        score,
        np.sqrt(stage_energy * query_energy) + 1e-12,
        out=np.zeros_like(score),
    )
