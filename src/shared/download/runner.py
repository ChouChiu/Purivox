"""Run one search or one download off the GUI thread.

Both calls block on the network for as long as the site takes; `TaskRunner`
owns the thread, and this names which of the two answers a result is.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from shared.download.media import DownloadUnavailable, fetch, search
from shared.tasks import Operation, TaskRunner


class DownloadRunner(TaskRunner):
    """Own the thread behind one search or download at a time."""

    results = Signal(object)
    """The `tuple[Track, ...]` a search returned."""
    fetched = Signal(object)
    """The `FetchedTrack` a download produced."""

    def __init__(self, parent: QObject | None = None):
        # A site refusing a link, a bad query or a full disk is an outcome the
        # dialog reports, not a fault worth a traceback.
        super().__init__(parent, expected=(DownloadUnavailable, ValueError, OSError))
        self._outcome = self.results
        self.succeeded.connect(self._succeeded)

    def search(self, query: str, limit: int) -> bool:
        return self._begin(lambda _token, _progress: search(query, limit), self.results)

    def fetch(self, url: str, directory: Path) -> bool:
        return self._begin(
            lambda token, progress: fetch(url, directory, token, progress), self.fetched
        )

    def _begin(self, work: Operation, outcome: Signal) -> bool:
        """Start `work`, or report that the runner is already busy."""
        if self.running:
            return False
        self._outcome = outcome
        self.start(work)
        return True

    @Slot(object)
    def _succeeded(self, result: object) -> None:
        self._outcome.emit(result)
