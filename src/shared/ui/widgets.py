"""The plain widgets a page is assembled from, and the filters it opens.

Each one is a small correction to what Fluent or Qt gives us: a combo box whose
popup does not depend on the platform's window opacity, the filters the file
dialogs are opened with, and the rules an output field is read by.
"""

from __future__ import annotations

from pathlib import Path

from qfluentwidgets import ComboBox, MenuAnimationType
from qfluentwidgets.components.widgets.combo_box import ComboBoxMenu
from qfluentwidgets.components.widgets.menu import MenuAnimationManager

from shared.audio import AUDIO_EXTENSIONS

AUDIO_FILE_FILTER = "Audio (" + " ".join(f"*{suffix}" for suffix in AUDIO_EXTENSIONS) + ")"
WAV_FILE_FILTER = "WAV (*.wav)"


def normalized_wav_path(text: str, source: str, default_suffix: str) -> Path | None:
    """Resolve what an output field holds into an absolute `.wav` path.

    Both reference pages offer the same field with the same rules — an empty one
    is named after the input, a bare filename lands beside it, and any other
    extension becomes `.wav` — so the rules live here rather than once per page.
    Returns `None` when the field is empty and there is no input to name it
    after.
    """
    text, source = text.strip(), source.strip()
    if text:
        path = Path(text).expanduser()
    elif source:
        origin = Path(source).expanduser().resolve()
        path = origin.with_name(origin.stem + default_suffix)
    else:
        return None
    if path.suffix.lower() != ".wav":
        path = path.with_suffix(".wav")
    if not path.is_absolute():
        base = Path(source).expanduser().resolve().parent if source else Path.cwd()
        path = base / path
    return path.resolve()


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
