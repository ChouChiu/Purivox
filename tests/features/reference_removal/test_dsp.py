from threading import Barrier, Lock, get_ident

import numpy as np
import pytest
from scipy.signal import fftconvolve

from features.reference_removal.dsp import align_audio, alignment, process_audio
from features.reference_removal.dsp.alignment import _spectral_flux_lag
from shared.audio import create_pcm_audio
from shared.processing import CancellationToken, ProcessingCancelled


def corr(first, second):
    return float(np.corrcoef(first, second)[0, 1])


@pytest.fixture(scope="module")
def scene():
    sample_rate = 22_050
    time = np.arange(sample_rate * 3) / sample_rate
    vocal = 0.5 * np.sin(2 * np.pi * 440 * time) + 0.2 * np.sin(2 * np.pi * 880 * time)
    instrumental = 0.4 * np.sin(2 * np.pi * 110 * time) + 0.1 * np.sin(2 * np.pi * 220 * time)
    return sample_rate, vocal, instrumental, vocal + instrumental


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


def test_reference_cancellation_stereo_mimo_cancels_crossfeed():
    sample_rate = 16_000
    time = np.arange(sample_rate * 2) / sample_rate
    left_ref = np.sin(2 * np.pi * 123 * time) * 0.25
    right_ref = np.sin(2 * np.pi * 181 * time) * 0.23
    left_vocal = np.sin(2 * np.pi * 431 * time) * 0.35
    right_vocal = left_vocal * 0.95
    mix = np.stack(
        [
            left_vocal + 0.72 * left_ref + 0.38 * right_ref,
            right_vocal - 0.26 * left_ref + 0.81 * right_ref,
        ]
    )
    output = process_audio(mix, np.stack([left_ref, right_ref]), sample_rate, 1.0, 8)
    assert min(corr(output[0], left_vocal), corr(output[1], right_vocal)) > 0.96
    assert max(abs(corr(output[0], left_ref)), abs(corr(output[1], right_ref))) < 0.12


def test_reference_cancellation_cancels_inverted_reference():
    sample_rate = 16_000
    length = sample_rate * 4
    rng = np.random.default_rng(93)
    reference = rng.normal(0.0, 0.08, (2, length))
    time = np.arange(length) / sample_rate
    live = np.stack(
        [
            0.3 * np.sin(2 * np.pi * 431 * time),
            0.27 * np.sin(2 * np.pi * 431 * time),
        ]
    )
    inverted_transfer = np.asarray([[-0.72, 0.18], [-0.11, -0.83]])
    mixture = live + inverted_transfer @ reference

    output = process_audio(mixture, reference, sample_rate, 1.0, 8)

    assert corr(output.ravel(), live.ravel()) > 0.995
    assert abs(corr(output.ravel(), reference.ravel())) < 0.01


def test_silent_reference_leaves_mix_nearly_bypassed():
    sample_rate = 16_000
    length = sample_rate * 2
    time = np.arange(length) / sample_rate
    centered = 0.2 * np.sin(2 * np.pi * 431 * time)
    mixture = np.stack(
        [
            centered + 0.05 * np.sin(2 * np.pi * 173 * time),
            centered + 0.05 * np.sin(2 * np.pi * 227 * time),
        ]
    )

    output = process_audio(
        mixture,
        np.zeros_like(mixture),
        sample_rate,
        0.75,
        8,
    )

    assert corr(output[0], mixture[0]) > 0.999
    assert corr(output[1], mixture[1]) > 0.999
    assert np.sqrt(np.mean((output - mixture) ** 2)) < 0.05 * np.sqrt(np.mean(mixture**2))


def test_bypass_and_cancellation(scene):
    sample_rate, _vocal, instrumental, mix = scene
    stereo = np.stack([mix, mix])
    assert np.array_equal(
        process_audio(
            stereo,
            np.stack([instrumental] * 2),
            sample_rate,
            0,
            8,
        ),
        stereo.astype(np.float32),
    )
    token = CancellationToken()
    token.cancel()
    with pytest.raises(ProcessingCancelled):
        process_audio(
            stereo,
            np.stack([instrumental] * 2),
            sample_rate,
            1,
            8,
            token,
        )


