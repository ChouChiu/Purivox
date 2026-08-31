from __future__ import annotations

import logging
import math
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    LineEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    Slider,
    StrongBodyLabel,
    SwitchButton,
    TitleLabel,
)

from features.reference_removal.preview import SeekSlider
from shared.audio import AudioStats
from shared.config import cfg
from shared.i18n import tr
from shared.ui import (
    AUDIO_FILE_FILTER,
    UNBOUNDED_WIDTH,
    WAV_FILE_FILTER,
    AudioDropLineEdit,
    FoldingRow,
    FormCard,
    Lane,
    LayoutMetrics,
    PageScrollArea,
    allow_shrinking,
)

logger = logging.getLogger(__name__)

VOLUME_SLIDER_WIDTH = 150
STAT_COLUMNS = 4


class MrPage(PageScrollArea):
    start_requested = Signal()
    cancel_requested = Signal()
    song_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mrPage")
        self.title = TitleLabel()
        self.layout.addWidget(self.title)
        self.files = FormCard()
        self.song_label, self.song_edit, self.song_button = (
            BodyLabel(),
            AudioDropLineEdit(),
            PushButton(),
        )
        self.acc_label, self.acc_edit, self.acc_button = (
            BodyLabel(),
            AudioDropLineEdit(),
            PushButton(),
        )
        self.output_label, self.output_edit, self.output_button = (
            BodyLabel(),
            LineEdit(),
            PushButton(),
        )
        for edit in (self.song_edit, self.acc_edit):
            edit.setReadOnly(True)
        self.output_edit.setClearButtonEnabled(True)
        self._output_user_edited = False
        self.auto_find = SwitchButton()
        self.auto_find.setChecked(bool(cfg.auto_find.value))
        self.files.add_row(self.song_label, self.song_edit, self.song_button)
        self.files.add_row(self.acc_label, self.acc_edit, self.acc_button, self.auto_find)
        self.files.add_row(self.output_label, self.output_edit, self.output_button)
        self.add_card(self.files)

        self.parameters = FormCard()
        self.strength_label, self.strength_value = BodyLabel(), BodyLabel("75%")
        self.strength = Slider(Qt.Orientation.Horizontal)
        self.strength.setRange(0, 100)
        self.strength.setValue(75)
        self.parameters.add_row(self.strength_label, self.strength, self.strength_value)
        self.add_card(self.parameters)

        self.status_card = FormCard()
        self.status = BodyLabel()
        self.status.setWordWrap(True)
        allow_shrinking(self.status)
        self.progress = ProgressBar()
        self.status_card.layout.addWidget(self.status)
        self.status_card.layout.addWidget(self.progress)
        self.add_card(self.status_card, Lane.SECONDARY)

        self.preview_card = FormCard()
        self.preview_status = BodyLabel()
        allow_shrinking(self.preview_status)
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
        self.start_button = PrimaryPushButton()
        self.cancel_button.setEnabled(False)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.start_button)
        self.layout.addLayout(actions)
        self.layout.addStretch()

        self.song_button.clicked.connect(self._select_song)
        self.acc_button.clicked.connect(self._select_acc)
        self.song_edit.file_dropped.connect(self.set_song)
        self.acc_edit.file_dropped.connect(self.set_accompaniment)
        self.output_button.clicked.connect(self._select_output)
        self.output_edit.textEdited.connect(self._output_edited)
        self.output_edit.editingFinished.connect(self.normalized_output_path)
        self.start_button.clicked.connect(self.start_requested)
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.strength.valueChanged.connect(lambda value: self.strength_value.setText(f"{value}%"))
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

    def retranslate(self) -> None:
        self.title.setText(tr("mr_single_title"))
        self.files.title_label.setText(tr("file_select"))
        self.parameters.title_label.setText(tr("params"))
        self.status_card.title_label.setText(tr("status_group"))
        self.preview_card.title_label.setText(tr("preview_title"))
        self.data_card.title_label.setText(tr("audio_data_title"))
        self.song_label.setText(tr("mr_audio_label"))
        self.acc_label.setText(tr("acc_label"))
        self.output_label.setText(tr("output_file"))
        self.output_edit.setPlaceholderText(tr("output_name_hint"))
        self.strength_label.setText(tr("strength"))
        for button in (self.song_button, self.acc_button, self.output_button):
            button.setText(tr("browse"))
        for edit in (self.song_edit, self.acc_edit):
            edit.setToolTip(tr("drop_hint"))
        self.auto_find.setOnText(tr("auto_find_on"))
        self.auto_find.setOffText(tr("auto_find_off"))
        self.cancel_button.setText(tr("cancel"))
        self.start_button.setText(tr("start"))
        self.preview_stop.setText(tr("preview_stop"))
        self.preview_volume_label.setText(tr("preview_volume"))
        for key, label in self.stat_labels.items():
            label.setText(tr(f"audio_{key}"))
        self._update_preview_button()
        self._render_stats()
        if self._result_path is None:
            self.preview_status.setText(tr("preview_empty"))
        if self.progress.value() == 0:
            self.status.setText(tr("ready"))

    def set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        for control in (
            self.song_button,
            self.acc_button,
            self.output_button,
            self.output_edit,
            self.strength,
            self.auto_find,
        ):
            control.setEnabled(not running)

    def browse_primary_input(self) -> None:
        """Open the file dialog a page-level shortcut should reach."""
        self._select_song()

    def _select_song(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("mr_audio_label"),
            filter=AUDIO_FILE_FILTER,
        )
        if path:
            self.set_song(path)

    def set_song(self, path: str) -> None:
        """Take a song from the file dialog or from a drop, identically."""
        self.clear_result()
        self.song_edit.setText(path)
        if not self._output_user_edited or not self.output_edit.text().strip():
            self.output_edit.setText(str(Path(path).with_name(Path(path).stem + "_vocals.wav")))
            self._output_user_edited = False
        self.song_changed.emit(path)

    def _select_acc(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("acc_label"),
            filter=AUDIO_FILE_FILTER,
        )
        if path:
            self.set_accompaniment(path)

    def set_accompaniment(self, path: str) -> None:
        self.clear_result()
        self.acc_edit.setText(path)

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
        text = self.output_edit.text().strip()
        if not text:
            song = self.song_edit.text().strip()
            if not song:
                return None
            source = Path(song).expanduser().resolve()
            path = source.with_name(source.stem + "_vocals.wav")
            self._output_user_edited = False
        else:
            path = Path(text).expanduser()
        if path.suffix.lower() != ".wav":
            path = path.with_suffix(".wav")
        if not path.is_absolute():
            song = self.song_edit.text().strip()
            base = Path(song).expanduser().resolve().parent if song else Path.cwd()
            path = base / path
        path = path.resolve()
        self.output_edit.setText(str(path))
        return path

    @staticmethod
    def _clock(milliseconds: int) -> str:
        total_seconds = max(0, int(milliseconds) // 1000)
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"

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
        duration = max(self.player.duration(), self.preview_seek.maximum())
        self.preview_time.setText(f"{self._clock(position)} / {self._clock(duration)}")

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
