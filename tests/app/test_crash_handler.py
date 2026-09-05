import logging
import sys

import pytest
from PySide6.QtWidgets import QWidget

from app import crash_handler
from shared.i18n import tr


class _StubMessageBox:
    """Stand in for the modal dialog: record what it was told, answer yes."""

    last: "_StubMessageBox | None" = None

    def __init__(self, title, content, parent):
        self.title = title
        self.content = content
        self.parent = parent
        self.yesButton = _StubButton()
        self.cancelButton = _StubButton()
        _StubMessageBox.last = self

    def exec(self):
        return 1


class _StubButton:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = text


@pytest.fixture
def crash(qtbot, monkeypatch):
    """A visible window, a fresh report state, and no browser or editor opened."""
    window = QWidget()
    qtbot.addWidget(window)
    with qtbot.waitExposed(window):
        window.show()
    opened: list[str] = []
    monkeypatch.setattr(
        crash_handler.QDesktopServices, "openUrl", lambda url: opened.append(url.toString()) or True
    )
    monkeypatch.setattr(crash_handler, "MessageBox", _StubMessageBox)
    monkeypatch.setattr(crash_handler, "_reported", False)
    _StubMessageBox.last = None
    # Yielded, so the frame holding `window` outlives the test: pytest-qt keeps
    # only a weak reference, and a collected window is no window to report in.
    yield opened


def test_a_crash_logs_opens_the_log_and_offers_the_issue_form(crash, monkeypatch, tmp_path, caplog):
    log = tmp_path / "2026-09-05.log"
    log.write_text("", encoding="utf-8")
    monkeypatch.setattr(crash_handler, "log_file_path", lambda: log)

    with caplog.at_level(logging.CRITICAL, logger="app.crash_handler"):
        crash_handler.report_crash(RuntimeError, RuntimeError("boom"), None)

    assert "unhandled exception" in caplog.text
    assert crash == [log.as_uri(), crash_handler.ISSUE_FORM_URL]
    dialog = _StubMessageBox.last
    assert dialog.title == tr("crash_title")
    assert "RuntimeError: boom" in dialog.content
    assert str(log) in dialog.content
    assert dialog.yesButton.text == tr("crash_report")
    assert dialog.cancelButton.text == tr("update_later")


def test_a_repeating_crash_is_reported_once(crash, monkeypatch, tmp_path):
    monkeypatch.setattr(crash_handler, "log_file_path", lambda: tmp_path / "today.log")

    for _ in range(3):
        crash_handler.report_crash(ValueError, ValueError("again"), None)

    assert crash.count(crash_handler.ISSUE_FORM_URL) == 1


def test_a_crash_without_a_log_file_still_reports(crash, monkeypatch):
    monkeypatch.setattr(crash_handler, "log_file_path", lambda: None)

    crash_handler.report_crash(OSError, OSError("no disk"), None)

    assert crash == [crash_handler.ISSUE_FORM_URL]
    assert tr("crash_no_log") in _StubMessageBox.last.content


def test_keyboard_interrupt_is_left_to_the_previous_hook(crash, monkeypatch):
    seen: list[type[BaseException]] = []
    monkeypatch.setattr(crash_handler, "_previous_excepthook", lambda t, e, tb: seen.append(t))

    crash_handler.report_crash(KeyboardInterrupt, KeyboardInterrupt(), None)

    assert seen == [KeyboardInterrupt]
    assert crash == []
    assert _StubMessageBox.last is None


def test_install_replaces_the_interpreter_hook(monkeypatch):
    previous = sys.excepthook
    monkeypatch.setattr(sys, "excepthook", previous)

    crash_handler.install_crash_handler()

    assert sys.excepthook is crash_handler.report_crash
    assert crash_handler._previous_excepthook is previous
