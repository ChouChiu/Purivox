from __future__ import annotations

import re

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt, Signal

from features.reference_removal.matching import add_manual_clip, edit_clip, remove_manual_clip
from features.reference_removal.models import ClipKind, StageAnalysis, TimelineClip
from shared.i18n import tr
from shared.ui.cards import format_clock

ENABLED, KIND, STAGE_RANGE, SOURCE_RANGE, SPEED, CONFIDENCE, SOURCE = range(7)
_HEADER_KEYS = (
    "stage_clip_enabled",
    "stage_clip_type",
    "stage_clip_time",
    "stage_source_time",
    "stage_clip_speed",
    "stage_confidence",
    "stage_clip_source",
)
_KIND_KEYS = {
    ClipKind.SONG: "stage_type_song",
    ClipKind.FRAGMENT: "stage_type_fragment",
    ClipKind.UNMATCHED: "stage_type_unmatched",
}
_CENTERED = {KIND, STAGE_RANGE, SOURCE_RANGE, SPEED, CONFIDENCE}
_RANGE_SEPARATOR = re.compile(r"\s+-\s+")
# Qt always passes a parent index; the shared invalid one keeps the override
# signature identical to the C++ virtual it replaces.
_NO_PARENT = QModelIndex()


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
    """Expose one stage analysis as an editable table.

    The analysis stays the single source of truth: the view reads it through
    `data()` and writes back through `setData()`, so no code re-renders rows or
    guards against the signals its own repainting would emit.
    """

    clip_edited = Signal()
    edit_rejected = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._analysis: StageAnalysis | None = None

    @property
    def analysis(self) -> StageAnalysis | None:
        return self._analysis

    def set_analysis(self, analysis: StageAnalysis | None) -> None:
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
        if clip is None:
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
            return (
                f"{format_clock(clip.stage_start, millis=True)}"
                f" - {format_clock(clip.stage_end, millis=True)}"
            )
        if column == SOURCE_RANGE:
            if clip.kind == ClipKind.UNMATCHED:
                return "—"
            return (
                f"{format_clock(clip.source_start, millis=True)}"
                f" - {format_clock(clip.source_end, millis=True)}"
            )
        if column == SPEED:
            if clip.kind == ClipKind.UNMATCHED or abs(clip.speed - 1.0) < 1e-9:
                return "—"
            return f"{clip.speed:.3f}×"  # noqa: RUF001 (a factor, not a letter x)
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
        if self._analysis is None or self.clip(index.row()) is None:
            return False
        row, column = index.row(), index.column()
        edit = role == Qt.ItemDataRole.EditRole
        try:
            if column == ENABLED and role == Qt.ItemDataRole.CheckStateRole:
                checked = Qt.CheckState(value) == Qt.CheckState.Checked
                analysis = edit_clip(self._analysis, row, enabled=checked)
            elif column == STAGE_RANGE and edit:
                analysis = edit_clip(self._analysis, row, stage_range=parse_range(str(value)))
            elif column == SOURCE_RANGE and edit:
                analysis = edit_clip(self._analysis, row, source_range=parse_range(str(value)))
            else:
                return False
        except ValueError:
            self.edit_rejected.emit()
            return False
        self._analysis = analysis
        self.dataChanged.emit(index.siblingAtColumn(0), index.siblingAtColumn(SOURCE))
        self.clip_edited.emit()
        return True

    def add_clip(self, clip: TimelineClip) -> bool:
        """Insert a user-supplied clip and rebuild the gaps around it."""
        if self._analysis is None:
            return False
        try:
            analysis = add_manual_clip(self._analysis, clip)
        except ValueError:
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
