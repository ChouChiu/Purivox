import logging
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QWidget

from app import main_window
from app.main_window import MainWindow
from features.settings.updates import Release
from shared.config import cfg, load_config
from shared.i18n import SUPPORTED_LANGUAGES, tr
from shared.jobs import OutputTracks
from shared.ui import CONTENT_MAX_WIDTH, Lane, LayoutMode


@pytest.fixture
def window(qtbot) -> MainWindow:
    load_config()
    window = MainWindow()
    qtbot.addWidget(window)
    return window


def _shown(window: MainWindow, width: int, height: int) -> None:
    """Show the window at a size and let every visible page act on its viewport."""
    window.show()
    window.resize(width, height)
    QApplication.processEvents()
    QApplication.processEvents()


def test_the_log_level_setting_reaches_the_root_logger(window: MainWindow):
    previous = cfg.log_level.value
    try:
        cfg.set(cfg.log_level, "ERROR")
        assert logging.getLogger().level == logging.ERROR
    finally:
        cfg.set(cfg.log_level, previous)


def test_the_home_card_opens_the_workflow(window: MainWindow):
    window.home.mr_card.open_button.click()

    assert window.current_page() is window.mr


@pytest.mark.parametrize(("highlight", "applied"), [("#d52b8c", True), ("#808080", False)])
def test_a_coloured_system_highlight_becomes_the_accent(
    window: MainWindow, monkeypatch, highlight: str, applied: bool
):
    """A grey highlight is the platform having no accent, not a choice of grey."""
    colours: list[QColor] = []
    monkeypatch.setattr(main_window, "setThemeColor", lambda colour, **_: colours.append(colour))
    original = QApplication.palette()
    palette = QPalette(original)
    palette.setColor(QPalette.ColorRole.Highlight, QColor(highlight))
    try:
        QApplication.setPalette(palette)
        QApplication.sendEvent(window, QEvent(QEvent.Type.ApplicationPaletteChange))
    finally:
        QApplication.setPalette(original)

    assert [colour.name() for colour in colours] == ([highlight] if applied else [])


def _fill(window: MainWindow, tmp_path: Path, stage: str, sources: list[str], output: str) -> None:
    if stage:
        window.mr.stage_edit.setText(str(tmp_path / stage))
    window.mr.add_source_paths([str(tmp_path / name) for name in sources])
    window.mr.output_edit.setText(str(tmp_path / output) if output else "")


@pytest.mark.parametrize(
    ("stage", "sources", "output", "tracks", "warning"),
    [
        ("", ["song.wav"], "out.wav", OutputTracks.VOCAL, "warn_no_stage"),
        ("live.wav", [], "out.wav", OutputTracks.VOCAL, "warn_no_source"),
        ("song.wav", ["song.wav"], "out.wav", OutputTracks.VOCAL, "warn_same_inputs"),
        ("live.wav", ["song.wav"], "song.wav", OutputTracks.VOCAL, "warn_output_conflict"),
        ("live.wav", ["x_backing.wav"], "x_vocals.wav", OutputTracks.BOTH, "warn_output_conflict"),
    ],
)
def test_an_invalid_job_is_named_before_any_thread_starts(
    window: MainWindow, tmp_path: Path, monkeypatch, stage, sources, output, tracks, warning
):
    # The export choice first: switching it renames an output nobody typed.
    window.mr.tracks.setCurrentIndex(window.mr.tracks.findData(tracks.value))
    _fill(window, tmp_path, stage, sources, output)
    warnings: list[str] = []
    monkeypatch.setattr(window, "_warning", warnings.append)
    monkeypatch.setattr(window.jobs, "start", lambda *_: pytest.fail("worker must not start"))

    window.start_isolation()
    window.analyze_sources()

    assert warnings == [warning, warning]


def test_start_hands_the_page_settings_to_the_pipeline(
    window: MainWindow, tmp_path: Path, monkeypatch
):
    _fill(window, tmp_path, "live.wav", ["a.wav", "b.wav"], "out.wav")
    window.mr.strength.setValue(60)
    started = []
    monkeypatch.setattr(window.jobs, "start", lambda page, operation: started.append(operation))

    window.start_isolation()

    (operation,) = started
    job, analysis = operation.args
    assert job.sources == ((tmp_path / "a.wav").resolve(), (tmp_path / "b.wav").resolve())
    assert job.output == (tmp_path / "out.wav").resolve()
    assert (job.strength, job.sigma, job.auto_align) == (60, 3, True)
    assert job.tracks is OutputTracks.VOCAL
    assert analysis is None, "a job with no analysis matches before it renders"


def test_window_shortcuts_act_only_on_the_visible_page(window: MainWindow, qtbot):
    window.switchTo(window.mr)
    with qtbot.waitSignal(window.mr.start_requested):
        window.start_shortcut.activated.emit()
    with qtbot.waitSignal(window.mr.analyze_requested):
        window.analyze_shortcut.activated.emit()

    window.switchTo(window.settings)
    with qtbot.assertNotEmitted(window.mr.start_requested):
        window.start_shortcut.activated.emit()

    # Cancelling with no job running must be harmless rather than an error.
    window.cancel_shortcut.activated.emit()


