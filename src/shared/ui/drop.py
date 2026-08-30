from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from qfluentwidgets import LineEdit, ListWidget

from shared.audio import AUDIO_EXTENSIONS


def dropped_audio_paths(mime: QMimeData) -> list[Path]:
    """Local audio files carried by a drag, in the order the drag lists them."""
    if not mime.hasUrls():
        return []
    paths: list[Path] = []
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = Path(url.toLocalFile())
        if path.suffix.casefold() in AUDIO_EXTENSIONS:
            paths.append(path)
    return paths


def _offer(event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> list[Path]:
    """Accept a drag only while it carries audio this application can open."""
    paths = dropped_audio_paths(event.mimeData())
    if paths:
        event.acceptProposedAction()
    else:
        event.ignore()
    return paths


class AudioDropLineEdit(LineEdit):
    """Read-only path field that also accepts one audio file by drag and drop."""

    file_dropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        _offer(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        _offer(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = _offer(event)
        if paths:
            self.file_dropped.emit(str(paths[0]))


class AudioDropListWidget(ListWidget):
    """Source list that accepts any number of audio files by drag and drop."""

    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        _offer(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        _offer(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = _offer(event)
        if paths:
            self.files_dropped.emit([str(path) for path in paths])
