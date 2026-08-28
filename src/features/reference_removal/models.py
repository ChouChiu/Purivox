from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
    taps: int = 2

    def __post_init__(self) -> None:
        if not 0 <= self.strength <= 100:
            raise ValueError("strength must be in [0, 100]")
        if self.sigma not in {1, 3, 8, 16}:
            raise ValueError("sigma must be one of 1, 3, 8, 16")
        if self.taps not in {1, 2, 3}:
            raise ValueError("taps must be one of 1, 2, 3")
        if self.open_mic_focus and not self.center_extraction:
            raise ValueError("open-mic focus requires center extraction")
