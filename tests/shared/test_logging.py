import io
import logging
import re
from datetime import datetime, timedelta

import pytest

from shared import logging as shared_logging
from shared.logging import (
    LOG_RETENTION_DAYS,
    ApplicationLogFormatter,
    configure_logging,
    log_file_path,
    normalise_log_level,
)


def test_application_log_formatter_is_single_line_and_parseable():
    record = logging.LogRecord(
        "audio.io",
        logging.WARNING,
        __file__,
        1,
        "decoder failed: %s\nretrying",
        ("unsupported codec",),
        None,
    )
    record.created = 1_786_275_296.789
    record.msecs = 789

    output = ApplicationLogFormatter().format(record)

    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.78 "
        r"\[WARNING\] audio\.io: "
        r"decoder failed: unsupported codec\\nretrying",
        output,
    )


def test_log_level_validation():
    assert normalise_log_level("debug") == logging.DEBUG
    assert normalise_log_level("CRITICAL") == logging.CRITICAL
    with pytest.raises(ValueError, match="unsupported log level"):
        normalise_log_level("verbose")


@pytest.fixture
def log_directory(tmp_path, monkeypatch):
    """Point file logging at a temporary directory and unwind it afterwards."""
    directory = tmp_path / "logs"
    root = logging.getLogger()
    installed = list(root.handlers)
    level = root.level
    monkeypatch.setattr(shared_logging, "log_directory", lambda: directory)
    monkeypatch.setattr(shared_logging, "_handler", None)
    monkeypatch.setattr(shared_logging, "_file_handler", None)
    yield directory
    for handler in root.handlers:
        if handler not in installed:
            handler.close()
    root.handlers[:] = installed
    root.setLevel(level)


def _configure(**kwargs):
    configure_logging(stream=io.StringIO(), install_qt_handler=False, **kwargs)


def test_file_logging_writes_todays_file(log_directory):
    _configure(log_to_file=True)
    path = log_directory / f"{datetime.now():%Y-%m-%d}.log"

    assert log_file_path() == path
    logging.getLogger("audio.io").warning("decoder failed")
    assert "[WARNING] audio.io: decoder failed" in path.read_text(encoding="utf-8")


def test_file_logging_is_off_unless_asked_for(log_directory):
    _configure()

    assert log_file_path() is None
    assert not log_directory.exists()


def test_expired_logs_are_pruned_and_foreign_files_are_left(log_directory):
    log_directory.mkdir(parents=True)
    now = datetime.now()
    expired = log_directory / f"{now - timedelta(days=LOG_RETENTION_DAYS + 1):%Y-%m-%d}.log"
    kept = log_directory / f"{now - timedelta(days=1):%Y-%m-%d}.log"
    foreign = log_directory / "crash-dump.log"
    for path in (expired, kept, foreign):
        path.write_text("earlier run\n", encoding="utf-8")

    _configure(log_to_file=True)

    assert not expired.exists()
    assert kept.exists()
    assert foreign.exists()


def test_an_unusable_directory_costs_the_log_file_not_the_run(tmp_path, monkeypatch, log_directory):
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(shared_logging, "log_directory", lambda: blocked / "logs")

    _configure(log_to_file=True)

    assert log_file_path() is None
    logging.getLogger("audio.io").warning("decoder failed")
