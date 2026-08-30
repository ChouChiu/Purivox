"""Offline A/B measurement for the reference-cancellation core.

The DSP in this project is judged by measurement, not by argument: every change
in `docs/reference-removal.md` carries the cancellation depth and live-source
fidelity it was accepted or rejected on.  This script synthesises that set of
scenes and prints the two numbers for each, so a change can be compared against
a baseline captured before it.

    uv run --locked python tools/eval_cancellation.py --save baseline.json
    uv run --locked python tools/eval_cancellation.py --compare baseline.json

Synthetic metrics only find regressions.  They do not claim real-music quality.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve, istft, stft

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from features.reference_removal.dsp import align_audio, process_audio

SAMPLE_RATE = 16_000


@dataclass(frozen=True, slots=True)
class Scene:
    """One synthetic measurement case.

    `live` is the content that must survive, `accompaniment` the content that
    must go.  `kind` selects which metrics make sense: an unrelated reference
    has no accompaniment to cancel, so it is scored on how untouched it stays.
    """

    name: str
    mixture: np.ndarray
    reference: np.ndarray
    live: np.ndarray
    accompaniment: np.ndarray
    kind: str = "cancel"
    extra: np.ndarray | None = None
    align: bool = False


def _music(rng: np.random.Generator, length: int, seed_tones: tuple[float, ...]) -> np.ndarray:
    """A broadband signal with tonal structure, closer to music than white noise."""
    time = np.arange(length) / SAMPLE_RATE
    signal = np.zeros(length)
    for frequency in seed_tones:
        signal += (0.6 / len(seed_tones)) * np.sin(
            2 * np.pi * frequency * time + rng.uniform(0, 2 * np.pi)
        )
    noise = np.convolve(rng.normal(0.0, 1.0, length), np.ones(4) / 4, mode="same")
    return 0.7 * signal + 0.25 * noise


def _room_response(rng: np.random.Generator, rt60_ms: float) -> np.ndarray:
    """Exponentially decaying noise burst: the standard synthetic room response."""
    length = max(int(SAMPLE_RATE * rt60_ms / 1000.0), 1)
    decay = np.exp(-6.9078 * np.arange(length) / max(length - 1, 1))
    response = rng.normal(0.0, 1.0, length) * decay
    response[0] += 1.0
    return response / np.sqrt(np.sum(response**2))


def _room_scene(rt60_ms: float, seconds: float = 6.0) -> Scene:
    rng = np.random.default_rng(int(rt60_ms) + 1000)
    length = int(SAMPLE_RATE * seconds)
    reference = np.stack(
        [
            _music(rng, length, (110.0, 220.0, 330.0, 660.0)),
            _music(rng, length, (98.0, 196.0, 294.0, 588.0)),
        ]
    )
    reference *= 0.25 / np.max(np.abs(reference))
    responses = [[_room_response(rng, rt60_ms) for _ in range(2)] for _ in range(2)]
    gains = ((0.85, 0.30), (-0.22, 0.78))
    accompaniment = np.stack(
        [
            sum(
                gains[row][column] * fftconvolve(reference[column], responses[row][column])[:length]
                for column in range(2)
            )
            for row in range(2)
        ]
    )
    center = _music(rng, length, (431.0, 862.0, 1293.0))
    live = np.stack([0.30 * center, 0.28 * center])
    return Scene(
        name=f"room_{int(rt60_ms)}ms",
        mixture=live + accompaniment,
        reference=reference,
        live=live,
        accompaniment=accompaniment,
    )


def _wide_backing_quiet_vocal() -> Scene:
    rng = np.random.default_rng(126)
    length = SAMPLE_RATE * 6
    time = np.arange(length) / SAMPLE_RATE
    reference = np.stack(
        [
            _music(rng, length, (123.0, 246.0, 492.0)),
            _music(rng, length, (181.0, 362.0, 724.0)),
        ]
    )
    reference *= 0.22 / np.max(np.abs(reference))
    accompaniment = np.stack([0.9 * reference[0], 0.88 * reference[1]])
    vocal = 0.03 * np.sin(2 * np.pi * 431 * time) + 0.012 * np.sin(2 * np.pi * 862 * time)
    live = np.stack([vocal, 0.85 * vocal])
    return Scene(
        name="quiet_vocal_wide_backing",
        mixture=live + accompaniment,
        reference=reference,
        live=live,
        accompaniment=accompaniment,
    )


def _drift_scene(rate: float) -> Scene:
    rng = np.random.default_rng(int(rate * 10_000))
    length = SAMPLE_RATE * 6
    reference = np.stack([_music(rng, length, (110.0, 220.0)), _music(rng, length, (110.0, 330.0))])
    reference *= 0.25 / np.max(np.abs(reference))
    index = np.arange(length) / (1.0 + rate)
    accompaniment = np.stack(
        [0.9 * np.interp(index, np.arange(length), channel) for channel in reference]
    )
    center = _music(rng, length, (431.0, 862.0))
    live = np.stack([0.3 * center, 0.28 * center])
    return Scene(
        name=f"drift_{rate * 100:.1f}pct",
        mixture=live + accompaniment,
        reference=reference,
        live=live,
        accompaniment=accompaniment,
        align=True,
    )


def _unrelated_reference() -> Scene:
    # Broadband noise on both sides, not tones: a tonal pair occupies too few
    # bins for a spurious fit to show up, and spurious fitting is the whole
    # point of this scene.
    rng = np.random.default_rng(131)
    length = SAMPLE_RATE * 4
    mixture = rng.normal(0.0, 0.1, (2, length))
    unrelated = rng.normal(0.0, 0.1, (2, length))
    return Scene(
        name="unrelated_reference",
        mixture=mixture,
        reference=unrelated,
        live=mixture,
        accompaniment=np.zeros_like(mixture),
        kind="bypass",
    )


def _reference_only_word() -> Scene:
    length = SAMPLE_RATE * 4
    time = np.arange(length) / SAMPLE_RATE
    changed = (time >= 1.5).astype(float)
    backing = 0.25 * np.sin(2 * np.pi * 125 * time) + 0.12 * np.sin(2 * np.pi * 250 * time)
    live_word = changed * 0.28 * np.sin(2 * np.pi * 437 * time)
    old_word = changed * 0.22 * np.sin(2 * np.pi * 703 * time)
    accompaniment = np.stack([backing, 0.95 * backing])
    live = np.stack([live_word, 0.9 * live_word])
    return Scene(
        name="reference_only_word",
        mixture=live + accompaniment,
        reference=np.stack([backing + old_word, 0.92 * backing + old_word]),
        live=live,
        accompaniment=accompaniment,
        kind="injection",
        extra=np.stack([old_word, old_word]),
    )


def _phase_decorrelated_stage() -> Scene:
    """The failure mode the incoherent power path exists for.

    A capture path (PA, room, broadcast limiter) can keep the magnitudes
    correlated with the reference while destroying the phase relationship, so
    the complex transfer has nothing to subtract even though the accompaniment
    is plainly audible.  The power-domain regression recovers that content, and
    this scene is the only synthetic guard for it: with the incoherent path
    disabled the depth collapses toward zero while the other scenes barely
    move.
    """
    rng = np.random.default_rng(4242)
    length = SAMPLE_RATE * 10
    time = np.arange(length) / SAMPLE_RATE
    reference = np.stack(
        [
            _music(rng, length, (110.0, 220.0, 330.0, 660.0)),
            _music(rng, length, (98.0, 196.0, 294.0, 588.0)),
        ]
    )
    reference *= 0.25 / np.max(np.abs(reference))
    # Strong musical dynamics: the power envelope is what the regression reads.
    beat = 0.5 + 0.5 * np.sin(2 * np.pi * 2.5 * time) * np.sin(2 * np.pi * 0.8 * time)
    envelope = 0.05 + 0.95 * beat**2
    reference *= envelope[None, :]

    def decorrelate(channel: np.ndarray) -> np.ndarray:
        _frequencies, _frames, spectrum = stft(
            channel, fs=SAMPLE_RATE, nperseg=1024, noverlap=768
        )
        phases = np.cumsum(rng.normal(0.0, 0.18, spectrum.shape), axis=1)
        transformed = np.abs(spectrum) * np.exp(1j * phases)
        _time, reconstructed = istft(
            transformed, fs=SAMPLE_RATE, nperseg=1024, noverlap=768
        )
        return reconstructed[:length]

    accompaniment = np.stack([decorrelate(reference[0]), decorrelate(reference[1])])
    accompaniment *= 4.0
    live = np.stack(
        [
            0.04 * np.sin(2 * np.pi * 431 * time) + 0.02 * np.sin(2 * np.pi * 862 * time),
            0.036 * np.sin(2 * np.pi * 431 * time) + 0.018 * np.sin(2 * np.pi * 862 * time),
        ]
    )
    return Scene(
        name="phase_decorrelated_stage",
        mixture=live + accompaniment,
        reference=reference,
        live=live,
        accompaniment=accompaniment,
    )


def _phase_correlated_stereo() -> Scene:
    rng = np.random.default_rng(311)
    length = SAMPLE_RATE * 5
    left = np.convolve(rng.normal(0.0, 0.25, length), np.ones(5) / 5, mode="same")
    delay = 7
    right = 0.9 * np.pad(left[:-delay], (delay, 0)) + rng.normal(0.0, 0.02, length)
    reference = np.stack([left, right])
    accompaniment = np.stack(
        [0.85 * left + 0.31 * right, -0.22 * left + 0.78 * right],
    )
    live_source = np.convolve(rng.normal(0.0, 0.08, length), np.ones(3) / 3, mode="same")
    live = np.stack([live_source, 0.95 * live_source])
    return Scene(
        name="phase_correlated_stereo",
        mixture=live + accompaniment,
        reference=reference,
        live=live,
        accompaniment=accompaniment,
    )


SCENES: tuple[Callable[[], Scene], ...] = (
    lambda: _room_scene(25.0),
    lambda: _room_scene(60.0),
    lambda: _room_scene(250.0),
    lambda: _room_scene(500.0),
    lambda: _room_scene(1000.0),
    lambda: _room_scene(2000.0),
    _wide_backing_quiet_vocal,
    lambda: _drift_scene(0.004),
    lambda: _drift_scene(0.01),
    _unrelated_reference,
    _reference_only_word,
    _phase_correlated_stereo,
    _phase_decorrelated_stage,
)


def _correlation(first: np.ndarray, second: np.ndarray) -> float:
    return float(np.corrcoef(first.ravel(), second.ravel())[0, 1])


def _projection(output: np.ndarray, target: np.ndarray) -> float:
    return float(np.dot(output.ravel(), target.ravel()) / np.dot(target.ravel(), target.ravel()))


def measure(scene: Scene, strength: float, sigma: int) -> dict[str, float]:
    """Score one scene.  Edges are trimmed: STFT boundaries are not the subject."""
    reference = scene.reference.astype(np.float32)
    if scene.align:
        # The drift scenes measure what survives alignment, which is what the
        # real pipeline hands to the canceller.
        reference = align_audio(scene.mixture.astype(np.float32), reference, SAMPLE_RATE)
    output = process_audio(
        scene.mixture.astype(np.float32),
        reference,
        SAMPLE_RATE,
        strength,
        sigma,
    )
    body = slice(SAMPLE_RATE // 2, scene.mixture.shape[1] - SAMPLE_RATE // 2)
    # process_audio caps the output at -1 dBFS, which would otherwise show up as
    # a fidelity loss that has nothing to do with cancellation.
    scale = _projection(output[:, body], scene.live[:, body]) if scene.kind != "bypass" else 1.0
    if scene.kind == "bypass":
        return {
            "preserved": _correlation(output[:, body], scene.mixture[:, body]),
            "rmse": float(np.sqrt(np.mean((output[:, body] - scene.mixture[:, body]) ** 2))),
        }
    residual = output[:, body] - scale * scene.live[:, body]
    depth = 10.0 * np.log10(
        float(np.mean(scene.accompaniment[:, body] ** 2)) / max(float(np.mean(residual**2)), 1e-20)
    )
    result = {
        "depth_db": float(depth),
        "fidelity": _correlation(output[:, body], scene.live[:, body]),
        "live_gain": scale,
    }
    if scene.extra is not None:
        result["injection"] = abs(_projection(output[:, body], scene.extra[:, body]))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strength", type=float, nargs="+", default=[1.0])
    parser.add_argument("--sigma", type=int, nargs="+", default=[3, 8])
    parser.add_argument("--save", type=Path)
    parser.add_argument("--compare", type=Path)
    arguments = parser.parse_args()

    baseline: dict[str, dict[str, float]] = {}
    if arguments.compare:
        baseline = json.loads(arguments.compare.read_text())

    results: dict[str, dict[str, float]] = {}
    for strength in arguments.strength:
        for sigma in arguments.sigma:
            print(f"\n=== strength={strength:g} sigma={sigma} ===")
            for build in SCENES:
                scene = build()
                key = f"{scene.name}|{strength:g}|{sigma}"
                scores = measure(scene, strength, sigma)
                results[key] = scores
                previous = baseline.get(key, {})
                cells = []
                for metric, value in scores.items():
                    if metric in previous:
                        delta = value - previous[metric]
                        cells.append(f"{metric}={value:.4f} ({delta:+.4f})")
                    else:
                        cells.append(f"{metric}={value:.4f}")
                print(f"  {scene.name:<26} " + "  ".join(cells))

    if arguments.save:
        arguments.save.write_text(json.dumps(results, indent=2, sort_keys=True))
        print(f"\nsaved {len(results)} measurements to {arguments.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
