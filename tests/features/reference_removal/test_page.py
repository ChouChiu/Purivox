from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
from PySide6.QtCore import QItemSelectionModel, QSize
from PySide6.QtWidgets import QApplication

from features.reference_removal import ClipKind, StageAnalysis, TimelineClip
from features.reference_removal.page import MrPage
from shared.audio import AudioStats
from shared.jobs import OutputTracks
from shared.ui import layout_metrics


def _page(qtbot) -> MrPage:
    page = MrPage()
    qtbot.addWidget(page)
    page.retranslate()
    return page


def _select_row(page: MrPage, row: int) -> None:
    """Select a timeline row the way clicking it does."""
    page.timeline.selectionModel().setCurrentIndex(
        page.timeline_model.index(row, 0),
        QItemSelectionModel.SelectionFlag.SelectCurrent | QItemSelectionModel.SelectionFlag.Rows,
    )


def _song(source: Path, start: float, end: float) -> TimelineClip:
    return TimelineClip(ClipKind.SONG, start, end, source, 0, 0.0, end - start, 0.9)


def test_choosing_a_recording_names_the_output_after_it(qtbot, tmp_path: Path):
    """The file dialog hands its result to `set_stage` and nothing else."""
    page = _page(qtbot)
    page.set_stage(str(tmp_path / "live.wav"))

    assert page.stage_edit.text() == str(tmp_path / "live.wav")
    assert Path(page.output_edit.text()).name == "live_vocals.wav"


def test_sources_keep_the_order_they_were_added_in_and_skip_repeats(qtbot, tmp_path: Path):
    page = _page(qtbot)
    page.add_source_paths([str(tmp_path / "b.wav"), str(tmp_path / "a.wav")])
    page.add_source_paths([str(tmp_path / "a.wav")])

    assert [path.name for path in page.source_paths()] == ["b.wav", "a.wav"]


def test_a_changed_source_list_discards_the_timeline(qtbot, tmp_path: Path):
    """A timeline describes the sources it was matched from, not the new set."""
    page = _page(qtbot)
    source = (tmp_path / "song.wav").resolve()
    page.add_source_paths([str(source)])
    page.set_analysis(StageAnalysis(30.0, (_song(source, 0.0, 20.0),)))
    assert page.analysis is not None

    page.add_source_paths([str(tmp_path / "other.wav")])

    assert page.analysis is None


def test_a_manual_clip_lands_in_the_first_gap_and_can_be_removed(qtbot, tmp_path: Path):
    """Spliced backing tracks need timeline rows the matcher cannot produce."""
    page = _page(qtbot)
    source = (tmp_path / "song.wav").resolve()
    page.add_source_paths([str(source)])
    page.set_analysis(
        StageAnalysis(
            60.0,
            (_song(source, 0.0, 20.0), TimelineClip(ClipKind.UNMATCHED, 20.0, 60.0)),
        )
    )
    assert not page.remove_clip.isEnabled()

    page.add_clip.click()

    (row,) = [row for row, clip in enumerate(page.analysis.clips) if clip.manual]
    assert page.analysis.clips[row].stage_start == 20.0
    assert page.analysis.clips[row].source == source
    _select_row(page, row)
    assert page.remove_clip.isEnabled()
    page.remove_clip.click()
    assert not any(clip.manual for clip in page.analysis.clips)


def test_a_detected_clip_cannot_be_removed(qtbot, tmp_path: Path):
    page = _page(qtbot)
    page.set_analysis(StageAnalysis(30.0, (_song((tmp_path / "song.wav").resolve(), 0.0, 20.0),)))

    _select_row(page, 0)

    assert not page.remove_clip.isEnabled()


def test_an_empty_output_is_named_beside_the_recording(qtbot, tmp_path: Path):
    page = _page(qtbot)
    page.stage_edit.setText(str(tmp_path / "concert.performance.m4a"))
    page.output_edit.clear()

    output = page.normalized_output_path()

    assert output == (tmp_path / "concert.performance_vocals.wav").resolve()
    assert page.output_edit.text() == str(output)


