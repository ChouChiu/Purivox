"""Panning-adaptive separation: what a fixed matrix cannot reach.

A stereo mix places its lead vocal in the middle, but "in the middle" is a
statement about one frequency at one instant, not about the waveform: pan
moves, reverb spreads, and a doubled line sits just off centre.  Subtracting a
fixed share of the mid channel therefore leaves the vocal behind and takes the
centred kick and bass with it.

Both routines here estimate what is actually shared between the channels, per
frequency, and act on that: one masks the centred content out of a stereo mix,
the other cancels a discrete centre channel out of the front pair of a surround
master.  Both read the project's own STFT, which the matching code already
shares, so there is one spectral implementation in the tree.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import uniform_filter1d

from shared.audio import AudioData
from shared.dsp import istft, stft
from shared.processing import CancellationToken

logger = logging.getLogger(__name__)

N_FFT = 2048
HOP = 512
# One spectral block, and the overlap two of them are crossfaded over.  The
# whole spectrogram of a concert is a hundred times the audio it describes, so
# the pass runs over blocks of it, the way the cancellation pipeline does.
BLOCK_SECONDS = 45.0
OVERLAP_SECONDS = 2.0
# How far the running average behind every estimate reaches: five frames is
# about sixty milliseconds at 44.1 kHz, long enough to average out one pitch
# period and short enough to follow a word.  Smoothing across frequency as well
# measured worse in `tools/eval_stems.py` - three bins of it cost two decibels
# of lead suppression - because it blurs a bin the lead owns into its
# neighbours, which other sources own.
SMOOTHING_FRAMES = 5
# The panning offset a source is still called centred at, as a fraction of the
# way to one side.  A lead vocal that sits slightly off centre, or is doubled,
# stays inside this; a guitar panned hard does not.
PAN_WIDTH = 0.25
# The band the centre mask is allowed to act in.  Below the first of these a
# mix is centred whatever it holds - the kick and the bass live there by
# convention, not because they are the lead - so taking centred content out
# there would empty the instrumental of its low end, which is the complaint
# every phase-cancellation karaoke track attracts.  The mask fades in between
# the two, and the band is kept narrow because a male lead's fundamental sits
# just above it: protecting further up would leave that part of the voice in
# the instrumental.
BASS_PROTECT_HZ = 100.0
BASS_PROTECT_EDGE_HZ = 200.0
# Below this coherence a front channel shares nothing measurable with the
# centre channel, so nothing is subtracted from it.
COHERENCE_FLOOR = 0.2
_EPSILON = 1e-12

ProgressFraction = Callable[[float], None]


@dataclass(frozen=True, slots=True)
class _Block:
    """One stretch of samples, and the crossfades joining it to its neighbours."""

    start: int
    stop: int
    fade_in: int
    fade_out: int

    @property
    def frames(self) -> int:
        return self.stop - self.start


def _round_to_hop(value: int) -> int:
    return max(1, value // HOP) * HOP


def block_plan(frames: int, sample_rate: int) -> list[_Block]:
    """Cut a recording into overlapping spectral blocks that add back to one signal."""
    block = max(_round_to_hop(int(BLOCK_SECONDS * sample_rate)), 4 * N_FFT)
    if frames <= block:
        return [_Block(0, frames, 0, 0)]
    overlap = max(HOP, min(_round_to_hop(int(OVERLAP_SECONDS * sample_rate)), block // 4))
    step = block - overlap
    plan: list[_Block] = []
    start = 0
    while start < frames:
        stop = min(start + block, frames)
        plan.append(_Block(start, stop, overlap if start else 0, overlap if stop < frames else 0))
        if stop >= frames:
            break
        start += step
    return plan


def _crossfade(block: _Block) -> np.ndarray:
    """A window whose overlapping halves sum to one, so the blocks rejoin flat."""
    window = np.ones(block.frames, dtype=np.float32)
    if block.fade_in:
        rising = np.linspace(0.0, np.pi / 2, block.fade_in, endpoint=False)
        window[: block.fade_in] = np.sin(rising) ** 2
    if block.fade_out:
        falling = np.linspace(0.0, np.pi / 2, block.fade_out, endpoint=False)
        window[block.frames - block.fade_out :] = np.cos(falling) ** 2
    return window


def _smooth(values: np.ndarray) -> np.ndarray:
    """Average a spectrogram over a few frames, symmetrically."""
    if np.iscomplexobj(values):
        return _smooth(values.real) + 1j * _smooth(values.imag)
    return uniform_filter1d(values, SMOOTHING_FRAMES, axis=0, mode="nearest")


def _bass_protection(bins: int, sample_rate: int) -> np.ndarray:
    """Fade the mask out under the band where a centred source means a lead."""
    frequencies = np.linspace(0.0, sample_rate / 2.0, bins)
    span = max(BASS_PROTECT_EDGE_HZ - BASS_PROTECT_HZ, 1.0)
    ramp = np.clip((frequencies - BASS_PROTECT_HZ) / span, 0.0, 1.0)
    return (0.5 - 0.5 * np.cos(np.pi * ramp)).astype(np.float32)


@dataclass(frozen=True, slots=True)
class CentreEstimate:
    """What the two channels share at each spectral cell, and where it sits.

    `weight` is how much of the cell belongs to a centred source; `tilt` is the
    share of it each channel carries, so an off-centre lead has the right
    amount taken out of each side instead of half of it taken out of both.
    """

    weight: np.ndarray
    tilt: tuple[np.ndarray, np.ndarray]


def estimate_centre(left: np.ndarray, right: np.ndarray, sample_rate: int) -> CentreEstimate:
    """Read the centred content out of a stereo spectrum.

    Two numbers describe a cell: how alike the channels are there, and where
    between them it sits.  A lead vocal scores high on both - one source, in
    the middle - while a hard-panned guitar fails the second and a reverb tail
    or a cymbal wash fails the first.
    """
    # A running average of squares is non-negative in exact arithmetic but not
    # in float32, where a cell that is all but silent comes back a hair below
    # zero - and the square roots below turn that into NaN for the whole stem.
    auto_left = np.maximum(_smooth(np.abs(left) ** 2), 0.0)
    auto_right = np.maximum(_smooth(np.abs(right) ** 2), 0.0)
    cross = _smooth(left * np.conj(right))
    total = auto_left + auto_right + _EPSILON
    similarity = np.clip(2.0 * np.abs(cross) / total, 0.0, 1.0)
    balance = (auto_left - auto_right) / total
    centred = np.exp(-(balance**2) / (2.0 * PAN_WIDTH**2))
    weight = similarity * centred * _bass_protection(left.shape[1], sample_rate)
    # The amplitudes the shared source arrives at on each side.  Their mean is
    # what the mid channel carries, so dividing by it gives each channel the
    # factor that takes exactly its own share of the source away.
    amplitude_left = np.sqrt(auto_left)
    amplitude_right = np.sqrt(auto_right)
    mean = 0.5 * (amplitude_left + amplitude_right) + _EPSILON
    return CentreEstimate(
        weight.astype(np.float32),
        ((amplitude_left / mean).astype(np.float32), (amplitude_right / mean).astype(np.float32)),
    )


def separate_centre(
    stereo: AudioData,
    centre: AudioData,
    instrumental: AudioData,
    token: CancellationToken,
    report: ProgressFraction | None = None,
) -> None:
    """Split a stereo mix into its centred content and everything else.

    The centre stem is mono, because a centred source is one signal; the
    instrumental keeps both channels, and is the mix with that signal taken out
    of each of them in the complex domain rather than attenuated in level.  The
    two are still a decomposition: putting the centre stem back at the panning
    the estimate measured returns the mix.
    """
    plan = block_plan(stereo.frames, stereo.sample_rate)
    for index, block in enumerate(plan):
        token.raise_if_cancelled()
        left = np.asarray(stereo.samples[0, block.start : block.stop], dtype=np.float32)
        right = np.asarray(stereo.samples[1, block.start : block.stop], dtype=np.float32)
        left_spectrum = stft(left, N_FFT, HOP)
        right_spectrum = stft(right, N_FFT, HOP)
        estimate = estimate_centre(left_spectrum, right_spectrum, stereo.sample_rate)
        centred = estimate.weight * 0.5 * (left_spectrum + right_spectrum)
        window = _crossfade(block)
        centre.samples[0, block.start : block.stop] += window * istft(
            centred, HOP, block.frames
        ).astype(np.float32, copy=False)
        for row, spectrum in ((0, left_spectrum), (1, right_spectrum)):
            rest = istft(spectrum - estimate.tilt[row] * centred, HOP, block.frames).astype(
                np.float32, copy=False
            )
            instrumental.samples[row, block.start : block.stop] += window * rest
        if report is not None:
            report((index + 1) / len(plan))


def _front_transfer(
    source: AudioData,
    front: tuple[int, int],
    centre_channel: int,
    token: CancellationToken,
) -> np.ndarray:
    """Estimate, per frequency, how much of the centre channel each front channel carries.

    Atome fits one real number over the whole recording.  What a mastering
    chain actually leaves in the front pair is a filter - delayed, shelved, and
    different at every frequency - so this is a complex ratio per bin, gated by
    the coherence behind it: where a front channel shares nothing measurable
    with the centre, nothing is subtracted from it.
    """
    bins = N_FFT // 2 + 1
    cross = np.zeros((2, bins), dtype=np.complex128)
    auto_front = np.zeros((2, bins))
    auto_centre = np.zeros(bins)
    for block in block_plan(source.frames, source.sample_rate):
        token.raise_if_cancelled()
        centre = stft(
            np.asarray(source.samples[centre_channel, block.start : block.stop], dtype=np.float32),
            N_FFT,
            HOP,
        )
        auto_centre += np.sum(np.abs(centre) ** 2, axis=0)
        for row, channel in enumerate(front):
            spectrum = stft(
                np.asarray(source.samples[channel, block.start : block.stop], dtype=np.float32),
                N_FFT,
                HOP,
            )
            cross[row] += np.sum(spectrum * np.conj(centre), axis=0)
            auto_front[row] += np.sum(np.abs(spectrum) ** 2, axis=0)
    transfer = cross / (auto_centre + _EPSILON)
    coherence = np.abs(cross) ** 2 / ((auto_front * auto_centre) + _EPSILON)
    transfer[coherence < COHERENCE_FLOOR] = 0.0
    logger.info(
        "centre leaks into the front pair over %d of %d bins",
        int(np.count_nonzero(transfer[0])),
        bins,
    )
    return transfer


def cancel_centre_from_front(
    source: AudioData,
    destination: AudioData,
    front: tuple[int, int],
    centre_channel: int,
    token: CancellationToken,
    report: ProgressFraction | None = None,
) -> None:
    """Take the centre channel back out of the front pair of a surround master."""
    transfer = _front_transfer(source, front, centre_channel, token)
    plan = block_plan(source.frames, source.sample_rate)
    for index, block in enumerate(plan):
        token.raise_if_cancelled()
        centre = stft(
            np.asarray(source.samples[centre_channel, block.start : block.stop], dtype=np.float32),
            N_FFT,
            HOP,
        )
        window = _crossfade(block)
        for row, channel in enumerate(front):
            spectrum = stft(
                np.asarray(source.samples[channel, block.start : block.stop], dtype=np.float32),
                N_FFT,
                HOP,
            )
            cleaned = istft(spectrum - transfer[row] * centre, HOP, block.frames)
            destination.samples[row, block.start : block.stop] += window * cleaned.astype(
                np.float32, copy=False
            )
        if report is not None:
            report((index + 1) / len(plan))
