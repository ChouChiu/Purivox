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
    out: np.ndarray | None = None,
) -> np.ndarray:
    """Smooth long spectral contexts in O(N) time along the frame axis.

    The two passes run through one array rather than through a fresh output per
    filter, the way scipy's own `uniform_filter` chains its axes: the line
    buffer inside each filter makes writing back into the input safe, and a
    smoothing pass over a whole spectrum is large enough that the allocation it
    saves is worth naming.  `out` lets a caller reuse a buffer across calls.
    """
    if np.iscomplexobj(values):
        # Assembling the halves as `a + 1j * b` would cost two more full complex
        # arrays; filling one result's real and imaginary views costs none.
        result = np.empty(values.shape, dtype=values.dtype) if out is None else out
        spectral_smooth(values.real, sigma_time, sigma_frequency, result.real)
        spectral_smooth(values.imag, sigma_time, sigma_frequency, result.imag)
        return result
    window = max(round(6.0 * sigma_time), 1)
    smoothed = uniform_filter1d(values, size=window, axis=0, mode="reflect", output=out)
    if sigma_frequency > 0.0:
        gaussian_filter1d(
            smoothed,
            sigma=sigma_frequency,
            axis=1,
            mode="reflect",
            output=smoothed,
        )
    return smoothed


def weighted_smooth(
    values: np.ndarray,
    weights: np.ndarray | None,
    sigma_time: float,
    denominator: np.ndarray | None = None,
    out: np.ndarray | None = None,
) -> np.ndarray:
    if weights is None:
        return spectral_smooth(values, sigma_time, out=out)
    if denominator is None:
        denominator = spectral_smooth(weights, sigma_time) + 1e-12
    numerator = spectral_smooth(values * weights, sigma_time, out=out)
    numerator /= denominator
    return numerator


