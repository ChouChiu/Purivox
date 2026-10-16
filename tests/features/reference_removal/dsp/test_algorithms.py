from threading import Barrier, Lock, get_ident

import numpy as np
import pytest
from scipy.signal import fftconvolve

from features.reference_removal.dsp import algorithms, process_audio
from shared.audio import create_pcm_audio
from shared.processing import CancellationToken, ProcessingCancelled


def corr(first, second):
    return float(np.corrcoef(first, second)[0, 1])


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
    block_44k = algorithms._processing_block_frames(44_100, 8)
    block_96k = algorithms._processing_block_frames(96_000, 8)

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
        return song.copy(), None

    monkeypatch.setattr(
        "features.reference_removal.dsp.algorithms._reference_cancel",
        passthrough,
    )

    output = process_audio(mixture, reference, sample_rate, 1.0, 8)

    assert len(worker_ids) == 2
    assert np.array_equal(output, mixture)


def test_inline_and_pooled_schedules_agree(monkeypatch):
    """Pyodide has no pthreads, so `process_audio` also has an inline schedule.

    Only the execution strategy differs: the layout still decides the block
    size, so the two paths have to produce the same samples.  The block is
    shrunk to the twelve-second context floor so forty seconds at a low rate
    spans several batches.
    """
    sample_rate, sigma = 8_000, 3
    monkeypatch.setattr(algorithms, "_MAX_PROCESSING_BLOCK_SECONDS", 12)
    monkeypatch.setattr(algorithms, "_MAX_PROCESSING_WORKERS", 3)
    time = np.arange(sample_rate * 40) / sample_rate
    accompaniment = 0.4 * np.sin(2 * np.pi * 110 * time) + 0.1 * np.sin(2 * np.pi * 220 * time)
    vocal = 0.5 * np.sin(2 * np.pi * 440 * time)
    reference = np.stack([accompaniment, accompaniment]).astype(np.float32)
    mix = np.stack([accompaniment + vocal, accompaniment + vocal]).astype(np.float32)
    _block, workers = algorithms._processing_layout(sample_rate, sigma, mix.shape[1])
    assert workers > 1, "a single-worker schedule would compare nothing"

    monkeypatch.setattr(algorithms, "_THREADS_AVAILABLE", True)
    pooled = process_audio(mix, reference, sample_rate, 0.75, sigma)
    monkeypatch.setattr(algorithms, "_THREADS_AVAILABLE", False)
    inline = process_audio(mix, reference, sample_rate, 0.75, sigma)

    assert np.array_equal(pooled, inline)


def _backing_scene(seconds: float = 3.0):
    sample_rate = 8_000
    time = np.arange(int(sample_rate * seconds)) / sample_rate
    source = 0.25 * np.sin(2 * np.pi * 110 * time) + 0.12 * np.sin(2 * np.pi * 220 * time)
    live = 0.3 * np.sin(2 * np.pi * 440 * time)
    accompaniment = np.stack([0.9 * source, 0.85 * source])
    mixture = (accompaniment + np.stack([live, 0.95 * live])).astype(np.float32)
    return sample_rate, np.stack([source, source]).astype(np.float32), accompaniment, live, mixture


