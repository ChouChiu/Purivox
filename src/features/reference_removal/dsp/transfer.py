"""Smoothed spectral statistics and the complex transfer estimated from them.

The canceller in `algorithms.py` needs one thing from this module: given the
mixture and reference spectra, what part of the mixture can the reference
explain, and how much should that estimate be trusted.  Keeping the normal
equations, the solver and the smoothing kernels they are built on together
here leaves `algorithms.py` to describe the cancellation itself.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter1d, uniform_filter1d

from shared.processing import CancellationToken

_MAX_TRANSFER_GAIN = 2.0
TRANSFER_ORDER = 2
# Consecutive STFT frames overlap by 75% and adjacent bins are already tied
# together by the analysis window, so a smoothing window of W frames is worth
# far fewer than W independent observations.  hop/n_fft = 1/4 is the obvious
# reading and it is too generous: the Hann window's own correlation between
# overlapping frames costs about another half, and the frequency Gaussian
# delivers fewer independent bins than its nominal tap count once the four-bin
# main lobe is accounted for.  Measured rather than derived - at 1/4 the quiet
# centre vocal lost 1.7% of its level against the mask path it replaced, and at
# 1/8 it gains 0.3% instead while keeping 2.55 dB of the 3.12 dB depth.
_FRAME_INDEPENDENCE = 0.125
_BIN_INDEPENDENCE = 1.5
_RELATIVE_LOADING = 2e-4


def spectral_smooth(
    values: np.ndarray,
    sigma_time: float,
    sigma_frequency: float = 1.0,
) -> np.ndarray:
    """Smooth long spectral contexts in O(N) time along the frame axis."""
    if np.iscomplexobj(values):
        return spectral_smooth(values.real, sigma_time, sigma_frequency) + 1j * spectral_smooth(
            values.imag,
            sigma_time,
            sigma_frequency,
        )
    window = max(round(6.0 * sigma_time), 1)
    smoothed = uniform_filter1d(values, size=window, axis=0, mode="reflect")
    if sigma_frequency > 0.0:
        smoothed = gaussian_filter1d(
            smoothed,
            sigma=sigma_frequency,
            axis=1,
            mode="reflect",
        )
    return smoothed


def weighted_smooth(
    values: np.ndarray,
    weights: np.ndarray | None,
    sigma_time: float,
    denominator: np.ndarray | None = None,
) -> np.ndarray:
    if weights is None:
        return spectral_smooth(values, sigma_time)
    if denominator is None:
        denominator = spectral_smooth(weights, sigma_time) + 1e-12
    numerator = spectral_smooth(values * weights, sigma_time)
    return numerator / denominator


def smoothstep(low: float, high: float, values: np.ndarray) -> np.ndarray:
    scaled = np.clip((values - low) / (high - low), 0.0, 1.0)
    return scaled * scaled * (3.0 - 2.0 * scaled)


def _solve_hermitian(
    covariance: list[list[np.ndarray]],
    cross: list[np.ndarray],
) -> list[np.ndarray]:
    """Solve the Hermitian system R h = c for every time-frequency cell.

    `covariance` holds the lower triangle as whole [frames, bins] spectra.
    Stacking the cells into one [frames, bins, order, order] tensor and calling
    `numpy.linalg.solve` makes LAPACK run once per cell, which measured about
    seven times slower.  An LDL^H factorisation written out over the spectra
    keeps every step a single vectorised array operation and needs no square
    roots.
    """
    order = len(cross)
    lower: list[list[np.ndarray | None]] = [[None] * order for _ in range(order)]
    pivot: list[np.ndarray] = []
    for column in range(order):
        value = covariance[column][column].real.copy()
        for index in range(column):
            factor = lower[column][index]
            value -= (factor.real**2 + factor.imag**2) * pivot[index]
        pivot.append(np.maximum(value, 1e-20))
        for row in range(column + 1, order):
            entry = covariance[row][column].copy()
            for index in range(column):
                entry -= lower[row][index] * np.conj(lower[column][index]) * pivot[index]
            lower[row][column] = entry / pivot[column]
    forward: list[np.ndarray] = []
    for row in range(order):
        value = cross[row].copy()
        for index in range(row):
            value -= lower[row][index] * forward[index]
        forward.append(value)
    transfer: list[np.ndarray | None] = [None] * order
    for row in reversed(range(order)):
        value = forward[row] / pivot[row]
        for index in range(row + 1, order):
            value = value - np.conj(lower[index][row]) * transfer[index]
        transfer[row] = value
    return transfer


def effective_observations(sigma_frames: float, frames: int) -> float:
    """Independent observations behind one smoothed statistic.

    The box filter reflects at the block edge rather than inventing samples, so
    a context wider than the block is worth only what the block holds.  Reading
    the nominal width there would overstate the count several times over in
    exactly the short blocks where the overfit bias is largest.
    """
    window = min(max(round(6.0 * sigma_frames), 1), max(frames, 1))
    return max(window * _FRAME_INDEPENDENCE * _BIN_INDEPENDENCE, TRANSFER_ORDER + 2.0)


def predict_reference_spectra(
    song_spectra: list[np.ndarray],
    reference_spectra: list[np.ndarray],
    sigma_frames: float,
    token: CancellationToken,
    weights: np.ndarray | None = None,
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Predict reference-correlated spectra without subtracting them from the mix.

    Returns the prediction per output channel together with how much of that
    channel the reference actually explains, as an adjusted multiple coherence.

    One reference frame per channel is the multiplicative narrowband model.
    Spanning several frames instead, as a convolutive transfer function, was
    measured and removed again: it only helped for room responses shorter than
    a few hundred milliseconds, and at the 0.8-2 s a real venue rings it was
    worth nothing or slightly negative while costing 4.5-5.2x the runtime.
    """
    epsilon = 1e-12
    order = len(reference_spectra)
    denominator = None
    if weights is not None:
        denominator = spectral_smooth(weights, sigma_frames) + 1e-12
    # The normal equations for y ~ sum_k h_k x_k are R h = c with
    # R[j][k] = E[x_k conj(x_j)] and c[j] = E[y conj(x_j)].  Filling R[j][k]
    # with E[x_j conj(x_k)] instead transposes the system and silently solves
    # for a different transfer, so only the lower triangle is built here and
    # the upper one is never needed.
    covariance: list[list[np.ndarray | None]] = [[None] * order for _ in range(order)]
    for row in range(order):
        for column in range(row + 1):
            covariance[row][column] = weighted_smooth(
                reference_spectra[column] * np.conj(reference_spectra[row]),
                weights,
                sigma_frames,
                denominator,
            )
    loading = covariance[0][0].real.copy()
    for index in range(1, order):
        loading += covariance[index][index].real
    # A floor under this, so that a bin where the reference falls momentarily
    # silent keeps some regularisation, was written and measured: the trace is
    # already smoothed over the whole statistical context, so the momentary
    # dips it was meant to catch are gone before it sees them and it moved the
    # loading by 1.6% on average.  It cost a full [frames, bins] copy for that.
    loading *= _RELATIVE_LOADING / order
    loading += epsilon
    for index in range(order):
        covariance[index][index] = covariance[index][index] + loading
    # A least-squares fit over a finite window always explains part of the
    # mixture by chance, and the expected size of that accident is exactly
    # order/observations.  Subtracting it turns the raw coherence into the
    # adjusted one, which reaches zero for a reference that shares nothing with
    # the mixture instead of settling on a small positive floor.
    observations = effective_observations(sigma_frames, song_spectra[0].shape[0])
    overfit_scale = observations / (observations - TRANSFER_ORDER)
    predicted: list[np.ndarray] = []
    explained: list[np.ndarray] = []
    for channel in song_spectra:
        token.raise_if_cancelled()
        cross = [
            weighted_smooth(channel * np.conj(reference), weights, sigma_frames, denominator)
            for reference in reference_spectra
        ]
        transfer = _solve_hermitian(covariance, cross)
        # At the least-squares optimum E[|Hx|^2] equals h^H c, so the explained
        # power ratio costs one more product instead of a second smoothing pass
        # over the mixture and the prediction.
        coherence = np.conj(transfer[0]) * cross[0]
        for index in range(1, order):
            coherence = coherence + np.conj(transfer[index]) * cross[index]
        mixture_power = weighted_smooth(
            np.abs(channel) ** 2,
            weights,
            sigma_frames,
            denominator,
        )
        ratio = np.clip(coherence.real / (mixture_power + epsilon), 0.0, 1.0)
        explained.append(np.clip(1.0 - (1.0 - ratio) * overfit_scale, 0.0, 1.0).astype(np.float32))
        row_gain = np.abs(transfer[0])
        for index in range(1, order):
            row_gain = row_gain + np.abs(transfer[index])
        gain_scale = np.minimum(1.0, _MAX_TRANSFER_GAIN / (row_gain + epsilon))
        combined = transfer[0] * reference_spectra[0]
        for index in range(1, order):
            combined = combined + transfer[index] * reference_spectra[index]
        predicted.append((gain_scale * combined).astype(np.complex64))
    return predicted, explained


