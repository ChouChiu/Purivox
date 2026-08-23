from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from resources import resource_path

_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def application_icon() -> QIcon:
    renderer = QSvgRenderer(str(resource_path("purivox.svg")))
    if not renderer.isValid():
        return QIcon()

    icon = QIcon()
    for size in _ICON_SIZES:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        icon.addPixmap(pixmap)
    return icon