def test_shortcut_hints_follow_the_interface_language(window: MainWindow):
    cfg.set(cfg.language, "en_us")
    assert window.mr.start_button.toolTip() == "Start (Ctrl+Return)"
    assert window.mr.analyze_button.toolTip().endswith("(F5)")
    cfg.set(cfg.language, "zh_cn")
    assert window.mr.start_button.toolTip() == "开始处理 (Ctrl+Return)"


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_no_label_shows_a_raw_translation_key(
    window: MainWindow, translation_keys: frozenset[str], language: str
):
    """A key built at run time is invisible to the literal-key check in test_i18n."""
    cfg.set(cfg.language, language)
    try:
        shown = {
            widget.text()
            for widget in window.findChildren(QWidget)
            if isinstance(widget, QLabel | QAbstractButton) and widget.text()
        }
        shown.update(window.mr.tracks.itemText(index) for index in range(window.mr.tracks.count()))
    finally:
        cfg.set(cfg.language, SUPPORTED_LANGUAGES[0])

    assert not shown & translation_keys


def test_a_portrait_window_folds_every_row_into_one_column(window: MainWindow, qtbot):
    window.switchTo(window.mr)
    _shown(window, 500, 900)

    assert window.mr.metrics.mode is LayoutMode.PORTRAIT
    assert window.mr.columns.lane_widgets(Lane.SECONDARY) == ()
    assert window.mr.files.layout.itemAt(1).widget().is_folded()
    assert window.mr.preview_controls.is_folded()
    # Nothing may demand more width than the page was given, or the page would
    # simply be cut off: the horizontal scroll bar is switched off.
    assert window.mr.content.minimumSizeHint().width() <= window.mr.viewport().width()


def test_an_ultrawide_window_splits_the_page_into_two_capped_lanes(window: MainWindow):
    window.switchTo(window.mr)
    _shown(window, 2560, 1080)

    assert window.mr.metrics.mode is LayoutMode.ULTRAWIDE
    assert window.mr.columns.lane_widgets(Lane.PRIMARY) == (
        window.mr.files,
        window.mr.sources_card,
        window.mr.parameters,
    )
    assert window.mr.columns.lane_widgets(Lane.SECONDARY) == (
        window.mr.status_card,
        window.mr.timeline_card,
        window.mr.preview_card,
        window.mr.data_card,
    )
    assert not window.mr.files.layout.itemAt(1).widget().is_folded()
    # A form stretched the whole width of an ultrawide screen is unreadable,
    # so the column stops growing and is centred instead.
    left, _top, right, _bottom = window.mr.layout.getContentsMargins()
    assert window.mr.viewport().width() - left - right <= CONTENT_MAX_WIDTH
    assert left == right


def test_every_page_fits_the_minimum_window(window: MainWindow):
    width, height = window.minimumWidth(), window.minimumHeight()

    for page in (window.home, window.mr, window.settings):
        window.switchTo(page)
        _shown(window, width, height)
        assert page.content.minimumSizeHint().width() <= page.viewport().width(), (
            f"{page.objectName()} does not fit a {width}x{height} window"
        )


def test_the_settings_page_checks_for_updates_on_request(window: MainWindow, monkeypatch):
    started: list[bool] = []
    monkeypatch.setattr(window.updates, "check", lambda: started.append(True))

    window.settings.update_now_card.button.click()

    assert started == [True]
    assert not window.silent_update_check, "a requested check reports whatever it finds"
    assert not window.settings.update_now_card.button.isEnabled()
    assert window.settings.update_now_card.contentLabel.text() == tr("update_checking")

    window.updates.finished.emit()
    assert window.settings.update_now_card.button.isEnabled()


@pytest.mark.parametrize("enabled", [False, True])
def test_the_startup_check_follows_its_switch(qtbot, monkeypatch, enabled: bool):
    load_config()
    started: list[bool] = []
    monkeypatch.setattr(main_window.UpdateChecker, "check", lambda _self: started.append(True))
    previous = cfg.check_updates.value
    cfg.set(cfg.check_updates, enabled)
    try:
        window = MainWindow()
        qtbot.addWidget(window)
        qtbot.wait(50)
    finally:
        cfg.set(cfg.check_updates, previous)

    assert started == ([True] if enabled else [])
    assert window.silent_update_check, "a check nobody asked for stays quiet"


def test_an_available_release_opens_its_page_on_request(window: MainWindow, monkeypatch):
    release = Release("9.9.9", "- everything", "https://example.invalid/releases/tag/v9.9.9")
    opened: list[str] = []

    class _AcceptedDialog:
        def __init__(self, offered, parent):
            assert offered is release
            assert parent is window

        def exec(self) -> int:
            return 1

        def deleteLater(self) -> None:
            pass

    monkeypatch.setattr(main_window, "UpdateDialog", _AcceptedDialog)
    monkeypatch.setattr(
        main_window.QDesktopServices, "openUrl", lambda url: opened.append(url.toString())
    )

    window.updates.update_available.emit(release)

    assert opened == [release.url]


def test_a_fetched_file_lands_in_the_field_that_asked_for_it(
    window: MainWindow, tmp_path: Path, monkeypatch
):
    """Pages ask; the window opens the dialog and routes what came back."""
    fetched = [tmp_path / "one.wav", tmp_path / "two.wav"]
    asked: list[bool] = []

    def fetch_audio(multiple: bool) -> list[Path]:
        asked.append(multiple)
        return fetched if multiple else fetched[:1]

    monkeypatch.setattr(window, "_fetch_audio", fetch_audio)

    window.mr.stage_download.click()
    assert window.mr.stage_edit.text() == str(fetched[0])

    window.mr.download_sources.click()
    assert [path.name for path in window.mr.source_paths()] == ["one.wav", "two.wav"]
    assert asked == [False, True], "only the source list takes more than one file"


def test_a_cancelled_fetch_leaves_every_field_alone(window: MainWindow, monkeypatch):
    monkeypatch.setattr(window, "_fetch_audio", lambda multiple: [])

    window.mr.stage_download.click()
    window.mr.download_sources.click()

    assert window.mr.stage_edit.text() == ""
    assert window.mr.source_paths() == ()
