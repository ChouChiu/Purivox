"""What happens when an exception reaches the top of the stack.

PySide6 prints an uncaught exception and lets the event loop carry on, so this
is a report rather than a shutdown: the traceback goes into today's log file,
that file opens in whatever the desktop reads text with, and the dialog points
the user at the issue form.  Nothing about the exception travels in the issue
URL - a message can carry a home directory, and the user pastes what they want
from the file they now have in front of them.

Only Python exceptions arrive here.  A native crash or a `qFatal` ends the
process without unwinding; the Qt message handler has already put whatever Qt
said about it in the same log file.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import TracebackType

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import MessageBox

from shared.branding import REPOSITORY_URL
from shared.i18n import tr
from shared.logging import log_file_path

logger = logging.getLogger(__name__)

ISSUE_FORM_URL = f"{REPOSITORY_URL}/issues/new"

_previous_excepthook = sys.excepthook
_reported = False


def install_crash_handler() -> None:
    """Send uncaught exceptions to the log file and to the user."""

    global _previous_excepthook
    _previous_excepthook = sys.excepthook
    sys.excepthook = report_crash


def report_crash(
    exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
) -> None:
    global _reported
    if issubclass(exc_type, KeyboardInterrupt):
        _previous_excepthook(exc_type, exc, tb)
        return
    logger.critical("unhandled exception", exc_info=(exc_type, exc, tb))
    if _reported:
        # An exception raised from paintEvent repeats on every frame.  One
        # dialog a run is a report; one a frame is a second failure.
        return
    _reported = True
    path = log_file_path()
    if path is not None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    _show_report(f"{exc_type.__name__}: {exc}", path)


def _show_report(summary: str, path: Path | None) -> None:
    parent = _dialog_parent()
    if parent is None:
        # Before the window exists, or after it is gone, the log file is the
        # whole report.
        logger.warning("no window to report the crash in")
        return
    location = str(path) if path is not None else tr("crash_no_log")
    dialog = MessageBox(
        tr("crash_title"), tr("crash_message", error=summary, path=location), parent
    )
    dialog.yesButton.setText(tr("crash_report"))
    dialog.cancelButton.setText(tr("update_later"))
    if dialog.exec():
        QDesktopServices.openUrl(QUrl(ISSUE_FORM_URL))


def _dialog_parent() -> QWidget | None:
    """A visible window to draw the dialog's mask over."""

    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return None
    active = app.activeWindow()
    if active is not None and active.isVisible():
        return active
    return next((window for window in app.topLevelWidgets() if window.isVisible()), None)
