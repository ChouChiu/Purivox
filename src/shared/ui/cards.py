from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, ProgressBar, ScrollArea, StrongBodyLabel

from shared.i18n import tr
from shared.ui.responsive import (
    CONTENT_MAX_WIDTH,
    ElidedLabel,
    FoldingRow,
    HeightForWidth,
    Lane,
    LayoutMetrics,
    Responsive,
    ResponsiveColumns,
    layout_metrics,
)

LABEL_COLUMN_WIDTH = 110
# The widest the status clock reads before it is showing hours, so the status
# line does not re-elide itself every time the tenth of a second rolls over.
CLOCK_SAMPLE = "00:00.000"


def format_clock(seconds: float, *, millis: bool = False) -> str:
    """Minutes and seconds, or hours once a take runs that long.

    One formatter for every readout in the interface: the status card's clock
    takes `millis` because the difference between two runs is a few hundred of
    them, and the preview's position and duration stay whole seconds.
    """
    total_millis = max(0, round(seconds * 1000))
    total_seconds, remainder = divmod(total_millis, 1000)
    hours, rest = divmod(total_seconds, 3600)
    minutes, secs = divmod(rest, 60)
    stamp = f"{minutes:02d}:{secs:02d}"
    if millis:
        stamp = f"{stamp}.{remainder:03d}"
    return f"{hours}:{stamp}" if hours else stamp


class FormCard(Responsive, HeightForWidth, CardWidget):
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


class PageContent(HeightForWidth, QWidget):
    """The single widget a `PageScrollArea` scrolls, holding every card."""


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
        self.content = PageContent(self)
        self.content.setStyleSheet("QWidget{background: transparent}")
        self.layout = QVBoxLayout(self.content)
        self.layout.setContentsMargins(36, 28, 36, 28)
        self.layout.setSpacing(16)
        self.setWidget(self.content)
        self.columns = ResponsiveColumns(self.content)
        self.metrics = layout_metrics(self.viewport().size())

    def add_status_card(self) -> None:
        """Add the status line, its clock and the progress bar a job reports through.

        `JobPresenter` reads these widgets back by name from any page that runs
        jobs, so the card that holds them is built here, in the secondary lane.
        The clock shares the status line, at its right edge, and is held to the
        width of an hour so a running job never re-elides the text beside it.
        """
        self.status_card = FormCard()
        self.status = ElidedLabel()
        self.elapsed = BodyLabel()
        self.elapsed.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.elapsed.setMinimumWidth(self.elapsed.fontMetrics().horizontalAdvance(CLOCK_SAMPLE))
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(12)
        status_row.addWidget(self.status, 1)
        status_row.addWidget(self.elapsed)
        self.progress = ProgressBar()
        self.status_card.layout.addLayout(status_row)
        self.status_card.layout.addWidget(self.progress)
        self.add_card(self.status_card, Lane.SECONDARY)
        self._elapsed_started: float | None = None
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(100)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

    def start_clock(self) -> None:
        """Restart the clock for a job that is starting, from zero."""
        self._elapsed_started = time.monotonic()
        self.elapsed.setText(format_clock(0.0, millis=True))
        self._elapsed_timer.start()

    def stop_clock(self) -> None:
        """Freeze the clock on the total the job took."""
        self._elapsed_timer.stop()
        self._tick_elapsed()
        self._elapsed_started = None

    def _tick_elapsed(self) -> None:
        if self._elapsed_started is not None:
            elapsed = time.monotonic() - self._elapsed_started
            self.elapsed.setText(format_clock(elapsed, millis=True))

    def retranslate_status_card(self) -> None:
        self.status_card.title_label.setText(tr("status_group"))

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
