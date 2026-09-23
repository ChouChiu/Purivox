"""Run one cancellable operation on a thread of its own.

A processing job and a download both block for as long as their work takes,
and the window that starts them has to stay responsive enough to cancel them.
The thread lifecycle is the same for both, so it lives here once.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

from shared.processing import (
    CancellationToken,
    ProcessingCancelled,
    ProgressCallback,
    ProgressEvent,
)

logger = logging.getLogger(__name__)

Operation = Callable[[CancellationToken, ProgressCallback], object]


class _Task(QObject):
    """One operation, run once on the thread it was moved to."""

    progress = Signal(int, str)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(self, operation: Operation, expected: tuple[type[Exception], ...]):
        super().__init__()
        self.operation = operation
        self.expected = expected
        self.token = CancellationToken()

    @Slot()
    def run(self) -> None:
        try:
            result = self.operation(self.token, self._report)
        except ProcessingCancelled:
            logger.info("task cancelled")
            self.cancelled.emit()
        except self.expected as error:
            logger.warning("task failed: %s", error)
            self.failed.emit(str(error))
        except Exception as error:
            logger.exception("task failed: %s", error)
            self.failed.emit(str(error))
        else:
            self.succeeded.emit(result)
        finally:
            self.finished.emit()

    def _report(self, event: ProgressEvent) -> None:
        self.progress.emit(event.value, event.message)


class TaskRunner(QObject):
    """Own the `QThread` behind one operation at a time.

    `expected` names the failures the operation reports as an outcome - a site
    refusing a download - which are logged without a traceback; anything else
    is a fault and keeps one.
    """

    progress = Signal(int, str)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(
        self,
        parent: QObject | None = None,
        expected: tuple[type[Exception], ...] = (),
    ):
        super().__init__(parent)
        self._expected = expected
        # The thread's Python wrapper is held until the thread is destroyed:
        # without it, about one start in ten crashed inside the thread.
        self._thread: QThread | None = None
        self._task: _Task | None = None

    @property
    def running(self) -> bool:
        return self._task is not None

    def start(self, operation: Operation) -> None:
        if self.running:
            raise RuntimeError("an operation is already running")
        thread = QThread(self)
        task = _Task(operation, self._expected)
        task.moveToThread(thread)
        thread.started.connect(task.run)
        task.progress.connect(self.progress)
        task.succeeded.connect(self.succeeded)
        task.failed.connect(self.failed)
        task.cancelled.connect(self.cancelled)
        task.finished.connect(thread.quit)
        task.finished.connect(task.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.destroyed.connect(self._reset)
        self._thread = thread
        self._task = task
        thread.start()

    def cancel(self) -> None:
        if self._task is not None:
            self._task.token.cancel()

    @Slot()
    def _reset(self) -> None:
        self._thread = None
        self._task = None
        self.finished.emit()
