from __future__ import annotations

from functools import partial
from pathlib import Path

from PySide6.QtCore import QEvent
from PySide6.QtGui import QCloseEvent, QColor, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import (
    FluentIcon,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
    NavigationItemPosition,
    Theme,
    setTheme,
    setThemeColor,
)

from app.full_stage_processing import analyze_full_stage_job, run_full_stage_job
from app.job_presenter import JobPresenter
from app.mr_workspace import MrWorkspace
from features.full_stage import FullStageJob
from features.full_stage.page import FullStagePage
from features.home import HomePage
from features.neural_separation import NeuralJob, get_model, run_neural_job
from features.neural_separation.page import AiPage
from features.reference_removal import (
    ReferenceJob,
    find_best_match,
    run_reference_job,
)
from features.reference_removal.page import MrPage
from features.settings import SettingsPage
from shared.branding import application_icon
from shared.config import cfg
from shared.i18n import install_language, tr
from shared.logging import set_log_level
from shared.processing import ProcessingOperation

_GUI_REFERENCE_SIGMA_SECONDS = 3


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowIcon(application_icon())
        install_language(str(cfg.language.value))
        self.jobs = JobPresenter(self)
        self.close_pending = False
        self.home = HomePage(self)
        self.mr = MrPage()
        self.full_stage = FullStagePage()
        self.mr_workspace = MrWorkspace(self.mr, self.full_stage, self)
        self.ai = AiPage(self)
        self.settings = SettingsPage(self)
        self.resize(1040, 760)
        # Small enough to dock the window to a portrait half of a screen; the
        # pages fold their own layout down from here.
        self.setMinimumSize(480, 520)
        self._apply_theme(str(cfg.theme.value))
        self._build_navigation()
        self._build_shortcuts()
        self._connect()
        self.retranslate()

    def _build_navigation(self) -> None:
        self.home_nav = self.addSubInterface(self.home, FluentIcon.HOME, "")
        self.mr_nav = self.addSubInterface(self.mr_workspace, FluentIcon.MUSIC, "")
        self.ai_nav = self.addSubInterface(self.ai, FluentIcon.MIX_VOLUMES, "")
        self.settings_nav = self.addSubInterface(
            self.settings, FluentIcon.SETTING, "", NavigationItemPosition.BOTTOM
        )

    def _build_shortcuts(self) -> None:
        """Bind window-level shortcuts that act on whichever page is showing.

        Binding them here rather than on each page keeps one accelerator per
        action: three page-local `Ctrl+O` shortcuts would be an ambiguous
        overload, and a window shortcut also works before a page takes focus.
        """
        self.open_shortcut = self._shortcut(
            QKeySequence.StandardKey.Open, self._browse_current_input
        )
        self.start_shortcut = self._shortcut(QKeySequence("Ctrl+Return"), self._start_current)
        self.analyze_shortcut = self._shortcut(
            QKeySequence.StandardKey.Refresh, self._analyze_current
        )
        self.cancel_shortcut = self._shortcut(QKeySequence.StandardKey.Cancel, self.cancel)
        self.preview_shortcut = self._shortcut(QKeySequence("Ctrl+P"), self._toggle_preview)

    def _shortcut(self, sequence: QKeySequence | QKeySequence.StandardKey, slot) -> QShortcut:
        shortcut = QShortcut(QKeySequence(sequence), self)
        shortcut.activated.connect(slot)
        return shortcut

    def current_page(self) -> QWidget:
        """The page a shortcut should act on, looking through the MR workspace."""
        current = self.stackedWidget.currentWidget()
        if current is self.mr_workspace:
            return self.mr_workspace.stack.currentWidget()
        return current

    def _browse_current_input(self) -> None:
        page = self.current_page()
        if isinstance(page, MrPage | AiPage | FullStagePage):
            page.browse_primary_input()

    def _start_current(self) -> None:
        page = self.current_page()
        if isinstance(page, MrPage | AiPage | FullStagePage):
            page.start_requested.emit()

    def _analyze_current(self) -> None:
        page = self.current_page()
        if isinstance(page, FullStagePage):
            page.analyze_requested.emit()

    def _toggle_preview(self) -> None:
        page = self.current_page()
        if isinstance(page, MrPage):
            page.toggle_preview()

    def _connect(self) -> None:
        self.home.mr_requested.connect(self._open_mr)
        self.home.ai_requested.connect(lambda: self.switchTo(self.ai))
        self.mr.start_requested.connect(self.start_reference)
        self.mr.cancel_requested.connect(self.cancel)
        self.full_stage.analyze_requested.connect(self.analyze_full_stage)
        self.full_stage.start_requested.connect(self.start_full_stage)
        self.full_stage.cancel_requested.connect(self.cancel)
        self.ai.start_requested.connect(self.start_neural)
        self.ai.cancel_requested.connect(self.cancel)
        self.mr.song_changed.connect(self._auto_find)
        cfg.language.valueChanged.connect(self._language_changed)
        cfg.theme.valueChanged.connect(lambda value: self._apply_theme(str(value)))
        cfg.log_level.valueChanged.connect(lambda value: set_log_level(str(value)))
        self.jobs.finished.connect(self._job_finished)

    def _language_changed(self, value: object) -> None:
        install_language(str(value))
        self.retranslate()

    def _open_mr(self) -> None:
        self.mr_workspace.show_single()
        self.switchTo(self.mr_workspace)

    def _apply_theme(self, value: str) -> None:
        theme = {"light": Theme.LIGHT, "dark": Theme.DARK}.get(value, Theme.AUTO)
        setTheme(theme)
        self._apply_system_accent()

    @staticmethod
    def _system_accent_color() -> QColor | None:
        accent = QApplication.palette().color(QPalette.ColorRole.Highlight)
        if not accent.isValid() or accent.hsvSaturationF() < 0.08:
            return None
        return accent

    def _apply_system_accent(self) -> None:
        if accent := self._system_accent_color():
            setThemeColor(accent, save=False, lazy=False)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ApplicationPaletteChange:
            self._apply_system_accent()
        return super().event(event)

    def retranslate(self) -> None:
        self.setWindowTitle(tr("window_title"))
        for page in (self.home, self.mr_workspace, self.ai, self.settings):
            page.retranslate()
        self._apply_shortcut_hints()
        for navigation, key in (
            (self.home_nav, "nav_home"),
            (self.mr_nav, "nav_mr"),
            (self.ai_nav, "nav_ai"),
            (self.settings_nav, "nav_settings"),
        ):
            navigation.setText(tr(key))

    def _apply_shortcut_hints(self) -> None:
        """Append each binding to the tooltip of the control it triggers."""
        for control, shortcut in (
            (self.mr.song_button, self.open_shortcut),
            (self.ai.song_button, self.open_shortcut),
            (self.full_stage.stage_button, self.open_shortcut),
            (self.mr.start_button, self.start_shortcut),
            (self.ai.start_button, self.start_shortcut),
            (self.full_stage.start_button, self.start_shortcut),
            (self.full_stage.analyze_button, self.analyze_shortcut),
            (self.mr.cancel_button, self.cancel_shortcut),
            (self.ai.cancel_button, self.cancel_shortcut),
            (self.full_stage.cancel_button, self.cancel_shortcut),
            (self.mr.preview_play, self.preview_shortcut),
        ):
            keys = shortcut.key().toString(QKeySequence.SequenceFormat.NativeText)
            control.setToolTip(f"{control.text()} ({keys})")

    def _warning(self, key: str) -> None:
        InfoBar.warning(
            tr("warn_title"),
            tr(key),
            duration=3500,
            position=InfoBarPosition.TOP_RIGHT,
            parent=self,
        )

    def _auto_find(self, song: str) -> None:
        if not self.mr.auto_find.isChecked():
            return
        match = find_best_match(Path(song))
        if match.found:
            self.mr.acc_edit.setText(str(match.path))
            self.mr.status.setText(tr("auto_found"))
        else:
            self.mr.acc_edit.clear()
            self.mr.status.setText(tr("auto_not_found"))

    def start_reference(self) -> None:
        if self.jobs.running:
            return
        if not self.mr.song_edit.text():
            self._warning("warn_no_song")
            return
        if not self.mr.acc_edit.text():
            self._warning("warn_no_acc")
            return
        output = self.mr.normalized_output_path()
        if output is None:
            self._warning("warn_no_out")
            return
        song = Path(self.mr.song_edit.text()).expanduser().resolve()
        accompaniment = Path(self.mr.acc_edit.text()).expanduser().resolve()
        if song == accompaniment:
            self._warning("warn_same_inputs")
            return
        if output in {song, accompaniment}:
            self._warning("warn_output_conflict")
            return
        try:
            job = ReferenceJob(
                song=song,
                accompaniment=accompaniment,
                output=output,
                strength=self.mr.strength.value(),
                sigma=_GUI_REFERENCE_SIGMA_SECONDS,
                auto_align=True,
            )
        except ValueError:
            self._warning("warn_invalid_parameters")
            return
        cfg.set(cfg.auto_find, self.mr.auto_find.isChecked())
        self.mr.clear_result()
        self._start_worker(self.mr, partial(run_reference_job, job))

    def start_neural(self) -> None:
        if self.jobs.running:
            return
        if not self.ai.song_edit.text():
            self._warning("ai_need_song")
            return
        model_id = str(self.ai.model.currentData())
        try:
            get_model(model_id)
        except KeyError:
            self._warning("ai_invalid_model")
            return
        cfg.set(cfg.model, model_id)
        song = Path(self.ai.song_edit.text())
        job = NeuralJob(song, song.resolve().parent, model_id)
        self._start_worker(self.ai, partial(run_neural_job, job))

    def _full_stage_job(self) -> FullStageJob | None:
        if not self.full_stage.stage_edit.text():
            self._warning("stage_need_audio")
            return None
        sources = self.full_stage.source_paths()
        if not sources:
            self._warning("stage_need_sources")
            return None
        output = self.full_stage.normalized_output_path()
        if output is None:
            self._warning("warn_no_out")
            return None
        try:
            job = FullStageJob(
                stage=Path(self.full_stage.stage_edit.text()).expanduser().resolve(),
                sources=sources,
                output=output,
                strength=self.full_stage.strength.value(),
                sigma=_GUI_REFERENCE_SIGMA_SECONDS,
                include_fragments=self.full_stage.include_fragments.isChecked(),
                auto_align=True,
            )
        except ValueError:
            self._warning("warn_output_conflict")
            return None
        return job

    def analyze_full_stage(self) -> None:
        if self.jobs.running:
            return
        job = self._full_stage_job()
        if job is None:
            return
        self.full_stage.invalidate_analysis()
        self._start_worker(self.full_stage, partial(analyze_full_stage_job, job))

    def start_full_stage(self) -> None:
        if self.jobs.running:
            return
        job = self._full_stage_job()
        if job is None:
            return
        if self.full_stage.analysis is None:
            self._warning("stage_need_analysis")
            return
        self._start_worker(
            self.full_stage,
            partial(run_full_stage_job, job, self.full_stage.analysis),
        )

    def _start_worker(
        self,
        page: MrPage | AiPage | FullStagePage,
        operation: ProcessingOperation,
    ) -> None:
        # Kept as the single interception point for starting a job: the GUI
        # tests replace it to assert that validation rejects a job before any
        # thread is created.
        self.jobs.start(page, operation)

    def _job_finished(self) -> None:
        if self.close_pending:
            self.close_pending = False
            self.close()

    def cancel(self) -> None:
        self.jobs.cancel()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.mr.stop_preview()
        if self.jobs.running:
            self.close_pending = True
            self.jobs.cancel()
            event.ignore()
            return
        super().closeEvent(event)
