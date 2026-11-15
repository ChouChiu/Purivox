from __future__ import annotations

import logging
import math
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from scipy.ndimage import gaussian_filter

from shared.audio import BLOCK_FRAMES, release_mapped_pages
from shared.dsp import istft, stft
from shared.processing import CancellationToken

from .transfer import (
    TRANSFER_ORDER,
    effective_observations,
    power_transfer,
    predict_reference_spectra,
    reverberant_power_transfer,
    smoothstep,
    spectral_smooth,
)

logger = logging.getLogger(__name__)

_MASK_FLOOR = 0.05
# The synthesised backing may be louder than the source file, because the
# playback can carry more gain than the master does.  A gain fitted on weak
# evidence must not run away, so it is bounded like the transfer itself.
_MAX_BACKING_GAIN = 2.0
# A geometric mean sits at about 0.56 of the arithmetic mean for the residual's
# distribution, so the threshold is scaled up to keep the same amount of
# down-weighting as the mean-based form it replaced.
_ROBUST_SCALE = 7.0
# Both power-domain fits - the leakage one and the incoherent one - need a
# clearly positive correlation before they are allowed to remove anything:
# unrelated music shares loudness envelopes, and this gate is what keeps an
# unrelated source from being suppressed.  Measured: with it removed the
# unrelated-reference bypass loses an order of magnitude, from an RMSE of
# 0.0001 to 0.0002, while nothing else moves by more than 0.2 dB.
_POWER_FIT_LOW = 0.15
_POWER_FIT_HIGH = 0.45
# The incoherent path fits power on power without any phase evidence at all,
# so unlike the leakage regression it keeps an over-subtraction factor: this is
# the knob to lower when that path suppresses cleanly but audibly costs quality,
# which is what it does on a badly phase-decorrelated capture.
_INCOHERENT_OVERSUBTRACTION = 1.5
# The incoherent path rides on much weaker evidence than the coherent one, so a
# single noisy cell must not be allowed to drive the mask all the way to the
# floor: that is exactly the fluctuation that is audible as musical noise.
# Capping how much of the residual power this path may claim per cell keeps
# the mask dips shallow wherever the evidence is weak, while confident cells
# still reach the same depth through the coherent stage.
_INCOHERENT_MAX_SHARE = 0.55
# Width of the single narrow smoothing pass over the finished mask, in
# (frames, bins).
_MASK_SMOOTHING = (0.75, 0.35)
# Phantom Center's width control, read as a refinement of the side fit.  Its
# exponent is -width/100, so a negative width makes the balance term stricter
# and content sitting between the channels keeps more of its cell.
_PC_WIDTH = -50.0
# How far the centre share may take a cell the side fit has already found
# leakage in, and the ceiling on that: the extraction may refine the side fit,
# not replace it, because on a capture that hears a mono PA the playback is the
# perfect centre and the crowd is not.
# The mask ratio is formed from instantaneous per-cell powers, which forces the
# narrow Gaussian pass to absorb nearly all of their variance.  Smoothing the
# numerator and denominator in time first (sigma in frames, ~11.6 ms each at
# 44.1 kHz) removes most of that fluctuation before the ratio is taken, which
# is the dominant source of musical noise on captures whose phase has been
# destroyed.
_MASK_POWER_SMOOTH = 1.5
_SPECTRAL_CELL_BUDGET = 4_000_000
_MAX_PROCESSING_BLOCK_SECONDS = 48
_MAX_PROCESSING_WORKERS = min(5, os.cpu_count() or 1)
# Pyodide builds CPython without pthreads, so the pool cannot start a worker
# there.  Only the execution strategy changes: the layout below still decides
# the block size, so a browser run schedules exactly the same blocks.
_THREADS_AVAILABLE = sys.platform != "emscripten"
_MAX_PARALLEL_SPECTRAL_CELLS = 9_000_000
# Blocks the level pass reads between handing mapped pages back, ~48 s at 44.1 kHz.
_LEVEL_RELEASE_BLOCKS = 8
# How much more of the stage the long window has to explain before it replaces
# the default; see `_capture_fft_size`.  Below it sit two synthetic scenes the
# long window explains 0.001-0.002 more of and still cancels worse.
_LONG_WINDOW_MARGIN = 0.003
_WINDOW_PROBES = 3
_WINDOW_PROBE_SECONDS = 8.0
# The centre extraction that follows the cancellation, and the gate it runs
# behind.  A phantom-centre reading only means anything when the content that
# was removed is the wide one: where the playback arrived over a mono PA the
# removal is the centre and the crowd is not, and extracting the centre there
# deletes the voice.  Measured on the scenes, removed and output width differ by
# 9.8-198x where the extraction helps and by 0.02-2.3x where it does not.
_CENTRE_WIDTH = -50.0
_CENTRE_MIN_WIDTH_RATIO = 4.0
# And the removal has to be worth reading at all: a stage whose reference is
# silent removes nothing, and the ratio of two negligible widths is noise.  The
# threshold is deliberately low - a capture close to the playback keeps the song
# at 12 dB over the voice, so the removal is a small fraction of the mixture
# while still being the wide part of it.
_CENTRE_MIN_REMOVED_SHARE = 0.01


