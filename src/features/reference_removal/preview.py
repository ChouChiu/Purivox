from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QStyle, QStyleOptionSlider
from qfluentwidgets import Slider


class SeekSlider(Slider):
    """Slider that seeks directly when the user clicks its groove."""

    seek_requested = Signal(int)

    def _value_at(self, point: QPoint) -> int:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )
        if self.orientation() == Qt.Orientation.Horizontal:
            slider_length = handle.width()
            slider_minimum = groove.left()
            slider_maximum = groove.right() - slider_length + 1
            position = point.x() - slider_length // 2
        else:
            slider_length = handle.height()
            slider_minimum = groove.top()
            slider_maximum = groove.bottom() - slider_length + 1
            position = point.y() - slider_length // 2
        return QStyle.sliderValueFromPosition(
            self.minimum(),
            self.maximum(),
            position - slider_minimum,
            max(slider_maximum - slider_minimum, 0),
            option.upsideDown,
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            option,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )
        point = event.position().toPoint()
        if handle.contains(point):
            super().mousePressEvent(event)
            return
        value = self._value_at(point)
        self.setValue(value)
        self.seek_requested.emit(value)
        event.accept()
