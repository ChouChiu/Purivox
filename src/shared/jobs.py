from __future__ import annotations

from enum import StrEnum
from pathlib import Path

SIGMA_CHOICES: tuple[int, ...] = (1, 3, 8, 16)
DEFAULT_SIGMA = 3
STRENGTH_MINIMUM = 0
STRENGTH_MAXIMUM = 100
STRENGTH_RANGE = range(STRENGTH_MINIMUM, STRENGTH_MAXIMUM + 1)
DEFAULT_STRENGTH = 75


def validate_reference_settings(strength: int, sigma: int) -> None:
    """Check the settings every reference-cancellation job shares.

    The job dataclasses, the CLI and the browser bridge all offer these
    options, and features must not import one another, so the accepted values
    are defined once here instead of three times.
    """
    if not STRENGTH_MINIMUM <= strength <= STRENGTH_MAXIMUM:
        raise ValueError(f"strength must be in [{STRENGTH_MINIMUM}, {STRENGTH_MAXIMUM}]")
    if sigma not in SIGMA_CHOICES:
        raise ValueError("sigma must be one of " + ", ".join(str(value) for value in SIGMA_CHOICES))


class OutputTracks(StrEnum):
    """Which stems one reference cancellation writes.

    The vocal is what the pipelines produce; the backing is the song source as
    the playback carried it, rendered from the source through the transfer the
    cancellation estimated, so it keeps the source's quality rather than the
    capture's and carries the level it actually had on stage.
    """

    VOCAL = "vocal"
    BACKING = "backing"
    BOTH = "both"


VOCAL_MARKER = "_vocals"
BACKING_MARKER = "_backing"


def backing_path(output: Path) -> Path:
    """Name the backing file beside the vocal one it is exported with."""
    stem = output.stem
    if stem.endswith(VOCAL_MARKER):
        stem = stem[: -len(VOCAL_MARKER)]
    return output.with_name(stem + BACKING_MARKER + output.suffix)


def planned_outputs(output: Path, tracks: OutputTracks) -> tuple[Path, ...]:
    """The files a job will write, in the order it writes them.

    `output` is whichever stem the user asked for, so a single-track export
    lands exactly where they named it; only "both" derives a second name.
    """
    if tracks is not OutputTracks.BOTH:
        return (output,)
    return (output, backing_path(output))


class PathConflict(StrEnum):
    """Why a job's files cannot be used together; the value is the error message."""

    STAGE_IS_SOURCE = "stage audio must not also be a source"
    OUTPUT_OVERWRITES_INPUT = "output path must not overwrite an input file"


def path_conflict(
    stage: Path, sources: tuple[Path, ...], output: Path, tracks: OutputTracks
) -> PathConflict | None:
    """Name what is wrong with a job that reads the recording as a source or writes over an input.

    The job dataclasses raise on it, and the GUI asks first so it can say which
    of the two it is rather than show the exception text.
    """
    resolved_stage = stage.expanduser().resolve()
    resolved_sources = {source.expanduser().resolve() for source in sources}
    if resolved_stage in resolved_sources:
        return PathConflict.STAGE_IS_SOURCE
    inputs = {resolved_stage, *resolved_sources}
    if any(path.expanduser().resolve() in inputs for path in planned_outputs(output, tracks)):
        return PathConflict.OUTPUT_OVERWRITES_INPUT
    return None


def validate_job_paths(
    stage: Path, sources: tuple[Path, ...], output: Path, tracks: OutputTracks
) -> None:
    if (conflict := path_conflict(stage, sources, output, tracks)) is not None:
        raise ValueError(conflict.value)
