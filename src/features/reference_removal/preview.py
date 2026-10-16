"""The two cards that show what a finished job wrote: a player and its numbers."""

from __future__ import annotations

import logging
import math
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, QUrl, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    PrimaryPushButton,
    PushButton,
    Slider,
    StrongBodyLabel,
)

from shared.audio import AudioStats
from shared.i18n import tr
from shared.ui import (
    UNBOUNDED_WIDTH,
    ElidedLabel,
    FoldingRow,
    FormCard,
    LayoutMetrics,
    format_clock,
)

logger = logging.getLogger(__name__)

VOLUME_SLIDER_WIDTH = 150
DEFAULT_VOLUME = 75
STAT_KEYS = ("duration", "sample_rate", "channels", "bit_depth", "peak", "rms", "file_size")


class SeekSlider(Slider):
    """Horizontal slider that seeks directly when the user clicks its groove."""

    seek_requested = Signal(int)

    def _sub_control(self, control: QStyle.SubControl) -> tuple[QStyleOptionSlider, QRect]:
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        rect = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, option, control, self)
        return option, rect

    def _value_at(self, point: QPoint) -> int:
        option, groove = self._sub_control(QStyle.SubControl.SC_SliderGroove)
        _option, handle = self._sub_control(QStyle.SubControl.SC_SliderHandle)
        slider_length = handle.width()
        slider_minimum = groove.left()
        slider_maximum = groove.right() - slider_length + 1
        position = point.x() - slider_length // 2
        return QStyle.sliderValueFromPosition(
            self.minimum(),
            self.maximum(),
            position - slider_minimum,
            max(slider_maximum - slider_minimum, 0),
            option.upsideDown,
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        point = event.position().toPoint()
        _option, handle = self._sub_control(QStyle.SubControl.SC_SliderHandle)
        if event.button() != Qt.MouseButton.LeftButton or handle.contains(point):
            super().mousePressEvent(event)
            return
        value = self._value_at(point)
        self.setValue(value)
        self.seek_requested.emit(value)
        event.accept()


def _clock(milliseconds: int) -> str:
    return format_clock(milliseconds / 1000)


class PreviewCard(FormCard):
    """Play back the file a job wrote, on whichever output the system uses now."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent=parent)
        self.status = ElidedLabel()
        self.time = BodyLabel()
        self.seek = SeekSlider(Qt.Orientation.Horizontal)
        self.play_button = PrimaryPushButton()
        self.stop_button = PushButton()
        self.volume_label = BodyLabel()
        self.volume = Slider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(DEFAULT_VOLUME)
        self.volume.setMinimumWidth(VOLUME_SLIDER_WIDTH)
        self.volume.setMaximumWidth(VOLUME_SLIDER_WIDTH)

        header = QHBoxLayout()
        header.addWidget(self.status, 1)
        header.addWidget(self.time)
        self.layout.addLayout(header)
        self.layout.addWidget(self.seek)
        # Transport buttons hold the line; the volume pair drops below them
        # rather than squeezing the slider down to a few pixels.
        self.controls = FoldingRow(self, lead_expands=True)
        self.controls.add_lead(self.play_button)
        self.controls.add_lead(self.stop_button)
        self.controls.add_lead_stretch()
        self.controls.add_trail(self.volume_label)
        self.controls.add_trail(self.volume, folded_stretch=1)
        self.layout.addWidget(self.controls)

        self.media_devices = QMediaDevices(self)
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(DEFAULT_VOLUME / 100)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self._path: Path | None = None
        self._seeking = False
        self._follow_default_output()

        self.media_devices.audioOutputsChanged.connect(self._follow_default_output)
        self.play_button.clicked.connect(self.toggle)
        self.stop_button.clicked.connect(self.stop)
        self.volume.valueChanged.connect(lambda value: self.audio_output.setVolume(value / 100))
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self._seek_released)
        self.seek.sliderMoved.connect(self._show_position)
        self.seek.seek_requested.connect(self._seek_to)
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(lambda _state: self._retranslate_play())
        self.player.errorOccurred.connect(self._playback_failed)
        self.clear()

    @property
    def path(self) -> Path | None:
        """The file loaded for playback, if a job has written one."""
        return self._path

    def load(self, path: Path, duration_seconds: float) -> None:
        self.stop()
        self._path = path
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        duration = round(duration_seconds * 1000)
        self.seek.setRange(0, max(duration, 1))
        self.seek.setValue(0)
        self.status.setText(path.name)
        self.status.setToolTip(str(path))
        self.time.setText(f"{_clock(0)} / {_clock(duration)}")
        self._set_loaded(True)

    def clear(self) -> None:
        self.stop()
        self.player.setSource(QUrl())
        self._path = None
        self.seek.setRange(0, 1)
        self.seek.setValue(0)
        self.status.setText(tr("preview_empty"))
        self.status.setToolTip("")
        self.time.setText(f"{_clock(0)} / {_clock(0)}")
        self._set_loaded(False)

    def toggle(self) -> None:
        if self._path is None:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            return
        self._follow_default_output()
        if self.player.duration() and self.player.position() >= self.player.duration():
            self.player.setPosition(0)
        self.player.play()

    def stop(self) -> None:
        self.player.stop()
        self._retranslate_play()

    def retranslate(self) -> None:
        self.title_label.setText(tr("preview_title"))
        self.stop_button.setText(tr("preview_stop"))
        self.volume_label.setText(tr("preview_volume"))
        self._retranslate_play()
        if self._path is None:
            self.status.setText(tr("preview_empty"))

    def apply_layout(self, metrics: LayoutMetrics) -> None:
        super().apply_layout(metrics)
        # A capped slider reads as a volume control; an uncapped one filling a
        # folded second line reads as a second seek bar, so it only spans the
        # row once the transport buttons have a line to themselves.
        self.volume.setMaximumWidth(
            UNBOUNDED_WIDTH if metrics.stacked_rows else VOLUME_SLIDER_WIDTH
        )

    def _set_loaded(self, loaded: bool) -> None:
        for control in (self.seek, self.play_button, self.stop_button):
            control.setEnabled(loaded)

    def _retranslate_play(self) -> None:
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setText(tr("preview_pause" if playing else "preview_play"))

    def _follow_default_output(self) -> None:
        selected = QMediaDevices.defaultAudioOutput()
        if selected.isNull() or self.audio_output.device().id() == selected.id():
            return
        self.audio_output.setDevice(selected)
        logger.info("preview output device changed: %s", selected.description())

    def _seek_released(self) -> None:
        self._seek_to(self.seek.value())
        self._seeking = False

    def _seek_to(self, position: int) -> None:
        self.player.setPosition(position)
        self._show_position(position)

    def _show_position(self, position: int) -> None:
        duration = max(self.player.duration(), self.seek.maximum())
        self.time.setText(f"{_clock(position)} / {_clock(duration)}")

    def _position_changed(self, position: int) -> None:
        if not self._seeking:
            self.seek.setValue(position)
        self._show_position(position)

    def _duration_changed(self, duration: int) -> None:
        if duration > 0:
            self.seek.setMaximum(duration)
        self._position_changed(self.player.position())

    def _playback_failed(self, *_unused: object) -> None:
        if self._path is not None:
            self.status.setText(tr("preview_error"))


def _db(value: float) -> str:
    return f"{value:.1f} dBFS" if math.isfinite(value) else "-inf dBFS"


def _file_size(size: int) -> str:
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KiB"
    return f"{size / (1024 * 1024):.1f} MiB"


class AudioDataCard(FormCard):
    """The format and levels of the file a job wrote, as a grid of tiles.

    It stays hidden until there is a file to describe: seven dashes say
    nothing a user needs before the first job has run.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent=parent)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(24)
        self.grid.setVerticalSpacing(14)
        self.labels: dict[str, CaptionLabel] = {}
        self.values: dict[str, StrongBodyLabel] = {}
        self._tiles: list[QWidget] = []
        for key in STAT_KEYS:
            tile = QWidget(self)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(0, 0, 0, 0)
            tile_layout.setSpacing(3)
            self.labels[key] = CaptionLabel(tile)
            self.values[key] = StrongBodyLabel("--", tile)
            tile_layout.addWidget(self.labels[key])
            tile_layout.addWidget(self.values[key])
            self._tiles.append(tile)
        # The widest arrangement until the page hands down its first metrics.
        self._reflow(4)
        self.layout.addLayout(self.grid)
        self._stats: AudioStats | None = None
        self.show_stats(None)

    def show_stats(self, stats: AudioStats | None) -> None:
        self._stats = stats
        self._render()
        self.setVisible(stats is not None)

    def retranslate(self) -> None:
        self.title_label.setText(tr("audio_data_title"))
        for key, label in self.labels.items():
            label.setText(tr(f"audio_{key}"))
        self._render()

    def apply_layout(self, metrics: LayoutMetrics) -> None:
        super().apply_layout(metrics)
        self._reflow(metrics.tile_columns)
        self.grid.setHorizontalSpacing(12 if metrics.stacked_rows else 24)

    def _reflow(self, columns: int) -> None:
        for tile in self._tiles:
            self.grid.removeWidget(tile)
        for index, tile in enumerate(self._tiles):
            self.grid.addWidget(tile, index // columns, index % columns)

    def _render(self) -> None:
        stats = self._stats
        if stats is None:
            for value in self.values.values():
                value.setText("--")
            return
        if stats.channels == 1:
            channels = tr("audio_mono")
        elif stats.channels == 2:
            channels = tr("audio_stereo")
        else:
            channels = tr("audio_channel_count", count=stats.channels)
        shown = {
            "duration": _clock(round(stats.duration_seconds * 1000)),
            "sample_rate": f"{stats.sample_rate / 1000:g} kHz",
            "channels": channels,
            "bit_depth": f"{stats.bit_depth}-bit PCM",
            "peak": _db(stats.peak_dbfs),
            "rms": _db(stats.rms_dbfs),
            "file_size": _file_size(stats.file_size),
        }
        for key, text in shown.items():
            self.values[key].setText(text)
