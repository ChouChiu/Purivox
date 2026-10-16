from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QListWidgetItem,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    LineEdit,
    ListWidget,
    PrimaryPushButton,
    PushButton,
    Slider,
    TableView,
    TitleLabel,
)

from features.reference_removal.models import (
    ClipKind,
    IsolationResult,
    StageAnalysis,
    TimelineClip,
)
from features.reference_removal.preview import AudioDataCard, PreviewCard
from features.reference_removal.timeline_model import SOURCE, TimelineModel
from shared.audio import AudioStats
from shared.config import cfg
from shared.i18n import tr
from shared.jobs import BACKING_MARKER, DEFAULT_STRENGTH, VOCAL_MARKER, OutputTracks
from shared.ui import (
    AUDIO_FILE_FILTER,
    WAV_FILE_FILTER,
    FormCard,
    Lane,
    LayoutMetrics,
    PageScrollArea,
    SmoothComboBox,
    allow_shrinking,
    normalized_wav_path,
)

logger = logging.getLogger(__name__)

SOURCES_HEIGHT, SHORT_SOURCES_HEIGHT = 150, 110
TIMELINE_HEIGHT, SHORT_TIMELINE_HEIGHT = 260, 180
# A manual clip covers this much of the first gap, or the whole gap if shorter.
MANUAL_CLIP_SECONDS = 30.0


