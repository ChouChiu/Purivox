from __future__ import annotations

import re
from dataclasses import replace

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt, Signal

from features.full_stage.matching import add_manual_clip, remove_manual_clip
from features.full_stage.models import ClipKind, FullStageAnalysis, TimelineClip
from shared.i18n import tr

ENABLED, KIND, STAGE_RANGE, SOURCE_RANGE, CONFIDENCE, SOURCE = range(6)
_HEADER_KEYS = (
    "stage_clip_enabled",
    "stage_clip_type",
    "stage_clip_time",
    "stage_source_time",
    "stage_confidence",
    "stage_clip_source",
)
_KIND_KEYS = {
    ClipKind.SONG: "stage_type_song",
    ClipKind.FRAGMENT: "stage_type_fragment",
    ClipKind.UNMATCHED: "stage_type_unmatched",
}
_CENTERED = {KIND, STAGE_RANGE, SOURCE_RANGE, CONFIDENCE}
_RANGE_SEPARATOR = re.compile(r"\s+-\s+")
# Qt always passes a parent index; the shared invalid one keeps the override
# signature identical to the C++ virtual it replaces.
_NO_PARENT = QModelIndex()


def clock(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    whole, millis = divmod(milliseconds, 1000)
    minutes, secs = divmod(whole, 60)
    hours, minutes = divmod(minutes, 60)
    prefix = f"{hours:d}:{minutes:02d}" if hours else f"{minutes:02d}"
    return f"{prefix}:{secs:02d}.{millis:03d}"


def parse_clock(text: str) -> float:
    parts = text.strip().split(":")
    if not 1 <= len(parts) <= 3:
        raise ValueError("invalid time")
    values = [float(part.strip()) for part in parts]
    if any(value < 0 for value in values):
        raise ValueError("negative time")
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return values[0] * 60 + values[1]
    return values[0] * 3600 + values[1] * 60 + values[2]


def parse_range(text: str) -> tuple[float, float]:
    parts = _RANGE_SEPARATOR.split(text.strip())
    if len(parts) != 2:
        raise ValueError("time range must contain a separated dash")
    start, end = (parse_clock(part) for part in parts)
    if end <= start:
        raise ValueError("time range must be positive")
    return start, end


class TimelineModel(QAbstractTableModel):
    """Expose one full-stage analysis as an editable table.

    The analysis stays the single source of truth: the view reads it through
    `data()` and writes back through `setData()`, so no code re-renders rows or
    guards against the signals its own repainting would emit.
    """

    clip_edited = Signal()
    edit_rejected = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._analysis: FullStageAnalysis | None = None

    @property
    def analysis(self) -> FullStageAnalysis | None:
        return self._analysis

    def set_analysis(self, analysis: FullStageAnalysis | None) -> None:
        self.beginResetModel()
        self._analysis = analysis
        self.endResetModel()

    def clip(self, row: int) -> TimelineClip | None:
        if self._analysis is None or not 0 <= row < len(self._analysis.clips):
            return None
        return self._analysis.clips[row]

    def rowCount(self, parent: QModelIndex = _NO_PARENT) -> int:
        if parent.isValid() or self._analysis is None:
            return 0
        return len(self._analysis.clips)

    def columnCount(self, parent: QModelIndex = _NO_PARENT) -> int:
        return 0 if parent.isValid() else len(_HEADER_KEYS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = 0):
        if orientation != Qt.Orientation.Horizontal or role != Qt.ItemDataRole.DisplayRole:
            return None
        return tr(_HEADER_KEYS[section])

    def data(self, index: QModelIndex, role: int = 0):
        clip = self.clip(index.row())
        if clip is None or not index.isValid():
            return None
        column = index.column()
        if role == Qt.ItemDataRole.CheckStateRole and column == ENABLED:
            if clip.kind == ClipKind.UNMATCHED:
                return None
            return Qt.CheckState.Checked if clip.enabled else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.TextAlignmentRole and column in _CENTERED:
            return Qt.AlignmentFlag.AlignCenter
        if role not in {Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole}:
            return None
        if column == KIND:
            return tr(_KIND_KEYS[clip.kind])
        if column == STAGE_RANGE:
            return f"{clock(clip.stage_start)} - {clock(clip.stage_end)}"
        if column == SOURCE_RANGE:
            if clip.kind == ClipKind.UNMATCHED:
                return "—"
            return f"{clock(clip.source_start)} - {clock(clip.source_end)}"
        if column == CONFIDENCE:
            if clip.manual:
                return tr("stage_manual_label")
            return "—" if clip.kind == ClipKind.UNMATCHED else f"{clip.confidence:.0%}"
        if column == SOURCE:
            return tr("stage_unmatched_label") if clip.source is None else clip.source.name
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        clip = self.clip(index.row())
        if clip is None:
            return Qt.ItemFlag.NoItemFlags
        matched = clip.kind != ClipKind.UNMATCHED
        if index.column() == ENABLED:
            if not matched:
                return Qt.ItemFlag.NoItemFlags
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == STAGE_RANGE or (index.column() == SOURCE_RANGE and matched):
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index: QModelIndex, value, role: int = 0) -> bool:
        clip = self.clip(index.row())
        if clip is None or self._analysis is None:
            return False
        try:
            updated = self._edited(clip, index.column(), value, role)
        except ValueError:
            self.edit_rejected.emit()
            return False
        if updated is None:
            return False
        clips = list(self._analysis.clips)
        clips[index.row()] = updated
        self._analysis = replace(self._analysis, clips=tuple(clips))
        self.dataChanged.emit(index.siblingAtColumn(0), index.siblingAtColumn(SOURCE))
        self.clip_edited.emit()
        return True

    def _edited(self, clip: TimelineClip, column: int, value, role: int) -> TimelineClip | None:
        """Apply one cell edit to a clip, or raise `ValueError` if it is invalid."""
        if column == ENABLED and role == Qt.ItemDataRole.CheckStateRole:
            if clip.kind == ClipKind.UNMATCHED:
                return None
            return replace(clip, enabled=Qt.CheckState(value) == Qt.CheckState.Checked)
        if role != Qt.ItemDataRole.EditRole:
            return None
        if column == STAGE_RANGE:
            start, end = parse_range(str(value))
            if end > self._analysis.duration_seconds:
                raise ValueError("stage range exceeds duration")
            return replace(clip, stage_start=start, stage_end=end)
        if column == SOURCE_RANGE and clip.kind != ClipKind.UNMATCHED:
            start, end = parse_range(str(value))
            return replace(clip, source_start=start, source_end=end)
        return None

    def add_clip(self, clip: TimelineClip) -> bool:
        """Insert a user-supplied clip and rebuild the gaps around it."""
        if self._analysis is None:
            return False
        try:
            analysis = add_manual_clip(self._analysis, clip)
        except (IndexError, ValueError):
            self.edit_rejected.emit()
            return False
        self.set_analysis(analysis)
        return True

    def remove_clip(self, row: int) -> bool:
        if self._analysis is None:
            return False
        try:
            analysis = remove_manual_clip(self._analysis, row)
        except (IndexError, ValueError):
            self.edit_rejected.emit()
            return False
        self.set_analysis(analysis)
        return True

    def retranslate(self) -> None:
        """Refresh every translated cell after the application language changes."""
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(_HEADER_KEYS) - 1)
        rows = self.rowCount()
        if rows:
            self.dataChanged.emit(self.index(0, 0), self.index(rows - 1, SOURCE))
