"""The dialog the page fetches either of its inputs through.

Nothing here reaches the network: the runner is never started, and the cache is
pointed at a temporary directory.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QWidget

from shared.download import cache as cache_module
from shared.download.cache import DownloadCache
from shared.download.media import FetchedTrack, Track
from shared.i18n import tr
from shared.ui.download_dialog import CACHE, RESULTS, DownloadDialog


@pytest.fixture
def downloads(tmp_path, monkeypatch):
    """Point the dialog's cache at a temporary directory."""
    monkeypatch.setattr(cache_module, "download_directory", lambda: tmp_path)
    return tmp_path


def _remember(directory, name="song.wav", url="https://example.invalid/watch"):
    path = directory / name
    path.write_bytes(b"0123456789")
    track = Track(url=url, identifier="abc", title="A Song", uploader="A Channel", duration=61)
    DownloadCache(directory).remember(FetchedTrack(track=track, path=path))
    return path


@pytest.fixture
def host(qtbot):
    """A parent for the dialog that outlives it, as the main window does."""
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


def test_an_empty_cache_opens_on_the_search_side(qtbot, downloads, host):
    dialog = DownloadDialog(host)

    assert dialog.stack.currentWidget() is dialog.result_list
    assert dialog.tabs.currentRouteKey() == RESULTS


def test_what_was_downloaded_before_is_offered_first(qtbot, downloads, host):
    _remember(downloads)

    dialog = DownloadDialog(host)

    assert dialog.stack.currentWidget() is dialog.cached_list
    assert dialog.cached_list.count() == 1
    item = dialog.cached_list.item(0)
    assert "A Song" in item.text()
    assert "A Channel" in item.text()
    assert "01:01" in item.text()
    assert dialog.tabs.items[CACHE].text().endswith("(1)")


def test_the_button_says_what_the_field_holds(qtbot, downloads, host):
    dialog = DownloadDialog(host)

    assert dialog.fetch_button.text() == tr("download_fetch")
    dialog.query.setText("some keywords")
    assert dialog.fetch_button.text() == tr("download_search")
    dialog.query.setText("https://music.youtube.com/watch?v=abc")
    assert dialog.fetch_button.text() == tr("download_fetch")


def test_an_empty_field_is_reported_rather_than_searched(qtbot, downloads, host):
    dialog = DownloadDialog(host)

    dialog.fetch_button.click()

    assert dialog.status.text() == tr("download_need_input")
    assert not dialog.runner.running


def test_a_link_already_downloaded_is_selected_instead_of_fetched(qtbot, downloads, host):
    path = _remember(downloads)
    dialog = DownloadDialog(host)

    dialog.query.setText("https://example.invalid/watch")
    dialog.fetch_button.click()

    assert dialog.status.text() == tr("download_already")
    assert not dialog.runner.running
    assert dialog.validate()
    assert dialog.selected_paths() == [path]


def test_the_dialog_will_not_close_without_a_selection(qtbot, downloads, host):
    _remember(downloads)
    dialog = DownloadDialog(host)
    dialog.cached_list.clearSelection()

    assert not dialog.validate()
    assert dialog.selected_paths() == []
    assert dialog.status.text() == tr("download_need_selection")


def test_a_selection_whose_file_vanished_is_refused(qtbot, downloads, host):
    """The index is only re-read on open, so the file can go while it is up."""
    path = _remember(downloads)
    dialog = DownloadDialog(host)
    dialog.cached_list.setCurrentRow(0)
    path.unlink()

    assert not dialog.validate()


def test_removing_a_download_deletes_the_file_behind_it(qtbot, downloads, host):
    path = _remember(downloads)
    dialog = DownloadDialog(host)
    dialog.cached_list.setCurrentRow(0)

    dialog.remove_button.click()

    assert not path.exists()
    assert dialog.cached_list.count() == 0
    assert DownloadCache(downloads).entries() == ()


def test_a_missing_ffmpeg_is_said_out_loud(qtbot, downloads, host, monkeypatch):
    import shared.ui.download_dialog as dialog_module

    monkeypatch.setattr(dialog_module, "ffmpeg_available", lambda: False)

    dialog = DownloadDialog(host)

    assert tr("download_no_ffmpeg") in dialog.hint.text()


def test_the_dialog_will_not_close_over_a_running_download(qtbot, downloads, host, monkeypatch):
    """Closing cancels and waits, the way the window waits for a running job."""
    from threading import Event

    from shared.download import runner as runner_module

    release = Event()
    monkeypatch.setattr(runner_module, "search", lambda query, limit: (release.wait(5), ())[1])

    dialog = DownloadDialog(host)
    dialog.query.setText("some keywords")
    dialog.fetch_button.click()
    qtbot.waitUntil(lambda: dialog.runner.running, timeout=2000)

    assert not dialog.yesButton.isEnabled(), "accepting would close over the thread"
    with qtbot.assertNotEmitted(dialog.rejected):
        dialog.reject()
    assert dialog.closing

    with qtbot.waitSignal(dialog.rejected, timeout=5000):
        release.set()


def test_a_dialog_that_cannot_close_yet_says_so(qtbot, downloads, host, monkeypatch):
    """Swallowing the close without a word reads as a frozen window."""
    from threading import Event

    from shared.download import runner as runner_module

    release = Event()
    monkeypatch.setattr(runner_module, "search", lambda query, limit: (release.wait(5), ())[1])

    dialog = DownloadDialog(host)
    dialog.query.setText("some keywords")
    dialog.fetch_button.click()
    qtbot.waitUntil(lambda: dialog.runner.running, timeout=2000)

    dialog.reject()

    assert dialog.status.text() == tr("download_stopping")
    assert not dialog.cancelButton.isEnabled()

    with qtbot.waitSignal(dialog.rejected, timeout=5000):
        release.set()
