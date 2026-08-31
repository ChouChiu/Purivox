"""Window-shape breakpoints and the containers that react to them.

One `LayoutMode` names each window shape the application is expected to be
used in, keyed off the width a page actually has to spend:

| mode        | page width | what changes                                    |
|-------------|------------|-------------------------------------------------|
| `PORTRAIT`  | < 620      | one column, labels above their controls         |
| `HALF`      | < 960      | one column, labels beside their controls        |
| `LANDSCAPE` | < 1440     | one column, full margins                        |
| `ULTRAWIDE` | >= 1440    | two lanes, capped and centred                   |

Width alone decides the mode: a tall 800 px window is a portrait *screen* but
still has room for a label beside its control, so it lays out like a half
screen rather than like a phone. Height only trims vertical breathing space,
through `LayoutMetrics.short`.

Pages never watch their own children: `PageScrollArea` measures its viewport
and hands the metrics down to every `Responsive` widget below it, so a control
folds because the *page* is narrow, not because it was already squeezed.

Height is the one thing a width cannot settle on its own: a wrapped status
line needs two lines here and three a breakpoint down. Qt puts that question
to a *widget*, never to the layout inside it, so `HeightForWidth` carries the
answer up from the label to the card and out to the page.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel

PORTRAIT_MAX_WIDTH = 620
HALF_MAX_WIDTH = 960
LANDSCAPE_MAX_WIDTH = 1440
SHORT_HEIGHT = 620
CONTENT_MAX_WIDTH = 1760
"""Widest a page column is allowed to grow before it is centred instead."""
UNBOUNDED_WIDTH = 16_777_215
"""Qt's `QWIDGETSIZE_MAX`, the way to clear a maximum PySide6 does not export."""


class LayoutMode(IntEnum):
    PORTRAIT = 0
    HALF = 1
    LANDSCAPE = 2
    ULTRAWIDE = 3


class Lane(IntEnum):
    """Which of the two `ResponsiveColumns` lanes a card prefers."""

    PRIMARY = 0
    SECONDARY = 1


@dataclass(frozen=True, slots=True)
class LayoutMetrics:
    """The window shape a page and its children should lay out for."""

    mode: LayoutMode
    width: int
    height: int

    @property
    def short(self) -> bool:
        """Whether vertical space is tight enough to trim padding for."""
        return self.height < SHORT_HEIGHT

    @property
    def stacked_rows(self) -> bool:
        """Whether a form row should put its label above its control."""
        return self.mode is LayoutMode.PORTRAIT

    @property
    def columns(self) -> int:
        """How many lanes a page splits its cards across."""
        return 2 if self.mode is LayoutMode.ULTRAWIDE else 1

    @property
    def tile_columns(self) -> int:
        """How many fixed-width tiles fit across one card."""
        return (2, 3, 4, 4)[self.mode]

    @property
    def page_margins(self) -> tuple[int, int, int, int]:
        side = (16, 24, 36, 36)[self.mode]
        vertical = 16 if self.short else (16, 20, 28, 28)[self.mode]
        return side, vertical, side, vertical

    @property
    def page_spacing(self) -> int:
        return (12, 14, 16, 16)[self.mode]

    @property
    def card_margins(self) -> tuple[int, int, int, int]:
        side = 14 if self.mode is LayoutMode.PORTRAIT else 20
        vertical = 12 if self.short or self.mode is LayoutMode.PORTRAIT else 18
        return side, vertical, side, vertical

    @property
    def card_spacing(self) -> int:
        return 10 if self.short or self.mode is LayoutMode.PORTRAIT else 14

    @property
    def key(self) -> tuple[LayoutMode, bool]:
        """What a widget re-lays out for; plain width changes are ignored."""
        return self.mode, self.short


def layout_mode(width: int) -> LayoutMode:
    if width < PORTRAIT_MAX_WIDTH:
        return LayoutMode.PORTRAIT
    if width < HALF_MAX_WIDTH:
        return LayoutMode.HALF
    if width < LANDSCAPE_MAX_WIDTH:
        return LayoutMode.LANDSCAPE
    return LayoutMode.ULTRAWIDE


def allow_shrinking(widget: QWidget) -> None:
    """Let a widget be narrowed past its text instead of widening the page.

    Even a word-wrapped label still asks for the width of its longest word, and
    a file path has no spaces to wrap at — one result message would then push
    the whole page wider than the window. An `Ignored` policy hands the width
    decision back to the layout, and the widget wraps or elides inside it.

    The rest of the policy is kept as it was found: a wrapped label announces
    that its height depends on the width it is given, and dropping that would
    leave it one line tall with the rest painted over the card's edge.
    """
    widget.setMinimumWidth(0)
    policy = widget.sizePolicy()
    policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
    widget.setSizePolicy(policy)


