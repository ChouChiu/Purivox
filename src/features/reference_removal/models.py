from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shared.jobs import validate_reference_settings


@dataclass(frozen=True, slots=True)
class ReferenceJob:
    song: Path
    accompaniment: Path
    output: Path
    strength: int = 75
    sigma: int = 3
    auto_align: bool = True
    language: str = "zh_cn"
    center_extraction: bool = False
    open_mic_focus: bool = False

    def __post_init__(self) -> None:
        validate_reference_settings(
            self.strength,
            self.sigma,
            center_extraction=self.center_extraction,
            open_mic_focus=self.open_mic_focus,
        )
