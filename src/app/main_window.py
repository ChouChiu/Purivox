from __future__ import annotations

from functools import partial
from pathlib import Path

from PySide6.QtCore import QEvent
from PySide6.QtGui import QCloseEvent, QColor, QPalette
from PySide6.QtWidgets import QApplication
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
        self.setMinimumSize(820, 620)
        self._apply_theme(str(cfg.theme.value))
        self._build_navigation()
        self._connect()
        self.retranslate()

    def _build_navigation(self) -> None:
        self.home_nav = self.addSubInterface(self.home, FluentIcon.HOME, "")
        self.mr_nav = self.addSubInterface(self.mr_workspace, FluentIcon.MUSIC, "")
        self.ai_nav = self.addSubInterface(self.ai, FluentIcon.MIX_VOLUMES, "")
        self.settings_nav = self.addSubInterface(
            self.settings, FluentIcon.SETTING, "", NavigationItemPosition.BOTTOM
        )

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
        for navigation, key in (
            (self.home_nav, "nav_home"),
            (self.mr_nav, "nav_mr"),
            (self.ai_nav, "nav_ai"),
            (self.settings_nav, "nav_settings"),
        ):
            navigation.setText(tr(key))

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
                center_extraction=self.mr.center_extraction.isChecked(),
                open_mic_focus=self.mr.open_mic_focus.isChecked(),
            )
        except (ValueError, TypeError):
            self._warning("warn_invalid_parameters")
            return
        cfg.set(cfg.auto_find, self.mr.auto_find.isChecked())
        cfg.set(cfg.center_extraction, job.center_extraction)
        cfg.set(cfg.open_mic_focus, job.open_mic_focus)
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
                center_extraction=self.full_stage.center_extraction.isChecked(),
                open_mic_focus=self.full_stage.open_mic_focus.isChecked(),
            )
        except (TypeError, ValueError):
            self._warning("warn_output_conflict")
            return None
        cfg.set(cfg.center_extraction, job.center_extraction)
        cfg.set(cfg.open_mic_focus, job.open_mic_focus)
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
