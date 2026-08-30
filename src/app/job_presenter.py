from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget
from qfluentwidgets import InfoBar, InfoBarPosition, StateToolTip

from app.job_runner import JobRunner
from features.full_stage import FullStageResult
from features.full_stage.page import FullStagePage
from features.neural_separation.page import AiPage
from features.reference_removal.page import MrPage
from shared.i18n import tr
from shared.processing import ProcessingOperation, ProcessingResultLike

ProcessingPage = MrPage | AiPage | FullStagePage


class JobPresenter(QObject):
    """Coordinate background jobs with the page-level progress and result UI."""

    finished = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._parent = parent
        self._runner = JobRunner(self)
        self._active_page: ProcessingPage | None = None
        self._state_tip: StateToolTip | None = None
        self._runner.progress.connect(self._progress)
        self._runner.succeeded.connect(self._success)
        self._runner.failed.connect(self._failure)
        self._runner.cancelled.connect(self._cancelled)
        self._runner.finished.connect(self._job_finished)

    @property
    def running(self) -> bool:
        return self._runner.running

    def start(self, page: ProcessingPage, operation: ProcessingOperation) -> None:
        if self.running:
            raise RuntimeError("a processing operation is already running")
        self._active_page = page
        page.progress.setValue(0)
        page.set_running(True)
        self._state_tip = StateToolTip(tr("processing"), tr("loading_song"), self._parent)
        self._state_tip.move(self._state_tip.getSuitablePos())
        self._state_tip.show()
        try:
            self._runner.start(operation)
        except BaseException:
            page.set_running(False)
            self._active_page = None
            self._discard_state_tip()
            raise

    def cancel(self) -> None:
        self._runner.cancel()

    def _progress(self, value: int, message: str) -> None:
        if self._active_page is not None:
            self._active_page.progress.setValue(value)
            self._active_page.status.setText(message)
        if self._state_tip is not None:
            self._state_tip.setContent(message)

    def _success(self, result: ProcessingResultLike) -> None:
        if self._state_tip is not None:
            self._state_tip.setState(True)
            self._state_tip = None
        outputs = "\n".join(map(str, result.outputs))
        if isinstance(self._active_page, MrPage) and result.outputs:
            stats = result.audio_stats[0] if result.audio_stats else None
            self._active_page.set_result(result.outputs[0], stats)
        if isinstance(self._active_page, FullStagePage) and isinstance(result, FullStageResult):
            self._active_page.set_analysis(result.analysis)
            if result.outputs:
                self._active_page.status.setText(tr("done_status", path=result.outputs[0]))
            else:
                outputs = tr(
                    "stage_analysis_summary",
                    songs=len(result.analysis.song_clips),
                    fragments=sum(clip.kind.value == "fragment" for clip in result.analysis.clips),
                    missing=len(result.analysis.missing_sources),
                )
        InfoBar.success(
            tr("done_title"),
            outputs,
            duration=5000,
            position=InfoBarPosition.TOP_RIGHT,
            parent=self._parent,
        )

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

    def _cancelled(self) -> None:
        if self._active_page is not None:
            self._active_page.status.setText(tr("cancelled"))
        self._discard_state_tip()

    def _discard_state_tip(self) -> None:
        if self._state_tip is not None:
            self._state_tip.deleteLater()
            self._state_tip = None

    def _job_finished(self) -> None:
        if self._active_page is not None:
            self._active_page.set_running(False)
        self._active_page = None
        self.finished.emit()