def test_reference_cancellation_applies_linked_minus_one_db_peak_protection():
    sample_rate = 16_000
    length = sample_rate * 2
    time = np.arange(length) / sample_rate
    centered = 0.98 * np.sin(2 * np.pi * 431 * time)
    reference = np.stack(
        [
            0.05 * np.sin(2 * np.pi * 123 * time),
            0.04 * np.sin(2 * np.pi * 181 * time),
        ]
    )
    mixture = np.stack([centered, 0.8 * centered]) + reference

    output = process_audio(
        mixture,
        reference,
        sample_rate,
        1.0,
        8,
    )

    ceiling = 10 ** (-1.0 / 20.0)
    assert np.max(np.abs(output)) <= ceiling + 1e-6
    assert np.max(np.abs(output[0])) == pytest.approx(ceiling, abs=1e-6)
    assert np.max(np.abs(output[1])) < ceiling


def test_reference_cancellation_clamps_strength_above_one(scene):
    sample_rate, _vocal, instrumental, mix = scene
    stereo_mix = np.stack([mix, mix])
    stereo_reference = np.stack([instrumental, instrumental])

    maximum = process_audio(
        stereo_mix,
        stereo_reference,
        sample_rate,
        1.0,
        8,
    )
    excessive = process_audio(
        stereo_mix,
        stereo_reference,
        sample_rate,
        5.0,
        8,
    )

    assert np.array_equal(excessive, maximum)


def test_process_audio_writes_supplied_disk_buffer(scene):
    sample_rate, _vocal, instrumental, mix = scene
    target = create_pcm_audio(2, mix.size, sample_rate)
    try:
        output = process_audio(
            np.stack([mix] * 2),
            np.stack([instrumental] * 2),
            sample_rate,
            0.5,
            8,
            output=target.samples,
        )
        assert output is target.samples
        assert np.isfinite(output).all()
    finally:
        target.cleanup()


def test_processing_block_uses_two_gib_working_set_budget():
    from features.reference_removal.dsp.algorithms import _processing_block_frames

    block_44k = _processing_block_frames(44_100, 8)
    block_96k = _processing_block_frames(96_000, 8)

    assert 44 * 44_100 <= block_44k <= 46 * 44_100
    assert 20 * 96_000 <= block_96k <= 22 * 96_000


def test_long_processing_uses_two_spectral_workers(monkeypatch):
    sample_rate = 44_100
    length = 40 * sample_rate
    mixture = np.zeros((2, length), dtype=np.float32)
    reference = np.zeros_like(mixture)
    worker_ids = set()
    rendezvous = Barrier(2)
    call_lock = Lock()
    calls = 0
    monkeypatch.setattr(
        "features.reference_removal.dsp.algorithms._MAX_PROCESSING_WORKERS",
        2,
    )

    def passthrough(song, *_args):
        nonlocal calls
        worker_ids.add(get_ident())
        with call_lock:
            call_index = calls
            calls += 1
        if call_index < 2:
            rendezvous.wait(timeout=5)
        return song.copy()

    monkeypatch.setattr(
        "features.reference_removal.dsp.algorithms._reference_cancel",
        passthrough,
    )

    output = process_audio(mixture, reference, sample_rate, 1.0, 8)

    assert len(worker_ids) == 2
    assert np.array_equal(output, mixture)


