"""Fetch an input audio file from a link, and pick one that was fetched before.

Both reference workflows take their inputs as files, and both of them regularly
want the same file: the song a stage recording is matched against.  The dialog
is therefore shared rather than built per page, and everything it downloads goes
through one cache — fetching the same link twice is a round trip nobody asked
for, and the file is an input to a job, not a temporary.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QListWidgetItem, QStackedWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    LineEdit,
    ListWidget,
    MessageBoxBase,
    ProgressBar,
    PushButton,
    SegmentedWidget,
    SubtitleLabel,
)

from shared.download import (
    SEARCH_LIMIT,
    DownloadCache,
    DownloadRunner,
    FetchedTrack,
    Track,
    ffmpeg_available,
    looks_like_url,
)
from shared.i18n import tr

logger = logging.getLogger(__name__)

DIALOG_WIDTH = 620
LIST_HEIGHT = 240
RESULTS, CACHE = "results", "cache"


def _duration(seconds: float) -> str:
    total = int(seconds)
    if total <= 0:
        return "--:--"
    hours, rest = divmod(total, 3600)
    minutes, remainder = divmod(rest, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{remainder:02d}"
    return f"{minutes:02d}:{remainder:02d}"


def _size(bytes_: int) -> str:
    megabytes = bytes_ / (1024 * 1024)
    return f"{megabytes:.1f} MB" if megabytes >= 0.1 else f"{bytes_} B"


def _describe(track: Track) -> str:
    parts = [track.title]
    if track.uploader:
        parts.append(track.uploader)
    parts.append(_duration(track.duration))
    return "  ·  ".join(parts)


class DownloadDialog(MessageBoxBase):
    """Fetch one link, or pick from what has already been fetched.

    A keyword goes to YouTube's search and lists candidates to choose from; a
    link is fetched directly, which is also the only way to reach a YouTube
    Music track, since its search does not answer with songs.
    """

    def __init__(self, parent=None, multiple: bool = False):
        super().__init__(parent)
        self.cache = DownloadCache()
        self.runner = DownloadRunner(self)
        self.results: tuple[Track, ...] = ()
        self.chosen: list[Path] = []
        self.closing = False

        self.widget.setMinimumWidth(DIALOG_WIDTH)
        self.title = SubtitleLabel()
        self.hint = CaptionLabel()
        self.hint.setWordWrap(True)
        self.viewLayout.addWidget(self.title)
        self.viewLayout.addWidget(self.hint)

        query_row = QHBoxLayout()
        self.query = LineEdit()
        self.query.setClearButtonEnabled(True)
        self.fetch_button = PushButton(FluentIcon.CLOUD_DOWNLOAD, "")
        query_row.addWidget(self.query, 1)
        query_row.addWidget(self.fetch_button)
        self.viewLayout.addLayout(query_row)

        self.tabs = SegmentedWidget(self)
        self.tabs.addItem(RESULTS, "", lambda: self._show(RESULTS), FluentIcon.SEARCH)
        self.tabs.addItem(CACHE, "", lambda: self._show(CACHE), FluentIcon.FOLDER)
        self.viewLayout.addWidget(self.tabs)

        selection = (
            QAbstractItemView.SelectionMode.ExtendedSelection
            if multiple
            else QAbstractItemView.SelectionMode.SingleSelection
        )
        self.result_list = ListWidget()
        self.cached_list = ListWidget()
        self.cached_list.setSelectionMode(selection)
        for view in (self.result_list, self.cached_list):
            view.setMinimumHeight(LIST_HEIGHT)
        self.stack = QStackedWidget(self)
        self.stack.addWidget(self.result_list)
        self.stack.addWidget(self.cached_list)
        self.viewLayout.addWidget(self.stack)

        actions = QHBoxLayout()
        self.remove_button = PushButton(FluentIcon.DELETE, "")
        self.folder_button = PushButton(FluentIcon.FOLDER, "")
        self.stop_button = PushButton(FluentIcon.CANCEL, "")
        self.stop_button.setEnabled(False)
        actions.addWidget(self.remove_button)
        actions.addWidget(self.folder_button)
        actions.addStretch()
        actions.addWidget(self.stop_button)
        self.viewLayout.addLayout(actions)

        self.status = BodyLabel()
        self.status.setWordWrap(True)
        self.progress = ProgressBar()
        self.viewLayout.addWidget(self.status)
        self.viewLayout.addWidget(self.progress)

        self.query.returnPressed.connect(self._fetch_requested)
        self.fetch_button.clicked.connect(self._fetch_requested)
        self.query.textChanged.connect(self._retranslate_fetch_button)
        self.result_list.itemDoubleClicked.connect(lambda _item: self._download_selected_result())
        self.cached_list.itemDoubleClicked.connect(lambda _item: self.yesButton.click())
        self.remove_button.clicked.connect(self._remove_selected)
        self.folder_button.clicked.connect(self._open_folder)
        self.stop_button.clicked.connect(self.runner.cancel)
        self.runner.results.connect(self._searched)
        self.runner.fetched.connect(self._downloaded)
        self.runner.progress.connect(self._progress)
        self.runner.failed.connect(self._failed)
        self.runner.cancelled.connect(self._cancelled)
        self.runner.finished.connect(self._finished)

        self.retranslate()
        self._fill_cache()
        self._show(CACHE if self.cache.entries() else RESULTS)

    def retranslate(self) -> None:
        self.title.setText(tr("download_title"))
        self.hint.setText(
            tr("download_hint")
            if ffmpeg_available()
            else tr("download_hint") + " " + tr("download_no_ffmpeg")
        )
        self.query.setPlaceholderText(tr("download_input_hint"))
        self.tabs.setItemText(RESULTS, tr("download_tab_results"))
        self.tabs.setItemText(CACHE, tr("download_tab_cache"))
        self.remove_button.setText(tr("download_remove"))
        self.folder_button.setText(tr("download_open_folder"))
        self.stop_button.setText(tr("cancel"))
        self.yesButton.setText(tr("download_use"))
        self.cancelButton.setText(tr("close"))
        self.status.setText(tr("download_ready"))
        self._retranslate_fetch_button()

    def _retranslate_fetch_button(self) -> None:
        """Name the button after what the field currently holds."""
        text = self.query.text().strip()
        self.fetch_button.setText(
            tr("download_fetch") if not text or looks_like_url(text) else tr("download_search")
        )

    def _show(self, route: str) -> None:
        self.tabs.setCurrentItem(route)
        self.stack.setCurrentWidget(self.result_list if route == RESULTS else self.cached_list)
        self._sync_actions()

    def _sync_actions(self) -> None:
        """Only a cached file can be removed or used, and only while idle.

        Accepting mid-download would close the dialog over a running thread,
        which is the one way its parent can take the thread down with it.
        """
        ready = self.tabs.currentRouteKey() == CACHE and not self.runner.running
        self.remove_button.setEnabled(ready)
        self.yesButton.setEnabled(ready)

    def _fill_cache(self) -> None:
        self.cached_list.clear()
        for entry in self.cache.entries():
            item = QListWidgetItem(f"{_describe(entry.track)}  ·  {_size(entry.size)}")
            item.setData(Qt.ItemDataRole.UserRole, str(entry.path))
            item.setToolTip(f"{entry.track.url}\n{entry.path}")
            self.cached_list.addItem(item)
        self.tabs.setItemText(CACHE, f"{tr('download_tab_cache')} ({self.cached_list.count()})")

    def _fetch_requested(self) -> None:
        text = self.query.text().strip()
        if not text:
            self.status.setText(tr("download_need_input"))
            return
        if self.runner.running:
            self.status.setText(tr("download_busy"))
            return
        if not looks_like_url(text):
            self.status.setText(tr("download_searching"))
            self._set_busy(True)
            self.runner.search(text, SEARCH_LIMIT)
            return
        self._download(text)

    def _download(self, url: str) -> None:
        if (existing := self.cache.find(url)) is not None:
            # Already on disk: show it rather than fetching the same bytes twice.
            self.status.setText(tr("download_already"))
            self._select_cached(existing.path)
            return
        self.progress.setValue(0)
        self._set_busy(True)
        self.runner.fetch(url, self.cache.directory)

    def _download_selected_result(self) -> None:
        row = self.result_list.currentRow()
        if row < 0 or row >= len(self.results):
            self.status.setText(tr("download_need_selection"))
            return
        if self.runner.running:
            self.status.setText(tr("download_busy"))
            return
        self._download(self.results[row].url)

    def _searched(self, results: object) -> None:
        self.results = tuple(results) if isinstance(results, tuple) else ()
        self.result_list.clear()
        for track in self.results:
            item = QListWidgetItem(_describe(track))
            item.setToolTip(track.url)
            self.result_list.addItem(item)
        self._show(RESULTS)
        if not self.results:
            self.status.setText(tr("download_no_results"))
            return
        self.result_list.setCurrentRow(0)
        self.status.setText(tr("download_results_found", count=len(self.results)))

    def _downloaded(self, fetched: object) -> None:
        if not isinstance(fetched, FetchedTrack):
            return
        entry = self.cache.remember(fetched)
        self._fill_cache()
        self._select_cached(entry.path)

    def _select_cached(self, path: Path) -> None:
        """Show the cached list with `path` selected, ready to be used."""
        self._show(CACHE)
        for row in range(self.cached_list.count()):
            item = self.cached_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == str(path):
                self.cached_list.setCurrentItem(item)
                break

    def _progress(self, value: int, message: str) -> None:
        self.progress.setValue(value)
        self.status.setText(message)

    def _failed(self, message: str) -> None:
        self.progress.setValue(0)
        self.status.setText(tr("download_failed", msg=message))

    def _cancelled(self) -> None:
        self.progress.setValue(0)
        self.status.setText(tr("download_cancelled"))

    def _finished(self) -> None:
        self._set_busy(False)
        if self.closing:
            super().reject()

    def _set_busy(self, busy: bool) -> None:
        self.stop_button.setEnabled(busy)
        self.fetch_button.setEnabled(not busy)
        self.query.setEnabled(not busy)
        self._sync_actions()

    def _remove_selected(self) -> None:
        """Forget the selected downloads and delete the files behind them."""
        paths = {Path(str(item.data(Qt.ItemDataRole.UserRole))) for item in self.selected_items()}
        if not paths:
            self.status.setText(tr("download_need_selection"))
            return
        for entry in self.cache.entries():
            if entry.path in paths:
                self.cache.forget(entry, delete_file=True)
        self._fill_cache()
        self.status.setText(tr("download_removed", count=len(paths)))

    def _open_folder(self) -> None:
        self.cache.directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.cache.directory)))

    def selected_items(self) -> list[QListWidgetItem]:
        return list(self.cached_list.selectedItems())

    def selected_paths(self) -> list[Path]:
        """The cached files the dialog was accepted with."""
        return list(self.chosen)

    def validate(self) -> bool:
        """Only close on a selection that still points at a file."""
        chosen = [
            path
            for item in self.selected_items()
            if (path := Path(str(item.data(Qt.ItemDataRole.UserRole)))).is_file()
        ]
        if not chosen:
            self.status.setText(tr("download_need_selection"))
            return False
        self.chosen = chosen
        return True

    def reject(self) -> None:
        """Close, or ask a running download to stop and close once it has.

        Cancellation is cooperative here as everywhere else, so the dialog
        waits for the thread the way the window waits for a running job —
        blocking on it instead would freeze the interface that asked.
        """
        if self.runner.running:
            self.closing = True
            self.runner.cancel()
            # Say so: a dialog that swallows the close it was given reads as
            # frozen, and stopping takes as long as the site takes to answer.
            self.status.setText(tr("download_stopping"))
            self.cancelButton.setEnabled(False)
            return
        super().reject()
