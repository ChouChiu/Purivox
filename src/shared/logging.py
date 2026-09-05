from __future__ import annotations

import logging
import os
import sys
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path
from typing import TextIO

from PySide6.QtCore import QStandardPaths, QtMsgType, qInstallMessageHandler

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
LOG_FILE_FORMAT = "%Y-%m-%d"
LOG_RETENTION_DAYS = 14

_handler: logging.StreamHandler | None = None
_file_handler: logging.FileHandler | None = None
_qt_handler_installed = False


class ApplicationLogFormatter(logging.Formatter):
    """Format every record as one stable, parseable line."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        centiseconds = int(record.msecs) // 10
        message = record.getMessage()
        if record.exc_info:
            traceback_text = self.formatException(record.exc_info)
            message = f"{message} | {traceback_text}"
        message = message.replace("\r", "\\r").replace("\n", "\\n")
        return f"{timestamp}.{centiseconds:02d} [{record.levelname}] {record.name}: {message}"


def normalise_log_level(level: str) -> int:
    name = level.upper()
    if name not in LOG_LEVELS:
        raise ValueError(f"unsupported log level: {level}")
    return logging.getLevelNamesMapping()[name]


def set_log_level(level: str) -> None:
    numeric_level = normalise_log_level(level)
    logging.getLogger().setLevel(numeric_level)
    for handler in (_handler, _file_handler):
        if handler is not None:
            handler.setLevel(numeric_level)


def log_directory() -> Path:
    """Where the daily log files live, beside the rest of the application data."""

    root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    return Path(root or Path.home() / ".local/share/purivox") / "logs"


def log_file_path() -> Path | None:
    """The file this run is writing to, or None when only stderr is attached."""

    return None if _file_handler is None else Path(_file_handler.baseFilename)


def configure_logging(
    level: str = "INFO",
    *,
    stream: TextIO | None = None,
    install_qt_handler: bool = True,
    log_to_file: bool = False,
) -> None:
    """Install the application handler once and update its active level.

    `log_to_file` adds today's file in `log_directory()` alongside the stream.
    It is off by default because the browser build shares this module and has
    nowhere to put a file; the desktop entry points ask for it once their
    application identity is set, which is what decides that directory.
    """

    global _handler, _qt_handler_installed
    if _handler is None:
        _handler = logging.StreamHandler(stream or sys.stderr)
        _handler.setFormatter(ApplicationLogFormatter())
        logging.getLogger().addHandler(_handler)
        logging.captureWarnings(True)
    elif stream is not None:
        _handler.setStream(stream)
    set_log_level(level)
    if log_to_file and _file_handler is None:
        # After the level, so the handler starts at it and the line naming the
        # file is not dropped by a root logger still sitting at its default.
        _install_file_handler()
    if install_qt_handler and not _qt_handler_installed:
        # Make Qt route libav diagnostics through qInstallMessageHandler rather
        # than allowing FFmpeg to write unformatted media dumps to stderr.
        os.environ.setdefault("QT_FFMPEG_DEBUG", "1")
        qInstallMessageHandler(_qt_message_handler)
        _qt_handler_installed = True


def _install_file_handler() -> None:
    """Open today's log file, and drop the days nobody is going to read."""

    global _file_handler
    directory = log_directory()
    path = directory / f"{datetime.now():{LOG_FILE_FORMAT}}.log"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        # Appended, so every run of a day shares one file and the file name
        # stays the date the user would look for.
        handler = logging.FileHandler(path, encoding="utf-8")
    except OSError:
        logging.getLogger(__name__).warning("no log file in %s", directory, exc_info=True)
        return
    handler.setFormatter(ApplicationLogFormatter())
    handler.setLevel(logging.getLogger().level)
    logging.getLogger().addHandler(handler)
    _file_handler = handler
    _prune_old_logs(directory)
    logging.getLogger(__name__).info("logging to %s", path)


def _prune_old_logs(directory: Path) -> None:
    cutoff = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)
    for path in directory.glob("*.log"):
        try:
            written = datetime.strptime(path.stem, LOG_FILE_FORMAT)
        except ValueError:
            continue
        if written >= cutoff:
            continue
        # A second instance running on another day holds its own file open,
        # and Windows refuses to unlink that one.
        with suppress(OSError):
            path.unlink()


def _qt_message_handler(message_type, context, message: str) -> None:
    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }
    category = getattr(context, "category", None)
    module = "qt" if not category or category == "default" else f"qt.{category}"
    level = levels.get(message_type, logging.INFO)
    if message.lstrip('"').startswith("FFmpeg log:"):
        module = "qt.multimedia.ffmpeg"
        level = logging.DEBUG
    logging.getLogger(module).log(level, message)
