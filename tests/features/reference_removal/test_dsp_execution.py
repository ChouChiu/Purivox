"""Pyodide has no pthreads, so `process_audio` also has an inline schedule.

Only the execution strategy differs: the layout still decides the block size,
so the two paths have to agree on the samples they produce.
"""

import numpy as np
import pytest

from features.reference_removal.dsp import algorithms, process_audio

# Blocks never span less than the smoothing context, which is floored at twelve
# seconds, and a second worker is only scheduled past twice that.  Forty seconds
# at a low rate is the cheapest scene that still fills more than one batch.
SAMPLE_RATE = 8_000
SECONDS = 40
SIGMA = 3


@pytest.fixture
def batched_layout(monkeypatch):
    """Shrink the block to the context floor so the scene spans several of them."""
    monkeypatch.setattr(algorithms, "_MAX_PROCESSING_BLOCK_SECONDS", 12)
    monkeypatch.setattr(algorithms, "_MAX_PROCESSING_WORKERS", 3)


@pytest.fixture
def scene():
    time = np.arange(SAMPLE_RATE * SECONDS) / SAMPLE_RATE
    accompaniment = 0.4 * np.sin(2 * np.pi * 110 * time) + 0.1 * np.sin(2 * np.pi * 220 * time)
    vocal = 0.5 * np.sin(2 * np.pi * 440 * time)
    reference = np.stack([accompaniment, accompaniment]).astype(np.float32)
    mix = np.stack([accompaniment + vocal, accompaniment + vocal]).astype(np.float32)
    return mix, reference


def _schedule(length: int) -> tuple[int, int]:
    """The block starts and worker count `process_audio` would derive."""
    block, workers = algorithms._processing_layout(SAMPLE_RATE, SIGMA, length)
    overlap = min(
        max(round(0.5 * SIGMA * SAMPLE_RATE), 2 * SAMPLE_RATE),
        block // 3,
    )
    return len(range(0, length, block - overlap)), workers


def test_the_scene_fills_more_than_one_batch(batched_layout, scene):
    """Guard the fixture: a single-block schedule would compare nothing."""
    mix, _reference = scene
    starts, workers = _schedule(mix.shape[1])
    assert workers > 1
    assert starts > workers


def test_inline_and_pooled_schedules_agree(batched_layout, scene, monkeypatch):
    mix, reference = scene

    monkeypatch.setattr(algorithms, "_THREADS_AVAILABLE", True)
    pooled = process_audio(mix, reference, SAMPLE_RATE, 0.75, SIGMA)
    monkeypatch.setattr(algorithms, "_THREADS_AVAILABLE", False)
    inline = process_audio(mix, reference, SAMPLE_RATE, 0.75, SIGMA)

    assert np.array_equal(pooled, inline)
