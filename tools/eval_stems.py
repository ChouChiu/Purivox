"""Offline A/B measurement for the stem split.

The DSP in this project is judged by measurement, not by argument.  The
cancellation core has `eval_cancellation.py`; this is the same idea for the
split, which has no reference to cancel against and is scored instead on what
each stem kept and what it let go.

    uv run --locked python tools/eval_stems.py --save baseline.json
    uv run --locked python tools/eval_stems.py --compare baseline.json

Every scene is built from parts this script knows, so "the lead is 40 dB down
in the instrumental" is a measured projection onto the lead that went in, not
an impression of the result.  Synthetic metrics only find regressions.  They
do not claim real-music quality.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from features.stem_split.dsp.crossover import difference, lowpass
from features.stem_split.dsp.panning import cancel_centre_from_front, separate_centre
from shared.audio import AudioData
from shared.processing import CancellationToken

SAMPLE_RATE = 22_050
SECONDS = 6.0
FRAMES = int(SAMPLE_RATE * SECONDS)
# Leave the first moments out of every measurement: a filter and a spectral
# block both need a running start, and neither is what is being scored.
BODY = slice(FRAMES // 4, FRAMES)


@dataclass(frozen=True, slots=True)
class Scene:
    """One synthetic split, and the parts that went into it.

    `mixture` is what the pipeline is given.  `lead` is the content a centre
    stem must keep and an instrumental must lose - as it arrives in the left
    channel, so a leak through a filter is scored against the filtered signal
    and not against what went into it.  `kept` are the parts an instrumental
    must come back with, each with the gain it was mixed in at.
    """

    name: str
    mixture: np.ndarray
    lead: np.ndarray
    lead_gain: float = 1.0
    kept: dict[str, tuple[np.ndarray, float]] = field(default_factory=dict)


def _audio(samples: np.ndarray) -> AudioData:
    return AudioData(np.ascontiguousarray(np.atleast_2d(samples), dtype=np.float32), SAMPLE_RATE)


def _voice(rng: np.random.Generator, fundamental: float) -> np.ndarray:
    """A sung note: a few harmonics with vibrato, which is what a mask has to follow."""
    time = np.arange(FRAMES) / SAMPLE_RATE
    vibrato = 1.0 + 0.004 * np.sin(2 * np.pi * 5.2 * time)
    note = sum(
        (0.6**index) * np.sin(2 * np.pi * fundamental * (index + 1) * time * vibrato)
        for index in range(5)
    )
    envelope = 0.7 + 0.3 * np.sin(2 * np.pi * 0.7 * time + rng.uniform(0, 2 * np.pi))
    return 0.35 * note * envelope / np.max(np.abs(note))


def _arrangement(rng: np.random.Generator, seed_tones: tuple[float, ...]) -> np.ndarray:
    time = np.arange(FRAMES) / SAMPLE_RATE
    signal = sum(
        np.sin(2 * np.pi * frequency * time + rng.uniform(0, 2 * np.pi)) for frequency in seed_tones
    )
    return 0.3 * signal / np.max(np.abs(signal))


def _room(rng: np.random.Generator, rt60_ms: float) -> np.ndarray:
    length = max(int(SAMPLE_RATE * rt60_ms / 1000.0), 1)
    decay = np.exp(-6.9078 * np.arange(length) / max(length - 1, 1))
    response = rng.normal(0.0, 1.0, length) * decay
    return response / np.sqrt(np.sum(response**2))


def _panned(rng: np.random.Generator, position: float) -> tuple[float, float]:
    """Amplitude panning: 0 is centred, 1 is hard left."""
    del rng
    angle = (position + 1.0) * np.pi / 4.0
    return float(np.sin(angle)), float(np.cos(angle))


def _stereo_scene(
    name: str,
    lead_position: float,
    fundamental: float = 196.0,
    reverberant: bool = False,
) -> Scene:
    rng = np.random.default_rng(int(lead_position * 1000 + fundamental) + (7 if reverberant else 0))
    lead = _voice(rng, fundamental)
    # A different key from the lead: partials that land on the lead's own
    # harmonics share its bins, and no mask over a spectrum can part those.
    guitar = _arrangement(rng, (415.0, 622.0, 831.0))
    bass = _arrangement(rng, (58.0, 87.0))
    left_gain, right_gain = _panned(rng, lead_position)
    left = left_gain * lead + 0.9 * guitar + bass
    right = right_gain * lead + 0.3 * guitar + bass
    if reverberant:
        # A vocal plate: the same source, spread across the image behind it,
        # which is what a similarity measure has to see past.
        tail = 0.25 * fftconvolve(lead, _room(rng, 400.0))[:FRAMES]
        left += tail
        right += 0.9 * np.roll(tail, 11)
    return Scene(
        name,
        np.stack([left, right]),
        lead,
        left_gain,
        {"arrangement": (guitar, 0.9), "bass": (bass, 1.0)},
    )


def _surround_scene() -> Scene:
    rng = np.random.default_rng(99)
    lead = _voice(rng, 220.0)
    guitar = _arrangement(rng, (330.0, 494.0))
    bass = _arrangement(rng, (73.0, 110.0))
    # What a mastering chain leaves of the centre channel in the front pair is
    # a filter, not a gain: delayed, shelved, different at every frequency.
    response = np.array([0.0, 0.0, 0.55, -0.22, 0.08, 0.03])
    leak = fftconvolve(lead, response)[:FRAMES]
    mixture = np.stack(
        [guitar + leak, bass + 0.8 * leak, lead, 0.4 * bass, 0.2 * guitar, 0.2 * guitar]
    )
    # Scored against the leak as it arrives, not against the dry centre: what
    # has to disappear from the front pair is the filtered signal.
    return Scene("surround-leak", mixture, leak, 1.0, {"front": (guitar, 1.0)})


SCENES: tuple[Callable[[], Scene], ...] = (
    lambda: _stereo_scene("centred-lead", 0.0, 330.0),
    # A male lead sits in the band the bass protection holds back, which is
    # the price of keeping the kick and the bass in the instrumental.
    lambda: _stereo_scene("low-centred-lead", 0.0, 196.0),
    lambda: _stereo_scene("off-centre-lead", 0.15, 330.0),
    lambda: _stereo_scene("reverberant-lead", 0.0, 330.0, reverberant=True),
    _surround_scene,
)


def _projection(signal: np.ndarray, part: np.ndarray) -> float:
    """How much of `part` is in `signal`, as the least-squares coefficient."""
    reference = part[BODY]
    energy = float(np.dot(reference, reference))
    return abs(float(np.dot(signal[BODY], reference) / energy)) if energy > 0 else 0.0


def _relative_db(signal: np.ndarray, part: np.ndarray, gain: float) -> float:
    """How far a part sits from the level it was mixed in at, in decibels."""
    ratio = _projection(signal, part) / max(abs(gain), 1e-12)
    return 20.0 * float(np.log10(max(ratio, 1e-9)))


def _measure_bands(mixture: np.ndarray, crossover_hz: float) -> float:
    """The band split has one thing to prove: that it adds back up."""
    token = CancellationToken()
    source = _audio(mixture)
    low = _audio(np.zeros_like(mixture))
    high = _audio(np.zeros_like(mixture))
    lowpass(source, low, crossover_hz, token)
    difference(high, source, low, token)
    residual = low.samples + high.samples - source.samples
    return float(np.sqrt(np.mean(residual**2)))


def measure(scene: Scene, crossover_hz: float) -> dict[str, float]:
    token = CancellationToken()
    scores: dict[str, float] = {"band_rmse": _measure_bands(scene.mixture, crossover_hz)}
    if scene.mixture.shape[0] >= 6:
        cleaned = _audio(np.zeros((2, FRAMES)))
        cancel_centre_from_front(_audio(scene.mixture), cleaned, (0, 1), 2, token)
        scores["centre_leak_db"] = _relative_db(cleaned.samples[0], scene.lead, scene.lead_gain)
        for name, (part, gain) in scene.kept.items():
            scores[f"{name}_kept_db"] = _relative_db(cleaned.samples[0], part, gain)
        return scores
    centre = _audio(np.zeros((1, FRAMES)))
    instrumental = _audio(np.zeros((2, FRAMES)))
    separate_centre(_audio(scene.mixture), centre, instrumental, token)
    scores["lead_removed_db"] = _relative_db(instrumental.samples[0], scene.lead, scene.lead_gain)
    scores["lead_kept_db"] = _relative_db(centre.samples[0], scene.lead, scene.lead_gain)
    for name, (part, gain) in scene.kept.items():
        scores[f"{name}_kept_db"] = _relative_db(instrumental.samples[0], part, gain)
    return scores


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crossover", type=float, nargs="+", default=[150.0])
    parser.add_argument("--save", type=Path)
    parser.add_argument("--compare", type=Path)
    arguments = parser.parse_args()

    baseline: dict[str, dict[str, float]] = {}
    if arguments.compare:
        baseline = json.loads(arguments.compare.read_text())

    results: dict[str, dict[str, float]] = {}
    for crossover in arguments.crossover:
        print(f"\n=== crossover={crossover:g} Hz ===")
        for build in SCENES:
            scene = build()
            key = f"{scene.name}|{crossover:g}"
            scores = measure(scene, crossover)
            results[key] = scores
            previous = baseline.get(key, {})
            cells = [
                f"{metric}={value:.4f} ({value - previous[metric]:+.4f})"
                if metric in previous
                else f"{metric}={value:.4f}"
                for metric, value in scores.items()
            ]
            print(f"  {scene.name:<20} " + "  ".join(cells))

    if arguments.save:
        arguments.save.write_text(json.dumps(results, indent=2, sort_keys=True))
        print(f"\nsaved {len(results)} measurements to {arguments.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
