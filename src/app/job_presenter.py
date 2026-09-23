from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QWidget
from qfluentwidgets import InfoBar, InfoBarPosition, ProgressBar, StateToolTip

from shared.i18n import tr
from shared.tasks import Operation, TaskRunner
from shared.ui import ElidedLabel


class JobPage(Protocol):
    """What the presenter needs of a page that runs jobs.

    The page shows its own result, because only it knows what its job returns;
    the presenter owns everything that is the same for every job.
    """

    progress: ProgressBar
    status: ElidedLabel

    def set_running(self, running: bool) -> None: ...

    def start_clock(self) -> None: ...

    def stop_clock(self) -> None: ...

    def show_result(self, result: object) -> str:
        """Show a finished job's result and return the line to announce it with."""
        ...


class JobPresenter(QObject):
    """Coordinate background jobs with the page-level progress and result UI."""

    finished = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._parent = parent
        self._runner = TaskRunner(self)
        self._active_page: JobPage | None = None
        self._state_tip: StateToolTip | None = None
        self._runner.progress.connect(self._progress)
        self._runner.succeeded.connect(self._success)
        self._runner.failed.connect(self._failure)
        self._runner.cancelled.connect(self._cancelled)
        self._runner.finished.connect(self._job_finished)

    @property
    def running(self) -> bool:
        return self._runner.running

    def start(self, page: JobPage, operation: Operation) -> None:
        if self.running:
            raise RuntimeError("a processing operation is already running")
        self._active_page = page
        page.progress.setValue(0)
        page.set_running(True)
        page.start_clock()
        self._state_tip = StateToolTip(tr("processing"), tr("loading_stage"), self._parent)
        self._state_tip.move(self._state_tip.getSuitablePos())
        self._state_tip.show()
        self._runner.start(operation)

    def cancel(self) -> None:
        self._runner.cancel()

    @Slot(int, str)
    def _progress(self, value: int, message: str) -> None:
        if self._active_page is not None:
            self._active_page.progress.setValue(value)
            self._active_page.status.setText(message)
        if self._state_tip is not None:
            self._state_tip.setContent(message)

    @Slot(object)
    def _success(self, result: object) -> None:
        if self._state_tip is not None:
            self._state_tip.setState(True)
            self._state_tip = None
        if self._active_page is None:
            return
        InfoBar.success(
            tr("done_title"),
            self._active_page.show_result(result),
            duration=5000,
            position=InfoBarPosition.TOP_RIGHT,
            parent=self._parent,
        )

    @Slot(str)
    def _failure(self, message: str) -> None:
        self._discard_state_tip()
        if self._active_page is not None:
            self._active_page.status.setText(tr("err_status", msg=message))
        InfoBar.error(
            tr("err_title"),
            message,
            duration=6000,
            position=InfoBarPosition.TOP_RIGHT,
            parent=self._parent,
        )

    @Slot()
    def _cancelled(self) -> None:
        if self._active_page is not None:
            self._active_page.status.setText(tr("cancelled"))
        self._discard_state_tip()

    def _discard_state_tip(self) -> None:
        if self._state_tip is not None:
            self._state_tip.deleteLater()
            self._state_tip = None

    @Slot()
    def _job_finished(self) -> None:
        if self._active_page is not None:
            self._active_page.set_running(False)
            self._active_page.stop_clock()
        self._active_page = None
        self.finished.emit()