def test_process_audio_uses_reference_cancellation(monkeypatch):
    sample_rate = 8_000
    time = np.arange(sample_rate * 2) / sample_rate
    vocal = 0.3 * np.sin(2 * np.pi * 440 * time)
    reference = 0.2 * np.sin(2 * np.pi * 110 * time)
    mixture = np.stack([vocal + reference, 0.95 * vocal + reference])
    from features.reference_removal.dsp import algorithms

    calls = []
    original = algorithms._reference_cancel
    monkeypatch.setattr(
        "features.reference_removal.dsp.algorithms._reference_cancel",
        lambda *args: calls.append(args) or original(*args),
    )

    output = process_audio(
        mixture,
        np.stack([reference, reference]),
        sample_rate,
        1.0,
        3,
    )

    assert calls
    assert corr(output[0], vocal) > 0.99
    assert abs(corr(output[0], reference)) < 0.08


def test_reference_mask_does_not_inject_reference_only_lyrics():
    sample_rate = 8_000
    length = sample_rate * 3
    time = np.arange(length) / sample_rate
    changed = time >= 1.0
    backing = 0.25 * np.sin(2 * np.pi * 125 * time)
    live_word = changed * 0.28 * np.sin(2 * np.pi * 437 * time)
    reference_only_word = changed * 0.22 * np.sin(2 * np.pi * 703 * time)
    mixture = np.stack([backing + live_word, 0.95 * backing + 0.9 * live_word])
    contaminated_reference = np.stack(
        [backing + reference_only_word, 0.92 * backing + reference_only_word]
    )

    output = process_audio(
        mixture,
        contaminated_reference,
        sample_rate,
        1.0,
        8,
    )

    old_word = np.stack([reference_only_word, reference_only_word])
    old_word_gain = np.dot(output.ravel(), old_word.ravel()) / np.dot(
        old_word.ravel(), old_word.ravel()
    )
    live_word_gain = np.dot(output.ravel(), np.tile(live_word, (2, 1)).ravel()) / np.dot(
        np.tile(live_word, (2, 1)).ravel(),
        np.tile(live_word, (2, 1)).ravel(),
    )
    assert abs(old_word_gain) < 0.01
    assert live_word_gain > 0.7


def test_reference_mask_ignores_reference_polarity():
    sample_rate = 8_000
    rng = np.random.default_rng(130)
    reference = rng.normal(0.0, 0.08, (2, sample_rate * 2))
    time = np.arange(reference.shape[1]) / sample_rate
    vocal = np.stack([0.3 * np.sin(2 * np.pi * 431 * time)] * 2)
    mixture = vocal + np.asarray([[0.7, 0.2], [-0.1, 0.8]]) @ reference

    normal = process_audio(mixture, reference, sample_rate, 1.0, 3)
    inverted = process_audio(mixture, -reference, sample_rate, 1.0, 3)

    assert np.allclose(normal, inverted, atol=2e-5)
    assert corr(normal.ravel(), vocal.ravel()) > 0.95


def test_reference_mask_leaves_an_unrelated_reference_nearly_bypassed():
    sample_rate = 8_000
    rng = np.random.default_rng(131)
    mixture = rng.normal(0.0, 0.1, (2, sample_rate * 2))
    unrelated = rng.normal(0.0, 0.1, mixture.shape)

    output = process_audio(mixture, unrelated, sample_rate, 1.0, 3)

    assert corr(output.ravel(), mixture.ravel()) > 0.999
    assert np.sqrt(np.mean((output - mixture) ** 2)) < 0.01


