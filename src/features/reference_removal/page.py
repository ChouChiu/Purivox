from __future__ import annotations

import logging
import math
from pathlib import Path

from PySide6.QtCore import QItemSelection, Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
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
    StrongBodyLabel,
    TableView,
    TitleLabel,
)

from features.reference_removal.models import (
    ClipKind,
    StageAnalysis,
    TimelineClip,
)
from features.reference_removal.preview import SeekSlider
from features.reference_removal.timeline_model import SOURCE, TimelineModel
from shared.audio import AudioStats
from shared.config import cfg
from shared.i18n import tr
from shared.jobs import BACKING_MARKER, VOCAL_MARKER, OutputTracks
from shared.ui import (
    AUDIO_FILE_FILTER,
    UNBOUNDED_WIDTH,
    WAV_FILE_FILTER,
    ElidedLabel,
    FoldingRow,
    FormCard,
    Lane,
    LayoutMetrics,
    PageScrollArea,
    SmoothComboBox,
    allow_shrinking,
    format_clock,
    normalized_wav_path,
)

logger = logging.getLogger(__name__)

VOLUME_SLIDER_WIDTH = 150
STAT_COLUMNS = 4
SOURCES_HEIGHT, SHORT_SOURCES_HEIGHT = 150, 110
TIMELINE_HEIGHT, SHORT_TIMELINE_HEIGHT = 260, 180


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
        self.title = TitleLabel()
        self.layout.addWidget(self.title)

        self.files = FormCard()
        self.stage_label, self.stage_edit, self.stage_button = (
            BodyLabel(),
            LineEdit(),
            PushButton(),
        )
        self.output_label, self.output_edit, self.output_button = (
            BodyLabel(),
            LineEdit(),
            PushButton(),
        )
        self.stage_download = PushButton(FluentIcon.CLOUD_DOWNLOAD, "")
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

        self.sources_card = FormCard()
        self.sources_hint = BodyLabel()
        self.sources_hint.setWordWrap(True)
        self.sources_card.layout.addWidget(self.sources_hint)
        self.sources = ListWidget()
        self.sources.setMinimumHeight(SOURCES_HEIGHT)
        self.sources_card.layout.addWidget(self.sources)
        source_actions = QHBoxLayout()
        self.add_sources = PushButton(FluentIcon.ADD, "")
        self.download_sources = PushButton(FluentIcon.CLOUD_DOWNLOAD, "")
        self.remove_source = PushButton(FluentIcon.DELETE, "")
        for button in (self.add_sources, self.download_sources, self.remove_source):
            source_actions.addWidget(button)
        source_actions.addStretch()
        self.sources_card.layout.addLayout(source_actions)
        self.add_card(self.sources_card)

        self.parameters = FormCard()
        self.tracks_label, self.tracks = BodyLabel(), SmoothComboBox()
        allow_shrinking(self.tracks)
        self.parameters.add_row(self.tracks_label, self.tracks)
        self.strength_label, self.strength_value = BodyLabel(), BodyLabel("75%")
        self.strength = Slider(Qt.Orientation.Horizontal)
        self.strength.setRange(0, 100)
        self.strength.setValue(75)
        self.parameters.add_row(self.strength_label, self.strength, self.strength_value)
        self.add_card(self.parameters)

        self.add_status_card()

        self.timeline_card = FormCard()
        self.timeline_hint = BodyLabel()
        self.timeline_hint.setWordWrap(True)
        self.timeline_card.layout.addWidget(self.timeline_hint)
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
        self.remove_clip.setEnabled(False)
        for button in (self.add_clip, self.remove_clip):
            clip_actions.addWidget(button)
        clip_actions.addStretch()
        self.timeline_card.layout.addLayout(clip_actions)
        self.add_card(self.timeline_card, Lane.SECONDARY)

        self.preview_card = FormCard()
        self.preview_status = ElidedLabel()
        self.preview_seek = SeekSlider(Qt.Orientation.Horizontal)
        self.preview_seek.setRange(0, 1)
        self.preview_seek.setEnabled(False)
        self.preview_time = BodyLabel("00:00 / 00:00")
        self.preview_play = PrimaryPushButton()
        self.preview_stop = PushButton()
        self.preview_play.setEnabled(False)
        self.preview_stop.setEnabled(False)
        preview_header = QHBoxLayout()
        preview_header.addWidget(self.preview_status, 1)
        preview_header.addWidget(self.preview_time)
        self.preview_card.layout.addLayout(preview_header)
        self.preview_card.layout.addWidget(self.preview_seek)
        self.preview_volume_label = BodyLabel()
        self.preview_volume = Slider(Qt.Orientation.Horizontal)
        self.preview_volume.setRange(0, 100)
        self.preview_volume.setValue(75)
        self.preview_volume.setMinimumWidth(VOLUME_SLIDER_WIDTH)
        self.preview_volume.setMaximumWidth(VOLUME_SLIDER_WIDTH)
        # Transport buttons hold the line; the volume pair drops below them
        # rather than squeezing the slider down to a few pixels.
        self.preview_controls = FoldingRow(self.preview_card, lead_expands=True)
        self.preview_controls.add_lead(self.preview_play)
        self.preview_controls.add_lead(self.preview_stop)
        self.preview_controls.add_lead_stretch()
        self.preview_controls.add_trail(self.preview_volume_label)
        self.preview_controls.add_trail(self.preview_volume, folded_stretch=1)
        self.preview_card.layout.addWidget(self.preview_controls)
        self.add_card(self.preview_card, Lane.SECONDARY)

        self.data_card = FormCard()
        self.stats_grid = QGridLayout()
        self.stats_grid.setHorizontalSpacing(24)
        self.stats_grid.setVerticalSpacing(14)
        self.stat_labels: dict[str, CaptionLabel] = {}
        self.stat_values: dict[str, StrongBodyLabel] = {}
        self.stat_tiles: list[QWidget] = []
        for key in (
            "duration",
            "sample_rate",
            "channels",
            "bit_depth",
            "peak",
            "rms",
            "file_size",
        ):
            tile = QWidget(self.data_card)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(0, 0, 0, 0)
            tile_layout.setSpacing(3)
            label = CaptionLabel(tile)
            value = StrongBodyLabel("--", tile)
            tile_layout.addWidget(label)
            tile_layout.addWidget(value)
            self.stat_labels[key] = label
            self.stat_values[key] = value
            self.stat_tiles.append(tile)
        self._reflow_stats(STAT_COLUMNS)
        self.data_card.layout.addLayout(self.stats_grid)
        self.add_card(self.data_card, Lane.SECONDARY)

        self.media_devices = QMediaDevices(self)
        self.audio_output = QAudioOutput(self)
        self.media_devices.audioOutputsChanged.connect(self._sync_preview_output_device)
        self._sync_preview_output_device()
        self.audio_output.setVolume(0.75)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self._result_path: Path | None = None
        self._result_stats: AudioStats | None = None
        self._seeking = False

        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_button = PushButton()
        self.analyze_button = PushButton(FluentIcon.SYNC, "")
        self.start_button = PrimaryPushButton(FluentIcon.PLAY, "")
        self.cancel_button.setEnabled(False)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.analyze_button)
        actions.addWidget(self.start_button)
        self.layout.addLayout(actions)
        self.layout.addStretch()

        self.stage_button.clicked.connect(self._select_stage)
        self.stage_download.clicked.connect(lambda: self.download_requested.emit("stage"))
        self.output_button.clicked.connect(self._select_output)
        self.output_edit.textEdited.connect(self._output_edited)
        self.output_edit.editingFinished.connect(self.normalized_output_path)
        self.add_sources.clicked.connect(self._add_sources)
        self.download_sources.clicked.connect(lambda: self.download_requested.emit("sources"))
        self.remove_source.clicked.connect(self._remove_source)
        self.analyze_button.clicked.connect(self.analyze_requested)
        self.start_button.clicked.connect(self.start_requested)
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.strength.valueChanged.connect(lambda value: self.strength_value.setText(f"{value}%"))
        self.tracks.currentIndexChanged.connect(self._tracks_changed)
        self.timeline.selectionModel().selectionChanged.connect(self._selection_changed)
        self.timeline_model.clip_edited.connect(self._clip_edited)
        self.timeline_model.edit_rejected.connect(self._edit_rejected)
        self.add_clip.clicked.connect(self._add_clip)
        self.remove_clip.clicked.connect(self._remove_clip)
        self.preview_play.clicked.connect(self.toggle_preview)
        self.preview_stop.clicked.connect(self.stop_preview)
        self.preview_volume.valueChanged.connect(
            lambda value: self.audio_output.setVolume(value / 100.0)
        )
        self.preview_seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.preview_seek.sliderReleased.connect(self._seek_preview)
        self.preview_seek.sliderMoved.connect(self._preview_slider_moved)
        self.preview_seek.seek_requested.connect(self._seek_preview_to)
        self.player.positionChanged.connect(self._preview_position_changed)
        self.player.durationChanged.connect(self._preview_duration_changed)
        self.player.playbackStateChanged.connect(lambda _state: self._update_preview_button())
        self.player.errorOccurred.connect(self._preview_error)

    @property
    def analysis(self) -> StageAnalysis | None:
        return self.timeline_model.analysis

    def _reflow_stats(self, columns: int) -> None:
        """Re-place the audio-data tiles across `columns` of the grid."""
        for tile in self.stat_tiles:
            self.stats_grid.removeWidget(tile)
        for index, tile in enumerate(self.stat_tiles):
            self.stats_grid.addWidget(tile, index // columns, index % columns)

    def apply_layout(self, metrics: LayoutMetrics) -> None:
        super().apply_layout(metrics)
        self._reflow_stats(metrics.tile_columns)
        self.stats_grid.setHorizontalSpacing(12 if metrics.stacked_rows else 24)
        # A capped slider reads as a volume control; an uncapped one filling a
        # folded second line reads as a second seek bar, so it only spans the
        # row once the transport buttons have a line to themselves.
        self.preview_volume.setMaximumWidth(
            UNBOUNDED_WIDTH if metrics.stacked_rows else VOLUME_SLIDER_WIDTH
        )
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
        self.sources_card.title_label.setText(tr("source_label"))
        self.sources_hint.setText(tr("stage_sources_hint"))
        self.add_sources.setText(tr("stage_add_sources"))
        self.remove_source.setText(tr("stage_remove_source"))
        self.parameters.title_label.setText(tr("params"))
        self.tracks_label.setText(tr("output_tracks"))
        self._retranslate_tracks()
        self.strength_label.setText(tr("strength"))
        self.retranslate_status_card()
        self.timeline_card.title_label.setText(tr("stage_timeline"))
        self.timeline_hint.setText(tr("stage_timeline_hint"))
        self.timeline_model.retranslate()
        self.add_clip.setText(tr("stage_add_clip"))
        self.remove_clip.setText(tr("stage_remove_clip"))
        self.preview_card.title_label.setText(tr("preview_title"))
        self.preview_stop.setText(tr("preview_stop"))
        self.preview_volume_label.setText(tr("preview_volume"))
        self.data_card.title_label.setText(tr("audio_data_title"))
        for key, label in self.stat_labels.items():
            label.setText(tr(f"audio_{key}"))
        self.cancel_button.setText(tr("cancel"))
        self.analyze_button.setText(tr("stage_analyze"))
        self.start_button.setText(tr("start"))
        self._update_preview_button()
        self._render_stats()
        if self._result_path is None:
            self.preview_status.setText(tr("preview_empty"))
        if self.progress.value() == 0:
            self.status.setText(tr("ready"))

    def set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.analyze_button.setEnabled(not running)
        self.remove_clip.setEnabled(not running and self._selected_manual_row() is not None)
        for control in (
            self.stage_button,
            self.stage_download,
            self.output_button,
            self.output_edit,
            self.add_sources,
            self.download_sources,
            self.remove_source,
            self.sources,
            self.tracks,
            self.strength,
            self.timeline,
            self.add_clip,
        ):
            control.setEnabled(not running)

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

    def _add_sources(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            tr("source_label"),
            filter=AUDIO_FILE_FILTER,
        )
        self.add_source_paths(paths)

    def _remove_source(self) -> None:
        row = self.sources.currentRow()
        if row >= 0:
            self.sources.takeItem(row)
            self.clear_result()
            self.invalidate_analysis()

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

    def set_analysis(self, analysis: StageAnalysis) -> None:
        self.timeline_model.set_analysis(analysis)
        self.status.setText(
            tr(
                "stage_analysis_summary",
                songs=len(analysis.song_clips),
                fragments=sum(clip.kind == ClipKind.FRAGMENT for clip in analysis.clips),
                missing=len(analysis.missing_sources),
            )
        )

    def invalidate_analysis(self, clear_timeline: bool = True) -> None:
        if clear_timeline:
            self.timeline_model.set_analysis(None)

    def _selected_manual_row(self) -> int | None:
        index = self.timeline.selectionModel().currentIndex()
        clip = self.timeline_model.clip(index.row()) if index.isValid() else None
        return index.row() if clip is not None and clip.manual else None

    def _update_clip_actions(self) -> None:
        self.remove_clip.setEnabled(self._selected_manual_row() is not None)

    def _selection_changed(self, _selected: QItemSelection, _deselected: QItemSelection) -> None:
        self._update_clip_actions()

    def _clip_edited(self) -> None:
        self.status.setText(tr("stage_manual_updated"))

    def _edit_rejected(self) -> None:
        self.status.setText(tr("stage_invalid_edit"))

    def _add_clip(self) -> None:
        if self.analysis is None:
            self.status.setText(tr("stage_need_analysis"))
            return
        sources = self.source_paths()
        if not sources:
            self.status.setText(tr("stage_need_sources"))
            return
        index = self.sources.currentRow()
        if not 0 <= index < len(sources):
            index = 0
        # Start inside the first gap the matcher left, which is where a spliced
        # backing track's missing pieces almost always belong.
        start = 0.0
        limit = self.analysis.duration_seconds
        for clip in self.analysis.clips:
            if clip.kind == ClipKind.UNMATCHED:
                start, limit = clip.stage_start, clip.stage_end
                break
        length = min(30.0, limit - start)
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
        if row is None:
            return
        if self.timeline_model.remove_clip(row):
            self.status.setText(tr("stage_manual_removed"))
            self._update_clip_actions()

    @staticmethod
    def _clock(milliseconds: int) -> str:
        return format_clock(milliseconds / 1000)

    def set_result(self, path: Path, stats: AudioStats | None = None) -> None:
        result = path.expanduser().resolve()
        if not result.is_file():
            return
        self.stop_preview()
        self._result_path = result
        self._result_stats = stats
        self.player.setSource(QUrl.fromLocalFile(str(result)))
        duration = round(stats.duration_seconds * 1000) if stats else 0
        self.preview_seek.setRange(0, max(duration, 1))
        self.preview_seek.setValue(0)
        self.preview_seek.setEnabled(True)
        self.preview_play.setEnabled(True)
        self.preview_stop.setEnabled(True)
        self.preview_status.setText(result.name)
        self.preview_status.setToolTip(str(result))
        self.preview_time.setText(f"00:00 / {self._clock(duration)}")
        self._render_stats()

    def clear_result(self) -> None:
        self.stop_preview()
        self.player.setSource(QUrl())
        self._result_path = None
        self._result_stats = None
        self.preview_seek.setRange(0, 1)
        self.preview_seek.setValue(0)
        self.preview_seek.setEnabled(False)
        self.preview_play.setEnabled(False)
        self.preview_stop.setEnabled(False)
        self.preview_status.setText(tr("preview_empty"))
        self.preview_status.setToolTip("")
        self.preview_time.setText("00:00 / 00:00")
        self._render_stats()

    def toggle_preview(self) -> None:
        if self._result_path is None:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self._sync_preview_output_device()
            if self.player.duration() and self.player.position() >= self.player.duration():
                self.player.setPosition(0)
            self.player.play()

    def _sync_preview_output_device(self) -> None:
        selected = QMediaDevices.defaultAudioOutput()
        if selected.isNull() or self.audio_output.device().id() == selected.id():
            return
        self.audio_output.setDevice(selected)
        logger.info("preview output device changed: %s", selected.description())

    def stop_preview(self) -> None:
        self.player.stop()
        self._update_preview_button()

    def _seek_preview(self) -> None:
        self._seek_preview_to(self.preview_seek.value())
        self._seeking = False

    def _seek_preview_to(self, position: int) -> None:
        self.player.setPosition(position)
        self._preview_slider_moved(position)

    def _preview_slider_moved(self, position: int) -> None:
        duration = max(self.player.duration(), self.preview_seek.maximum())
        self.preview_time.setText(f"{self._clock(position)} / {self._clock(duration)}")

    def _preview_position_changed(self, position: int) -> None:
        if not self._seeking:
            self.preview_seek.setValue(position)
        self._preview_slider_moved(position)

    def _preview_duration_changed(self, duration: int) -> None:
        if duration > 0:
            self.preview_seek.setMaximum(duration)
        self._preview_position_changed(self.player.position())

    def _update_preview_button(self) -> None:
        key = (
            "preview_pause"
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            else "preview_play"
        )
        self.preview_play.setText(tr(key))

    def _preview_error(self, *_unused: object) -> None:
        if self._result_path is not None:
            self.preview_status.setText(tr("preview_error"))

    @staticmethod
    def _db(value: float) -> str:
        return f"{value:.1f} dBFS" if math.isfinite(value) else "-inf dBFS"

    @staticmethod
    def _file_size(size: int) -> str:
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KiB"
        return f"{size / (1024 * 1024):.1f} MiB"

    def _render_stats(self) -> None:
        stats = self._result_stats
        if stats is None:
            for value in self.stat_values.values():
                value.setText("--")
            return
        channels = (
            tr("audio_mono")
            if stats.channels == 1
            else tr("audio_stereo")
            if stats.channels == 2
            else tr("audio_channel_count", count=stats.channels)
        )
        values = {
            "duration": self._clock(round(stats.duration_seconds * 1000)),
            "sample_rate": f"{stats.sample_rate / 1000:g} kHz",
            "channels": channels,
            "bit_depth": f"{stats.bit_depth}-bit PCM",
            "peak": self._db(stats.peak_dbfs),
            "rms": self._db(stats.rms_dbfs),
            "file_size": self._file_size(stats.file_size),
        }
        for key, value in values.items():
            self.stat_values[key].setText(value)
