from __future__ import annotations

import numpy as np
import pytest

from shared.dsp import time_stretch
from shared.processing import CancellationToken, ProcessingCancelled

SAMPLE_RATE = 16_000


def _tone(seconds: float = 3.0, frequency: float = 440.0) -> np.ndarray:
    time = np.arange(round(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return np.sin(2 * np.pi * frequency * time).astype(np.float32)


def _rms(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(values, dtype=np.float64) ** 2)))


def test_a_ratio_of_one_returns_the_input_unchanged():
    signal = np.stack([_tone(), _tone()])
    assert time_stretch(signal, SAMPLE_RATE, 1.0) is signal


def test_the_output_length_follows_the_ratio():
    signal = np.stack([_tone()])
    for ratio in (0.5, 0.9, 1.0, 1.03, 2.0):
        assert time_stretch(signal, SAMPLE_RATE, ratio).shape == (1, round(signal.shape[1] * ratio))


def test_the_pitch_survives_the_stretch():
    """The whole point: a resample would move 1.03 to -51 cents."""
    signal = np.stack([_tone(frequency=440.0)])
    stretched = time_stretch(signal, SAMPLE_RATE, 1.03)[0]
    spectrum = np.abs(np.fft.rfft(stretched * np.hanning(stretched.size), 1 << 16))
    frequencies = np.fft.rfftfreq(1 << 16, 1 / SAMPLE_RATE)
    peak = float(frequencies[int(np.argmax(spectrum))])
    assert abs(peak - 440.0) < 1.0, f"stretched tone landed at {peak:.2f} Hz"


def test_the_envelope_survives_the_edges():
    """A missing overlap-add normalisation is only visible at the boundaries."""
    signal = np.stack([_tone(seconds=2.0)])
    stretched = time_stretch(signal, SAMPLE_RATE, 1.5)[0]
    window = round(0.064 * SAMPLE_RATE)
    for start in (0, stretched.size // 2, stretched.size - 2 * window):
        source = round(start / 1.5)
        assert _rms(stretched[start : start + window]) == pytest.approx(
            _rms(signal[0, source : source + window]), rel=0.15
        )


def test_a_round_trip_keeps_the_waveform():
    signal = np.stack([_tone(seconds=2.0)])
    there = time_stretch(signal, SAMPLE_RATE, 2.0)
    back = time_stretch(there, SAMPLE_RATE, 0.5)
    first, second = signal[0], back[0]
    length = min(first.size, second.size)
    correlation = float(np.corrcoef(first[:length], second[:length])[0, 1])
    assert correlation > 0.9


def test_channels_keep_their_relationship():
    left = _tone()
    right = np.roll(left, 37)
    stretched = time_stretch(np.stack([left, right]), SAMPLE_RATE, 1.05)
    length = min(stretched.shape[1], right.size)
    assert float(np.corrcoef(stretched[0, :length], stretched[1, :length])[0, 1]) > 0.9


def test_audio_shorter_than_a_window_is_returned_unchanged():
    signal = np.zeros((1, 200), dtype=np.float32)
    assert time_stretch(signal, SAMPLE_RATE, 1.5).shape == signal.shape


def test_an_impossible_ratio_is_rejected():
    signal = np.stack([_tone()])
    for ratio in (0.0, -1.0, 8.0, float("nan")):
        with pytest.raises(ValueError):
            time_stretch(signal, SAMPLE_RATE, ratio)


def test_cancellation_is_honoured():
    token = CancellationToken()
    token.cancel()
    with pytest.raises(ProcessingCancelled):
        time_stretch(np.stack([_tone()]), SAMPLE_RATE, 1.05, token)
