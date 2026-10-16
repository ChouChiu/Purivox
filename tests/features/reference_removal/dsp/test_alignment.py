import numpy as np
import pytest
import soxr
from scipy.signal import butter, sosfilt

from features.reference_removal.dsp import align_audio, alignment, process_audio
from features.reference_removal.dsp.alignment import _spectral_flux_lag
from shared.dsp import time_stretch


def corr(first, second):
    return float(np.corrcoef(first, second)[0, 1])


def test_alignment_recovers_integer_and_fractional_delay(scene):
    sample_rate, _vocal, instrumental, mix = scene
    delay = int(0.05 * sample_rate)
    delayed = np.pad(instrumental[:-delay], (delay, 0))
    aligned = align_audio(np.stack([mix, mix]), np.stack([delayed, delayed]), sample_rate)
    assert corr(aligned[0, :sample_rate], instrumental[:sample_rate]) > 0.99


def test_alignment_recovers_delay_from_inverted_reference():
    sample_rate = 22_050
    rng = np.random.default_rng(72)
    instrumental = np.convolve(rng.normal(0.0, 0.1, sample_rate * 3), np.ones(9) / 9, mode="same")
    time = np.arange(instrumental.size) / sample_rate
    mix = instrumental + 0.3 * np.sin(2 * np.pi * 443 * time)
    delay = int(0.04 * sample_rate)
    inverted = -np.pad(instrumental[:-delay], (delay, 0))

    aligned = align_audio(np.stack([mix, mix]), np.stack([inverted, inverted]), sample_rate)

    assert (
        corr(aligned[0, sample_rate : 2 * sample_rate], instrumental[sample_rate : 2 * sample_rate])
        < -0.99
    )


def test_alignment_proxy_rejects_aliased_high_frequency_vocals():
    sample_rate = 22_050
    length = sample_rate * 4
    time = np.arange(length) / sample_rate
    rng = np.random.default_rng(91)
    reference = (
        0.12 * np.sin(2 * np.pi * 170 * time)
        + 0.08 * np.sin(2 * np.pi * 310 * time)
        + 0.04 * rng.normal(size=length)
    )
    delay = sample_rate // 25
    delayed = np.pad(reference[:-delay], (delay, 0))
    # This strong component is above the 2 kHz proxy's Nyquist frequency.  A
    # strided proxy aliases it into the alignment band even though it is absent
    # from the reference.
    unrelated_vocal = 0.45 * np.sin(2 * np.pi * 7_130 * time)
    mixture = delayed + unrelated_vocal

    aligned = align_audio(
        np.stack([mixture, mixture]),
        np.stack([reference, reference]),
        sample_rate,
    )

    assert (
        corr(aligned[0, sample_rate : 3 * sample_rate], delayed[sample_rate : 3 * sample_rate])
        > 0.98
    )


def test_spectral_flux_alignment_handles_different_mastering_and_polarity():
    sample_rate = 8_000
    length = sample_rate * 12
    rng = np.random.default_rng(124)
    reference = np.convolve(
        rng.normal(0.0, 0.08, length),
        np.ones(9) / 9,
        mode="same",
    )
    delay = round(0.36 * sample_rate)
    shifted = -np.pad(reference[:-delay], (delay, 0))
    time = np.arange(length) / sample_rate
    stage = (
        np.tanh(1.3 * shifted) / 1.3
        + 0.03 * np.sin(2 * np.pi * 431 * time)
        + rng.normal(0.0, 0.005, length)
    )

    lag = _spectral_flux_lag(
        np.stack([stage, 0.97 * stage]),
        np.stack([reference, 0.92 * reference]),
        sample_rate,
    )

    assert lag == pytest.approx(delay, abs=0.02 * sample_rate)


def test_confident_musical_offset_is_not_overridden_by_gcc(monkeypatch):
    sample_rate = 8_000
    rng = np.random.default_rng(125)
    reference = rng.normal(0.0, 0.08, (2, sample_rate * 3))
    mixture = reference + rng.normal(0.0, 0.01, reference.shape)
    musical_lag = 0.8 * sample_rate

    monkeypatch.setattr(
        alignment,
        "_spectral_flux_lag",
        lambda *_args, **_kwargs: musical_lag,
    )

    def unexpected_gcc(*_args, **_kwargs):
        raise AssertionError("GCC must only run when musical onset matching fails")

    monkeypatch.setattr(alignment, "_gcc_phat_lag", unexpected_gcc)

    aligned = align_audio(mixture, reference, sample_rate)

    assert aligned.shape == reference.shape


@pytest.mark.parametrize("rate", [0.004, 0.01])
def test_reference_cancellation_tracks_tempo_drift(rate):
    sample_rate = 22_050
    length = sample_rate * 5
    time = np.arange(length) / sample_rate
    vocal = 0.5 * np.sin(2 * np.pi * 440 * time) + 0.2 * np.sin(2 * np.pi * 880 * time)
    reference = 0.4 * np.sin(2 * np.pi * 110 * time) + 0.1 * np.sin(2 * np.pi * 220 * time)
    drifted = np.interp(np.arange(length) / (1 + rate), np.arange(length), reference)
    mixture = vocal + drifted
    aligned = align_audio(np.stack([mixture] * 2), np.stack([reference] * 2), sample_rate)
    output = process_audio(np.stack([mixture] * 2), aligned, sample_rate, 1.0, 8)
    assert corr(output[0], vocal) > 0.98
    assert abs(corr(output[0], reference)) < 0.05


