from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QItemSelection, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QListWidgetItem,
)
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    LineEdit,
    ListWidget,
    PrimaryPushButton,
    PushButton,
    Slider,
    SwitchButton,
    TableView,
    TitleLabel,
)

from features.full_stage.models import ClipKind, FullStageAnalysis, TimelineClip
from features.full_stage.timeline_model import SOURCE, TimelineModel
from shared.i18n import tr
from shared.ui import (
    AUDIO_FILE_FILTER,
    WAV_FILE_FILTER,
    FormCard,
    Lane,
    LayoutMetrics,
    PageScrollArea,
    normalized_wav_path,
)

SOURCES_HEIGHT, SHORT_SOURCES_HEIGHT = 150, 110
TIMELINE_HEIGHT, SHORT_TIMELINE_HEIGHT = 260, 180


class FullStagePage(PageScrollArea):
    analyze_requested = Signal()
    start_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("fullStagePage")

        self.title = TitleLabel()
        self.layout.addWidget(self.title)

        self.files = FormCard()
        self.stage_label, self.stage_edit, self.stage_button = (
            BodyLabel(),
            LineEdit(),
            PushButton(),
        )
        self.stage_edit.setReadOnly(True)
        self.output_label, self.output_edit, self.output_button = (
            BodyLabel(),
            LineEdit(),
            PushButton(),
        )
        self.files.add_row(self.stage_label, self.stage_edit, self.stage_button)
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
        self.remove_source = PushButton(FluentIcon.DELETE, "")
        for button in (self.add_sources, self.remove_source):
            source_actions.addWidget(button)
        source_actions.addStretch()
        self.sources_card.layout.addLayout(source_actions)
        self.add_card(self.sources_card)

        self.parameters = FormCard()
        self.strength_label, self.strength_value = BodyLabel(), BodyLabel("75%")
        self.strength = Slider(Qt.Orientation.Horizontal)
        self.strength.setRange(0, 100)
        self.strength.setValue(75)
        self.include_fragments_label, self.include_fragments = BodyLabel(), SwitchButton()
        self.include_fragments.setChecked(True)
        self.parameters.add_row(self.strength_label, self.strength, self.strength_value)
        self.parameters.add_row(self.include_fragments_label, self.include_fragments)
        self.add_card(self.parameters)

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

        self.add_status_card()

        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_button = PushButton()
        self.analyze_button = PushButton(FluentIcon.SYNC, "")
        self.start_button = PrimaryPushButton(FluentIcon.PLAY, "")
        self.cancel_button.setEnabled(False)
        self.start_button.setEnabled(False)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.analyze_button)
        actions.addWidget(self.start_button)
        self.layout.addLayout(actions)
        self.layout.addStretch()

        self.stage_button.clicked.connect(self._select_stage)
        self.output_button.clicked.connect(self._select_output)
        self.add_sources.clicked.connect(self._add_sources)
        self.remove_source.clicked.connect(self._remove_source)
        self.analyze_button.clicked.connect(self.analyze_requested)
        self.start_button.clicked.connect(self.start_requested)
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.strength.valueChanged.connect(lambda value: self.strength_value.setText(f"{value}%"))
        self.timeline.selectionModel().selectionChanged.connect(self._selection_changed)
        self.timeline_model.clip_edited.connect(self._clip_edited)
        self.timeline_model.edit_rejected.connect(self._edit_rejected)
        self.add_clip.clicked.connect(self._add_clip)
        self.remove_clip.clicked.connect(self._remove_clip)

    @property
    def analysis(self) -> FullStageAnalysis | None:
        return self.timeline_model.analysis

    def apply_layout(self, metrics: LayoutMetrics) -> None:
        super().apply_layout(metrics)
        # The source list and the timeline are the two panes that would eat a
        # short window whole, so they give back height before anything else.
        self.sources.setMinimumHeight(SHORT_SOURCES_HEIGHT if metrics.short else SOURCES_HEIGHT)
        self.timeline.setMinimumHeight(SHORT_TIMELINE_HEIGHT if metrics.short else TIMELINE_HEIGHT)

    def retranslate(self) -> None:
        self.title.setText(tr("nav_full_stage"))
        self.files.title_label.setText(tr("stage_files"))
        self.stage_label.setText(tr("stage_audio"))
        self.output_label.setText(tr("output_file"))
        self.output_edit.setPlaceholderText(tr("stage_output_hint"))
        self.stage_button.setText(tr("browse"))
        self.output_button.setText(tr("browse"))
        self.sources_card.title_label.setText(tr("stage_sources"))
        self.sources_hint.setText(tr("stage_sources_hint"))
        self.add_sources.setText(tr("stage_add_sources"))
        self.remove_source.setText(tr("stage_remove_source"))
        self.add_clip.setText(tr("stage_add_clip"))
        self.remove_clip.setText(tr("stage_remove_clip"))
        self.parameters.title_label.setText(tr("params"))
        self.strength_label.setText(tr("strength"))
        self.include_fragments_label.setText(tr("stage_include_fragments"))
        self.include_fragments.setOnText(tr("switch_on"))
        self.include_fragments.setOffText(tr("switch_off"))
        self.timeline_card.title_label.setText(tr("stage_timeline"))
        self.timeline_hint.setText(tr("stage_timeline_hint"))
        self.timeline_model.retranslate()
        self.retranslate_status_card()
        self.cancel_button.setText(tr("cancel"))
        self.analyze_button.setText(tr("stage_analyze"))
        self.start_button.setText(tr("stage_start"))
        if self.progress.value() == 0:
            self.status.setText(tr("stage_ready"))

    def source_paths(self) -> tuple[Path, ...]:
        return tuple(
            Path(str(self.sources.item(index).data(Qt.ItemDataRole.UserRole)))
            for index in range(self.sources.count())
        )

    def normalized_output_path(self) -> Path | None:
        path = normalized_wav_path(
            self.output_edit.text(), self.stage_edit.text(), "_full_stage_vocals.wav"
        )
        if path is None:
            return None
        self.output_edit.setText(str(path))
        return path

    def set_running(self, running: bool) -> None:
        self.cancel_button.setEnabled(running)
        self.analyze_button.setEnabled(not running)
        self.start_button.setEnabled(not running and self.analysis is not None)
        for control in (
            self.stage_button,
            self.output_button,
            self.output_edit,
            self.add_sources,
            self.remove_source,
            self.sources,
            self.strength,
            self.include_fragments,
            self.timeline,
            self.add_clip,
        ):
            control.setEnabled(not running)
        self.remove_clip.setEnabled(not running and self._selected_manual_row() is not None)

    def set_analysis(self, analysis: FullStageAnalysis) -> None:
        self.timeline_model.set_analysis(analysis)
        self.start_button.setEnabled(True)
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
        self.start_button.setEnabled(False)

    def browse_primary_input(self) -> None:
        """Open the file dialog a page-level shortcut should reach."""
        self._select_stage()

    def _select_stage(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("stage_audio"),
            filter=AUDIO_FILE_FILTER,
        )
        if path:
            self.set_stage(path)

    def set_stage(self, path: str) -> None:
        self.stage_edit.setText(path)
        self.output_edit.setText(
            str(Path(path).with_name(Path(path).stem + "_full_stage_vocals.wav"))
        )
        self.invalidate_analysis()

    def _select_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("output_file"),
            self.output_edit.text(),
            WAV_FILE_FILTER,
        )
        if path:
            self.output_edit.setText(path)

    def _add_sources(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            tr("stage_sources"),
            filter=AUDIO_FILE_FILTER,
        )
        self.add_source_paths(paths)

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
            self.invalidate_analysis()

    def _remove_source(self) -> None:
        row = self.sources.currentRow()
        if row >= 0:
            self.sources.takeItem(row)
            self.invalidate_analysis()

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
