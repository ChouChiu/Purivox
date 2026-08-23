from __future__ import annotations

from PySide6.QtWidgets import QWidget

from app.job_presenter import JobPresenter
from features.reference_removal.page import MrPage
from shared.processing import ProcessingResult, ProgressEvent


def test_job_presenter_owns_page_running_and_progress_state(qtbot, monkeypatch):
    parent = QWidget()
    page = MrPage(parent)
    qtbot.addWidget(parent)
    presenter = JobPresenter(parent, lambda: "zh_cn")
    monkeypatch.setattr("app.job_presenter.InfoBar.success", lambda *_args, **_kwargs: None)

    def operation(_token, report):
        report(ProgressEvent(64, "处理中"))
        return ProcessingResult(())

    with qtbot.waitSignal(presenter.finished, timeout=2_000):
        presenter.start(page, operation)
        assert presenter.running
        assert not page.start_button.isEnabled()

    assert not presenter.running
    assert page.start_button.isEnabled()
    assert page.progress.value() == 64
    assert page.status.text() == "处理中"
