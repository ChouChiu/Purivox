from __future__ import annotations

from pathlib import Path

import pytest

from features.stem_split.models import (
    StemKind,
    StemLayout,
    StemSplitJob,
    layout_for,
    layout_stems,
    stem_path,
)


@pytest.mark.parametrize(
    ("channels", "layout"),
    [
        (1, StemLayout.MONO),
        (2, StemLayout.STEREO),
        # Three to five channels is a layout with no decode matrix here, so it
        # is folded to its front pair rather than guessed at.
        (4, StemLayout.STEREO),
        (6, StemLayout.SURROUND),
        (8, StemLayout.SURROUND),
    ],
)
def test_the_channel_count_picks_the_layout(channels: int, layout: StemLayout):
    assert layout_for(channels) is layout


def test_every_layout_names_stems_that_exist():
    for layout in StemLayout:
        stems = layout_stems(layout)
        assert stems
        assert len(set(stems)) == len(stems)
        assert set(stems) <= set(StemKind)


def test_no_stem_can_land_on_the_file_it_was_split_from(tmp_path: Path):
    """Which is why the job carries no overwrite check: the names cannot meet."""
    for kind in StemKind:
        source = tmp_path / f"mix_{kind.value}.wav"
        written = {stem_path(source, tmp_path, other) for other in StemKind}
        assert source not in written


def test_a_job_writes_beside_its_input_when_asked_to(tmp_path: Path):
    source = tmp_path / "mix.wav"

    job = StemSplitJob(source=source, output_dir=tmp_path)

    assert stem_path(job.source, job.output_dir, StemKind.CENTER).name == "mix_center.wav"


@pytest.mark.parametrize("crossover", [0.0, 19.0, 44_100.0])
def test_a_job_refuses_a_crossover_outside_the_audible_range(tmp_path: Path, crossover: float):
    with pytest.raises(ValueError, match="crossover"):
        StemSplitJob(source=tmp_path / "mix.wav", output_dir=tmp_path, crossover_hz=crossover)
