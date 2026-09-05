"""What happens when an exception reaches the top of the stack.

PySide6 prints an uncaught exception and lets the event loop carry on, so this
is a report rather than a shutdown: the traceback goes into today's log file,
that file opens in whatever the desktop reads text with, and the dialog points
the user at the issue form.

What travels in the issue URL is only what cannot identify the reporter - the
version, the platform, and the exception's type.  Not its message and not the
log: both carry absolute paths, and a URL is in the browser's history before
anyone has read it.  The log goes through the clipboard instead, which costs no
URL length, and only once the user has chosen to report.

Only Python exceptions arrive here.  A native crash or a `qFatal` ends the
process without unwinding; the Qt message handler has already put whatever Qt
said about it in the same log file.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import TracebackType
from urllib.parse import urlencode

from PySide6.QtCore import QSysInfo, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import MessageBox

from app.version import __version__
from shared.branding import REPOSITORY_URL
from shared.i18n import tr
from shared.logging import log_file_path

logger = logging.getLogger(__name__)

ISSUE_FORM_URL = f"{REPOSITORY_URL}/issues/new"
# Named explicitly: with issue templates in the repository a bare `issues/new`
# lands on the template chooser, and a crash already knows which form it wants.
ISSUE_TEMPLATE = "bug_report.yml"
# Both must match `.github/ISSUE_TEMPLATE/bug_report.yml`: a field is filled by
# its `id`, and a dropdown by the text of the option.  test_crash_handler.py
# reads the file and holds these to it.
ISSUE_BUILD_OPTION = "桌面版图形界面 / Desktop GUI"
ISSUE_LOG_FIELD = "logs"
# Enough to cover a run that failed late, and short enough to stay a comment
# rather than an attachment.
LOG_TAIL_LINES = 200

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
    _show_report(exc_type.__name__, f"{exc_type.__name__}: {exc}", path)


def issue_url(exception_name: str) -> str:
    """The bug form, carrying the little that describes the build, not the user.

    Encoded by `urlencode` rather than `QUrlQuery`, which leaves `+` alone: a
    shortcut written `Ctrl+A` would reach the form as `Ctrl A`.
    """

    fields = {
        "template": ISSUE_TEMPLATE,
        "title": f"[Bug] {exception_name}",
        "version": __version__,
        "os": f"{QSysInfo.prettyProductName()} ({QSysInfo.currentCpuArchitecture()})",
        "build": ISSUE_BUILD_OPTION,
        ISSUE_LOG_FIELD: tr("crash_log_paste"),
    }
    return f"{ISSUE_FORM_URL}?{urlencode(fields)}"


def copy_log_tail(path: Path) -> bool:
    """Put the end of the log on the clipboard for the user to paste."""

    clipboard = QGuiApplication.clipboard()
    if clipboard is None:
        return False
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        logger.warning("cannot read %s to copy it", path, exc_info=True)
        return False
    clipboard.setText("\n".join(lines[-LOG_TAIL_LINES:]))
    return True


def _show_report(exception_name: str, summary: str, path: Path | None) -> None:
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
    if not dialog.exec():
        return
    # Only now: taking over the clipboard is rude to someone who chose to
    # dismiss the dialog and carry on.
    if path is not None:
        copy_log_tail(path)
    QDesktopServices.openUrl(QUrl(issue_url(exception_name)))


def _dialog_parent() -> QWidget | None:
    """A visible window to draw the dialog's mask over."""

    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return None
    active = app.activeWindow()
    if active is not None and active.isVisible():
        return active
    return next((window for window in app.topLevelWidgets() if window.isVisible()), None)
