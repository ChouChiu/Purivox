from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import CardWidget, ScrollArea, StrongBodyLabel

from shared.ui.responsive import (
    CONTENT_MAX_WIDTH,
    FoldingRow,
    Lane,
    LayoutMetrics,
    Responsive,
    ResponsiveColumns,
    layout_metrics,
)

LABEL_COLUMN_WIDTH = 110


class FormCard(Responsive, CardWidget):
    def __init__(self, title: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(20, 18, 20, 18)
        self.layout.setSpacing(14)
        self.title_label = StrongBodyLabel(title, self)
        self.layout.addWidget(self.title_label)

    def add_row(self, label: QWidget, control: QWidget, *extras: QWidget) -> FoldingRow:
        row = FoldingRow(self)
        row.set_lead_minimum_width(LABEL_COLUMN_WIDTH)
        row.add_lead(label)
        row.add_trail(control, 1)
        for extra in extras:
            row.add_trail(extra)
        self.layout.addWidget(row)
        return row

    def apply_layout(self, metrics: LayoutMetrics) -> None:
        self.layout.setContentsMargins(*metrics.card_margins)
        self.layout.setSpacing(metrics.card_spacing)


class PageScrollArea(ScrollArea):
    """A page that lays itself out for the shape of the window it is shown in.

    The page measures its own viewport, keeps the content column from growing
    past `CONTENT_MAX_WIDTH` on a very wide screen — centring it instead of
    stretching a form to arm's length — and hands the resulting metrics to
    every `Responsive` widget it contains.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("QScrollArea{background: transparent; border: none}")
        self.content = QWidget(self)
        self.content.setStyleSheet("QWidget{background: transparent}")
        self.layout = QVBoxLayout(self.content)
        self.layout.setContentsMargins(36, 28, 36, 28)
        self.layout.setSpacing(16)
        self.setWidget(self.content)
        self.columns = ResponsiveColumns(self.content)
        self.metrics = layout_metrics(self.viewport().size())

    def add_card(self, card: QWidget, lane: Lane = Lane.PRIMARY) -> None:
        """Place a card in the page's lane container, creating it on first use.

        Deferring the container keeps it below whatever header the page has
        already added, and above the action row a page adds afterwards.
        """
        if self.layout.indexOf(self.columns) < 0:
            self.layout.addWidget(self.columns)
        self.columns.add(card, lane)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.update_layout()

    def update_layout(self) -> None:
        metrics = layout_metrics(self.viewport().size())
        changed = metrics.key != self.metrics.key
        self.metrics = metrics
        if changed:
            self.apply_layout(metrics)
        self._centre_content(metrics)

    def apply_layout(self, metrics: LayoutMetrics) -> None:
        self.layout.setSpacing(metrics.page_spacing)
        self.columns.set_columns(metrics.columns)
        self.columns.set_spacing(metrics.page_spacing)
        for child in self.content.findChildren(QWidget):
            if isinstance(child, Responsive):
                child.apply_layout(metrics)

    def _centre_content(self, metrics: LayoutMetrics) -> None:
        left, top, right, bottom = metrics.page_margins
        overflow = metrics.width - left - right - CONTENT_MAX_WIDTH
        # Round the gutter up so an odd leftover pixel narrows the column
        # rather than pushing it past the cap.
        gutter = (max(0, overflow) + 1) // 2
        margins = (left + gutter, top, right + gutter, bottom)
        if self.layout.getContentsMargins() != margins:
            self.layout.setContentsMargins(*margins)