class ElidedLabel(BodyLabel):
    """One line of text that ends in an ellipsis rather than wrapping.

    A result path is longer than any card is wide, and wrapping it turns a
    one-line status into three that push everything under it down the page.
    The label keeps the whole text — `text()` still answers with it, and a
    tooltip offers the part that did not fit — and shows as much of it as the
    width the layout gave it can hold.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._full_text = ""
        self.setWordWrap(False)
        allow_shrinking(self)
        self.setText(text)

    def text(self) -> str:
        return self._full_text

    def setText(self, text: str) -> None:
        self._full_text = text
        self._fit_to_width()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_to_width()

    def _fit_to_width(self) -> None:
        elided = self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, self.width()
        )
        super().setText(elided)
        self.setToolTip("" if elided == self._full_text else self._full_text)


def layout_metrics(size: QSize) -> LayoutMetrics:
    width, height = max(size.width(), 0), max(size.height(), 0)
    return LayoutMetrics(layout_mode(width), width, height)


class Responsive:
    """Mixin marking a widget the page re-lays out on a shape change.

    It stays a plain mixin rather than a `QWidget` subclass so that it can be
    mixed into `CardWidget` as easily as into `QWidget`; pages collect the
    widgets to notify with an `isinstance` sweep over their children.
    """

    def apply_layout(self, metrics: LayoutMetrics) -> None:
        raise NotImplementedError


class HeightForWidth:
    """Mixin carrying a wrapped label's height past the widget that holds it.

    Qt asks a *widget's* size policy whether its height depends on its width,
    and never the layout inside it, so a card holding a word-wrapped status
    line is measured at one line and paints the other two over its own edge.
    The mixin re-reads its layout whenever that layout changes and mirrors the
    answer onto the widget's own policy, which is all a parent layout needs to
    start asking for the taller height. A widget with nothing wrapping inside
    it keeps a plain policy: claiming a height-for-width it cannot compute
    would collapse it to nothing.
    """

    def sync_height_for_width(self) -> None:
        # `QWidget.layout` explicitly: a card keeps its own layout under a
        # `layout` attribute, which shadows the method on the instance.
        layout = QWidget.layout(self)
        wanted = layout is not None and layout.hasHeightForWidth()
        policy = self.sizePolicy()
        if policy.hasHeightForWidth() == wanted:
            return
        policy.setHeightForWidth(wanted)
        self.setSizePolicy(policy)
        _resync_enclosing(self)

    def event(self, event: QEvent) -> bool:
        handled = super().event(event)
        if event.type() is QEvent.Type.LayoutRequest:
            self.sync_height_for_width()
        return handled

    def showEvent(self, event: QShowEvent) -> None:
        # A card is filled while it is still hidden, where a layout change
        # posts no request; catch up before the first paint.
        self.sync_height_for_width()
        super().showEvent(event)


def _resync_enclosing(widget: QWidget) -> None:
    """Put the question to the containers above `widget` again.

    A layout is asked once whether anything inside it needs a height for its
    width and then remembers the answer, and a nested lane is not asked again
    just because a card it holds has changed its mind. A widget that only
    learns its own answer when it is filled therefore clears that record and
    carries the answer up itself, one container at a time.
    """
    parent = widget.parentWidget()
    while parent is not None:
        layout = QWidget.layout(parent)
        if layout is not None:
            for nested in layout.findChildren(QLayout):
                nested.invalidate()
            layout.invalidate()
        if isinstance(parent, HeightForWidth):
            parent.sync_height_for_width()
            return
        parent = parent.parentWidget()


class ResponsiveColumns(HeightForWidth, QWidget):
    """Cards stacked in one column, or split across two lanes when asked.

    The lane a card declares only matters once there are two of them; in one
    column the cards keep the order they were added in, so a page reads the
    same top to bottom on a phone-shaped window as it does side by side.
    """

    def __init__(self, parent: QWidget | None = None, spacing: int = 16):
        super().__init__(parent)
        self._entries: list[tuple[QWidget, Lane]] = []
        self._count = 1
        self._spacing = spacing
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._lanes = [QVBoxLayout(), QVBoxLayout()]
        for lane in self._lanes:
            lane.setContentsMargins(0, 0, 0, 0)
            lane.setSpacing(spacing)
            self._row.addLayout(lane, 1)
        self._rebuild()

    def add(self, widget: QWidget, lane: Lane = Lane.PRIMARY) -> None:
        self._entries.append((widget, lane))
        self._rebuild()

    def columns(self) -> int:
        return self._count

    def lane_widgets(self, lane: Lane) -> tuple[QWidget, ...]:
        """The cards currently laid out in one lane, top to bottom."""
        layout = self._lanes[lane]
        items = (layout.itemAt(index) for index in range(layout.count()))
        return tuple(item.widget() for item in items if item.widget() is not None)

    def set_columns(self, count: int) -> None:
        count = 2 if count >= 2 else 1
        if count == self._count:
            return
        self._count = count
        self._rebuild()

    def set_spacing(self, spacing: int) -> None:
        self._spacing = spacing
        for lane in self._lanes:
            lane.setSpacing(spacing)
        self._row.setSpacing(spacing if self._count == 2 else 0)

    def _rebuild(self) -> None:
        for lane in self._lanes:
            while lane.count():
                lane.takeAt(0)
        for widget, lane in self._entries:
            self._lanes[lane if self._count == 2 else Lane.PRIMARY].addWidget(widget)
        for lane in self._lanes:
            lane.addStretch()
        self._row.setSpacing(self._spacing if self._count == 2 else 0)
        self._row.setStretch(0, 1)
        self._row.setStretch(1, 1 if self._count == 2 else 0)


class FoldingRow(Responsive, QWidget):
    """One line of controls that folds onto a second line when space runs out.

    The leading group (a form label, or the transport buttons) keeps the first
    line; the trailing group shares it while the page is wide and drops below
    it in `PORTRAIT`, where a label plus a path field plus a button cannot fit
    side by side without cutting the field down to nothing.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        spacing: int = 12,
        lead_expands: bool = False,
    ):
        super().__init__(parent)
        # Which group claims the slack on an unfolded line: a form row gives it
        # to the control it labels, a transport row keeps its buttons at the
        # left edge and lets the gap push the rest to the right.
        self._lead_expands = lead_expands
        self._folded: bool | None = None
        self._lead_minimum_width = 0
        self._trail_stretches: list[tuple[int, int]] = []
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(spacing)
        self._grid.setVerticalSpacing(6)
        self._lead = QWidget(self)
        self._lead_row = QHBoxLayout(self._lead)
        self._lead_row.setContentsMargins(0, 0, 0, 0)
        self._lead_row.setSpacing(spacing)
        self._trail = QWidget(self)
        self._trail_row = QHBoxLayout(self._trail)
        self._trail_row.setContentsMargins(0, 0, 0, 0)
        self._trail_row.setSpacing(spacing)
        self._set_folded(False)

    def add_lead(self, widget: QWidget, stretch: int = 0) -> None:
        self._lead_row.addWidget(widget, stretch)

    def add_lead_stretch(self) -> None:
        """Push the trailing group to the far edge while the row is unfolded."""
        self._lead_row.addStretch(1)

    def add_trail(
        self, widget: QWidget, stretch: int = 0, folded_stretch: int | None = None
    ) -> None:
        """Append to the trailing group.

        `folded_stretch` lets a control that hugs its label on one line — a
        volume slider beside "Volume" — take the whole width once the group has
        a line of its own.
        """
        self._trail_row.addWidget(widget, stretch)
        self._trail_stretches.append(
            (stretch, stretch if folded_stretch is None else folded_stretch)
        )
        self._apply_trail_stretches()

    def set_lead_minimum_width(self, width: int) -> None:
        """Keep labels in a column while the row is unfolded, not once folded."""
        self._lead_minimum_width = width
        self._lead.setMinimumWidth(0 if self._folded else width)

    def is_folded(self) -> bool:
        return bool(self._folded)

    def apply_layout(self, metrics: LayoutMetrics) -> None:
        self._set_folded(metrics.stacked_rows)

    def _set_folded(self, folded: bool) -> None:
        if folded == self._folded:
            return
        self._folded = folded
        self._grid.removeWidget(self._lead)
        self._grid.removeWidget(self._trail)
        self._grid.addWidget(self._lead, 0, 0)
        if folded:
            self._grid.addWidget(self._trail, 1, 0)
        else:
            self._grid.addWidget(self._trail, 0, 1)
        lead_column = folded or self._lead_expands
        self._grid.setColumnStretch(0, 1 if lead_column else 0)
        self._grid.setColumnStretch(1, 0 if lead_column else 1)
        self._lead.setMinimumWidth(0 if folded else self._lead_minimum_width)
        self._apply_trail_stretches()

    def _apply_trail_stretches(self) -> None:
        for index, (stretch, folded_stretch) in enumerate(self._trail_stretches):
            self._trail_row.setStretch(index, folded_stretch if self._folded else stretch)
