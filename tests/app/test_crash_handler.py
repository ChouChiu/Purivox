import logging
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from app import crash_handler
from app.version import __version__
from shared.i18n import tr

TEMPLATE = Path(__file__).parents[2] / ".github/ISSUE_TEMPLATE" / crash_handler.ISSUE_TEMPLATE


class _StubMessageBox:
    """Stand in for the modal dialog: record what it was told, answer `answer`."""

    last: "_StubMessageBox | None" = None
    answer = 1

    def __init__(self, title, content, parent):
        self.title = title
        self.content = content
        self.parent = parent
        self.yesButton = _StubButton()
        self.cancelButton = _StubButton()
        _StubMessageBox.last = self

    def exec(self):
        return _StubMessageBox.answer


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
    monkeypatch.setattr(_StubMessageBox, "answer", 1)
    _StubMessageBox.last = None
    QGuiApplication.clipboard().setText("what the user had copied")
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
    assert crash[0] == log.as_uri()
    assert crash[1].startswith(crash_handler.ISSUE_FORM_URL)
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

    assert sum(url.startswith(crash_handler.ISSUE_FORM_URL) for url in crash) == 1


def test_a_crash_without_a_log_file_still_reports(crash, monkeypatch):
    monkeypatch.setattr(crash_handler, "log_file_path", lambda: None)

    crash_handler.report_crash(OSError, OSError("no disk"), None)

    assert len(crash) == 1
    assert crash[0].startswith(crash_handler.ISSUE_FORM_URL)
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


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def test_the_issue_url_carries_the_build_and_not_the_reporter(crash, monkeypatch, tmp_path):
    log = tmp_path / "2026-09-05.log"
    log.write_text("", encoding="utf-8")
    monkeypatch.setattr(crash_handler, "log_file_path", lambda: log)

    crash_handler.report_crash(RuntimeError, RuntimeError("boom in /home/someone/song.wav"), None)

    query = _query(crash[1])
    assert query["template"] == [crash_handler.ISSUE_TEMPLATE]
    assert query["title"] == ["[Bug] RuntimeError"]
    assert query["version"] == [__version__]
    assert query["build"] == [crash_handler.ISSUE_BUILD_OPTION]
    assert query["os"] and query["os"][0]
    # The exception's message is the part most likely to be a path.
    assert "/home/someone" not in crash[1]


def test_reporting_puts_the_log_tail_on_the_clipboard(crash, monkeypatch, tmp_path):
    log = tmp_path / "2026-09-05.log"
    lines = [f"line {index}" for index in range(crash_handler.LOG_TAIL_LINES + 40)]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(crash_handler, "log_file_path", lambda: log)

    crash_handler.report_crash(RuntimeError, RuntimeError("boom"), None)

    copied = QGuiApplication.clipboard().text().splitlines()
    assert len(copied) == crash_handler.LOG_TAIL_LINES
    assert copied[-1] == lines[-1]
    assert copied[0] == lines[-crash_handler.LOG_TAIL_LINES]


def test_dismissing_leaves_the_clipboard_alone(crash, monkeypatch, tmp_path):
    log = tmp_path / "2026-09-05.log"
    log.write_text("something private\n", encoding="utf-8")
    monkeypatch.setattr(crash_handler, "log_file_path", lambda: log)
    monkeypatch.setattr(_StubMessageBox, "answer", 0)

    crash_handler.report_crash(RuntimeError, RuntimeError("boom"), None)

    assert QGuiApplication.clipboard().text() == "what the user had copied"
    assert crash == [log.as_uri()]


def test_the_prefilled_fields_exist_in_the_issue_template():
    """The form fills by field id and a dropdown by option text; both are literals here."""
    template = TEMPLATE.read_text(encoding="utf-8")

    for field in ("version", "os", "build"):
        assert f"id: {field}\n" in template, f"no {field} field in {TEMPLATE.name}"
    assert f"- {crash_handler.ISSUE_BUILD_OPTION}\n" in template


def test_the_log_field_writes_its_own_block_instead_of_using_render():
    """`render:` would wrap the submission in a code block on its own, but a
    prefilled rendered text area cannot be edited - and this field arrives
    prefilled, from its own `value:`.  So the block is spelled out there."""
    fields = TEMPLATE.read_text(encoding="utf-8").split("  - type: ")
    logs = next(field for field in fields if "id: logs\n" in field)
    lines = [line.strip() for line in logs.splitlines()]

    assert "render:" not in logs
    assert "<details open><summary>Log</summary>" in lines
    assert "```text" in lines
