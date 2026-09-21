from __future__ import annotations

import numpy as np
from scipy.signal import sosfilt

from features.stem_split.dsp.crossover import difference, lowpass, lowpass_sections
from shared.audio import BLOCK_FRAMES, AudioData
from shared.processing import CancellationToken

RATE = 8000


def _audio(samples: np.ndarray) -> AudioData:
    return AudioData(np.ascontiguousarray(samples, dtype=np.float32), RATE)


def _noise(channels: int, frames: int) -> np.ndarray:
    generator = np.random.default_rng(7)
    return generator.normal(0.0, 0.2, (channels, frames)).astype(np.float32)


def test_blocked_filtering_matches_one_pass():
    """The state carries across the block boundary, or every block starts at rest."""
    frames = BLOCK_FRAMES * 2 + 1234
    source = _audio(_noise(2, frames))
    destination = _audio(np.zeros((2, frames)))

    lowpass(source, destination, 150.0, CancellationToken())

    sections = lowpass_sections(RATE, 150.0)
    expected = sosfilt(sections, np.asarray(source.samples, dtype=np.float64), axis=1)
    assert np.allclose(destination.samples, expected, atol=1e-6)


def test_the_two_bands_reconstruct_the_recording():
    """A Butterworth pair does not add back up; a complementary split does."""
    frames = 40_000
    source = _audio(_noise(2, frames))
    low = _audio(np.zeros((2, frames)))
    high = _audio(np.zeros((2, frames)))
    token = CancellationToken()

    lowpass(source, low, 150.0, token)
    difference(high, source, low, token)

    assert np.allclose(low.samples + high.samples, source.samples, atol=1e-6)


def _tone_level(values: np.ndarray, frequency: float) -> float:
    """How much of one frequency a signal carries, regardless of its phase."""
    time = np.arange(values.size) / RATE
    reference = np.exp(-2j * np.pi * frequency * time)
    return float(np.abs(np.mean(values * reference)))


def test_the_low_band_keeps_the_bass_and_drops_the_presence():
    """Measured by level, not by waveform: a causal filter shifts the phase.

    The low band lags what it passes, which is the price of a single forward
    pass over a mapped recording.  What has to hold is its magnitude response
    and the exact reconstruction the test above asserts.
    """
    frames = 40_000
    time = np.arange(frames) / RATE
    bass = np.sin(2 * np.pi * 50.0 * time)
    presence = np.sin(2 * np.pi * 2000.0 * time)
    source = _audio(np.stack([bass + presence, bass + presence]))
    low = _audio(np.zeros((2, frames)))

    lowpass(source, low, 150.0, CancellationToken())

    # Well past the ramp-in of the filter, so the transient is not measured.
    body = low.samples[0, frames // 2 :]
    assert _tone_level(body, 50.0) > 0.9 * _tone_level(bass[frames // 2 :], 50.0)
    assert _tone_level(body, 2000.0) < 0.01 * _tone_level(presence[frames // 2 :], 2000.0)
