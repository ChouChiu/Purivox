from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from features.reference_removal.preview import SeekSlider


@pytest.fixture
def slider(qtbot) -> SeekSlider:
    slider = SeekSlider(Qt.Orientation.Horizontal)
    qtbot.addWidget(slider)
    slider.setRange(0, 10_000)
    slider.setFixedWidth(400)
    slider.show()
    qtbot.waitExposed(slider)
    QApplication.processEvents()
    return slider


def test_a_click_on_the_groove_seeks_straight_to_it(qtbot, slider: SeekSlider):
    """A stock slider only pages towards the click; a seek bar jumps there."""
    requested: list[int] = []
    slider.seek_requested.connect(requested.append)

    qtbot.mouseClick(
        slider,
        Qt.MouseButton.LeftButton,
        pos=QPoint(3 * slider.width() // 4, slider.height() // 2),
    )

    assert requested == [slider.value()]
    assert requested[0] == pytest.approx(7_500, abs=600)


def test_a_press_on_the_handle_is_left_to_the_drag(qtbot, slider: SeekSlider):
    """The page seeks once the drag is released; the press must not seek as well."""
    slider.setValue(5_000)
    requested: list[int] = []
    slider.seek_requested.connect(requested.append)
    centre = QPoint(slider.width() // 2, slider.height() // 2)

    qtbot.mousePress(slider, Qt.MouseButton.LeftButton, pos=centre)
    qtbot.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=centre)

    assert requested == []
