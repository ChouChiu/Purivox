from __future__ import annotations

import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import BodyLabel, LineEdit, ProgressBar, PushButton

from shared.ui import (
    ElidedLabel,
    FormCard,
    Lane,
    LayoutMode,
    PageScrollArea,
    ResponsiveColumns,
    allow_shrinking,
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


LONG_STATUS = (
    "processing finished, saved to /home/singer/Videos/MR/2026 KWDA awards stage backing/"
    "R14 - Hit 'Em_vocals.wav"
)


def _status_page(
    qtbot, size: QSize, status: BodyLabel
) -> tuple[PageScrollArea, FormCard, ProgressBar]:
    """A page with one status card, the shape a running job leaves behind."""
    page = PageScrollArea()
    qtbot.addWidget(page)
    card = FormCard("状态")
    progress = ProgressBar()
    card.layout.addWidget(status)
    card.layout.addWidget(progress)
    page.add_card(card, Lane.SECONDARY)
    page.resize(size)
    page.show()
    qtbot.waitExposed(page)
    return page, card, progress


def _flush() -> None:
    for _ in range(3):
        QApplication.processEvents()


def _wrapping_label() -> BodyLabel:
    label = BodyLabel()
    label.setWordWrap(True)
    allow_shrinking(label)
    return label


def _shown(label: ElidedLabel) -> str:
    """What the label paints, as opposed to the text it was given."""
    return BodyLabel.text(label)


@pytest.mark.parametrize("size", [QSize(700, 500), QSize(420, 700), QSize(1600, 900)])
def test_a_card_grows_for_the_wrapped_text_it_is_given(qtbot, size: QSize):
    """Wrapped prose takes its second line inside the card, not over its edge."""
    text = _wrapping_label()
    _, card, progress = _status_page(qtbot, size, text)

    text.setText(LONG_STATUS)
    _flush()

    wrapped = text.heightForWidth(text.width())
    assert wrapped > text.fontMetrics().height()  # the text really does take a second line
    assert text.height() >= wrapped
    assert progress.y() >= text.y() + wrapped
    assert card.height() >= progress.y() + progress.height()


def test_a_card_without_wrapping_content_keeps_its_own_height(qtbot):
    """Only a card that can answer for its height claims to depend on width."""
    page = PageScrollArea()
    qtbot.addWidget(page)
    card = FormCard("参数")
    card.layout.addWidget(ProgressBar())
    page.add_card(card)
    page.resize(700, 500)
    page.show()
    qtbot.waitExposed(page)
    _flush()

    assert not card.sizePolicy().hasHeightForWidth()
    assert card.height() >= card.minimumSizeHint().height()


def test_a_shrinking_label_still_asks_for_the_height_its_text_needs(qtbot):
    label = BodyLabel(LONG_STATUS)
    qtbot.addWidget(label)
    label.setWordWrap(True)

    allow_shrinking(label)

    assert label.sizePolicy().hasHeightForWidth()


@pytest.mark.parametrize("size", [QSize(700, 500), QSize(420, 700), QSize(1600, 900)])
def test_a_long_status_is_cut_short_instead_of_taking_a_second_line(qtbot, size: QSize):
    """A result path is longer than any card is wide, at every window shape."""
    status = ElidedLabel()
    page, _, progress = _status_page(qtbot, size, status)

    status.setText(LONG_STATUS)
    _flush()

    assert _shown(status).endswith("…")
    assert status.fontMetrics().horizontalAdvance(_shown(status)) <= status.width()
    assert status.height() <= status.fontMetrics().height() + 4
    assert progress.y() >= status.y() + status.height()
    assert page.content.sizeHint().width() <= page.viewport().width()
    # Cut on the way out only: the path stays readable from code and on hover.
    assert status.text() == status.toolTip() == LONG_STATUS


def test_a_status_line_is_re_cut_for_the_width_it_has(qtbot):
    status = ElidedLabel()
    page, _, _ = _status_page(qtbot, QSize(900, 500), status)
    status.setText(LONG_STATUS)
    _flush()
    roomy = _shown(status)

    page.resize(420, 500)
    _flush()
    assert len(_shown(status)) < len(roomy)

    status.setText("就绪")
    _flush()

    assert _shown(status) == "就绪"
    assert status.toolTip() == ""