def power_transfer(
    mixture_power: np.ndarray,
    reference_power: np.ndarray,
    sigma_frames: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Fit the accompaniment power the reference explains without using phase.

    A stage capture can carry the song source through a PA, a room and a
    broadcast limiter.  Measured on real material that whole path leaves the
    magnitudes correlated at around 0.5 while the complex coherence collapses
    to 0.04 above 500 Hz, so the transfer estimate has almost nothing to
    subtract even though the accompaniment is plainly audible.  Regressing
    power on power recovers what phase cannot reach.

    The regression carries an intercept on purpose: `P_y ~ g P_x + c` splits the
    mixture into the part that follows the reference and a slowly varying floor,
    and that floor is the live content.  Only `g P_x` may be removed.  Returns
    the explained power and the adjusted correlation it was fitted at.
    """
    epsilon = 1e-20
    mean_x = spectral_smooth(reference_power, sigma_frames)
    mean_y = spectral_smooth(mixture_power, sigma_frames)
    variance_x = spectral_smooth(reference_power**2, sigma_frames) - mean_x**2
    variance_y = spectral_smooth(mixture_power**2, sigma_frames) - mean_y**2
    covariance = spectral_smooth(reference_power * mixture_power, sigma_frames) - mean_x * mean_y
    # Only a positive slope is physical: more accompaniment in the source cannot
    # mean less of it on stage.
    slope = np.maximum(covariance, 0.0) / (np.maximum(variance_x, 0.0) + epsilon)
    correlation = covariance**2 / (
        np.maximum(variance_x, 0.0) * np.maximum(variance_y, 0.0) + epsilon
    )
    observations = effective_observations(sigma_frames, mixture_power.shape[0])
    adjusted = np.clip(
        1.0 - (1.0 - np.clip(correlation, 0.0, 1.0)) * observations / (observations - 1.0),
        0.0,
        1.0,
    )
    return (slope * reference_power).astype(np.float32), adjusted.astype(np.float32)
