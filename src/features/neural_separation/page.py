from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout
from qfluentwidgets import (
    BodyLabel,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    TitleLabel,
)

from features.neural_separation.catalog import DEFAULT_MODEL_ID, get_model, model_catalog
from features.neural_separation.model_store import candidate_model_dirs, find_model
from shared.config import cfg
from shared.i18n import tr
from shared.ui import (
    AUDIO_FILE_FILTER,
    AudioDropLineEdit,
    FormCard,
    PageScrollArea,
    SmoothComboBox,
)


class AiPage(PageScrollArea):
    start_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiPage")
        self.title = TitleLabel()
        self.layout.addWidget(self.title)
        self.form = FormCard()
        self.song_label, self.song_edit, self.song_button = (
            BodyLabel(),
            AudioDropLineEdit(),
            PushButton(),
        )
        self.song_edit.setReadOnly(True)
        self.model_label, self.model = BodyLabel(), SmoothComboBox()
        self.model_status = BodyLabel()
        self.form.add_row(self.song_label, self.song_edit, self.song_button)
        self.form.add_row(self.model_label, self.model)
        self.form.layout.addWidget(self.model_status)
        self.layout.addWidget(self.form)
        self.status_card = FormCard()
        self.status = BodyLabel()
        self.progress = ProgressBar()
        self.status_card.layout.addWidget(self.status)
        self.status_card.layout.addWidget(self.progress)
        self.layout.addWidget(self.status_card)
        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_button, self.start_button = PushButton(), PrimaryPushButton()
        self.cancel_button.setEnabled(False)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.start_button)
        self.layout.addLayout(actions)
        self.layout.addStretch()
        self.model_watcher = QFileSystemWatcher(self)
        self.model_watcher.directoryChanged.connect(self._model_directory_changed)
        self._watch_model_dirs()
        self.song_button.clicked.connect(self._select_song)
        self.song_edit.file_dropped.connect(self.song_edit.setText)
        self.start_button.clicked.connect(self.start_requested)
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.model.currentIndexChanged.connect(lambda _index: self._update_model_status())

    def retranslate(self) -> None:
        self.title.setText(tr("ai_title"))
        self.form.title_label.setText(tr("file_select"))
        self.status_card.title_label.setText(tr("status_group"))
        self.song_label.setText(tr("song_label"))
        self.song_button.setText(tr("browse"))
        self.song_edit.setToolTip(tr("drop_hint"))
        self.model_label.setText(tr("ai_model_label"))
        self.cancel_button.setText(tr("cancel"))
        self.start_button.setText(tr("ai_extract"))
        if self.progress.value() == 0:
            self.status.setText(tr("ready"))
        previous = self.model.currentData() or cfg.model.value or DEFAULT_MODEL_ID
        self.model.clear()
        for entry in model_catalog():
            self.model.addItem(f"{entry.name} — {tr(entry.description_key)}", userData=entry.id)
        self.model.setCurrentIndex(max(0, self.model.findData(previous)))
        self._update_model_status()

    def _watch_model_dirs(self) -> None:
        """Follow the directories the model search reads.

        A weight can appear while the page is open — a finished download, a file
        copied in by hand — and the watcher turns that into a status refresh
        instead of leaving a stale "needs download" label until the page is
        rebuilt.
        """
        wanted = {str(directory) for directory in candidate_model_dirs() if directory.is_dir()}
        watched = set(self.model_watcher.directories())
        if stale := sorted(watched - wanted):
            self.model_watcher.removePaths(stale)
        if missing := sorted(wanted - watched):
            self.model_watcher.addPaths(missing)

    def _model_directory_changed(self, _path: str) -> None:
        self._update_model_status()

    def _update_model_status(self) -> None:
        self._watch_model_dirs()
        try:
            entry = get_model(str(self.model.currentData()))
        except KeyError:
            return
        key = "ai_model_ready" if find_model(entry) else "ai_model_need_download"
        self.model_status.setText(tr(key))

    def set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.song_button.setEnabled(not running)
        self.model.setEnabled(not running)

    def browse_primary_input(self) -> None:
        """Open the file dialog a page-level shortcut should reach."""
        self._select_song()

    def _select_song(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("song_label"),
            filter=AUDIO_FILE_FILTER,
        )
        if path:
            self.song_edit.setText(str(Path(path)))