def _stereo_width_and_energy(audio: np.ndarray, cancel: CancellationToken) -> tuple[float, float]:
    """How wide a signal sits, and how much of it there is.

    A phantom-centre reading only means something when the content that was
    taken out is the wide one.  Width is the side power over the mid power,
    measured the same way on both sides of the cancellation; the mid power comes
    back with it so the gate can tell a real removal from a statistical one.
    """
    block = min(audio.shape[1], BLOCK_FRAMES)
    side = 0.0
    mid = 0.0
    for start in range(0, audio.shape[1], block):
        cancel.raise_if_cancelled()
        view = np.asarray(audio[:, start : start + block], dtype=np.float32)
        difference = view[0] - view[1]
        total = view[0] + view[1]
        side += float(np.sum(np.square(difference)))
        mid += float(np.sum(np.square(total)))
    return side / max(mid, 1e-20), mid


def _centre_extract(
    audio: np.ndarray,
    n_fft: int,
    hop: int,
    cancel: CancellationToken,
) -> np.ndarray:
    """Keep the phantom centre of audio and let its width go.

    This is Phantom Center's stage, applied to the finished cancellation rather
    than inside it: |L+R| against |L-R| is the inter-channel coherence and the
    smaller over the larger channel is the balance, so the product says how much
    of a cell sits between the two channels.  The side is scaled by that share
    and the mid is left alone, which is what a centre extraction is.
    """
    left = stft(np.asarray(audio[0], dtype=np.float32), n_fft=n_fft, hop=hop)
    right = stft(np.asarray(audio[1], dtype=np.float32), n_fft=n_fft, hop=hop)
    cancel.raise_if_cancelled()
    total = np.abs(left + right)
    difference = np.abs(left - right)
    share = np.maximum((total - difference) / np.maximum(total, 1e-20), 0.0)
    np.minimum(share, 1.0, out=share)
    balance = np.minimum(np.abs(left), np.abs(right))
    np.divide(
        balance,
        np.maximum(np.maximum(np.abs(left), np.abs(right)), 1e-20),
        out=balance,
    )
    np.power(balance, np.float32(-_CENTRE_WIDTH / 100.0), out=balance)
    balance *= share
    del share
    # The criterion is instantaneous geometry and far too noisy to act on cell
    # by cell; the same two passes the mask gets are what make it usable.
    spectral_smooth(balance, _MASK_POWER_SMOOTH, 0.0, out=balance)
    gaussian_filter(balance, sigma=_MASK_SMOOTHING, mode="reflect", output=balance)
    np.clip(balance, 0.0, 1.0, out=balance)
    mid = (left + right) * 0.5
    side = (left - right) * 0.5
    side *= balance
    del balance
    return np.stack(
        [
            istft(mid + side, hop=hop, length=audio.shape[1]),
            istft(mid - side, hop=hop, length=audio.shape[1]),
        ],
        dtype=np.float32,
    )


def _analysis_fft_size(sample_rate: int) -> int:
    target = max(0.046 * sample_rate, 1.0)
    exponent = round(math.log2(target))
    return int(np.clip(2**exponent, 512, 4096))


def _explained_share(
    mix: np.ndarray, reference: np.ndarray, sample_rate: int, sigma: float, n_fft: int
) -> tuple[float, float]:
    """The mixture power the reference explains at one window, and the total."""
    hop = n_fft // 4
    mix_spectra = [stft(channel, n_fft=n_fft, hop=hop) for channel in mix]
    reference_spectra = [stft(channel, n_fft=n_fft, hop=hop) for channel in reference[:2]]
    if len(reference_spectra) == 1:
        reference_spectra.append(reference_spectra[0])
    sigma_frames = max(float(sigma) * sample_rate / hop / 6.0, 1.0)
    _predicted, explained = predict_reference_spectra(
        mix_spectra, reference_spectra, sigma_frames, CancellationToken()
    )
    explained_power = 0.0
    total_power = 0.0
    for spectrum, share in zip(mix_spectra, explained, strict=True):
        power = np.square(np.abs(spectrum))
        explained_power += float(np.sum(share * power))
        total_power += float(np.sum(power))
    return explained_power, total_power


