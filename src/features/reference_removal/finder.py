from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from shared.audio import AUDIO_EXTENSIONS

_KEYWORDS = ("伴奏", "accompaniment", "instrumental", "inst", "karaoke", "off vocal", "minus one")
_OUTPUT_MARKERS = ("_vocals", "-vocals", "_backing", "-backing", "消音")
_EXTENSIONS = frozenset(AUDIO_EXTENSIONS)


@dataclass(frozen=True, slots=True)
class Match:
    path: Path | None = None
    score: float = 0.0

    @property
    def found(self) -> bool:
        return self.path is not None


def filename_similarity(first: str, second: str) -> float:
    return SequenceMatcher(None, first.casefold(), second.casefold()).ratio()


def find_best_match(stage: Path, minimum_score: float = 0.5) -> Match:
    recording = stage.expanduser().resolve()
    if not recording.is_file():
        return Match()
    best = Match()
    for candidate in sorted(recording.parent.iterdir()):
        resolved_candidate = candidate.expanduser().resolve()
        if (
            resolved_candidate == recording
            or not candidate.is_file()
            or candidate.suffix.casefold() not in _EXTENSIONS
        ):
            continue
        name = candidate.stem.casefold()
        if any(marker in name for marker in _OUTPUT_MARKERS):
            continue
        score = filename_similarity(recording.stem, name)
        if any(keyword in name for keyword in _KEYWORDS):
            score += 0.2
        if score > best.score:
            best = Match(resolved_candidate, score)
    return best if best.score > minimum_score else Match()
