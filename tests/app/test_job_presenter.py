from __future__ import annotations

from pathlib import Path
from threading import Event

import numpy as np
import soundfile as sf
from PySide6.QtWidgets import QWidget

from app.job_presenter import JobPresenter
from features.reference_removal import ClipKind, IsolationResult, StageAnalysis, TimelineClip
from features.reference_removal.page import MrPage
from shared.processing import ProgressEvent


def test_job_presenter_owns_page_running_and_progress_state(qtbot, monkeypatch):
    parent = QWidget()
    page = MrPage(parent)
    qtbot.addWidget(parent)
    presenter = JobPresenter(parent)
    monkeypatch.setattr("app.job_presenter.InfoBar.success", lambda *_args, **_kwargs: None)

    release = Event()

    def operation(_token, report):
        report(ProgressEvent(64, "处理中"))
        release.wait(2)
        return _analysis(Path("/work/song.wav"))

    with qtbot.waitSignal(presenter.finished, timeout=2_000):
        presenter.start(page, operation)
        assert presenter.running
        assert not page.start_button.isEnabled()
        qtbot.waitUntil(lambda: page.status.text() == "处理中", timeout=2_000)
        assert page.progress.value() == 64
        release.set()

    assert not presenter.running
    assert page.start_button.isEnabled()
    # The presenter brackets the clock around the job, so the page ends up with
    # a total rather than the empty readout it started from.
    assert page.elapsed.text() != ""


def _analysis(source: Path) -> StageAnalysis:
    return StageAnalysis(
        4.0,
        (
            TimelineClip(ClipKind.SONG, 0.0, 4.0, source, 0, 0.0, 4.0, 0.9),
            TimelineClip(ClipKind.UNMATCHED, 4.0, 8.0),
        ),
    )


def _presenter(qtbot, monkeypatch) -> tuple[QWidget, MrPage, JobPresenter]:
    parent = QWidget()
    page = MrPage(parent)
    qtbot.addWidget(parent)
    monkeypatch.setattr("app.job_presenter.InfoBar.success", lambda *_args, **_kwargs: None)
    return parent, page, JobPresenter(parent)


def test_an_isolation_result_fills_the_timeline_the_preview_and_the_status(
    qtbot, monkeypatch, tmp_path: Path
):
    _parent, page, presenter = _presenter(qtbot, monkeypatch)
    result_path = tmp_path / "result.wav"
    sf.write(result_path, np.zeros((8_000, 2), dtype=np.float32), 8_000)
    analysis = _analysis(Path("/work/song.wav"))

    with qtbot.waitSignal(presenter.finished, timeout=2_000):
        presenter.start(page, lambda _token, _report: IsolationResult(analysis, (result_path,)))

    assert page.analysis is analysis
    assert page.preview.status.text() == result_path.name
    assert str(result_path) in page.status.text()
    assert page.preview.play_button.isEnabled()


def test_an_analysis_only_result_leaves_the_preview_alone(qtbot, monkeypatch):
    """Find songs reports a timeline and writes nothing."""
    _parent, page, presenter = _presenter(qtbot, monkeypatch)
    analysis = _analysis(Path("/work/song.wav"))

    with qtbot.waitSignal(presenter.finished, timeout=2_000):
        presenter.start(page, lambda _token, _report: analysis)

    assert page.analysis is analysis
    assert page.preview.path is None
    assert not page.preview.play_button.isEnabled()
