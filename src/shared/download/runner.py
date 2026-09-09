"""Run one search or one download on a thread of its own.

Both calls block on the network for as long as the site takes, and the dialog
that starts them has to stay responsive enough to be cancelled.  `JobRunner`
cannot serve here — it lives in `app` and carries the processing contract — so
the thread lifecycle is repeated in the smaller shape these two calls need.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot

from shared.download.media import DownloadUnavailable, fetch, search
from shared.processing import (
    CancellationToken,
    ProcessingCancelled,
    ProgressCallback,
    ProgressEvent,
)

logger = logging.getLogger(__name__)

DownloadWork = Callable[[CancellationToken, ProgressCallback], object]


class _DownloadTask(QObject):
    """One piece of network work, run once on the thread it was moved to."""

    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()
    progress = Signal(int, str)

    def __init__(self, work: DownloadWork):
        super().__init__()
        self.work = work
        self.token = CancellationToken()

    def request_cancel(self) -> None:
        self.token.cancel()

    @Slot()
    def run(self) -> None:
        try:
            self.succeeded.emit(self.work(self.token, self._report))
        except ProcessingCancelled:
            logger.info("download cancelled")
            self.cancelled.emit()
        except (DownloadUnavailable, ValueError, OSError) as error:
            logger.warning("download failed: %s", error)
            self.failed.emit(str(error))
        finally:
            self.finished.emit()

    def _report(self, event: ProgressEvent) -> None:
        self.progress.emit(event.value, event.message)


class DownloadRunner(QObject):
    """Own the thread behind one search or download at a time."""

    results = Signal(object)
    """The `tuple[Track, ...]` a search returned."""
    fetched = Signal(object)
    """The `FetchedTrack` a download produced."""
    progress = Signal(int, str)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._task: _DownloadTask | None = None

    @property
    def running(self) -> bool:
        return self._task is not None

    def search(self, query: str, limit: int) -> bool:
        return self._start(
            lambda _token, _progress: search(query, limit),
            self.results,
        )

    def fetch(self, url: str, directory: Path) -> bool:
        return self._start(
            lambda token, progress: fetch(url, directory, token, progress),
            self.fetched,
        )

    def _start(self, work: DownloadWork, outcome: Signal) -> bool:
        """Start `work`, or report that the runner is already busy."""
        if self.running:
            return False
        thread = QThread(self)
        task = _DownloadTask(work)
        task.moveToThread(thread)
        thread.started.connect(task.run)
        task.succeeded.connect(outcome)
        task.progress.connect(self.progress)
        task.failed.connect(self.failed)
        task.cancelled.connect(self.cancelled)
        task.finished.connect(thread.quit)
        task.finished.connect(task.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.destroyed.connect(self._reset)
        self._task = task
        thread.start()
        return True

    def cancel(self) -> None:
        if self._task is not None:
            self._task.request_cancel()

    @Slot()
    def _reset(self) -> None:
        self._task = None
        self.finished.emit()