def test_alignment_follows_a_device_clock_drift_to_a_fraction_of_a_sample():
    """Two clocks 60 ppm apart move the lag by a fraction of a sample per second.

    Above 4 kHz a lag error of one proxy sample is already most of a cycle, so
    the warped source matches the playback up there only if the track holds the
    lag well inside a sample.
    """
    sample_rate = 44_100
    frames = sample_rate * 8
    rng = np.random.default_rng(61)
    envelope = np.repeat(rng.uniform(0.2, 1.0, (2, 33)), sample_rate // 4, axis=1)[:, :frames]
    reference = (0.1 * rng.normal(0.0, 1.0, (2, frames)) * envelope).astype(np.float32)
    played = soxr.resample(reference.T, sample_rate, sample_rate * (1.0 + 60e-6), quality="VHQ").T[
        :, :frames
    ]
    live = 0.05 * np.sin(2 * np.pi * 431 * np.arange(frames) / sample_rate)
    stage = (played + live).astype(np.float32)

    aligned = align_audio(stage, reference, sample_rate, detect_speed=False)

    high = butter(6, 4000.0, "high", fs=sample_rate, output="sos")
    body = slice(sample_rate, frames - sample_rate)
    produced = sosfilt(high, aligned[:, body], axis=1)
    expected = sosfilt(high, played[:, body], axis=1)
    assert corr(produced.ravel(), expected.ravel()) > 0.9


def test_alignment_and_reference_cancellation_handle_segment_jitter():
    sample_rate = 22_050
    length = sample_rate * 5
    time = np.arange(length) / sample_rate
    vocal = 0.5 * np.sin(2 * np.pi * 440 * time)
    reference = 0.4 * np.sin(2 * np.pi * 110 * time)
    jittered = np.zeros_like(reference)
    for start in range(0, length, sample_rate):
        end = min(length, start + sample_rate)
        offset = ((start // sample_rate) % 5 - 2) * sample_rate // 500
        source = np.arange(start, end) + offset
        valid = (source >= 0) & (source < length)
        jittered[np.arange(start, end)[valid]] = reference[source[valid]]
    mixture = vocal + jittered
    aligned = align_audio(np.stack([mixture] * 2), np.stack([reference] * 2), sample_rate)
    output = process_audio(np.stack([mixture] * 2), aligned, sample_rate, 1.0, 8)
    assert corr(output[0], vocal) > 0.96
    assert abs(corr(output[0], reference)) < 0.08


def _attack_music(sample_rate: int, seconds: float, seed: int) -> np.ndarray:
    """Envelope-modulated tones: enough attacks for a tempo search to bite."""
    random = np.random.default_rng(seed)
    frames = round(seconds * sample_rate)
    time = np.arange(frames) / sample_rate
    signal = np.zeros(frames)
    for frequency in (97.0, 211.0, 389.0, 733.0):
        envelope = np.repeat(random.uniform(0.1, 1.0, round(seconds * 8)), sample_rate // 8)
        signal += envelope[:frames] * np.sin(
            2 * np.pi * frequency * time + random.uniform(0, 2 * np.pi)
        )
    return signal / 4


def test_alignment_recovers_a_tempo_shifted_reference():
    """A stage played 4% slower is invisible to drift tracking alone."""

    sample_rate = 8_000
    reference = _attack_music(sample_rate, 12.0, 7).astype(np.float32)
    stage_instrumental = time_stretch(reference[None, :], sample_rate, 1.04)[0]
    time = np.arange(stage_instrumental.size) / sample_rate
    live = (0.2 * np.sin(2 * np.pi * 441 * time)).astype(np.float32)
    mixture = stage_instrumental + live

    detected = align_audio(mixture[None, :], reference[None, :], sample_rate, detect_speed=True)
    undetected = align_audio(mixture[None, :], reference[None, :], sample_rate, detect_speed=False)

    window = slice(sample_rate, sample_rate * 6)
    assert corr(detected[0, window], stage_instrumental[window]) > 0.8
    assert corr(undetected[0, window], stage_instrumental[window]) < 0.5


def test_lanczos_interior_path_matches_the_boundary_formulation():
    """The interior fast path is an optimisation, not a second interpolation.

    A block inside the recording skips the mask/clip/gather reduction the first
    and last block still take.  The two have to agree, or every block seam would
    carry a step: the boundary blocks are pinned to the masked formulation
    exactly, and the interior to it within the precision it accumulates in.
    """
    from features.reference_removal.dsp.alignment import (
        _LANCZOS_PHASES,
        _LANCZOS_RADIUS,
        _lanczos,
        _lanczos_table,
    )

    def masked(values: np.ndarray, source: np.ndarray, radius: int = _LANCZOS_RADIUS):
        table, _sums = _lanczos_table(radius, _LANCZOS_PHASES)
        base = np.floor(source)
        phase = np.minimum(
            ((source - base) * _LANCZOS_PHASES).astype(np.int64),
            _LANCZOS_PHASES - 1,
        )
        weights = table[phase]
        indices = base.astype(np.int64)[:, None] + np.arange(-radius + 1, radius + 1)
        weights = weights * ((indices >= 0) & (indices < values.size))
        safe = np.clip(indices, 0, max(values.size - 1, 0))
        denominator = np.sum(weights, axis=1)
        return np.divide(
            np.sum(values[safe] * weights, axis=1),
            denominator,
            out=np.zeros(source.size, dtype=np.float64),
            where=np.abs(denominator) > 1e-12,
        )

    random = np.random.default_rng(7)
    values = random.normal(size=65_536).astype(np.float32)
    for start in (0, 20_000, 45_536):
        source = np.arange(start, start + 20_000, dtype=np.float64)
        source += random.uniform(-0.5, 0.5, source.size)
        produced = _lanczos(values, source)
        expected = masked(values, source)
        if start == 20_000:  # every tap lands inside the recording
            assert np.allclose(produced, expected, rtol=0.0, atol=1e-6)
        else:
            assert np.array_equal(produced, expected)
