from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QWidget

from features.settings import updates
from features.settings.dialog import UpdateDialog
from features.settings.updates import Release, UpdateChecker, is_newer, parse_release, version_parts

RELEASE = {
    "tag_name": "v9.9.9",
    "body": "## What changed\n\n- Everything",
    "html_url": "https://example.invalid/releases/tag/v9.9.9",
}


class _Handler(BaseHTTPRequestHandler):
    payload = json.dumps(RELEASE).encode()
    status = 200

    def do_GET(self):
        if type(self).status != 200:
            self.send_error(type(self).status)
            return
        body = type(self).payload
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


@pytest.fixture(autouse=True)
def local_release_host(monkeypatch):
    """Answer the release query from localhost so no test reaches GitHub."""
    _Handler.payload = json.dumps(RELEASE).encode()
    _Handler.status = 200
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(
        updates, "RELEASES_API", f"http://127.0.0.1:{httpd.server_address[1]}/latest"
    )
    yield _Handler
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


@pytest.fixture(autouse=True)
def installed_release():
    """Pin the running version the way the entry points do."""
    previous = QCoreApplication.applicationVersion()
    QCoreApplication.setApplicationVersion("1.0.0")
    yield
    QCoreApplication.setApplicationVersion(previous)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.0.0", (1, 0, 0)),
        ("v1.2.3", (1, 2, 3)),
        ("V1.2", (1, 2)),
        (" 1.10.0 ", (1, 10, 0)),
        ("1.2.0-rc1", (1, 2, 0)),
        ("1.2.0+build7", (1, 2, 0)),
        ("nightly", ()),
    ],
)
def test_a_tag_reads_as_its_numeric_release(text: str, expected: tuple[int, ...]):
    assert version_parts(text) == expected


@pytest.mark.parametrize(
    ("candidate", "installed", "expected"),
    [
        ("1.0.1", "1.0.0", True),
        ("v1.1", "1.0.9", True),
        ("1.10.0", "1.9.0", True),
        ("2", "1.9.9", True),
        ("1.0.0", "1.0.0", False),
        ("1.0", "1.0.0", False),
        ("0.9.9", "1.0.0", False),
        ("1.0.0-rc1", "1.0.0", False),
        ("nightly", "1.0.0", False),
    ],
)
def test_only_a_later_release_counts_as_newer(candidate: str, installed: str, expected: bool):
    assert is_newer(candidate, installed) is expected


def test_an_unversioned_build_takes_the_first_release_it_is_offered():
    QCoreApplication.setApplicationVersion("")
    assert is_newer("1.0.0", updates.installed_version())


def test_a_release_document_reads_its_tag_notes_and_page():
    release = parse_release(json.dumps(RELEASE).encode())
    assert release == Release("9.9.9", RELEASE["body"], RELEASE["html_url"])


def test_a_release_without_a_page_falls_back_to_the_releases_page():
    release = parse_release(json.dumps({"tag_name": "1.5.0"}).encode())
    assert release.url == updates.RELEASES_PAGE
    assert release.notes == ""


@pytest.mark.parametrize("payload", [b"<html>proxy error</html>", b"[]", b'{"body": "no tag"}'])
def test_anything_that_is_not_a_release_is_rejected(payload: bytes):
    with pytest.raises(ValueError):
        parse_release(payload)


def test_a_newer_release_is_offered_with_its_notes(qtbot):
    checker = UpdateChecker()
    with qtbot.waitSignal(checker.update_available, timeout=5000) as offered:
        assert checker.check()
    release = offered.args[0]
    assert release.version == "9.9.9"
    assert release.notes == RELEASE["body"]
    assert release.url == RELEASE["html_url"]


def test_the_current_release_reports_no_update(qtbot, local_release_host):
    local_release_host.payload = json.dumps({**RELEASE, "tag_name": "v1.0.0"}).encode()
    checker = UpdateChecker()
    with qtbot.waitSignal(checker.up_to_date, timeout=5000):
        checker.check()


def test_a_project_without_a_release_reports_no_update(qtbot, local_release_host):
    """GitHub answers 404 until something is published, which is not a failure."""
    local_release_host.status = 404
    checker = UpdateChecker()
    with qtbot.waitSignal(checker.up_to_date, timeout=5000):
        checker.check()


def test_an_unreachable_release_host_reports_a_failure(qtbot, local_release_host):
    local_release_host.status = 500
    checker = UpdateChecker()
    with qtbot.waitSignal(checker.failed, timeout=5000) as failure:
        checker.check()
    assert failure.args[0]


def test_an_unreadable_answer_reports_a_failure(qtbot, local_release_host):
    local_release_host.payload = b"<html>not a release</html>"
    checker = UpdateChecker()
    with qtbot.waitSignal(checker.failed, timeout=5000):
        checker.check()


def test_one_check_runs_at_a_time(qtbot):
    checker = UpdateChecker()
    with qtbot.waitSignal(checker.finished, timeout=5000):
        assert checker.check()
        assert not checker.check()
        assert checker.busy
    assert not checker.busy


def test_the_dialog_shows_the_version_and_the_notes(qtbot):
    window = QWidget()
    qtbot.addWidget(window)
    dialog = UpdateDialog(Release("9.9.9", "- fixed everything", RELEASE["html_url"]), window)
    assert "9.9.9" in dialog.title_label.text()
    assert "fixed everything" in dialog.notes.toPlainText()
    assert dialog.yesButton.text() == "前往 Release 页面"


def test_the_dialog_says_so_when_a_release_ships_no_notes(qtbot):
    window = QWidget()
    qtbot.addWidget(window)
    dialog = UpdateDialog(Release("9.9.9", "   ", RELEASE["html_url"]), window)
    assert dialog.notes.toPlainText().strip() == "这个版本没有提供更新说明。"
