from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from shared.audio import AudioStats

# The band the bass and the kick drum live under, and the one the mono path
# splits its presence band at.  Atome exposes only the first of these, so the
# second stays a constant rather than becoming a knob nobody asked for.
DEFAULT_CROSSOVER_HZ = 150.0
PRESENCE_HZ = 4000.0
CROSSOVER_RANGE = (20.0, 20_000.0)


class StemKind(StrEnum):
    """One stem, named by the marker its file carries.

    The value is both the file-name marker and the suffix of the translation
    key describing it, so a stem is named once.  Markers stay English in every
    locale: a file name that changed with the interface language would rename
    the same stem on the next run.
    """

    CENTER = "center"
    INSTRUMENTAL = "instrumental"
    SIDE = "side"
    MID = "mid"
    LOW = "low"
    MID_BAND = "mid_band"
    HIGH = "high"
    SURROUND = "surround"
    LFE = "lfe"
    FRONT = "front"
    FRONT_NO_CENTER = "front_no_center"
    DOWNMIX = "downmix"


class StemLayout(StrEnum):
    """Which path the channel count of the input picked."""

    SURROUND = "surround"
    STEREO = "stereo"
    MONO = "mono"


_LAYOUT_STEMS: dict[StemLayout, tuple[StemKind, ...]] = {
    StemLayout.SURROUND: (
        StemKind.SURROUND,
        StemKind.CENTER,
        StemKind.LFE,
        StemKind.FRONT,
        StemKind.FRONT_NO_CENTER,
        StemKind.DOWNMIX,
        StemKind.LOW,
        StemKind.HIGH,
    ),
    StemLayout.STEREO: (
        StemKind.CENTER,
        StemKind.INSTRUMENTAL,
        StemKind.SIDE,
        StemKind.MID,
        StemKind.LOW,
        StemKind.HIGH,
    ),
    StemLayout.MONO: (StemKind.LOW, StemKind.MID_BAND, StemKind.HIGH),
}

# Six channels is where a discrete surround master starts.  Anything between
# three and five is a layout this pipeline has no decode matrix for, so it is
# folded to its first two channels and split as stereo rather than guessed at.
SURROUND_CHANNELS = 6


def layout_for(channels: int) -> StemLayout:
    if channels >= SURROUND_CHANNELS:
        return StemLayout.SURROUND
    return StemLayout.MONO if channels == 1 else StemLayout.STEREO


def layout_stems(layout: StemLayout) -> tuple[StemKind, ...]:
    return _LAYOUT_STEMS[layout]


def stem_path(source: Path, output_dir: Path, kind: StemKind) -> Path:
    return output_dir / f"{source.stem}_{kind.value}.wav"


@dataclass(frozen=True, slots=True)
class StemSplitJob:
    """One audio file, split into the stems its channel layout allows.

    Unlike an isolation job this one cannot be asked to overwrite its own
    input: every stem it writes carries a marker the input does not, so there
    is no path they can collide on and no check here for one.
    """

    source: Path
    output_dir: Path
    crossover_hz: float = DEFAULT_CROSSOVER_HZ

    def __post_init__(self) -> None:
        low, high = CROSSOVER_RANGE
        if not low <= self.crossover_hz <= high:
            raise ValueError(f"crossover must be in [{low:g}, {high:g}] Hz")


@dataclass(frozen=True, slots=True)
class StemSplitResult:
    layout: StemLayout
    kinds: tuple[StemKind, ...] = ()
    outputs: tuple[Path, ...] = ()
    audio_stats: tuple[AudioStats, ...] = ()
