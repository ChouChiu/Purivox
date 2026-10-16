"""The status card's clock: it runs with the job and keeps the total after it."""

from PySide6.QtCore import QSize

from shared.ui import PageScrollArea, format_clock


def test_elapsed_formatting_reads_as_minutes_until_it_needs_hours():
    assert format_clock(0) == "00:00"
    assert format_clock(59.9) == "00:59"
    assert format_clock(61) == "01:01"
    assert format_clock(3661) == "1:01:01"


def test_the_clock_reads_milliseconds_when_it_is_asked_for_them():
    """The gap between two runs of the same job is a few hundred of them."""
    assert format_clock(0, millis=True) == "00:00.000"
    assert format_clock(61.234, millis=True) == "01:01.234"
    assert format_clock(3661.5, millis=True) == "1:01:01.500"


def test_status_clock_runs_with_the_job_and_keeps_its_total(qtbot):
    page = PageScrollArea()
    qtbot.addWidget(page)
    page.add_status_card()
    page.resize(QSize(900, 500))
    page.show()
    qtbot.waitExposed(page)

    # Nothing has run yet, so the readout is empty rather than a zero.
    assert page.elapsed.text() == ""

    page.start_clock()
    assert page.elapsed.text() == "00:00.000"
    # The readout has to move on its own: a long render can sit between two
    # progress events for a minute at a time.
    qtbot.waitUntil(lambda: page.elapsed.text() != "00:00.000", timeout=5_000)

    page.stop_clock()
    total = page.elapsed.text()
    qtbot.wait(1_200)
    assert page.elapsed.text() == total
