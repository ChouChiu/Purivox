from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from shared.dsp import RateEstimate, estimate_rate, time_stretch
from shared.processing import CancellationToken, ProcessingCancelled

SAMPLE_RATE = 8_000
FEATURE_RATE = 4_000


def _music(seconds: float = 12.0, seed: int = 3) -> np.ndarray:
    """Envelope-modulated tones, so the attack features have something to find."""
    random = np.random.default_rng(seed)
    frames = round(seconds * SAMPLE_RATE)
    time = np.arange(frames) / SAMPLE_RATE
    signal = np.zeros(frames)
    for frequency in (97.0, 211.0, 389.0, 733.0):
        envelope = np.repeat(random.uniform(0.1, 1.0, round(seconds * 8)), SAMPLE_RATE // 8)
        signal += envelope[:frames] * np.sin(
            2 * np.pi * frequency * time + random.uniform(0, 2 * np.pi)
        )
    return (signal / 4).astype(np.float32)


def _proxy(signal: np.ndarray) -> np.ndarray:
    return signal[:: SAMPLE_RATE // FEATURE_RATE].astype(np.float64)


def _stage(source: np.ndarray, ratio: float, seed: int = 11) -> np.ndarray:
    """A stage take that plays `source` at a shifted tempo, plus some live noise."""
    stretched = time_stretch(source[None, :], SAMPLE_RATE, ratio)[0]
    noise = np.random.default_rng(seed).normal(0, 0.02, stretched.size).astype(np.float32)
    return stretched + noise


@pytest.mark.parametrize("ratio", [0.94, 0.97, 1.0, 1.03, 1.06])
def test_the_ratio_of_a_shifted_stage_is_recovered(ratio: float):
    source = _music()
    stage = _stage(source, ratio)
    estimate = estimate_rate(_proxy(stage), _proxy(source), FEATURE_RATE)
    assert estimate is not None
    assert estimate.ratio == pytest.approx(ratio, abs=0.002)
    if ratio == 1.0:
        assert not estimate.reliable, "an unchanged stage must stay on the existing path"
    else:
        assert estimate.reliable
        assert estimate.improvement > 0.0


def test_a_source_played_twice_at_two_tempos_is_left_alone():
    """Two comparable peaks mean no single global ratio can be trusted."""
    source = _music()
    stage = np.concatenate(
        (
            _stage(source, 0.96, seed=21),
            np.zeros(SAMPLE_RATE, dtype=np.float32),
            _stage(source, 1.04, seed=22),
        )
    )

    estimate = estimate_rate(_proxy(stage), _proxy(source), FEATURE_RATE)

    assert estimate is not None
    assert not estimate.reliable


def test_an_estimate_that_is_not_clearly_better_is_refused():
    """The gates are the safety net that keeps aligned material untouched."""
    accepted = RateEstimate(ratio=1.03, score=0.66, rival=0.31, improvement=0.39)
    assert accepted.reliable
    assert not replace(accepted, score=0.24).reliable
    assert not replace(accepted, rival=0.65).reliable
    assert not replace(accepted, improvement=0.03).reliable
    assert not replace(accepted, ratio=1.001).reliable


def test_a_different_piece_at_the_same_tempo_is_left_alone():
    estimate = estimate_rate(_proxy(_music(seed=1)), _proxy(_music(seed=2)), FEATURE_RATE)
    assert estimate is None or not estimate.reliable


def test_audio_with_no_common_structure_produces_no_peak():
    source = _music()
    noise = np.random.default_rng(4).normal(0, 0.2, source.size).astype(np.float32)
    assert estimate_rate(_proxy(source), _proxy(noise), FEATURE_RATE) is None


def test_short_audio_is_refused():
    assert estimate_rate(_proxy(_music(4.0)), _proxy(_music(4.0)), FEATURE_RATE) is None


def test_cancellation_is_honoured():
    token = CancellationToken()
    token.cancel()
    with pytest.raises(ProcessingCancelled):
        estimate_rate(_proxy(_music()), _proxy(_music()), FEATURE_RATE, token)