class MrPage(PageScrollArea):
    """The one vocal-isolation page: a stage recording and one or more sources.

    Every job is the same job.  With one source the page is the single-song
    workflow it has always been; adding sources is the only difference, and the
    pipeline matches each of them against the recording on its own.
    """

    start_requested = Signal()
    analyze_requested = Signal()
    cancel_requested = Signal()
    download_requested = Signal(str)
    """Which input a fetched file belongs to: `stage` or `sources`."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mrPage")
        self._running = False
        self.title = TitleLabel()
        self.layout.addWidget(self.title)
        self._build_files()
        self._build_sources()
        self._build_parameters()
        self._build_status()
        self._build_timeline()
        self.preview = PreviewCard()
        self.add_card(self.preview, Lane.SECONDARY)
        self.audio_data = AudioDataCard()
        self.add_card(self.audio_data, Lane.SECONDARY)
        self.layout.addStretch()
        self._connect()
        self._sync_sources()
        self._sync_timeline()

    def _build_files(self) -> None:
        self.files = FormCard()
        self.stage_label, self.stage_edit, self.stage_button = BodyLabel(), LineEdit(), PushButton()
        self.stage_download = PushButton(FluentIcon.CLOUD_DOWNLOAD, "")
        self.output_label, self.output_edit = BodyLabel(), LineEdit()
        self.output_button = PushButton()
        self.stage_edit.setReadOnly(True)
        # A path field beside both a browse and a fetch button is wider than a
        # phone-narrow row can hold: the field gives way, never the page.
        for edit in (self.stage_edit, self.output_edit):
            allow_shrinking(edit)
        self.output_edit.setClearButtonEnabled(True)
        self._output_user_edited = False
        self.files.add_row(
            self.stage_label, self.stage_edit, self.stage_button, self.stage_download
        )
        self.files.add_row(self.output_label, self.output_edit, self.output_button)
        self.add_card(self.files)

    def _build_sources(self) -> None:
        self.sources_card = FormCard()
        self.sources_hint = BodyLabel()
        self.sources_hint.setWordWrap(True)
        self.sources_card.layout.addWidget(self.sources_hint)
        self.sources = ListWidget()
        self.sources.setMinimumHeight(SOURCES_HEIGHT)
        self.sources_card.layout.addWidget(self.sources)
        self.sources_empty = CaptionLabel()
        self.sources_card.layout.addWidget(self.sources_empty)
        source_actions = QHBoxLayout()
        self.add_sources = PushButton(FluentIcon.ADD, "")
        self.download_sources = PushButton(FluentIcon.CLOUD_DOWNLOAD, "")
        self.remove_source = PushButton(FluentIcon.DELETE, "")
        for button in (self.add_sources, self.download_sources, self.remove_source):
            source_actions.addWidget(button)
        source_actions.addStretch()
        self.sources_card.layout.addLayout(source_actions)
        self.add_card(self.sources_card)

    def _build_parameters(self) -> None:
        self.parameters = FormCard()
        self.tracks_label, self.tracks = BodyLabel(), SmoothComboBox()
        allow_shrinking(self.tracks)
        self.parameters.add_row(self.tracks_label, self.tracks)
        self.strength_label, self.strength_value = BodyLabel(), BodyLabel(f"{DEFAULT_STRENGTH}%")
        self.strength = Slider(Qt.Orientation.Horizontal)
        self.strength.setRange(0, 100)
        self.strength.setValue(DEFAULT_STRENGTH)
        self.parameters.add_row(self.strength_label, self.strength, self.strength_value)
        self.add_card(self.parameters)

    def _build_status(self) -> None:
        """The status card also carries the actions, so starting never needs a scroll.

        It is the first card of the second lane on a wide window and follows
        the parameters in one column, which is where a form is finished.
        """
        self.add_status_card()
        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_button = PushButton()
        self.analyze_button = PushButton(FluentIcon.SYNC, "")
        self.start_button = PrimaryPushButton(FluentIcon.PLAY, "")
        self.cancel_button.setEnabled(False)
        for button in (self.cancel_button, self.analyze_button, self.start_button):
            actions.addWidget(button)
        self.status_card.layout.addLayout(actions)

    def _build_timeline(self) -> None:
        self.timeline_card = FormCard()
        self.timeline_hint = BodyLabel()
        self.timeline_hint.setWordWrap(True)
        self.timeline_card.layout.addWidget(self.timeline_hint)
        self.timeline_empty = CaptionLabel()
        self.timeline_card.layout.addWidget(self.timeline_empty)
        self.timeline_model = TimelineModel(self)
        self.timeline = TableView()
        self.timeline.setModel(self.timeline_model)
        self.timeline.setMinimumHeight(TIMELINE_HEIGHT)
        self.timeline.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.timeline.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.timeline.verticalHeader().hide()
        header = self.timeline.horizontalHeader()
        for column in range(self.timeline_model.columnCount() - 1):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(SOURCE, QHeaderView.ResizeMode.Stretch)
        self.timeline_card.layout.addWidget(self.timeline)
        clip_actions = QHBoxLayout()
        self.add_clip = PushButton(FluentIcon.ADD, "")
        self.remove_clip = PushButton(FluentIcon.DELETE, "")
        for button in (self.add_clip, self.remove_clip):
            clip_actions.addWidget(button)
        clip_actions.addStretch()
        self.timeline_card.layout.addLayout(clip_actions)
        self.add_card(self.timeline_card, Lane.SECONDARY)

    def _connect(self) -> None:
        self.stage_button.clicked.connect(self._select_stage)
        self.stage_download.clicked.connect(lambda: self.download_requested.emit("stage"))
        self.output_button.clicked.connect(self._select_output)
        self.output_edit.textEdited.connect(self._output_edited)
        self.output_edit.editingFinished.connect(self.normalized_output_path)
        self.add_sources.clicked.connect(self._add_sources)
        self.download_sources.clicked.connect(lambda: self.download_requested.emit("sources"))
        self.remove_source.clicked.connect(self._remove_source)
        self.sources.currentRowChanged.connect(lambda _row: self._sync_sources())
        self.analyze_button.clicked.connect(self.analyze_requested)
        self.start_button.clicked.connect(self.start_requested)
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.strength.valueChanged.connect(lambda value: self.strength_value.setText(f"{value}%"))
        self.tracks.currentIndexChanged.connect(self._tracks_changed)
        self.timeline.selectionModel().currentChanged.connect(
            lambda _current, _previous: self._sync_timeline()
        )
        self.timeline_model.modelReset.connect(self._sync_timeline)
        self.timeline_model.clip_edited.connect(
            lambda: self.status.setText(tr("stage_manual_updated"))
        )
        self.timeline_model.edit_rejected.connect(
            lambda: self.status.setText(tr("stage_invalid_edit"))
        )
        self.add_clip.clicked.connect(self._add_clip)
        self.remove_clip.clicked.connect(self._remove_clip)

    @property
    def analysis(self) -> StageAnalysis | None:
        return self.timeline_model.analysis

    def apply_layout(self, metrics: LayoutMetrics) -> None:
        super().apply_layout(metrics)
        # The source list and the timeline are the two panes that would eat a
        # short window whole, so they give back height before anything else.
        self.sources.setMinimumHeight(SHORT_SOURCES_HEIGHT if metrics.short else SOURCES_HEIGHT)
        self.timeline.setMinimumHeight(SHORT_TIMELINE_HEIGHT if metrics.short else TIMELINE_HEIGHT)

    def retranslate(self) -> None:
        self.title.setText(tr("nav_mr"))
        self.files.title_label.setText(tr("file_select"))
        self.stage_label.setText(tr("mr_audio_label"))
        self.output_label.setText(tr("output_file"))
        self.output_edit.setPlaceholderText(tr("output_name_hint"))
        self.stage_button.setText(tr("browse"))
        self.output_button.setText(tr("browse"))
        for button in (self.stage_download, self.download_sources):
            button.setText(tr("download_fetch"))
        self.sources_card.title_label.setText(tr("sources_title"))
        self.sources_hint.setText(tr("stage_sources_hint"))
        self.sources_empty.setText(tr("warn_no_source"))
        self.add_sources.setText(tr("stage_add_sources"))
        self.remove_source.setText(tr("stage_remove_source"))
        self.parameters.title_label.setText(tr("params"))
        self.tracks_label.setText(tr("output_tracks"))
        self._retranslate_tracks()
        self.strength_label.setText(tr("strength"))
        self.retranslate_status_card()
        self.cancel_button.setText(tr("cancel"))
        self.analyze_button.setText(tr("stage_analyze"))
        self.start_button.setText(tr("start"))
        self.timeline_card.title_label.setText(tr("stage_timeline"))
        self.timeline_hint.setText(tr("stage_timeline_hint"))
        self.timeline_empty.setText(tr("stage_need_analysis"))
        self.timeline_model.retranslate()
        self.add_clip.setText(tr("stage_add_clip"))
        self.remove_clip.setText(tr("stage_remove_clip"))
        self.preview.retranslate()
        self.audio_data.retranslate()
        if self.progress.value() == 0:
            self.status.setText(tr("ready"))

    def set_running(self, running: bool) -> None:
        self._running = running
        self.start_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        for control in (
            self.analyze_button,
            self.stage_button,
            self.stage_download,
            self.output_button,
            self.output_edit,
            self.add_sources,
            self.download_sources,
            self.sources,
            self.tracks,
            self.strength,
            self.timeline,
        ):
            control.setEnabled(not running)
        self._sync_sources()
        self._sync_timeline()

    def browse_primary_input(self) -> None:
        """Open the file dialog a page-level shortcut should reach."""
        self._select_stage()

    def _select_stage(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("mr_audio_label"),
            filter=AUDIO_FILE_FILTER,
        )
        if path:
            self.set_stage(path)

    def set_stage(self, path: str) -> None:
        self.clear_result()
        self.stage_edit.setText(path)
        if not self._output_user_edited or not self.output_edit.text().strip():
            self._apply_default_output()
        self.invalidate_analysis()

    def stage_path(self) -> Path | None:
        text = self.stage_edit.text().strip()
        return Path(text).expanduser().resolve() if text else None

    def source_paths(self) -> tuple[Path, ...]:
        return tuple(
            Path(str(self.sources.item(index).data(Qt.ItemDataRole.UserRole)))
            for index in range(self.sources.count())
        )

    def add_source_paths(self, paths: list[str]) -> None:
        """Append the chosen sources, skipping ones the list already holds."""
        existing = {str(path.resolve()) for path in self.source_paths()}
        added = False
        for path_text in paths:
            path = Path(path_text).expanduser().resolve()
            if str(path) in existing:
                continue
            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(str(path))
            self.sources.addItem(item)
            existing.add(str(path))
            added = True
        if added:
            self.clear_result()
            self.invalidate_analysis()
        self._sync_sources()

    def _add_sources(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            tr("sources_title"),
            filter=AUDIO_FILE_FILTER,
        )
        self.add_source_paths(paths)

    def _remove_source(self) -> None:
        row = self.sources.currentRow()
        if row < 0:
            return
        self.sources.takeItem(row)
        self.clear_result()
        self.invalidate_analysis()
        self._sync_sources()

    def _sync_sources(self) -> None:
        """Show the list once it holds something, and the hint until then."""
        empty = self.sources.count() == 0
        self.sources.setVisible(not empty)
        self.sources_empty.setVisible(empty)
        self.remove_source.setEnabled(not self._running and self.sources.currentRow() >= 0)

    def selected_tracks(self) -> OutputTracks:
        return OutputTracks(str(self.tracks.currentData() or OutputTracks.VOCAL.value))

    def _default_output_suffix(self) -> str:
        marker = BACKING_MARKER if self.selected_tracks() is OutputTracks.BACKING else VOCAL_MARKER
        return f"{marker}.wav"

    def _apply_default_output(self) -> None:
        stage = self.stage_edit.text().strip()
        if not stage:
            return
        origin = Path(stage)
        self.output_edit.setText(str(origin.with_name(origin.stem + self._default_output_suffix())))
        self._output_user_edited = False

    def _retranslate_tracks(self) -> None:
        # Rebuilding the items re-emits currentIndexChanged, and this page's slot
        # renames the output file: a language switch must not touch it.
        previous = str(self.tracks.currentData() or cfg.output_tracks.value)
        self.tracks.blockSignals(True)
        self.tracks.clear()
        for choice in OutputTracks:
            self.tracks.addItem(tr(f"output_tracks_{choice.value}"), userData=choice.value)
        self.tracks.setCurrentIndex(max(0, self.tracks.findData(previous)))
        self.tracks.blockSignals(False)

    def _tracks_changed(self, _index: int) -> None:
        self.clear_result()
        if not self._output_user_edited:
            self._apply_default_output()

    def _select_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, tr("output_file"), self.output_edit.text(), WAV_FILE_FILTER
        )
        if path:
            self.clear_result()
            self._output_user_edited = True
            self.output_edit.setText(path)

    def _output_edited(self, _text: str) -> None:
        self._output_user_edited = True
        self.clear_result()

    def normalized_output_path(self) -> Path | None:
        path = normalized_wav_path(
            self.output_edit.text(), self.stage_edit.text(), self._default_output_suffix()
        )
        if path is None:
            return None
        if not self.output_edit.text().strip():
            # The name came from the stage recording, so it is not the user's choice.
            self._output_user_edited = False
        self.output_edit.setText(str(path))
        return path

    @staticmethod
    def _summary(analysis: StageAnalysis) -> str:
        return tr(
            "stage_analysis_summary",
            songs=len(analysis.song_clips),
            fragments=sum(clip.kind == ClipKind.FRAGMENT for clip in analysis.clips),
            missing=len(analysis.missing_sources),
        )

    def set_analysis(self, analysis: StageAnalysis) -> None:
        self.timeline_model.set_analysis(analysis)
        self.status.setText(self._summary(analysis))

    def show_result(self, result: StageAnalysis | IsolationResult) -> str:
        """Show what a job returned and name it for the notification."""
        if isinstance(result, StageAnalysis):
            # Find songs reports a timeline and writes nothing.
            self.set_analysis(result)
            return self._summary(result)
        self.set_analysis(result.analysis)
        stats = result.audio_stats[0] if result.audio_stats else None
        self.set_result(result.outputs[0], stats)
        self.status.setText(tr("done_status", path=result.outputs[0]))
        return "\n".join(map(str, result.outputs))

    def invalidate_analysis(self) -> None:
        self.timeline_model.set_analysis(None)

    def _selected_manual_row(self) -> int | None:
        index = self.timeline.selectionModel().currentIndex()
        clip = self.timeline_model.clip(index.row()) if index.isValid() else None
        return index.row() if clip is not None and clip.manual else None

    def _sync_timeline(self) -> None:
        """Show the table once there is a timeline to edit, and what to do until then."""
        has_analysis = self.analysis is not None
        self.timeline.setVisible(has_analysis)
        self.timeline_empty.setVisible(not has_analysis)
        self.add_clip.setEnabled(not self._running and has_analysis)
        self.remove_clip.setEnabled(not self._running and self._selected_manual_row() is not None)

    def _add_clip(self) -> None:
        # Enabled only with a timeline, and a timeline only survives with the
        # sources it was matched from, so both are there.
        analysis = self.analysis
        if analysis is None:
            return
        sources = self.source_paths()
        index = self.sources.currentRow()
        if not 0 <= index < len(sources):
            index = 0
        # Start inside the first gap the matcher left, which is where a spliced
        # backing track's missing pieces almost always belong.
        start = 0.0
        limit = analysis.duration_seconds
        for clip in analysis.clips:
            if clip.kind == ClipKind.UNMATCHED:
                start, limit = clip.stage_start, clip.stage_end
                break
        length = min(MANUAL_CLIP_SECONDS, limit - start)
        if length <= 0.0:
            self.status.setText(tr("stage_no_room_for_clip"))
            return
        added = self.timeline_model.add_clip(
            TimelineClip(
                ClipKind.SONG,
                start,
                start + length,
                source=sources[index],
                source_index=index,
                source_start=0.0,
                source_end=length,
                manual=True,
            )
        )
        if added:
            self.status.setText(tr("stage_manual_added"))

    def _remove_clip(self) -> None:
        row = self._selected_manual_row()
        if row is not None and self.timeline_model.remove_clip(row):
            self.status.setText(tr("stage_manual_removed"))

    def set_result(self, path: Path, stats: AudioStats | None = None) -> None:
        result = path.expanduser().resolve()
        if not result.is_file():
            return
        self.preview.load(result, stats.duration_seconds if stats else 0.0)
        self.audio_data.show_stats(stats)

    def clear_result(self) -> None:
        self.preview.clear()
        self.audio_data.show_stats(None)
