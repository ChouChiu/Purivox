"""What a reference job costs, phase by phase.

The harness next door (`eval_cancellation.py`) says whether a DSP change sounds
the same; this one says what it costs.  It runs the real job through
`run_reference_job` and times each phase from the progress events that job
already emits, so no pipeline code has to carry a stopwatch.  Peak RSS is
reported from the same run, because a change that buys wall-clock time with
memory is not a speed-up here.

    uv run --locked python tools/bench_pipeline.py --save baseline.json
    uv run --locked python tools/bench_pipeline.py --compare baseline.json

Wall-clock numbers are machine-specific, so compare only against a baseline
taken on the same machine with the same settings.
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from features.reference_removal.dsp import algorithms
from features.reference_removal.models import ReferenceJob
from features.reference_removal.processing import run_reference_job
from shared.processing import CancellationToken, ProgressEvent

SAMPLE_RATE = 44_100
DEFAULT_SECONDS = 180


def _scene(seconds: int, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """A deterministic stereo pair: steady accompaniment plus a gated live line."""
    frames = seconds * SAMPLE_RATE
    time = np.arange(frames, dtype=np.float64) / SAMPLE_RATE
    random = np.random.default_rng(seed)
    accompaniment = (
        0.30 * np.sin(2 * np.pi * 110.0 * time)
        + 0.20 * np.sin(2 * np.pi * 220.0 * time)
        + 0.05 * random.normal(size=frames)
    ).astype(np.float32)
    vocal = (
        0.25 * np.sin(2 * np.pi * 440.0 * time) * (0.5 + 0.5 * np.sin(2 * np.pi * 3.0 * time))
    ).astype(np.float32)
    song = np.stack([accompaniment + vocal, 0.97 * accompaniment + 0.95 * vocal])
    reference = np.stack([accompaniment, 0.95 * accompaniment])
    return song, reference


class PhaseClock:
    """Attribute the gap between consecutive progress events to the earlier key.

    A key that repeats - the two exports both report `analyzing_output` - sums
    into one row, which is what a reader wants: the phase cost, not the call.
    """

    def __init__(self) -> None:
        self._last_key: str | None = None
        self._last_at = time.perf_counter()
        self.phases: dict[str, float] = {}
        self.order: list[str] = []

    def __call__(self, event: ProgressEvent) -> None:
        now = time.perf_counter()
        if self._last_key is not None:
            elapsed = now - self._last_at
            self.phases[self._last_key] = self.phases.get(self._last_key, 0.0) + elapsed
        self._last_key = event.key or f"progress_{event.value}"
        if self._last_key not in self.order:
            self.order.append(self._last_key)
        self._last_at = now


def measure(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.workers is not None:
        # The layout derives its block size from this cap, so the two move
        # together; report both rather than hide the coupling.
        algorithms._MAX_PROCESSING_WORKERS = arguments.workers
    with tempfile.TemporaryDirectory(prefix="purivox-bench-") as name:
        work = Path(name)
        if arguments.input is not None:
            song_path = arguments.input
            reference_path = arguments.reference
            frames = sf.info(song_path).frames
        else:
            song, reference = _scene(arguments.seconds, arguments.seed)
            frames = song.shape[1]
            song_path, reference_path = work / "song.wav", work / "reference.wav"
            sf.write(song_path, song.T, SAMPLE_RATE, subtype="PCM_24")
            sf.write(reference_path, reference.T, SAMPLE_RATE, subtype="PCM_24")
            del song, reference
        job = ReferenceJob(
            stage=song_path,
            source=reference_path,
            output=work / "result.wav",
            strength=arguments.strength,
            sigma=arguments.sigma,
            auto_align=not arguments.no_align,
        )
        clock = PhaseClock()
        started = time.perf_counter()
        run_reference_job(job, CancellationToken(), clock)
        total = time.perf_counter() - started
        peak_rss_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    block, workers = algorithms._processing_layout(SAMPLE_RATE, arguments.sigma, frames)
    return {
        "seconds": round(frames / SAMPLE_RATE, 3),
        "sample_rate": SAMPLE_RATE,
        "sigma": arguments.sigma,
        "strength": arguments.strength,
        "align": not arguments.no_align,
        "workers": workers,
        "block_seconds": round(block / SAMPLE_RATE, 3),
        "phases": {key: round(clock.phases[key], 4) for key in clock.order if key in clock.phases},
        "total_seconds": round(total, 4),
        "peak_rss_mib": round(peak_rss_mib, 1),
    }


def report(record: dict[str, object], baseline: dict[str, object] | None) -> None:
    print(
        f"scene: {record['seconds']:g} s at {record['sample_rate']} Hz, "
        f"sigma={record['sigma']}, strength={record['strength']}, align={record['align']}"
    )
    print(f"layout: block={record['block_seconds']}s, workers={record['workers']}")
    phases: dict[str, float] = record["phases"]  # type: ignore[assignment]
    total = float(record["total_seconds"])
    previous: dict[str, float] = baseline.get("phases", {}) if baseline else {}  # type: ignore[assignment]
    print(f"  {'phase':<20}{'seconds':>9}{'share':>8}   baseline")
    for key, value in phases.items():
        delta = ""
        if key in previous:
            delta = f"{float(previous[key]):8.3f} ({value - float(previous[key]):+.3f})"
        print(f"  {key:<20}{value:9.3f}{100.0 * value / total:7.1f}%   {delta}")
    print(f"  {'TOTAL':<20}{total:9.3f}{100.0:7.1f}%")
    rss = float(record["peak_rss_mib"])
    rss_note = ""
    if baseline and "peak_rss_mib" in baseline:
        old_rss = float(baseline["peak_rss_mib"])
        rss_note = f"  (baseline {old_rss:.1f}, {rss - old_rss:+.1f})"
    print(f"  peak RSS: {rss:.1f} MiB{rss_note}")
    if baseline and "total_seconds" in baseline:
        old_total = float(baseline["total_seconds"])
        change = 100.0 * (total - old_total) / old_total
        print(f"  total vs baseline: {old_total:.3f}s -> {total:.3f}s ({change:+.1f}%)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--seconds", type=int, default=DEFAULT_SECONDS, help="synthetic scene length"
    )
    parser.add_argument("--seed", type=int, default=0, help="synthetic scene seed")
    parser.add_argument("--sigma", type=int, default=3)
    parser.add_argument(
        "--strength", type=int, default=75, help="percent, as ReferenceJob takes it"
    )
    parser.add_argument("--workers", type=int, default=None, help="override the DSP worker cap")
    parser.add_argument("--no-align", action="store_true", help="skip the alignment phase")
    parser.add_argument(
        "--input", type=Path, default=None, help="measure this file instead of a scene"
    )
    parser.add_argument("--reference", type=Path, default=None, help="accompaniment for --input")
    parser.add_argument("--save", type=Path, default=None)
    parser.add_argument("--compare", type=Path, default=None)
    arguments = parser.parse_args()

    if (arguments.input is None) != (arguments.reference is None):
        parser.error("--input and --reference are given together")

    baseline = json.loads(arguments.compare.read_text()) if arguments.compare else None
    record = measure(arguments)
    report(record, baseline)
    if arguments.save:
        arguments.save.write_text(json.dumps(record, indent=2, sort_keys=True))
        print(f"saved to {arguments.save}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
