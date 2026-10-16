from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint
from qfluentwidgets import MenuAnimationType
from qfluentwidgets.components.widgets.menu import DummyMenuAnimationManager

from shared.ui import SmoothComboBox, SmoothComboBoxMenu, normalized_wav_path


def test_the_combo_menu_opens_without_an_opacity_animation(qtbot):
    """Fluent's fade calls setWindowOpacity, which not every platform plugin supports."""
    combo = SmoothComboBox()
    qtbot.addWidget(combo)
    menu = combo._createComboMenu()
    assert isinstance(menu, SmoothComboBoxMenu)

    menu.exec(QPoint(0, combo.height()), aniType=MenuAnimationType.PULL_UP)

    assert isinstance(menu.aniManager, DummyMenuAnimationManager)
    menu.close()


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("", "show_vocals.wav"),
        ("mine", "mine.wav"),
        ("mine.flac", "mine.wav"),
        ("sub/mine.WAV", "sub/mine.WAV"),
    ],
)
def test_an_output_field_resolves_beside_the_recording(tmp_path: Path, typed: str, expected: str):
    recording = tmp_path / "show.m4a"

    path = normalized_wav_path(typed, str(recording), "_vocals.wav")

    assert path == (tmp_path / expected).resolve()


def test_an_absolute_output_stays_where_it_was_named(tmp_path: Path):
    elsewhere = tmp_path / "elsewhere" / "result.wav"
    assert normalized_wav_path(str(elsewhere), str(tmp_path / "show.wav"), "_vocals.wav") == (
        elsewhere.resolve()
    )


def test_an_empty_field_with_nothing_to_name_it_after_is_left_empty():
    assert normalized_wav_path("  ", "", "_vocals.wav") is None