def test_export_choice_renames_the_default_output_until_the_user_names_it(qtbot, tmp_path: Path):
    page = _page(qtbot)
    page.set_stage(str(tmp_path / "concert.wav"))

    page.tracks.setCurrentIndex(page.tracks.findData(OutputTracks.BACKING.value))
    assert page.selected_tracks() is OutputTracks.BACKING
    assert Path(page.output_edit.text()).name == "concert_backing.wav"

    # A name the user typed is theirs; switching the export must not take it back.
    page.output_edit.setText("我的消音")
    page.output_edit.textEdited.emit("我的消音")
    page.tracks.setCurrentIndex(page.tracks.findData(OutputTracks.BOTH.value))
    assert page.output_edit.text() == "我的消音"
    assert page.normalized_output_path() == (tmp_path / "我的消音.wav").resolve()


def test_export_choice_survives_a_language_switch(qtbot):
    """Rebuilding the items re-emits the signal; the choice must not drift."""
    page = _page(qtbot)
    page.tracks.setCurrentIndex(page.tracks.findData(OutputTracks.BOTH.value))

    page.retranslate()
    page.retranslate()

    assert page.tracks.count() == len(OutputTracks)
    assert page.selected_tracks() is OutputTracks.BOTH


def test_a_running_job_locks_every_input_and_leaves_only_cancel(qtbot):
    page = _page(qtbot)
    inputs = (
        page.stage_button,
        page.stage_download,
        page.output_edit,
        page.add_sources,
        page.remove_source,
        page.tracks,
        page.strength,
        page.timeline,
        page.add_clip,
        page.analyze_button,
        page.start_button,
    )

    page.set_running(True)
    assert not any(control.isEnabled() for control in inputs)
    assert page.cancel_button.isEnabled()

    page.set_running(False)
    assert all(control.isEnabled() for control in inputs)
    assert not page.cancel_button.isEnabled()


def test_a_result_enables_the_preview_and_fills_the_audio_data(qtbot, tmp_path: Path):
    page = _page(qtbot)
    output = tmp_path / "result.wav"
    sf.write(output, np.zeros((8_000, 2), dtype=np.float32), 8_000, subtype="PCM_24")
    stats = AudioStats(1.0, 8_000, 2, 24, -1.2, float("-inf"), output.stat().st_size)

    page.set_result(output, stats)

    assert page.preview_play.isEnabled()
    assert page.preview_status.text() == output.name
    assert page.stat_values["duration"].text() == "00:01"
    assert page.stat_values["sample_rate"].text() == "8 kHz"
    assert page.stat_values["bit_depth"].text() == "24-bit PCM"
    assert page.stat_values["peak"].text() == "-1.2 dBFS"
    assert page.stat_values["rms"].text() == "-inf dBFS"

    page.clear_result()

    assert not page.preview_play.isEnabled()
    assert page.stat_values["duration"].text() == "--"


def test_a_long_output_path_does_not_widen_the_page(qtbot, tmp_path: Path):
    page = MrPage()
    qtbot.addWidget(page)
    page.resize(800, 700)
    page.show()
    qtbot.waitExposed(page)
    page.retranslate()
    QApplication.processEvents()
    baseline = page.content.sizeHint().width()
    long_path = tmp_path.joinpath(*(["very-long-directory-name"] * 40), "result.wav")

    page.output_edit.setText(str(long_path))
    page.status.setText(f"处理完成! 文件已保存到: {long_path}")
    page.preview_status.setText("very-long-output-name-" * 80 + ".wav")
    page.content.layout().invalidate()
    page.content.layout().activate()
    QApplication.processEvents()

    assert page.content.sizeHint().width() <= baseline


def test_the_audio_data_tiles_reflow_with_the_window(qtbot):
    page = MrPage()
    qtbot.addWidget(page)
    page.resize(1200, 800)
    page.show()
    qtbot.waitExposed(page)

    def rows() -> int:
        grid = page.stats_grid
        return len({grid.getItemPosition(index)[0] for index in range(grid.count())})

    page.apply_layout(layout_metrics(QSize(1200, 800)))
    assert rows() == 2

    page.apply_layout(layout_metrics(QSize(500, 900)))
    assert rows() == 4


def test_a_short_window_gives_the_stage_panes_less_height(qtbot):
    page = MrPage()
    qtbot.addWidget(page)

    page.apply_layout(layout_metrics(QSize(1280, 900)))
    tall = (page.sources.minimumHeight(), page.timeline.minimumHeight())
    page.apply_layout(layout_metrics(QSize(1280, 500)))

    assert (page.sources.minimumHeight(), page.timeline.minimumHeight()) < tall
