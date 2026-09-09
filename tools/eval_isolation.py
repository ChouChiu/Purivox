"""Offline A/B measurement for the isolation pipeline's engine choice.

`eval_cancellation.py` measures the canceller.  This measures the pipeline built
on it: `run_isolation_job` matches a source against the recording and then picks
an engine by geometry, and this script shows what that choice costs or buys on
the same scene with both engines, so the choice can be re-checked after a change
to the matcher, the renderer or the rule itself.

    uv run --locked python tools/eval_isolation.py --save isolation-baseline.json
    uv run --locked python tools/eval_isolation.py --compare isolation-baseline.json

Synthetic scenes only find regressions.  They do not claim real-music quality,
and the tempo-shift scenes are the hardest case for the matcher on purpose.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import eval_cancellation as ev

from features.reference_removal import (
    IsolationJob,
    ReferenceJob,
    run_isolation_job,
    run_reference_job,
)
from shared.processing import CancellationToken

SR = ev.SAMPLE_RATE
STRENGTH = 75
SIGMA = 3
WORK = Path("/tmp/purivox-eval-isolation")


@dataclass(frozen=True, slots=True)
class Scene:
    """One stage recording, the sources to cancel, and what must survive.

    `song` is the window the metrics are scored over: the rest of the recording
    is material no source explains, and the measurement there is how untouched
    it stays.
    """

    name: str
    stage: np.ndarray
    reference: np.ndarray
    live: np.ndarray
    accompaniment: np.ndarray
    song: slice
    seconds: float


def _percussion(rng: np.random.Generator, length: int, bpm: float = 120.0) -> np.ndarray:
    """A click train: the transient structure a flux matcher keys on."""
    beat = SR * 60.0 / bpm
    out = np.zeros(length)
    for index in range(int(length / beat)):
        at = int(index * beat) + rng.integers(0, 40)
        hits = rng.normal(0.0, 1.0, 700) * np.exp(-np.arange(700) / 90.0)
        end = min(length, at + hits.size)
        out[at:end] += hits[: end - at]
    return out


def _music(rng: np.random.Generator, length: int, tones: tuple[float, ...]) -> np.ndarray:
    return ev._music(rng, length, tones) + 0.6 * _percussion(rng, length)


def _talk(rng: np.random.Generator, length: int) -> np.ndarray:
    return np.stack(
        [
            0.08 * rng.normal(0.0, 1.0, length) + 0.05 * ev._music(rng, length, (170.0,)),
            0.075 * rng.normal(0.0, 1.0, length) + 0.045 * ev._music(rng, length, (185.0,)),
        ]
    )


def _song(seconds: float, offset: float = 0.0, rate: float = 0.0, tail: float = 0.0) -> Scene:
    """A song at `offset` seconds into a recording, optionally followed by talk.

    `rate` is the capture's clock error: the stage plays the source 1+rate times
    faster, which is what makes a matcher misplace it and what the whole-file
    path's own tempo search exists for.
    """
    rng = np.random.default_rng(int(seconds) + int(offset * 10) + int(rate * 1000))
    length = int(SR * seconds)
    lead = int(SR * offset)
    trailing = int(SR * tail)
    reference = np.stack(
        [_music(rng, length, (110.0, 220.0)), _music(rng, length, (110.0, 330.0))]
    )
    reference *= 0.25 / np.max(np.abs(reference))
    index = np.arange(length) / (1.0 + rate)
    accompaniment = np.stack(
        [0.9 * np.interp(index, np.arange(length), channel) for channel in reference]
    )
    center = _music(rng, length, (431.0, 862.0))
    live = np.stack([0.30 * center, 0.28 * center])
    song = live + accompaniment

    trng = np.random.default_rng(4242)
    parts, live_parts, acc_parts = [], [], []
    if lead:
        talk = _talk(trng, lead)
        parts.append(talk)
        live_parts.append(np.zeros((2, lead)))
        acc_parts.append(talk)
    parts.append(song)
    live_parts.append(live)
    acc_parts.append(accompaniment)
    if trailing:
        talk = _talk(trng, trailing)
        parts.append(talk)
        live_parts.append(np.zeros((2, trailing)))
        acc_parts.append(talk)
    name = f"song_{seconds:g}s"
    if offset:
        name += f"_at_{offset:g}s"
    if rate:
        name += f"_drift_{rate * 100:g}pct"
    if tail:
        name += f"_tail_{tail:g}s"
    return Scene(
        name,
        np.concatenate(parts, axis=1),
        reference,
        np.concatenate(live_parts, axis=1),
        np.concatenate(acc_parts, axis=1),
        slice(lead, lead + length),
        seconds,
    )


SCENES: tuple[Callable[[], Scene], ...] = (
    lambda: _song(60.0),
    lambda: _song(60.0, offset=3.0),
    lambda: _song(60.0, offset=30.0),
    lambda: _song(60.0, tail=60.0),
    lambda: _song(60.0, rate=0.004),
    lambda: _song(60.0, rate=0.01),
)


def _depth(output: np.ndarray, scene: Scene) -> float:
    window = scene.song
    scale = float(
        np.dot(output[:, window].ravel(), scene.live[:, window].ravel())
        / max(np.dot(scene.live[:, window].ravel(), scene.live[:, window].ravel()), 1e-20)
    )
    residual = output[:, window] - scale * scene.live[:, window]
    return 10.0 * np.log10(
        float(np.mean(scene.accompaniment[:, window] ** 2))
        / max(float(np.mean(residual**2)), 1e-20)
    )


def _fidelity(output: np.ndarray, scene: Scene) -> float:
    return float(
        np.corrcoef(output[:, scene.song].ravel(), scene.live[:, scene.song].ravel())[0, 1]
    )


def _untouched(output: np.ndarray, scene: Scene) -> float:
    """How far the material no source explains moved, against its own level."""
    outside = np.ones(scene.stage.shape[1], dtype=bool)
    outside[scene.song] = False
    if not outside.any():
        return 0.0
    rmse = float(np.sqrt(np.mean((output[:, outside] - scene.stage[:, outside]) ** 2)))
    level = float(np.sqrt(np.mean(scene.stage[:, outside] ** 2)))
    return 20.0 * np.log10(max(rmse, 1e-20) / max(level, 1e-20))


def measure(scene: Scene, token: CancellationToken) -> dict[str, float]:
    """Run both engines over one scene and report the depth each reaches."""
    WORK.mkdir(parents=True, exist_ok=True)
    for label, data in (("stage", scene.stage), ("source", scene.reference)):
        sf.write(
            str(WORK / f"{scene.name}-{label}.wav"),
            data.T.astype(np.float32),
            SR,
            format="WAV",
            subtype="FLOAT",
        )
    stage = WORK / f"{scene.name}-stage.wav"
    source = WORK / f"{scene.name}-source.wav"

    started = time.perf_counter()
    run_reference_job(
        ReferenceJob(stage, source, WORK / f"{scene.name}-whole.vocal.wav", STRENGTH, SIGMA, True),
        token,
    )
    whole_seconds = time.perf_counter() - started
    started = time.perf_counter()
    result = run_isolation_job(
        IsolationJob(
            stage,
            (source,),
            WORK / f"{scene.name}-merged.vocal.wav",
            STRENGTH,
            SIGMA,
            auto_align=True,
        ),
        None,
        token,
    )
    merged_seconds = time.perf_counter() - started

    whole, _ = sf.read(
        str(WORK / f"{scene.name}-whole.vocal.wav"), dtype="float32", always_2d=True
    )
    merged, _ = sf.read(
        str(WORK / f"{scene.name}-merged.vocal.wav"), dtype="float32", always_2d=True
    )
    return {
        "whole_depth_db": _depth(whole.T, scene),
        "merged_depth_db": _depth(merged.T, scene),
        "depth_delta_db": _depth(merged.T, scene) - _depth(whole.T, scene),
        "merged_fidelity": _fidelity(merged.T, scene),
        "merged_outside_db": _untouched(merged.T, scene),
        "matched_clips": float(len(result.analysis.matched_clips)),
        "whole_seconds": whole_seconds,
        "merged_seconds": merged_seconds,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", type=Path)
    parser.add_argument("--compare", type=Path)
    arguments = parser.parse_args()

    baseline: dict[str, dict[str, float]] = {}
    if arguments.compare:
        baseline = json.loads(arguments.compare.read_text())

    results: dict[str, dict[str, float]] = {}
    worst = 0.0
    for build in SCENES:
        scene = build()
        scores = measure(scene, CancellationToken())
        results[scene.name] = scores
        worst = min(worst, scores["depth_delta_db"])
        previous = baseline.get(scene.name, {})
        cells = []
        for metric, value in scores.items():
            if metric in previous:
                cells.append(f"{metric}={value:.4f} ({value - previous[metric]:+.4f})")
            else:
                cells.append(f"{metric}={value:.4f}")
        print(f"  {scene.name:<34} " + "  ".join(cells))

    print(f"\nworst depth delta against the whole-file engine: {worst:+.3f} dB")
    if worst < -0.05:
        print("the merged pipeline is losing cancellation depth somewhere")
    if arguments.save:
        arguments.save.write_text(json.dumps(results, indent=2, sort_keys=True))
        print(f"saved {len(results)} measurements to {arguments.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
