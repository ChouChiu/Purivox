from __future__ import annotations

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import BodyLabel, LineEdit, PushButton

from shared.ui import (
    FormCard,
    Lane,
    LayoutMode,
    ResponsiveColumns,
    layout_metrics,
    layout_mode,
)
from shared.ui.responsive import (
    HALF_MAX_WIDTH,
    LANDSCAPE_MAX_WIDTH,
    PORTRAIT_MAX_WIDTH,
    SHORT_HEIGHT,
)


@pytest.mark.parametrize(
    ("width", "expected"),
    [
        (360, LayoutMode.PORTRAIT),
        (PORTRAIT_MAX_WIDTH - 1, LayoutMode.PORTRAIT),
        (PORTRAIT_MAX_WIDTH, LayoutMode.HALF),
        (HALF_MAX_WIDTH - 1, LayoutMode.HALF),
        (HALF_MAX_WIDTH, LayoutMode.LANDSCAPE),
        (LANDSCAPE_MAX_WIDTH - 1, LayoutMode.LANDSCAPE),
        (LANDSCAPE_MAX_WIDTH, LayoutMode.ULTRAWIDE),
        (3440, LayoutMode.ULTRAWIDE),
    ],
)
def test_layout_mode_follows_width(width: int, expected: LayoutMode):
    assert layout_mode(width) is expected


def test_a_portrait_screen_is_classified_by_its_width_not_its_shape():
    """A tall 800 px window still has room for a label beside its control."""
    tall = layout_metrics(QSize(800, 1600))
    wide = layout_metrics(QSize(800, 600))

    assert tall.mode is wide.mode is LayoutMode.HALF
    assert not tall.stacked_rows


def test_only_an_ultrawide_page_splits_into_two_lanes():
    assert layout_metrics(QSize(1280, 800)).columns == 1
    assert layout_metrics(QSize(2560, 1080)).columns == 2


def test_a_short_window_trims_vertical_space_at_any_width():
    assert layout_metrics(QSize(1280, SHORT_HEIGHT - 1)).short
    assert not layout_metrics(QSize(1280, SHORT_HEIGHT)).short
    tall, short = (layout_metrics(QSize(1280, height)) for height in (900, 500))
    assert short.page_margins[1] < tall.page_margins[1]


def test_tiles_reflow_from_four_columns_down_to_two():
    columns = [layout_metrics(QSize(width, 900)).tile_columns for width in (500, 800, 1200, 2560)]
    assert columns == [2, 3, 4, 4]


def test_columns_keep_declaration_order_in_one_lane(qtbot):
    columns = ResponsiveColumns()
    qtbot.addWidget(columns)
    first, second, third = (QWidget(), QWidget(), QWidget())
    columns.add(first, Lane.PRIMARY)
    columns.add(second, Lane.SECONDARY)
    columns.add(third, Lane.PRIMARY)

    assert columns.lane_widgets(Lane.PRIMARY) == (first, second, third)
    assert columns.lane_widgets(Lane.SECONDARY) == ()

    columns.set_columns(2)

    assert columns.lane_widgets(Lane.PRIMARY) == (first, third)
    assert columns.lane_widgets(Lane.SECONDARY) == (second,)

    columns.set_columns(1)

    assert columns.lane_widgets(Lane.PRIMARY) == (first, second, third)


def _settle(card: FormCard) -> None:
    card.layout.invalidate()
    card.layout.activate()
    QApplication.processEvents()


def test_a_folded_row_puts_its_label_above_the_control(qtbot):
    card = FormCard()
    qtbot.addWidget(card)
    label, control, button = BodyLabel(), LineEdit(), PushButton()
    row = card.add_row(label, control, button)
    card.resize(600, 200)
    card.show()
    qtbot.waitExposed(card)

    row.apply_layout(layout_metrics(QSize(1280, 900)))
    _settle(card)
    assert not row.is_folded()
    assert label.mapTo(row, label.rect().center()).y() == pytest.approx(
        control.mapTo(row, control.rect().center()).y(), abs=6
    )
    assert (
        label.mapTo(row, label.rect().topLeft()).x()
        < control.mapTo(row, control.rect().topLeft()).x()
    )

    row.apply_layout(layout_metrics(QSize(420, 900)))
    _settle(card)
    assert row.is_folded()
    assert (
        label.mapTo(row, label.rect().bottomLeft()).y()
        <= control.mapTo(row, control.rect().topLeft()).y()
    )


def test_a_card_gives_back_padding_when_the_window_is_narrow(qtbot):
    card = FormCard()
    qtbot.addWidget(card)

    card.apply_layout(layout_metrics(QSize(1280, 900)))
    roomy = card.layout.getContentsMargins()
    card.apply_layout(layout_metrics(QSize(420, 900)))

    assert card.layout.getContentsMargins() < roomy
