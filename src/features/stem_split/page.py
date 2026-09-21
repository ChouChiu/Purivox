from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    LineEdit,
    ListWidget,
    PrimaryPushButton,
    PushButton,
    Slider,
    TitleLabel,
)

from features.stem_split.models import (
    DEFAULT_CROSSOVER_HZ,
    StemLayout,
    StemSplitResult,
    layout_stems,
)
from shared.i18n import tr
from shared.ui import (
    AUDIO_FILE_FILTER,
    FormCard,
    Lane,
    LayoutMetrics,
    PageScrollArea,
    allow_shrinking,
)

logger = logging.getLogger(__name__)

# The band a bass split is worth putting a control on.  The job accepts the
# whole audible range and the CLI offers it; a slider that wide would put every
# useful value in its first few pixels.
CROSSOVER_SLIDER_RANGE = (40, 400)
STEMS_HEIGHT, SHORT_STEMS_HEIGHT = 190, 130
# The suffix a split's folder is named with when the field is left alone.
OUTPUT_SUFFIX = "_stems"


class StemPage(PageScrollArea):
    """The stem-split page: one recording, and the stems its channels allow.

    There is no song source here and nothing to match.  What can be separated
    follows from the channel layout of the file, which is why the page names
    the stems it is about to write only once the split has read it.
    """

    start_requested = Signal()
    cancel_requested = Signal()
    download_requested = Signal()
    open_output_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("stemPage")
        self.title = TitleLabel()
        self.layout.addWidget(self.title)

        self.files = FormCard()
        self.source_label, self.source_edit, self.source_button = (
            BodyLabel(),
            LineEdit(),
            PushButton(),
        )
        self.source_download = PushButton(FluentIcon.CLOUD_DOWNLOAD, "")
        self.source_edit.setReadOnly(True)
        self.output_label, self.output_edit, self.output_button = (
            BodyLabel(),
            LineEdit(),
            PushButton(),
        )
        self.output_edit.setClearButtonEnabled(True)
        self._output_user_edited = False
        for edit in (self.source_edit, self.output_edit):
            allow_shrinking(edit)
        self.files.add_row(
            self.source_label, self.source_edit, self.source_button, self.source_download
        )
        self.files.add_row(self.output_label, self.output_edit, self.output_button)
        self.add_card(self.files)

        self.parameters = FormCard()
        self.crossover_label, self.crossover_value = BodyLabel(), BodyLabel()
        self.crossover = Slider(Qt.Orientation.Horizontal)
        self.crossover.setRange(*CROSSOVER_SLIDER_RANGE)
        self.crossover.setValue(int(DEFAULT_CROSSOVER_HZ))
        self.parameters.add_row(self.crossover_label, self.crossover, self.crossover_value)
        self.crossover_hint = BodyLabel()
        self.crossover_hint.setWordWrap(True)
        self.parameters.layout.addWidget(self.crossover_hint)
        self.add_card(self.parameters)

        self.add_status_card()

        self.stems_card = FormCard()
        self.stems_hint = BodyLabel()
        self.stems_hint.setWordWrap(True)
        self.stems_card.layout.addWidget(self.stems_hint)
        self.stems = ListWidget()
        self.stems.setMinimumHeight(STEMS_HEIGHT)
        self.stems_card.layout.addWidget(self.stems)
        self.open_output = PushButton(FluentIcon.FOLDER, "")
        self.open_output.setEnabled(False)
        stem_actions = QHBoxLayout()
        stem_actions.addWidget(self.open_output)
        stem_actions.addStretch()
        self.stems_card.layout.addLayout(stem_actions)
        self.add_card(self.stems_card, Lane.SECONDARY)

        self._result: StemSplitResult | None = None

        actions = QHBoxLayout()
        actions.addStretch()
        self.cancel_button = PushButton()
        self.start_button = PrimaryPushButton(FluentIcon.PLAY, "")
        self.cancel_button.setEnabled(False)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.start_button)
        self.layout.addLayout(actions)
        self.layout.addStretch()

        self.source_button.clicked.connect(self.browse_primary_input)
        self.source_download.clicked.connect(self.download_requested)
        self.output_button.clicked.connect(self._select_output)
        self.output_edit.textEdited.connect(self._output_edited)
        self.crossover.valueChanged.connect(self._crossover_changed)
        self.open_output.clicked.connect(self.open_output_requested)
        self.start_button.clicked.connect(self.start_requested)
        self.cancel_button.clicked.connect(self.cancel_requested)

    def apply_layout(self, metrics: LayoutMetrics) -> None:
        super().apply_layout(metrics)
        self.stems.setMinimumHeight(SHORT_STEMS_HEIGHT if metrics.short else STEMS_HEIGHT)

    def browse_primary_input(self) -> None:
        chosen, _filter = QFileDialog.getOpenFileName(
            self, tr("stem_pick_source"), "", AUDIO_FILE_FILTER
        )
        if chosen:
            self.set_source(chosen)

    def set_source(self, path: str) -> None:
        """The one way a recording reaches this page, whoever chose it."""
        self.source_edit.setText(path)
        self.clear_result()
        if not self._output_user_edited:
            self.output_edit.setText(str(self._default_output_dir(Path(path))))

    @staticmethod
    def _default_output_dir(source: Path) -> Path:
        source = source.expanduser().resolve()
        return source.with_name(source.stem + OUTPUT_SUFFIX)

    def _select_output(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, tr("stem_pick_output"), "")
        if chosen:
            self._output_user_edited = True
            self.output_edit.setText(chosen)

    def _output_edited(self, _text: str) -> None:
        self._output_user_edited = True

    def _crossover_changed(self, value: int) -> None:
        self.crossover_value.setText(tr("stem_hertz", hz=value))

    def source_path(self) -> Path | None:
        text = self.source_edit.text().strip()
        return Path(text).expanduser().resolve() if text else None

    def output_directory(self) -> Path | None:
        """Where the stems go: what the field holds, or a folder named after the input."""
        text = self.output_edit.text().strip()
        if text:
            path = Path(text).expanduser()
            source = self.source_path()
            if not path.is_absolute():
                path = (source.parent if source else Path.cwd()) / path
            return path.resolve()
        source = self.source_path()
        return self._default_output_dir(source) if source else None

    def crossover_hz(self) -> float:
        return float(self.crossover.value())

    def set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        for control in (
            self.source_button,
            self.source_download,
            self.output_button,
            self.output_edit,
            self.crossover,
        ):
            control.setEnabled(not running)

    def clear_result(self) -> None:
        self._result = None
        self.stems.clear()
        self.open_output.setEnabled(False)

    def set_result(self, result: StemSplitResult) -> None:
        self._result = result
        self.open_output.setEnabled(bool(result.outputs))
        self._render_result()

    def _render_result(self) -> None:
        self.stems.clear()
        if self._result is None:
            return
        for kind, path, stats in zip(
            self._result.kinds, self._result.outputs, self._result.audio_stats, strict=False
        ):
            self.stems.addItem(
                tr(
                    "stem_result_row",
                    # The key is built from the marker the stem is named by, so
                    # a stem is named once; `test_i18n` holds every locale to
                    # the whole set.
                    name=tr(f"stem_{kind.value}"),
                    file=path.name,
                    channels=stats.channels,
                    peak=f"{stats.peak_dbfs:+.1f}",
                )
            )

    def retranslate(self) -> None:
        self.title.setText(tr("nav_stems"))
        self.files.title_label.setText(tr("file_select"))
        self.source_label.setText(tr("stem_source_label"))
        self.output_label.setText(tr("stem_output_label"))
        self.output_edit.setPlaceholderText(tr("stem_output_hint"))
        self.source_button.setText(tr("browse"))
        self.output_button.setText(tr("browse"))
        self.source_download.setText(tr("download_fetch"))
        self.parameters.title_label.setText(tr("params"))
        self.crossover_label.setText(tr("stem_crossover_label"))
        self.crossover_hint.setText(tr("stem_crossover_hint"))
        self._crossover_changed(self.crossover.value())
        self.stems_card.title_label.setText(tr("stem_result_group"))
        self.stems_hint.setText(
            tr(
                "stem_layout_hint",
                surround=len(layout_stems(StemLayout.SURROUND)),
                stereo=len(layout_stems(StemLayout.STEREO)),
                mono=len(layout_stems(StemLayout.MONO)),
            )
        )
        self.open_output.setText(tr("stem_open_output"))
        self.retranslate_status_card()
        self.start_button.setText(tr("stem_start"))
        self.cancel_button.setText(tr("cancel"))
        self._render_result()
        if self.progress.value() == 0:
            self.status.setText(tr("ready"))
