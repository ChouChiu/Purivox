from __future__ import annotations

import resource
from time import perf_counter

import numpy as np
import pytest

from features.reference_removal.dsp import process_audio
from features.reference_removal.dsp.algorithms import _processing_layout
from shared.audio import create_pcm_audio
from shared.processing import CancellationToken


@pytest.mark.slow
def test_fifteen_minute_stereo_rss_length_and_seams():
    """Synthetic regression evidence only; this is not a real-music quality claim."""
    sample_rate = 44_100
    frames = 15 * 60 * sample_rate
    mix = create_pcm_audio(2, frames, sample_rate)
    reference = create_pcm_audio(2, frames, sample_rate)
    output = create_pcm_audio(2, frames, sample_rate)
    try:
        fill_block = sample_rate * 10
        for start in range(0, frames, fill_block):
            end = min(start + fill_block, frames)
            time = np.arange(start, end, dtype=np.float64) / sample_rate
            accompaniment = (0.20 * np.sin(2 * np.pi * 110 * time)).astype(np.float32)
            vocal = (0.12 * np.sin(2 * np.pi * 440 * time)).astype(np.float32)
            reference.samples[:, start:end] = accompaniment
            mix.samples[:, start:end] = accompaniment + vocal
        mix.release_pages()
        reference.release_pages()

        started = perf_counter()
        result = process_audio(
            mix.samples,
            reference.samples,
            sample_rate,
            0.75,
            8,
            CancellationToken(),
            output.samples,
        )
        elapsed = perf_counter() - started
        assert result is output.samples
        assert result.shape == (2, frames)
        assert np.isfinite(result[:, ::sample_rate]).all()
        # The 2 GiB working-set budget permits about 45-second blocks at 44.1 kHz.
        # The four-second overlap still supplies the full sigma context.
        block, _workers = _processing_layout(sample_rate, 8, frames)
        overlap = min(round(0.5 * 8 * sample_rate), block // 3)
        step = block - overlap
        seams = np.arange(step, frames, step)
        jumps = np.abs(result[0, seams] - result[0, seams - 1])
        assert float(np.max(jumps, initial=0.0)) < 0.05
        peak_rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Printed, never asserted: wall clock depends on the machine and the
        # number of cores `_processing_layout` picks, so a threshold here would
        # be a flaky gate rather than a measurement.
        print(
            f"15-minute benchmark: {elapsed:.1f} s "
            f"({15 * 60 / elapsed:.1f}x realtime), peak RSS {peak_rss_kib / 1024:.1f} MiB"
        )
        assert peak_rss_kib <= 2 * 1024 * 1024
    finally:
        output.cleanup()
        reference.cleanup()
        mix.cleanup()
