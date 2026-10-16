import numpy as np
import pytest

from features.reference_removal.dsp import transfer
from shared.dsp import stft
from shared.processing import CancellationToken


def test_complex_smoothing_matches_the_real_and_imaginary_views():
    """One pass over a trailing axis of two must equal two strided passes."""

    random = np.random.default_rng(9)
    values = (random.normal(size=(64, 32)) + 1j * random.normal(size=(64, 32))).astype(np.complex64)

    fused = transfer.spectral_smooth(values, 3.0)
    expected = np.empty_like(values)
    transfer.spectral_smooth(values.real, 3.0, 1.0, expected.real)
    transfer.spectral_smooth(values.imag, 3.0, 1.0, expected.imag)

    assert np.array_equal(fused, expected)


def test_prediction_does_not_depend_on_measuring_coherence():
    """The first robust-weighting pass skips the coherence it throws away."""

    sample_rate = 8_000
    time = np.arange(sample_rate * 3) / sample_rate
    accompaniment = 0.3 * np.sin(2 * np.pi * 110 * time)
    live = 0.25 * np.sin(2 * np.pi * 431 * time)
    song_spectra = [
        stft(channel, n_fft=512, hop=128)
        for channel in (accompaniment + live, 0.95 * accompaniment + live)
    ]
    reference_spectra = [
        stft(channel, n_fft=512, hop=128) for channel in (accompaniment, 0.95 * accompaniment)
    ]

    measured, explained = transfer.predict_reference_spectra(
        song_spectra, reference_spectra, 40.0, CancellationToken()
    )
    skipped, none = transfer.predict_reference_spectra(
        song_spectra, reference_spectra, 40.0, CancellationToken(), coherence=False
    )

    assert explained and none == []
    for measured_channel, skipped_channel in zip(measured, skipped, strict=True):
        assert np.array_equal(measured_channel, skipped_channel)


def test_factorised_solver_solves_the_normal_equations():
    """R is channel independent, so it is factorised once and substituted per channel."""

    random = np.random.default_rng(88)
    order = 2
    shape = (2, 3)
    reference = [
        (random.normal(size=shape) + 1j * random.normal(size=shape)).astype(np.complex64)
        for _ in range(order)
    ]
    mixture = (random.normal(size=shape) + 1j * random.normal(size=shape)).astype(np.complex64)
    covariance = [[None] * order for _ in range(order)]
    for row in range(order):
        for column in range(row + 1):
            covariance[row][column] = reference[column] * np.conj(reference[row])
    # One observation per cell makes the raw covariance rank one, which is
    # what the relative loading in `predict_reference_spectra` exists for.
    loading = 1e-2 * sum(np.abs(band) ** 2 for band in reference).real + 1e-6
    for index in range(order):
        covariance[index][index] = covariance[index][index] + loading
    cross = [mixture * np.conj(band) for band in reference]

    lower, inverse_pivot = transfer._factorize_hermitian(covariance)
    solved = transfer._solve_hermitian(lower, inverse_pivot, cross)

    for row in range(order):
        residual = cross[row].copy()
        for column in range(order):
            entry = covariance[row][column] if column <= row else np.conj(covariance[column][row])
            residual -= entry * solved[column]
        assert float(np.max(np.abs(residual))) < 1e-4


def test_consuming_the_cross_terms_solves_the_same_system():
    """The first pass hands its cross terms over; the measuring pass keeps them."""

    random = np.random.default_rng(91)
    order = 2
    shape = (3, 4)
    reference = [
        (random.normal(size=shape) + 1j * random.normal(size=shape)).astype(np.complex64)
        for _ in range(order)
    ]
    covariance = [[None] * order for _ in range(order)]
    for row in range(order):
        for column in range(row + 1):
            covariance[row][column] = reference[column] * np.conj(reference[row])
    loading = 1e-2 * sum(np.abs(band) ** 2 for band in reference).real + 1e-6
    for index in range(order):
        covariance[index][index] = covariance[index][index] + loading
    lower, inverse_pivot = transfer._factorize_hermitian(covariance)
    mixture = (random.normal(size=shape) + 1j * random.normal(size=shape)).astype(np.complex64)
    cross = [mixture * np.conj(band) for band in reference]

    copied = transfer._solve_hermitian(lower, inverse_pivot, [band.copy() for band in cross])
    consumed = transfer._solve_hermitian(
        lower, inverse_pivot, [band.copy() for band in cross], consume=True
    )

    for copied_row, consumed_row in zip(copied, consumed, strict=True):
        assert np.array_equal(copied_row, consumed_row)


def test_diagonal_fit_matches_the_full_fit_for_one_reference_channel():
    """With a single reference the two fits are the same 1x1 system."""

    sample_rate = 8_000
    time = np.arange(sample_rate * 2) / sample_rate
    accompaniment = 0.3 * np.sin(2 * np.pi * 110 * time)
    live = 0.25 * np.sin(2 * np.pi * 431 * time)
    song_spectra = [stft(accompaniment + live, n_fft=512, hop=128)]
    reference_spectra = [stft(accompaniment, n_fft=512, hop=128)]

    full, _ = transfer.predict_reference_spectra(
        song_spectra, reference_spectra, 40.0, CancellationToken(), coherence=False
    )
    diagonal, _ = transfer.predict_reference_spectra(
        song_spectra,
        reference_spectra,
        40.0,
        CancellationToken(),
        coherence=False,
        diagonal=True,
    )

    assert np.array_equal(full[0], diagonal[0])


def test_leakage_fit_follows_a_hall_tail_past_the_notes_that_excited_it():
    """The tail of a 1 s hall rings on through the rests, where nothing is removed."""

    hop_seconds = 512 / 44_100
    frames, bins = 2000, 64
    random = np.random.default_rng(23)
    # Quarter-second notes with rests between them, independently per bin.
    playing = np.repeat(random.random((frames // 20 + 1, bins)) < 0.7, 20, axis=0)[:frames]
    removed = (playing * random.uniform(0.5, 1.5, (frames, bins))).astype(np.float32)
    decay = 10.0 ** (-6.0 * hop_seconds / 1.0)
    ringing = removed.copy()
    for frame in range(1, frames):
        ringing[frame] = decay * ringing[frame - 1] + removed[frame]
    tail = 0.2 * (ringing - removed)
    live_floor = 0.3
    residual = (live_floor + tail).astype(np.float32)

    leaked, _confidence = transfer.reverberant_power_transfer(residual, removed, 40.0, hop_seconds)

    assert float(np.corrcoef(leaked.ravel(), tail.ravel())[0, 1]) > 0.95
    assert float(np.mean(leaked)) == pytest.approx(float(np.mean(tail)), rel=0.1)