def test_process_audio_renders_the_backing_from_the_source():
    """The backing is the estimate applied to the source, not the stage less the vocal."""
    sample_rate, reference, accompaniment, live, mixture = _backing_scene()
    output = np.empty_like(mixture)
    backing = np.empty_like(mixture)

    process_audio(mixture, reference, sample_rate, 1.0, 8, None, output, backing)

    body = slice(sample_rate // 2, -sample_rate // 2)
    # The source's own waveform, at the level the stage carried it.
    assert corr(backing[0, body], reference[0, body]) > 0.99
    level_db = 10 * np.log10(np.mean(backing[:, body] ** 2) / np.mean(accompaniment[:, body] ** 2))
    assert abs(level_db) < 1.0
    # And none of the live voice, which the source does not contain.
    assert abs(float(np.dot(backing[0, body], live[body]) / np.dot(live[body], live[body]))) < 0.01


def test_a_playback_hotter_than_the_source_cancels_like_a_level_matched_one():
    """A quiet master against a hot PA is a level difference, not weak evidence."""
    sample_rate, reference, accompaniment, live, mixture = _backing_scene()
    body = slice(sample_rate // 2, -sample_rate // 2)
    stage_live = np.stack([live, 0.95 * live])

    def run(source):
        output = np.empty_like(mixture)
        backing = np.empty_like(mixture)
        process_audio(mixture, source, sample_rate, 1.0, 8, None, output, backing)
        residual = output[:, body] - stage_live[:, body]
        depth = 10 * np.log10(np.mean(accompaniment[:, body] ** 2) / np.mean(residual**2))
        level = 10 * np.log10(np.mean(backing[:, body] ** 2) / np.mean(accompaniment[:, body] ** 2))
        return depth, level

    matched_depth, _matched_level = run(reference)
    # The stage carries the source 12 dB hotter than the file holds it.
    hot_depth, hot_level = run(reference / 4.0)

    assert hot_depth > matched_depth - 1.0
    assert abs(hot_level) < 1.0


def test_process_audio_bypass_leaves_the_backing_silent():
    """Nothing was cancelled, so there is no estimate to render."""
    sample_rate, reference, _accompaniment, _live, mixture = _backing_scene()
    backing = np.ones_like(mixture)

    output = process_audio(mixture, reference, sample_rate, 0.0, 8, None, None, backing)

    assert np.array_equal(output, mixture)
    assert not np.any(backing)


def test_process_audio_backs_nothing_off_an_unrelated_source():
    sample_rate = 8_000
    rng = np.random.default_rng(404)
    mixture = rng.normal(0.0, 0.1, (2, sample_rate * 3)).astype(np.float32)
    unrelated = rng.normal(0.0, 0.1, mixture.shape).astype(np.float32)
    backing = np.empty_like(mixture)

    process_audio(mixture, unrelated, sample_rate, 1.0, 3, None, None, backing)

    quiet = 10 * np.log10(np.mean(backing**2) / np.mean(unrelated**2))
    assert quiet < -40.0


def test_process_audio_rejects_a_mismatched_backing_buffer():
    sample_rate, reference, _accompaniment, _live, mixture = _backing_scene(0.5)
    with pytest.raises(ValueError, match="backing must be a float32"):
        process_audio(
            mixture,
            reference,
            sample_rate,
            1.0,
            3,
            None,
            None,
            np.zeros((2, 16), dtype=np.float32),
        )


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


# A source far quieter than the stage is brought up to its level before the
# fit, which must not turn an unrelated one into something to subtract.
@pytest.mark.parametrize("source_level", [1.0, 0.01])
def test_reference_mask_leaves_an_unrelated_reference_nearly_bypassed(source_level):
    sample_rate = 8_000
    rng = np.random.default_rng(131)
    mixture = rng.normal(0.0, 0.1, (2, sample_rate * 2))
    unrelated = source_level * rng.normal(0.0, 0.1, mixture.shape)

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


def _gain(output: np.ndarray, target: np.ndarray) -> float:
    return float(np.dot(output.ravel(), target.ravel()) / np.dot(target.ravel(), target.ravel()))


def test_residual_mask_keeps_a_live_source_that_never_stops():
    """The leakage estimate must not read the live source as leftover accompaniment.

    A live source that plays throughout leaves no frame where only the
    reference is sounding.  Measuring the leakage as a plain residual-over-
    removed ratio then measures the live source along with it and the mask
    takes it out: on this scene that cost 41% of the live source's level and
    3.4 dB of depth, because the distorted live source lands in the residual
    the depth is measured against.  Regressing the residual power on the
    removed power with an intercept separates the two - leakage follows the
    accompaniment that was there, the live floor does not.
    """
    sample_rate = 16_000
    length = sample_rate * 5
    rng = np.random.default_rng(311)
    left_ref = np.convolve(rng.normal(0.0, 0.25, length), np.ones(5) / 5, mode="same")
    delay = 7
    right_ref = 0.9 * np.pad(left_ref[:-delay], (delay, 0)) + rng.normal(0.0, 0.02, length)
    live = np.convolve(rng.normal(0.0, 0.08, length), np.ones(3) / 3, mode="same")
    accompaniment = np.stack(
        [0.85 * left_ref + 0.31 * right_ref, -0.22 * left_ref + 0.78 * right_ref]
    )
    live_stereo = np.stack([live, 0.95 * live])
    mix = (live_stereo + accompaniment).astype(np.float32)

    output = process_audio(
        mix, np.stack([left_ref, right_ref]).astype(np.float32), sample_rate, 1.0, 3
    )

    body = slice(sample_rate // 2, length - sample_rate // 2)
    gain = _gain(output[:, body], live_stereo[:, body])
    residual = output[:, body] - gain * live_stereo[:, body]
    depth = 10 * np.log10(
        float(np.mean(accompaniment[:, body] ** 2)) / max(float(np.mean(residual**2)), 1e-20)
    )
    assert gain > 0.78
    assert depth > 21.0


def test_reference_cancellation_preserves_centered_non_reference_content():
    sample_rate = 22_050
    length = sample_rate * 5
    time = np.arange(length) / sample_rate
    vocal = 0.5 * np.sin(2 * np.pi * 440 * time)
    reference = 0.4 * np.sin(2 * np.pi * 110 * time)
    noise = np.random.default_rng(42).uniform(-0.15, 0.15, length)
    mixture = vocal + reference + noise
    output = process_audio(
        np.stack([mixture] * 2),
        np.stack([reference] * 2),
        sample_rate,
        1.0,
        8,
    )
    assert corr(output[0], vocal) > 0.96
    assert corr(output[0], vocal + noise) > 0.96


def test_reference_cancellation_regularizes_a_nearly_mono_reference():
    sample_rate = 22_050
    length = sample_rate * 4
    time = np.arange(length) / sample_rate
    vocal = 0.35 * np.sin(2 * np.pi * 431 * time)
    common_reference = 0.2 * np.sin(2 * np.pi * 127 * time)
    tiny_side = 1e-4 * np.sin(2 * np.pi * 181 * time)
    reference = np.stack([common_reference + tiny_side, common_reference - tiny_side])
    mixture = np.stack([vocal + 0.8 * reference[0], 0.97 * vocal + 0.75 * reference[1]])

    output = process_audio(
        mixture,
        reference,
        sample_rate,
        1.0,
        8,
    )

    assert np.isfinite(output).all()
    assert min(corr(output[0], vocal), corr(output[1], vocal)) > 0.98
