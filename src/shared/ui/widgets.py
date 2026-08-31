"""The plain widgets a page is assembled from, and the filters it opens.

Each one is a small correction to what Fluent or Qt gives us: a combo box
whose popup does not depend on the platform's window opacity, fields that
take an audio file dragged onto them, and the filters the file dialogs are
opened with.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from qfluentwidgets import ComboBox, LineEdit, ListWidget, MenuAnimationType
from qfluentwidgets.components.widgets.combo_box import ComboBoxMenu
from qfluentwidgets.components.widgets.menu import MenuAnimationManager

from shared.audio import AUDIO_EXTENSIONS

AUDIO_FILE_FILTER = "Audio (" + " ".join(f"*{suffix}" for suffix in AUDIO_EXTENSIONS) + ")"
WAV_FILE_FILTER = "WAV (*.wav)"


class SmoothComboBoxMenu(ComboBoxMenu):
    """Combo menu positioned by Fluent without a platform-dependent animation."""

    def exec(
        self,
        pos,
        ani: bool = True,
        aniType: MenuAnimationType = MenuAnimationType.DROP_DOWN,
    ):
        # QFluentWidgets' slide animation looks distorted for long menus, while
        # its fade variant repeatedly calls setWindowOpacity(), which is not
        # supported by every Qt platform plugin.  Use the requested direction
        # only to calculate the final position, then explicitly select Fluent's
        # no-animation manager for display.
        self.view.adjustSize(pos, aniType)
        self.adjustSize()
        position_manager = MenuAnimationManager.make(self, aniType)
        end_position = position_manager._endPosition(pos)
        self.aniManager = MenuAnimationManager.make(self, MenuAnimationType.NONE)
        self.move(end_position)
        self.clearMask()
        self.show()
        return None


class SmoothComboBox(ComboBox):
    """Project combo box with a stable, immediate popup."""

    def _createComboMenu(self):
        return SmoothComboBoxMenu(self)


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
