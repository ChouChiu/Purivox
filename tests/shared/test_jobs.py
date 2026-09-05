from pathlib import Path

import pytest

from shared.jobs import OutputTracks, backing_path, planned_outputs


def test_backing_path_replaces_the_vocal_marker():
    assert backing_path(Path("/tmp/concert_vocals.wav")) == Path("/tmp/concert_backing.wav")


def test_backing_path_appends_when_there_is_no_marker():
    assert backing_path(Path("/tmp/我的现场.wav")) == Path("/tmp/我的现场_backing.wav")


def test_backing_path_keeps_the_full_stage_default_readable():
    assert backing_path(Path("/tmp/live_full_stage_vocals.wav")) == Path(
        "/tmp/live_full_stage_backing.wav"
    )


@pytest.mark.parametrize("tracks", [OutputTracks.VOCAL, OutputTracks.BACKING])
def test_a_single_track_lands_where_the_user_named_it(tracks: OutputTracks):
    """The one file a single-track export writes is the one that was asked for."""
    assert planned_outputs(Path("/tmp/out.wav"), tracks) == (Path("/tmp/out.wav"),)


def test_both_derives_the_second_path_and_keeps_the_writing_order():
    assert planned_outputs(Path("/tmp/out_vocals.wav"), OutputTracks.BOTH) == (
        Path("/tmp/out_vocals.wav"),
        Path("/tmp/out_backing.wav"),
    )


def test_an_unknown_track_name_is_rejected():
    with pytest.raises(ValueError):
        OutputTracks("nope")
