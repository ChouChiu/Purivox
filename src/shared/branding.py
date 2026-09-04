from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtGui import QIcon

APPLICATION_NAME = "Purivox"
ORGANIZATION_NAME = "Purivox"

_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def user_agent() -> str:
    """Identify the application to a server from Qt's metadata, not a literal."""
    from PySide6.QtCore import QCoreApplication

    name = QCoreApplication.applicationName() or APPLICATION_NAME
    version = QCoreApplication.applicationVersion()
    return f"{name}/{version}" if version else name


def application_icon() -> QIcon:
    # Imported here so the CLI can read the application identity above without
    # pulling QtGui and QtSvg into a run that never opens a window.
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer

    from resources import resource_path

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