def test_reference_mask_handles_frequency_dependent_room_transfer():
    sample_rate = 8_000
    length = sample_rate * 4
    rng = np.random.default_rng(140)
    reference = np.stack(
        [
            np.convolve(rng.normal(0.0, 0.11, length), np.ones(3) / 3, mode="same"),
            np.convolve(rng.normal(0.0, 0.11, length), np.ones(7) / 7, mode="same"),
        ]
    )

    def impulse(size, taps):
        response = np.zeros(size)
        for delay, gain in taps:
            response[delay] = gain
        return response

    transfers = (
        impulse(301, ((0, 0.45), (57, 0.4), (160, -0.25), (300, 0.2))),
        impulse(241, ((15, 0.35), (100, 0.25), (240, -0.2))),
        impulse(281, ((7, -0.3), (120, 0.25), (280, 0.2))),
        impulse(351, ((0, 0.5), (73, 0.35), (180, -0.25), (350, 0.2))),
    )
    transferred = np.stack(
        [
            fftconvolve(reference[0], transfers[0])[:length]
            + fftconvolve(reference[1], transfers[1])[:length],
            fftconvolve(reference[0], transfers[2])[:length]
            + fftconvolve(reference[1], transfers[3])[:length],
        ]
    )
    time = np.arange(length) / sample_rate
    center = 0.24 * np.sin(2 * np.pi * 431 * time) + 0.1 * np.sin(2 * np.pi * 863 * time)
    vocal = np.stack([center, 0.95 * center])
    mixture = vocal + transferred

    spectral = process_audio(mixture, reference, sample_rate, 1.0, 3)

    spectral_error = np.sqrt(np.mean((spectral - vocal) ** 2))
    assert spectral_error < 0.05
    assert corr(spectral.ravel(), vocal.ravel()) > 0.9


def test_reference_mask_keeps_the_song_tail_after_a_short_reference():
    sample_rate = 8_000
    song_length = sample_rate * 4
    reference_length = sample_rate * 2
    time = np.arange(song_length) / sample_rate
    vocal = 0.24 * np.sin(2 * np.pi * 431 * time)
    reference = 0.18 * np.sin(2 * np.pi * 127 * np.arange(reference_length) / sample_rate)
    padded_reference = np.pad(reference, (0, song_length - reference_length))
    mixture = np.stack([vocal + padded_reference, 0.95 * vocal + padded_reference])

    output = process_audio(
        mixture,
        np.stack([reference, reference]),
        sample_rate,
        1.0,
        8,
    )

    # Exclude the final STFT synthesis window, whose zero-padding changes only
    # the last few milliseconds while retaining the complete output duration.
    tail = slice(3 * sample_rate, song_length - sample_rate // 10)
    assert output.shape == mixture.shape
    assert np.allclose(output[:, tail], mixture[:, tail], atol=2e-4)


def test_reference_cancellation_handles_a_phase_correlated_stereo_reference():
    """Guards the orientation of the normal equations.

    The existing MIMO case mixes two uncorrelated tones, so the reference
    covariance is nearly diagonal and a transposed system still cancels.  A
    real stereo accompaniment has strongly correlated channels separated by a
    small inter-channel delay, which puts most of the cross term in the
    imaginary part.  Solving the conjugate transpose then fits a different
    transfer: measured on this scene it costs about 3.4 dB of cancellation
    depth and drops live-source fidelity from 0.68 to 0.39.
    """
    sample_rate = 16_000
    length = sample_rate * 4
    rng = np.random.default_rng(311)
    left_ref = np.convolve(rng.normal(0.0, 0.25, length), np.ones(5) / 5, mode="same")
    delay = 7
    right_ref = 0.9 * np.pad(left_ref[:-delay], (delay, 0)) + rng.normal(0.0, 0.02, length)
    # A broadband live source, not a tone: a single tone occupies too few bins
    # for a wrongly oriented transfer to show up.
    live = np.convolve(rng.normal(0.0, 0.08, length), np.ones(3) / 3, mode="same")
    accompaniment = 0.85 * left_ref + 0.31 * right_ref
    mix = np.stack([live + accompaniment, 0.95 * live - 0.22 * left_ref + 0.78 * right_ref])

    output = process_audio(mix, np.stack([left_ref, right_ref]), sample_rate, 1.0, 8)

    body = slice(sample_rate, 3 * sample_rate)
    residual = output[0][body] - live[body]
    depth = 10 * np.log10(
        float(np.mean(accompaniment[body] ** 2)) / max(float(np.mean(residual**2)), 1e-20)
    )
    assert depth > 8.0
    assert corr(output[0][body], live[body]) > 0.60
