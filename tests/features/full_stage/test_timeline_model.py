from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt

from features.full_stage import ClipKind, FullStageAnalysis, TimelineClip
from features.full_stage.timeline_model import (
    CONFIDENCE,
    ENABLED,
    KIND,
    SOURCE,
    SOURCE_RANGE,
    STAGE_RANGE,
    TimelineModel,
)
from shared.i18n import install_language, tr


def _analysis(source: Path) -> FullStageAnalysis:
    return FullStageAnalysis(
        30.0,
        (
            TimelineClip(ClipKind.UNMATCHED, 0.0, 5.0),
            TimelineClip(ClipKind.SONG, 5.0, 25.0, source, 0, 0.0, 20.0, 0.9),
        ),
    )


def _model(tmp_path: Path) -> TimelineModel:
    model = TimelineModel()
    model.set_analysis(_analysis((tmp_path / "song.wav").resolve()))
    return model


def test_model_shape_matches_the_analysis(tmp_path: Path):
    model = _model(tmp_path)
    assert model.rowCount() == 2
    assert model.columnCount() == 6
    assert model.data(model.index(1, KIND), Qt.ItemDataRole.DisplayRole) == tr("stage_type_song")
    assert model.data(model.index(1, STAGE_RANGE), Qt.ItemDataRole.DisplayRole) == (
        "00:05.000 - 00:25.000"
    )
    assert model.data(model.index(1, CONFIDENCE), Qt.ItemDataRole.DisplayRole) == "90%"
    assert model.data(model.index(1, SOURCE), Qt.ItemDataRole.DisplayRole) == "song.wav"


def test_unmatched_rows_are_neither_checkable_nor_source_editable(tmp_path: Path):
    model = _model(tmp_path)
    assert model.flags(model.index(0, ENABLED)) == Qt.ItemFlag.NoItemFlags
    assert model.data(model.index(0, ENABLED), Qt.ItemDataRole.CheckStateRole) is None
    assert not model.flags(model.index(0, SOURCE_RANGE)) & Qt.ItemFlag.ItemIsEditable
    assert model.flags(model.index(0, STAGE_RANGE)) & Qt.ItemFlag.ItemIsEditable
    assert model.flags(model.index(1, SOURCE_RANGE)) & Qt.ItemFlag.ItemIsEditable


def test_editing_a_range_updates_the_analysis(qtbot, tmp_path: Path):
    model = _model(tmp_path)
    with qtbot.waitSignal(model.dataChanged):
        assert model.setData(
            model.index(1, STAGE_RANGE), "00:06.000 - 00:20.000", Qt.ItemDataRole.EditRole
        )
    clip = model.analysis.clips[1]
    assert (clip.stage_start, clip.stage_end) == (6.0, 20.0)


def test_unparsable_and_out_of_range_edits_are_rejected(qtbot, tmp_path: Path):
    model = _model(tmp_path)
    for text in ("not a range", "00:20.000 - 00:10.000", "00:10.000 - 00:40.000"):
        with qtbot.waitSignal(model.edit_rejected):
            assert not model.setData(model.index(1, STAGE_RANGE), text, Qt.ItemDataRole.EditRole)
    clip = model.analysis.clips[1]
    assert (clip.stage_start, clip.stage_end) == (5.0, 25.0), "a rejected edit must change nothing"


def test_unchecking_a_row_drops_it_from_the_render_set(tmp_path: Path):
    model = _model(tmp_path)
    assert model.setData(
        model.index(1, ENABLED), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole
    )
    assert not model.analysis.matched_clips


def test_manual_clips_round_trip_through_the_model(tmp_path: Path):
    model = _model(tmp_path)
    source = (tmp_path / "song.wav").resolve()
    assert model.add_clip(TimelineClip(ClipKind.SONG, 0.0, 4.0, source, 0, 0.0, 4.0, manual=True))
    manual = [row for row in range(model.rowCount()) if model.clip(row).manual]
    assert len(manual) == 1
    assert model.data(model.index(manual[0], CONFIDENCE), Qt.ItemDataRole.DisplayRole) == tr(
        "stage_manual_label"
    )
    assert model.remove_clip(manual[0])
    assert not any(model.clip(row).manual for row in range(model.rowCount()))


def test_detected_clips_cannot_be_removed(qtbot, tmp_path: Path):
    model = _model(tmp_path)
    with qtbot.waitSignal(model.edit_rejected):
        assert not model.remove_clip(1)
    assert model.rowCount() == 2


def test_retranslate_refreshes_headers_and_cells(qtbot, tmp_path: Path):
    model = _model(tmp_path)
    assert model.headerData(KIND, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == tr(
        "stage_clip_type"
    )
    install_language("en_us")
    with qtbot.waitSignal(model.headerDataChanged):
        model.retranslate()
    assert model.headerData(KIND, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == (
        "Type"
    )
    assert model.data(model.index(1, KIND), Qt.ItemDataRole.DisplayRole) == "Full song"


def test_an_empty_model_reports_no_rows():
    model = TimelineModel()
    assert model.rowCount() == 0
    assert model.clip(0) is None
    assert not model.add_clip(TimelineClip(ClipKind.SONG, 0.0, 1.0, Path("a.wav"), 0, 0.0, 1.0))
    assert not model.remove_clip(0)
