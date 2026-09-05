from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shared.jobs import OutputTracks, validate_reference_settings


@dataclass(frozen=True, slots=True)
class ReferenceJob:
    song: Path
    accompaniment: Path
    output: Path
    strength: int = 75
    sigma: int = 3
    auto_align: bool = True
    tracks: OutputTracks = OutputTracks.VOCAL

    def __post_init__(self) -> None:
        validate_reference_settings(self.strength, self.sigma)
