from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

from app.worker import ProcessingWorker
from shared.processing import ProcessingOperation


class JobRunner(QObject):
    """Own the QThread lifecycle for one processing operation at a time."""

    progress = Signal(int, str)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: ProcessingWorker | None = None

    @property
    def running(self) -> bool:
        return self._worker is not None

    def start(self, operation: ProcessingOperation) -> None:
        if self.running:
            raise RuntimeError("a processing operation is already running")
        thread = QThread(self)
        worker = ProcessingWorker(operation)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.progress)
        worker.succeeded.connect(self.succeeded)
        worker.failed.connect(self.failed)
        worker.cancelled.connect(self.cancelled)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.destroyed.connect(self._reset)
        self._thread = thread
        self._worker = worker
        thread.start()

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.request_cancel()

    @Slot()
    def _reset(self) -> None:
        self._thread = None
        self._worker = None
        self.finished.emit()