def smoothstep(low: float, high: float, values: np.ndarray) -> np.ndarray:
    scaled = np.subtract(values, low)
    scaled /= high - low
    np.clip(scaled, 0.0, 1.0, out=scaled)
    ramp = np.multiply(scaled, -2.0)
    ramp += 3.0
    # Grouped as (s * s) * ramp, which is what the arithmetic below reads as and
    # what the expression this replaces evaluated: float multiplication does not
    # associate, so the order is part of the result.
    square = np.square(scaled, out=scaled)
    square *= ramp
    return square


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
    # Every product below is consumed by the smoothing pass it is handed to, so
    # they share one buffer rather than allocating a spectrum apiece.  Its dtype
    # is the one the products would have promoted to on their own.
    spectrum_dtype = np.result_type(song_spectra[0], reference_spectra[0])
    product = np.empty(reference_spectra[0].shape, dtype=spectrum_dtype)
    for row in range(order):
        for column in range(row + 1):
            # The operands keep the order the expression this replaces used:
            # numpy's complex multiply is not bit-symmetric in its arguments, so
            # swapping them would move the last digit of every covariance cell.
            np.conj(reference_spectra[row], out=product)
            np.multiply(reference_spectra[column], product, out=product)
            covariance[row][column] = weighted_smooth(
                product,
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
        # The loading is real, so it only ever lands on the diagonal's real part;
        # writing it there keeps the whole covariance in the arrays it is in.
        covariance[index][index].real += loading
    # A least-squares fit over a finite window always explains part of the
    # mixture by chance, and the expected size of that accident is exactly
    # order/observations.  Subtracting it turns the raw coherence into the
    # adjusted one, which reaches zero for a reference that shares nothing with
    # the mixture instead of settling on a small positive floor.
    observations = effective_observations(sigma_frames, song_spectra[0].shape[0])
    overfit_scale = observations / (observations - TRANSFER_ORDER)
    predicted: list[np.ndarray] = []
    explained: list[np.ndarray] = []
    magnitude = np.empty(song_spectra[0].shape, dtype=np.empty(0, spectrum_dtype).real.dtype)
    for channel in song_spectra:
        token.raise_if_cancelled()
        cross = []
        for reference in reference_spectra:
            np.conj(reference, out=product)
            np.multiply(channel, product, out=product)
            cross.append(weighted_smooth(product, weights, sigma_frames, denominator))
        transfer = _solve_hermitian(covariance, cross)
        # At the least-squares optimum E[|Hx|^2] equals h^H c, so the explained
        # power ratio costs one more product instead of a second smoothing pass
        # over the mixture and the prediction.
        # The buffer the cross terms were built in is free again here, and the
        # cross terms themselves are dead once the coherence has been read out
        # of them: neither needs to stay resident while the prediction is formed.
        coherence = np.conj(transfer[0], out=product)
        np.multiply(coherence, cross[0], out=coherence)
        for index in range(1, order):
            coherence += np.conj(transfer[index]) * cross[index]
        del cross
        mixture_power = weighted_smooth(
            np.square(np.abs(channel, out=magnitude), out=magnitude),
            weights,
            sigma_frames,
            denominator,
        )
        # 1 - (1 - clip(ratio)) * overfit_scale, formed in place: the adjustment
        # is a handful of scalar steps over a spectrum that is already there.
        mixture_power += epsilon
        ratio = np.divide(coherence.real, mixture_power)
        np.clip(ratio, 0.0, 1.0, out=ratio)
        ratio -= 1.0
        ratio *= overfit_scale
        ratio += 1.0
        np.clip(ratio, 0.0, 1.0, out=ratio)
        explained.append(ratio.astype(np.float32, copy=False))
        row_gain = np.abs(transfer[0])
        for index in range(1, order):
            row_gain += np.abs(transfer[index])
        row_gain += epsilon
        gain_scale = np.divide(_MAX_TRANSFER_GAIN, row_gain, out=row_gain)
        np.minimum(gain_scale, 1.0, out=gain_scale)
        combined = transfer[0] * reference_spectra[0]
        for index in range(1, order):
            combined += transfer[index] * reference_spectra[index]
        combined *= gain_scale
        predicted.append(combined.astype(np.complex64, copy=False))
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
    # Each product below feeds a smoothing pass and is never read again, so they
    # all pass through one buffer: five separate full spectra of intermediates
    # would otherwise sit in the block working set for the length of this call.
    scratch = np.empty_like(reference_power)
    variance_x = spectral_smooth(np.square(reference_power, out=scratch), sigma_frames)
    variance_x -= np.square(mean_x, out=scratch)
    variance_y = spectral_smooth(np.square(mixture_power, out=scratch), sigma_frames)
    variance_y -= np.square(mean_y, out=scratch)
    covariance = spectral_smooth(
        np.multiply(reference_power, mixture_power, out=scratch), sigma_frames
    )
    covariance -= np.multiply(mean_x, mean_y, out=scratch)
    del mean_x, mean_y, scratch
    np.maximum(variance_x, 0.0, out=variance_x)
    np.maximum(variance_y, 0.0, out=variance_y)
    # Only a positive slope is physical: more accompaniment in the source cannot
    # mean less of it on stage.
    slope = np.maximum(covariance, 0.0)
    slope /= variance_x + epsilon
    correlation = np.square(covariance, out=covariance)
    np.multiply(variance_x, variance_y, out=variance_x)
    variance_x += epsilon
    correlation /= variance_x
    del variance_x, variance_y
    observations = effective_observations(sigma_frames, mixture_power.shape[0])
    # 1 - (1 - clip(r)) * observations / (observations - 1), read from the inside
    # out so that no step needs a spectrum of its own.  The multiply and the
    # divide stay separate steps because folding them into one scalar would
    # round differently from the expression this replaces.
    adjusted = np.clip(correlation, 0.0, 1.0, out=correlation)
    adjusted -= 1.0
    adjusted *= observations
    adjusted /= observations - 1.0
    adjusted += 1.0
    np.clip(adjusted, 0.0, 1.0, out=adjusted)
    slope *= reference_power
    return slope.astype(np.float32, copy=False), adjusted.astype(np.float32, copy=False)
