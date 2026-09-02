from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from shared.audio.analysis import AudioStats


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    value: int
    message: str
    key: str = ""
    """The catalogue key `message` was translated from, for shells that translate later."""
    values: tuple[tuple[str, str], ...] = ()
    """The placeholder names and values `message` was filled with, in call order."""


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    outputs: tuple[Path, ...]
    audio_stats: tuple[AudioStats, ...] = ()


class ProcessingResultLike(Protocol):
    @property
    def outputs(self) -> tuple[Path, ...]: ...

    @property
    def audio_stats(self) -> tuple[AudioStats, ...]: ...


@dataclass(slots=True)
class CancellationToken:
    _event: Event = field(default_factory=Event)

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise ProcessingCancelled


class ProcessingCancelled(RuntimeError):
    pass


ProgressCallback = Callable[[ProgressEvent], None]
ProcessingOperation = Callable[[CancellationToken, ProgressCallback], ProcessingResultLike]