def _capture_fft_size(
    mix: np.ndarray,
    reference: np.ndarray,
    sample_rate: int,
    sigma: float,
    token: CancellationToken,
) -> int:
    """The analysis window for this capture: the default one, or twice as long.

    A capture far from the PA hears the playback through a room whose early
    reflections run past the ~46 ms default, and every one that falls outside
    the window is backing the per-bin transfer cannot describe.  A fancam at an
    open-air festival had the reference explain 0.256 of it at 43 ms and 0.329
    at 85 ms.  A capture close to the playback is the opposite case: the longer
    window buys no reach and halves the frames the transfer is fitted over.
    Which one a capture is shows in the same adjusted coherence the canceller
    trusts, so it is measured over a few excerpts at both windows and the long
    one is taken only when it explains clearly more.  On the synthetic scenes
    that rule picks the better window wherever the two differ by more than a
    few tenths of a decibel.  One window serves the whole call, because blocks
    blended across a seam must come from the same analysis.
    """
    n_fft = _analysis_fft_size(sample_rate)
    length = min(mix.shape[1], reference.shape[1])
    excerpt = min(round(_WINDOW_PROBE_SECONDS * sample_rate), length)
    if excerpt < 4 * n_fft:
        return n_fft
    count = min(_WINDOW_PROBES, max(length // excerpt, 1))
    starts = np.linspace(0, length - excerpt, count).astype(np.int64)
    shares = []
    for candidate in (n_fft, 2 * n_fft):
        explained_power = 0.0
        total_power = 0.0
        for start in starts:
            token.raise_if_cancelled()
            stop = int(start) + excerpt
            explained, total = _explained_share(
                np.asarray(mix[:, start:stop], dtype=np.float32),
                np.asarray(reference[:, start:stop], dtype=np.float32),
                sample_rate,
                sigma,
                candidate,
            )
            explained_power += explained
            total_power += total
        shares.append(explained_power / total_power if total_power > 0.0 else 0.0)
    chosen = 2 * n_fft if shares[1] > shares[0] + _LONG_WINDOW_MARGIN else n_fft
    logger.info(
        "analysis window %.0f ms: the source explains %.3f of the stage at %.0f ms, %.3f at %.0f ms",
        1000.0 * chosen / sample_rate,
        shares[0],
        1000.0 * n_fft / sample_rate,
        shares[1],
        2000.0 * n_fft / sample_rate,
    )
    return chosen


def _context_frames(sample_rate: int, sigma: float) -> int:
    """Frames a block must span before its smoothing context is representative."""
    return max(
        round((1.5 * float(sigma) + 4.0) * sample_rate),
        12 * sample_rate,
    )


def _processing_block_frames(
    sample_rate: int,
    sigma: float,
    spectral_cell_budget: int = _SPECTRAL_CELL_BUDGET,
    n_fft: int | None = None,
) -> int:
    """Use the 2 GiB working-set budget to reduce repeated overlap analysis."""
    context_frames = _context_frames(sample_rate, sigma)
    n_fft = n_fft or _analysis_fft_size(sample_rate)
    hop = n_fft // 4
    bins = n_fft // 2 + 1
    # A spectral cell expands into several complex and real work arrays.  Four
    # million cells keeps measured peak RSS below 2 GiB while allowing roughly
    # 45 seconds per block at 44.1 kHz instead of the previous 16 seconds.
    budget_stft_frames = max(spectral_cell_budget // bins, 2)
    budget_audio_frames = max((budget_stft_frames - 2) * hop, 1)
    throughput_frames = min(
        _MAX_PROCESSING_BLOCK_SECONDS * sample_rate,
        budget_audio_frames,
    )
    return max(context_frames, throughput_frames)


def _processing_workers(
    sample_rate: int, sigma: float, length: int, n_fft: int | None = None
) -> int:
    context_frames = _context_frames(sample_rate, sigma)
    n_fft = n_fft or _analysis_fft_size(sample_rate)
    context_stft_frames = math.ceil(context_frames / (n_fft // 4)) + 2
    context_cells = context_stft_frames * (n_fft // 2 + 1)
    if length < 2 * context_frames:
        return 1
    memory_limited_workers = _MAX_PARALLEL_SPECTRAL_CELLS // context_cells
    return max(1, min(_MAX_PROCESSING_WORKERS, memory_limited_workers))


def _processing_layout(
    sample_rate: int, sigma: float, length: int, n_fft: int | None = None
) -> tuple[int, int]:
    workers = _processing_workers(sample_rate, sigma, length, n_fft)
    block = _processing_block_frames(sample_rate, sigma, _SPECTRAL_CELL_BUDGET // workers, n_fft)
    return block, workers


def _source_level(mix: np.ndarray, reference: np.ndarray) -> float:
    """The gain that brings the source up to the stage's level, never down.

    The bounds on the transfer and on the backing gain are there for gains fitted
    on weak evidence, not for how loud either file was mastered.  A stage that
    carries the playback hotter than the source - a quiet master, a phone's
    automatic gain, a PA run hot - otherwise sits above them everywhere: measured
    12 dB hotter, the phase-correlated scene lost 10 dB of depth and its backing
    came out 4.7 dB short.  Removing the bound instead cost the reference-only
    word 2.5 dB, so it stays and is made relative.  Read over the whole call
    rather than per block, because a block where the source falls silent would
    loosen the bounds exactly where nothing backs them.  The pass reads both
    mappings end to end, so it hands their pages back as it goes: left resident,
    the two files lifted the 15-minute benchmark's peak from 1.6 to 2.1 GiB.
    """
    common = min(mix.shape[1], reference.shape[1])
    channels = min(reference.shape[0], 2)
    if common == 0 or channels == 0:
        return 1.0
    mix_energy = 0.0
    reference_energy = 0.0
    for start in range(0, common, BLOCK_FRAMES):
        end = min(start + BLOCK_FRAMES, common)
        mix_energy += float(np.sum(np.square(mix[:, start:end], dtype=np.float64)))
        reference_energy += float(
            np.sum(np.square(reference[:channels, start:end], dtype=np.float64))
        )
        if (start // BLOCK_FRAMES) % _LEVEL_RELEASE_BLOCKS == _LEVEL_RELEASE_BLOCKS - 1:
            release_mapped_pages(mix)
            release_mapped_pages(reference)
    release_mapped_pages(mix)
    release_mapped_pages(reference)
    mix_power = mix_energy / mix.shape[0]
    reference_power = reference_energy / channels
    if reference_power <= 0.0 or mix_power <= reference_power:
        return 1.0
    return math.sqrt(mix_power / reference_power)


def _reference_cancel(
    mix: np.ndarray,
    reference: np.ndarray,
    sample_rate: int,
    strength: float,
    sigma: float,
    token: CancellationToken,
    backing: bool = False,
    source_level: float = 1.0,
    n_fft: int | None = None,
) -> tuple[np.ndarray, np.ndarray | None]:
    """Cancel reference-correlated content coherently, then suppress what is left.

    A real mask can only attenuate a whole time-frequency cell.  Where a live
    voice and the backing share a cell - which in the vocal range is the
    normal case, not the exception - the mask has to choose between removing
    both and keeping both, so depth is always paid for with the voice.  The
    transfer estimate is a complex vector, and subtracting it removes the
    backing vector from inside the cell while the live vector survives.

    This is the linear-canceller-then-residual-suppressor arrangement acoustic
    echo cancellers use.  It is not the direct residual this project removed
    earlier: that one subtracted a broadband real 2x2 matrix in the time domain
    with no per-bin projection, no confidence and no bound on the result, which
    is why a word present only in the reference ended up inverted in the output.

    With `backing=True` the same pass renders the second export track as well:
    the source as the playback carried it, from the estimate this canceller
    built, rather than from the stage minus the vocal.  `source_level` is the
    gain `_source_level` found; the backing renders from the source at that
    level, so it comes out at the stage's.
    """
    length = min(mix.shape[1], reference.shape[1])
    mix = np.asarray(mix[:, :length], dtype=np.float32)
    reference_audio = np.asarray(reference[:, :length], dtype=np.float32)
    n_fft = n_fft or _analysis_fft_size(sample_rate)
    hop = n_fft // 4
    mix_spectra = [stft(channel, n_fft=n_fft, hop=hop) for channel in mix]
    token.raise_if_cancelled()
    reference_spectra = [stft(channel, n_fft=n_fft, hop=hop) for channel in reference_audio[:2]]
    if not reference_spectra:
        return mix.copy(), None
    if source_level != 1.0:
        for reference_spectrum in reference_spectra:
            reference_spectrum *= source_level
    if len(reference_spectra) == 1:
        reference_spectra.append(reference_spectra[0])
    sigma_frames = max(float(sigma) * sample_rate / hop / 6.0, 1.0)

    # Every step below works over a whole [frames, bins] spectrum, so a chain of
    # operators would put half a dozen of them in the block working set at once.
    # One real and one complex buffer carry all the intermediates instead; what
    # a line reads is still exactly the expression it spells out.
    power = np.empty(mix_spectra[0].shape, dtype=mix_spectra[0].real.dtype)
    spectrum = np.empty(mix_spectra[0].shape, dtype=mix_spectra[0].dtype)

    # The robust weights need a prediction, not the best prediction: they only
    # weigh how the residual power fluctuates against its own local mean, so a
    # diagonal fit - each reference channel on its own - is enough here.  The
    # pass that actually subtracts still fits the full two-channel system, and
    # the coherence is not measured in either pass of the first one.
    predicted, _ = predict_reference_spectra(
        mix_spectra,
        reference_spectra,
        sigma_frames,
        token,
        coherence=False,
        diagonal=True,
    )
    residual_power = np.zeros(mix_spectra[0].shape, dtype=np.float32)
    for mixture_channel, predicted_channel in zip(mix_spectra, predicted, strict=True):
        np.subtract(mixture_channel, predicted_channel, out=spectrum)
        np.abs(spectrum, out=power)
        np.square(power, out=power)
        residual_power += power
    # The scale the outliers are judged against has to be one they cannot lift
    # themselves.  A smoothed arithmetic mean is dragged up by the very live
    # transients it is meant to down-weight, so take the geometric mean: the
    # same O(N) smoother, read in the log domain.
    residual_floor = 1e-10 * float(np.mean(residual_power)) + 1e-30
    np.add(residual_power, residual_floor, out=power)
    np.log(power, out=power)
    local_residual = spectral_smooth(power, sigma_frames)
    np.exp(local_residual, out=local_residual)
    local_residual *= _ROBUST_SCALE
    np.add(residual_power, 1e-12, out=power)
    local_residual /= power
    np.minimum(local_residual, 1.0, out=local_residual)
    robust_weights = local_residual.astype(np.float32, copy=False)
    del residual_power, local_residual, predicted
    predicted, explained = predict_reference_spectra(
        mix_spectra,
        reference_spectra,
        sigma_frames,
        token,
        robust_weights,
    )
    del robust_weights
    token.raise_if_cancelled()

    # How much of the prediction to subtract is not a free parameter.  The
    # transfer is estimated from a finite window, so its error variance is
    # about order/observations of the unexplained power, and the shrinkage that
    # minimises the mean square error of the subtraction follows from that
    # alone.  It reaches zero for a reference that explains nothing, which is
    # what keeps an unrelated reference from being subtracted at all.
    variance_ratio = TRANSFER_ORDER / effective_observations(sigma_frames, mix_spectra[0].shape[0])
    alignment = np.zeros(mix_spectra[0].shape, dtype=np.float32)
    predicted_power = np.zeros_like(alignment)
    for mixture_channel, predicted_channel, confidence in zip(
        mix_spectra, predicted, explained, strict=True
    ):
        # confidence / (confidence + variance_ratio * (1 - confidence) + 1e-12)
        np.subtract(1.0, confidence, out=power)
        power *= variance_ratio
        power += confidence
        power += 1e-12
        np.divide(confidence, power, out=power)
        predicted_channel *= power
        np.conj(predicted_channel, out=spectrum)
        np.multiply(mixture_channel, spectrum, out=spectrum)
        alignment += spectrum.real
        np.abs(predicted_channel, out=power)
        np.square(power, out=power)
        predicted_power += power
    # The linear stage may only take energy out.  Solving |y - t*d| <= |y| for t
    # gives 2*Re(y conj(d))/|d|^2 exactly, so this is the largest step that
    # cannot amplify - and because it reads the phase, it also falls to zero
    # where the prediction is orthogonal to the mixture in a cell.  Bounding
    # |e| by |y| instead leaves the residual pointing wherever the bad
    # prediction put it, merely rescaled.  The step is linked across channels
    # like the mask that follows it.
    alignment *= 2.0
    predicted_power += 1e-20
    alignment /= predicted_power
    step = np.clip(alignment, 0.0, 1.0, out=alignment)
    del predicted_power
    removable_power = np.zeros(mix_spectra[0].shape, dtype=np.float32)
    residual_spectra: list[np.ndarray] = []
    for mixture_channel, predicted_channel in zip(mix_spectra, predicted, strict=True):
        removed = np.multiply(step, predicted_channel, out=spectrum)
        np.abs(removed, out=power)
        np.square(power, out=power)
        removable_power += power
        # The prediction is spent once it has been scaled, so the residual takes
        # its buffer instead of a third full-length complex spectrum.
        np.subtract(mixture_channel, removed, out=predicted_channel)
        residual_spectra.append(predicted_channel)
    del predicted, step, alignment
    token.raise_if_cancelled()

    # What survives the subtraction is not only the live source: reverberation
    # ringing past the analysis window, residual misalignment and level moves
    # all leave backing behind that the narrowband transfer could not
    # describe.  How much is a regression of the residual power on the power
    # that was removed, carrying an intercept:
    #
    #     P_e = rho P_d + c
    #
    # `rho P_d` follows the backing that was there, so it is leakage; the
    # slowly varying `c` does not, so it is the live source, and only the first
    # term may be taken out.  This is the same split the incoherent path below
    # makes for the same reason.
    residual_power = np.zeros_like(removable_power)
    for residual in residual_spectra:
        np.abs(residual, out=power)
        np.square(power, out=power)
        residual_power += power
    del explained
    leaked_power, leakage_confidence = reverberant_power_transfer(
        residual_power, removable_power, sigma_frames, hop / sample_rate
    )
    leaked_power *= smoothstep(_POWER_FIT_LOW, _POWER_FIT_HIGH, leakage_confidence)
    # Leakage cannot exceed the residual it was found in.
    np.minimum(leaked_power, residual_power, out=leaked_power)
    del leakage_confidence
    # The backing track is rendered from the source, so it needs the source's
    # share of each cell rather than the amount the mask happens to remove.  Two
    # estimates answer that question and the larger is taken: the coherent stage
    # plus this leakage regression describes what the subtraction left behind,
    # while the incoherent path below fits the source's power in the mixture
    # directly.
    backing_power = None
    if backing:
        backing_power = removable_power.copy()
        backing_power += leaked_power

    # Where the capture path destroyed phase, the coherent stage has nothing to
    # subtract and `removable_power` is far smaller than the backing that
    # is actually present.  The power-domain fit sees that content, so the mask
    # removes whichever of the two explains more, minus what has already gone.
    reference_power = np.zeros_like(residual_power)
    for reference_channel in reference_spectra:
        np.abs(reference_channel, out=power)
        np.square(power, out=power)
        reference_power += power
    # The side mask below is built after the backing track has already read
    # whatever it needs from the source, so its regressor is taken here, while
    # the reference spectra are still resident.
    side_reference_power = np.empty_like(residual_power)
    np.subtract(reference_spectra[0], reference_spectra[1], out=spectrum)
    np.abs(spectrum, out=side_reference_power)
    np.square(side_reference_power, out=side_reference_power)
    mixture_power = np.zeros_like(residual_power)
    for mixture_channel in mix_spectra:
        np.abs(mixture_channel, out=power)
        np.square(power, out=power)
        mixture_power += power
    incoherent_power, incoherent_confidence = power_transfer(
        mixture_power, reference_power, sigma_frames
    )
    # Amplitude regression is less dominated by loud transients than power
    # regression when effects decorrelate phase; its intercept keeps live content.
    amplitude_power, amplitude_confidence = power_transfer(
        np.sqrt(mixture_power), np.sqrt(reference_power), sigma_frames
    )
    np.square(amplitude_power, out=amplitude_power)
    amplitude_power *= smoothstep(_POWER_FIT_LOW, _POWER_FIT_HIGH, amplitude_confidence)
    del reference_power
    if backing_power is None:
        del mixture_power, reference_spectra
    incoherent_power *= smoothstep(_POWER_FIT_LOW, _POWER_FIT_HIGH, incoherent_confidence)
    np.maximum(incoherent_power, amplitude_power, out=incoherent_power)
    del amplitude_power, amplitude_confidence
    if backing_power is not None:
        np.maximum(backing_power, incoherent_power, out=backing_power)
        # No backing can carry more power than the mixture it was fitted on.
        # The bound is what keeps a take whose level barely moves honest: with
        # no variance to regress on, the fit's slope is noise, and without this
        # the rendered backing turns into a wild equaliser.
        np.minimum(backing_power, mixture_power, out=backing_power)
        del mixture_power
    incoherent_power -= removable_power
    np.maximum(incoherent_power, 0.0, out=incoherent_power)
    del incoherent_confidence
    # Bound the weak-evidence path so one noisy cell cannot drive the mask to
    # the floor: deep, isolated mask dips are what musical noise sounds like.
    np.multiply(residual_power, _INCOHERENT_MAX_SHARE, out=power)
    np.minimum(incoherent_power, power, out=incoherent_power)

    # residual - leakage - oversubtraction * incoherent, floored at the mask
    # floor's share of the residual; formed in the buffers those terms are in.
    np.multiply(residual_power, _MASK_FLOOR**2, out=power)
    incoherent_power *= _INCOHERENT_OVERSUBTRACTION
    remaining_power = np.subtract(residual_power, leaked_power, out=leaked_power)
    remaining_power -= incoherent_power
    np.maximum(remaining_power, power, out=remaining_power)
    del incoherent_power, leaked_power
    # Form the mask from powers smoothed in time rather than from instantaneous
    # per-cell powers: most of the ratio's variance is removed before it
    # reaches the mask, and the Gaussian pass below only has to catch what is
    # left.  This is what tamed the musical noise on phase-decorrelated
    # captures; the floor still bounds the ratio from below.
    mask = spectral_smooth(remaining_power, _MASK_POWER_SMOOTH, 0.0)
    mask_residual = spectral_smooth(residual_power, _MASK_POWER_SMOOTH, 0.0)
    mask_residual += 1e-12
    mask /= mask_residual
    np.clip(mask, _MASK_FLOOR**2, 1.0, out=mask)
    np.sqrt(mask, out=mask)
    # The backing track is the estimate applied to the source, not the stage
    # minus the vocal, so it carries the source's own quality instead of the
    # capture's.  `backing_gain` is the share of the source's local power the
    # playback carried: the estimated backing power over the source's own power.
    # Both sides are smoothed over the same context before they are divided,
    # which leaves a slowly varying real gain; applied to the source's own
    # spectrum it keeps the source's phase, transients and fine structure.  The
    # complex transfer cannot be used for this: where the coherence is low its
    # phase is noise, and rendering it would smear exactly the content the power
    # path recovered.
    backing_gain = None
    if backing_power is not None:
        source_power = np.zeros_like(backing_power)
        for reference_channel in reference_spectra:
            np.abs(reference_channel, out=power)
            np.square(power, out=power)
            source_power += power
        spectral_smooth(backing_power, sigma_frames, out=backing_power)
        spectral_smooth(source_power, sigma_frames, out=source_power)
        source_power += 1e-20
        np.divide(backing_power, source_power, out=backing_power)
        del source_power
        # A ratio of powers, and the running sum inside the smoother, can both
        # round below zero where the content is silent; the root may not.
        np.maximum(backing_power, 0.0, out=backing_power)
        np.sqrt(backing_power, out=backing_power)
        backing_gain = np.clip(backing_power, 0.0, _MAX_BACKING_GAIN, out=backing_power)
        del backing_power
    # Phamtom-Center-style L-R stage.  The difference channel is the backing's
    # own: a live stage adds content that is close to mono, so L-R carries the
    # playback with far less of the voice in it.  Decomposing the residual into
    # mid and side and masking each in its own basis therefore suppresses the
    # width the shared mask has to leave behind.  Applying one side gain to
    # L and R instead was measured and is wrong - a side floor applied to both
    # channels alike is a mid floor, and it took the live gain with it
    # (-0.27 on the drift scenes).
    #
    # The side mask is built from the same leakage split as the shared one:
    # residual side power regressed on source side power, floored at the mask
    # floor.  It can only ever be stricter than the shared mask - where the side
    # has no evidence it falls back to that one - so a capture it says nothing
    # about keeps exactly the depth it had.
    side_residual_power = np.empty_like(residual_power)
    np.subtract(residual_spectra[0], residual_spectra[1], out=spectrum)
    np.abs(spectrum, out=side_residual_power)
    np.square(side_residual_power, out=side_residual_power)
    side_leakage, side_confidence = power_transfer(
        side_residual_power, side_reference_power, sigma_frames
    )
    side_leakage *= smoothstep(_POWER_FIT_LOW, _POWER_FIT_HIGH, side_confidence)
    np.minimum(side_leakage, side_residual_power, out=side_leakage)
    np.multiply(side_residual_power, _MASK_FLOOR**2, out=power)
    side_remaining = np.subtract(side_residual_power, side_leakage, out=side_leakage)
    np.maximum(side_remaining, power, out=side_remaining)
    side_mask = spectral_smooth(side_remaining, _MASK_POWER_SMOOTH, 0.0)
    side_denominator = spectral_smooth(side_residual_power, _MASK_POWER_SMOOTH, 0.0)
    side_denominator += 1e-12
    side_mask /= side_denominator
    np.clip(side_mask, _MASK_FLOOR**2, 1.0, out=side_mask)
    np.sqrt(side_mask, out=side_mask)
    gaussian_filter(side_mask, sigma=_MASK_SMOOTHING, mode="reflect", output=side_mask)
    np.clip(side_mask, _MASK_FLOOR, 1.0, out=side_mask)
    del side_denominator, side_remaining, side_residual_power, side_reference_power
    del side_leakage, side_confidence
    del mask_residual, remaining_power, removable_power, residual_power
    # The narrow Gaussian pass catches what the power-domain smoothing left:
    # isolated-bin musical noise, without refilling tonal notches from
    # untouched neighbours.  Berouti-style signal-dependent over-subtraction, an
    # Ephraim-Malah decision-directed Wiener gain and Breithaupt cepstral gain
    # smoothing were all measured here against this line: each bought a few dB
    # on short reverberation but roughly halved fidelity on a quiet live vocal,
    # so none of them replaced it.
    gaussian_filter(mask, sigma=_MASK_SMOOTHING, mode="reflect", output=mask)
    np.clip(mask, _MASK_FLOOR, 1.0, out=mask)
    token.raise_if_cancelled()
    # Strength interpolates towards the fully processed spectrum.  With nothing
    # subtracted this is exactly the mask blend it replaces, 1 - a(1 - M), so
    # bypass at zero and monotonicity are unchanged.
    np.minimum(side_mask, mask, out=side_mask)
    left_residual = residual_spectra[0]
    right_residual = residual_spectra[1]
    mid = np.add(left_residual, right_residual, out=spectrum)
    mid *= 0.5
    side = np.empty_like(left_residual)
    np.subtract(left_residual, right_residual, out=side)
    side *= 0.5
    mid *= mask
    side *= side_mask
    # Rotate the two masked halves back.  Both are still complex, so the
    # channel that lost its side content reconstructs as a narrower version of
    # itself rather than as an attenuated copy of the other.
    np.add(mid, side, out=left_residual)
    np.subtract(mid, side, out=right_residual)
    del mid, side, side_mask
    for mixture_channel, residual in zip(mix_spectra, residual_spectra, strict=True):
        residual -= mixture_channel
        residual *= strength
        residual += mixture_channel
    del mix_spectra, mask, spectrum
    processed = np.asarray(
        [istft(channel, hop=hop, length=length) for channel in residual_spectra],
        dtype=np.float32,
    )
    if backing_gain is None:
        return processed, None
    # Strength scales the backing the way it scales the subtraction, so a
    # bypass exports silence rather than a backing nothing was taken from.
    backing_gain *= strength
    return processed, np.asarray(
        [
            istft(reference_channel * backing_gain, hop=hop, length=length)
            for reference_channel in reference_spectra
        ],
        dtype=np.float32,
    )


def process_audio(
    mix: np.ndarray,
    reference: np.ndarray,
    sample_rate: int,
    strength: float,
    sigma: float,
    token: CancellationToken | None = None,
    output: np.ndarray | None = None,
    backing: np.ndarray | None = None,
) -> np.ndarray:
    """Cancel the reference out of the mix, optionally rendering the backing too.

    `output` receives the vocal and is returned.  `backing`, when given, receives
    the second export track: the source as the playback carried it, synthesised
    from the cancellation's own estimate rather than from the stage minus the
    vocal, so it carries the source's quality instead of the capture's.
    """
    cancel = token or CancellationToken()
    mix = np.asarray(mix, dtype=np.float32)
    reference_audio = np.asarray(reference, dtype=np.float32)
    if mix.ndim != 2 or reference_audio.ndim != 2 or sample_rate <= 0:
        raise ValueError("audio must have shape [channels, frames] and a positive sample rate")
    strength = float(np.clip(strength, 0.0, 1.0))
    length = mix.shape[1]
    if output is None:
        result = np.empty((mix.shape[0], length), dtype=np.float32)
    else:
        if output.shape != (mix.shape[0], length) or output.dtype != np.float32:
            raise ValueError("output must be a float32 [channels, frames] array")
        result = output
    if backing is not None and (
        backing.shape != (mix.shape[0], length) or backing.dtype != np.float32
    ):
        raise ValueError("backing must be a float32 [channels, frames] array")
    if strength == 0:
        result[:] = mix
        if backing is not None:
            # Nothing was cancelled, so there is no estimate to render.
            backing[:] = 0.0
        return result
    source_level = _source_level(mix, reference_audio)
    n_fft = _capture_fft_size(mix, reference_audio, sample_rate, sigma, cancel)
    # Long recordings scale across independent spectral workers.  The layout
    # divides the working-set budget; large contexts automatically use fewer.
    block, workers = _processing_layout(sample_rate, sigma, length, n_fft)
    overlap = min(
        max(round(0.5 * float(sigma) * sample_rate), 2 * sample_rate),
        block // 3,
    )
    step = block - overlap
    starts = list(range(0, length, step))

    def process_block(
        start: int,
    ) -> tuple[int, int, np.ndarray, np.ndarray | None]:
        cancel.raise_if_cancelled()
        end = min(start + block, length)
        reference_end = min(end, reference_audio.shape[1])
        if reference_end < end:
            # The reference ran out inside this block: pad the rest with silence.
            reference_block = np.zeros((reference_audio.shape[0], end - start), dtype=np.float32)
            if start < reference_end:
                reference_block[:, : reference_end - start] = reference_audio[
                    :, start:reference_end
                ]
        else:
            reference_block = reference_audio[:, start:end]
        processed, processed_backing = _reference_cancel(
            mix[:, start:end],
            reference_block,
            sample_rate,
            strength,
            sigma,
            cancel,
            backing is not None,
            source_level,
            n_fft,
        )
        return start, end, processed, processed_backing

    def blend_into(destination: np.ndarray, processed: np.ndarray, start: int, end: int) -> None:
        fade = min(overlap, end - start) if start > 0 else 0
        if fade:
            phase = np.linspace(0, np.pi / 2, fade, dtype=np.float32)
            old_weight = np.cos(phase) ** 2
            new_weight = np.sin(phase) ** 2
            destination[:, start : start + fade] = (
                destination[:, start : start + fade] * old_weight + processed[:, :fade] * new_weight
            )
        destination[:, start + fade : end] = processed[:, fade : end - start]

    def blend_block(
        start: int,
        end: int,
        processed: np.ndarray,
        processed_backing: np.ndarray | None,
    ) -> None:
        blend_into(result, processed, start, end)
        if processed_backing is not None and backing is not None:
            blend_into(backing, processed_backing, start, end)

    def release_batch() -> None:
        release_mapped_pages(mix)
        release_mapped_pages(reference_audio)
        release_mapped_pages(result)
        if backing is not None:
            release_mapped_pages(backing)

    indexed_starts = list(enumerate(starts))
    if _THREADS_AVAILABLE:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="purivox-dsp") as executor:
            for batch_start in range(0, len(indexed_starts), workers):
                batch = indexed_starts[batch_start : batch_start + workers]
                futures = [executor.submit(process_block, start) for _index, start in batch]
                for future in futures:
                    blend_block(*future.result())
                release_batch()
    else:
        # The blocks are independent and blended in the order they were
        # scheduled, so running them inline gives the same result one core at a
        # time.  Pages are released per block rather than per batch: the browser
        # has no disk to page out to and needs the hint sooner.
        for _index, start in indexed_starts:
            blend_block(*process_block(start))
            release_batch()
    peak = 0.0
    backing_peak = 0.0
    cleanup_block = BLOCK_FRAMES
    for start in range(0, length, cleanup_block):
        view = result[:, start : start + cleanup_block]
        np.nan_to_num(view, copy=False)
        peak = max(peak, float(np.max(np.abs(view), initial=0.0)))
        if backing is not None:
            backing_view = backing[:, start : start + cleanup_block]
            np.nan_to_num(backing_view, copy=False)
            backing_peak = max(backing_peak, float(np.max(np.abs(backing_view), initial=0.0)))
    peak_ceiling = 10 ** (-1.0 / 20.0)
    # Each track is bounded on its own peak: the synthesised backing can be
    # louder than the vocal it was estimated alongside, and clipping one to
    # protect the other would trade a level for a distortion.
    for values, value in ((result, peak), (backing, backing_peak)):
        if values is None or value <= peak_ceiling:
            continue
        scale = peak_ceiling / value
        for start in range(0, length, cleanup_block):
            values[:, start : start + cleanup_block] *= scale
    # Phantom Center runs after the removal, on what is left, and it is an
    # enhancement rather than part of the cancellation, so it is gated on
    # whether the cancellation actually took a wide image out.  A capture that
    # heard a mono playback has a centre-shaped removal and keeps its centre.
    removed_width, removed_energy = _stereo_width_and_energy(mix - result, cancel)
    output_width, output_energy = _stereo_width_and_energy(result, cancel)
    # A removal that took almost nothing has no wide image to read: the ratio of
    # two tiny widths is noise, and a stage whose reference is silent must pass
    # through untouched.
    if (
        removed_energy >= _CENTRE_MIN_REMOVED_SHARE * output_energy
        and removed_width >= _CENTRE_MIN_WIDTH_RATIO * output_width
    ):
        extracted = _centre_extract(result, n_fft, n_fft // 4, cancel)
        np.copyto(result, extracted)
        del extracted
        logger.info(
            "centre extraction: the removed content is %.2f times as wide as the output",
            removed_width / max(output_width, 1e-20),
        )
    return result
