from __future__ import annotations

from functools import partial
from pathlib import Path

from PySide6.QtCore import QEvent, QTimer, QUrl
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QDesktopServices,
    QKeySequence,
    QPalette,
    QShortcut,
)
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

from app.job_presenter import JobPresenter
from features.home import HomePage
from features.reference_removal import (
    IsolationJob,
    analyze_stage,
    run_isolation_job,
)
from features.reference_removal.page import MrPage
from features.settings import SettingsPage
from features.settings.dialog import UpdateDialog
from features.settings.updates import Release, UpdateChecker, installed_version
from shared.branding import application_icon
from shared.config import cfg
from shared.i18n import install_language, tr
from shared.jobs import PathConflict, path_conflict
from shared.logging import set_log_level
from shared.tasks import Operation

_CONFLICT_WARNINGS = {
    PathConflict.STAGE_IS_SOURCE: "warn_same_inputs",
    PathConflict.OUTPUT_OVERWRITES_INPUT: "warn_output_conflict",
}


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.setWindowIcon(application_icon())
        install_language(str(cfg.language.value))
        self.jobs = JobPresenter(self)
        self.updates = UpdateChecker(self)
        # A check nobody asked for reports only what it found, never that it
        # found nothing or could not reach the release host.
        self.silent_update_check = True
        self.close_pending = False
        self.home = HomePage(self)
        self.mr = MrPage()
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
        # Runs once the event loop is up, so the window is on screen before a
        # release dialog can mask it.
        QTimer.singleShot(0, self._check_updates_at_startup)

    def _build_navigation(self) -> None:
        self.home_nav = self.addSubInterface(self.home, FluentIcon.HOME, "")
        self.mr_nav = self.addSubInterface(self.mr, FluentIcon.MUSIC, "")
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
        """The page a shortcut should act on."""
        return self.stackedWidget.currentWidget()

    def _browse_current_input(self) -> None:
        if isinstance(self.current_page(), MrPage):
            self.mr.browse_primary_input()

    def _start_current(self) -> None:
        if isinstance(self.current_page(), MrPage):
            self.mr.start_requested.emit()

    def _analyze_current(self) -> None:
        if isinstance(self.current_page(), MrPage):
            self.mr.analyze_requested.emit()

    def _toggle_preview(self) -> None:
        if isinstance(self.current_page(), MrPage):
            self.mr.toggle_preview()

    def _connect(self) -> None:
        self.home.mr_requested.connect(self._open_mr)
        self.mr.start_requested.connect(self.start_isolation)
        self.mr.cancel_requested.connect(self.cancel)
        self.mr.analyze_requested.connect(self.analyze_sources)
        self.mr.download_requested.connect(self._download)
        cfg.language.valueChanged.connect(self._language_changed)
        cfg.theme.valueChanged.connect(lambda value: self._apply_theme(str(value)))
        cfg.log_level.valueChanged.connect(lambda value: set_log_level(str(value)))
        self.settings.update_check_requested.connect(self.check_updates)
        self.updates.update_available.connect(self._update_available)
        self.updates.up_to_date.connect(self._update_up_to_date)
        self.updates.failed.connect(self._update_failed)
        self.updates.finished.connect(self._update_check_finished)
        self.jobs.finished.connect(self._job_finished)

    def _language_changed(self, value: object) -> None:
        install_language(str(value))
        self.retranslate()

    def _open_mr(self) -> None:
        self.switchTo(self.mr)

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
        for page in (self.home, self.mr, self.settings):
            page.retranslate()
        self._apply_shortcut_hints()
        for navigation, key in (
            (self.home_nav, "nav_home"),
            (self.mr_nav, "nav_mr"),
            (self.settings_nav, "nav_settings"),
        ):
            navigation.setText(tr(key))

    def _apply_shortcut_hints(self) -> None:
        """Append each binding to the tooltip of the control it triggers."""
        for control, shortcut in (
            (self.mr.stage_button, self.open_shortcut),
            (self.mr.start_button, self.start_shortcut),
            (self.mr.analyze_button, self.analyze_shortcut),
            (self.mr.cancel_button, self.cancel_shortcut),
            (self.mr.preview_play, self.preview_shortcut),
        ):
            keys = shortcut.key().toString(QKeySequence.SequenceFormat.NativeText)
            control.setToolTip(f"{control.text()} ({keys})")

    def check_updates(self) -> None:
        """Check on request, which reports its outcome whichever way it goes."""
        self.silent_update_check = False
        self._start_update_check()

    def _check_updates_at_startup(self) -> None:
        if not bool(cfg.check_updates.value):
            return
        self.silent_update_check = True
        self._start_update_check()

    def _start_update_check(self) -> None:
        self.settings.set_checking_updates(True)
        self.updates.check()

    def _update_available(self, release: Release) -> None:
        """Show what the release changed; downloading it stays the user's move."""
        dialog = UpdateDialog(release, self)
        accepted = dialog.exec()
        # The dialog is a child of the window and filters its events, so a
        # closed one has to be dropped rather than left behind for the session.
        dialog.deleteLater()
        if accepted:
            QDesktopServices.openUrl(QUrl(release.url))

    def _update_up_to_date(self) -> None:
        if self.silent_update_check:
            return
        InfoBar.success(
            tr("done_title"),
            tr("update_latest", version=installed_version()),
            duration=3500,
            position=InfoBarPosition.TOP_RIGHT,
            parent=self,
        )

    def _update_failed(self, message: str) -> None:
        if self.silent_update_check:
            return
        InfoBar.error(
            tr("err_title"),
            tr("update_failed", msg=message),
            duration=6000,
            position=InfoBarPosition.TOP_RIGHT,
            parent=self,
        )

    def _update_check_finished(self) -> None:
        self.settings.set_checking_updates(False)

    def _warning(self, key: str) -> None:
        InfoBar.warning(
            tr("warn_title"),
            tr(key),
            duration=3500,
            position=InfoBarPosition.TOP_RIGHT,
            parent=self,
        )

    def _fetch_audio(self, multiple: bool) -> list[Path]:
        """Fetch audio from a link, returning the files the user picked.

        The dialog is imported here rather than at module scope: it pulls in
        yt-dlp, a tenth of a second of startup nothing pays for until a download
        is actually asked for.
        """
        from shared.ui.download_dialog import DownloadDialog

        dialog = DownloadDialog(self, multiple=multiple)
        accepted = dialog.exec()
        chosen = dialog.selected_paths() if accepted else []
        # The dialog is a child of the window and filters its events, so a
        # closed one has to be dropped rather than left behind for the session.
        dialog.deleteLater()
        return chosen

    def _download(self, target: str) -> None:
        """Fetch what the field that asked for it needs: one file or several."""
        if self.jobs.running:
            return
        sources = target == "sources"
        chosen = self._fetch_audio(multiple=sources)
        if not chosen:
            return
        if sources:
            self.mr.add_source_paths([str(path) for path in chosen])
        else:
            self.mr.set_stage(str(chosen[0]))

    def start_isolation(self) -> None:
        if self.jobs.running:
            return
        job = self._isolation_job()
        if job is None:
            return
        cfg.set(cfg.output_tracks, job.tracks.value)
        self.mr.clear_result()
        # An analysis the page already holds carries the timeline the user
        # checked and possibly edited; without one the pipeline matches first.
        self._start_worker(self.mr, partial(run_isolation_job, job, self.mr.analysis))

    def _isolation_job(self) -> IsolationJob | None:
        """Build the job from what the page collected, or warn and return None."""
        if not self.mr.stage_edit.text():
            self._warning("warn_no_stage")
            return None
        sources = self.mr.source_paths()
        if not sources:
            self._warning("warn_no_source")
            return None
        output = self.mr.normalized_output_path()
        if output is None:
            self._warning("warn_no_out")
            return None
        stage = Path(self.mr.stage_edit.text()).expanduser().resolve()
        tracks = self.mr.selected_tracks()
        if (conflict := path_conflict(stage, sources, output, tracks)) is not None:
            self._warning(_CONFLICT_WARNINGS[conflict])
            return None
        try:
            return IsolationJob(
                stage=stage,
                sources=sources,
                output=output,
                strength=self.mr.strength.value(),
                tracks=tracks,
            )
        except ValueError:
            self._warning("warn_invalid_parameters")
            return None

    def analyze_sources(self) -> None:
        """Match the sources against the recording without cancelling anything."""
        if self.jobs.running:
            return
        job = self._isolation_job()
        if job is None:
            return
        self.mr.invalidate_analysis()
        self._start_worker(self.mr, partial(analyze_stage, job))

    def _start_worker(
        self,
        page: MrPage,
        operation: Operation,
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
