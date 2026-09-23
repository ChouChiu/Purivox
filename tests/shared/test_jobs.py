from pathlib import Path

import pytest

from shared.jobs import OutputTracks, backing_path, planned_outputs, validate_job_paths


def test_backing_path_replaces_the_vocal_marker():
    assert backing_path(Path("/tmp/concert_vocals.wav")) == Path("/tmp/concert_backing.wav")


def test_backing_path_appends_when_there_is_no_marker():
    assert backing_path(Path("/tmp/我的现场.wav")) == Path("/tmp/我的现场_backing.wav")


def test_backing_path_swaps_the_vocal_marker_wherever_it_sits():
    assert backing_path(Path("/tmp/live_encore_vocals.wav")) == Path("/tmp/live_encore_backing.wav")


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


def test_job_paths_refuse_the_recording_as_a_source():
    stage = Path("/tmp/show.wav")
    with pytest.raises(ValueError, match="must not also be a source"):
        validate_job_paths(
            stage, (Path("/tmp/song.wav"), stage), Path("/tmp/out.wav"), OutputTracks.VOCAL
        )


def test_job_paths_refuse_a_derived_output_over_an_input():
    source = Path("/tmp/show_backing.wav")
    with pytest.raises(ValueError, match="overwrite an input"):
        validate_job_paths(
            Path("/tmp/live.wav"), (source,), Path("/tmp/show_vocals.wav"), OutputTracks.BOTH
        )
    validate_job_paths(
        Path("/tmp/live.wav"), (source,), Path("/tmp/show_vocals.wav"), OutputTracks.VOCAL
    )
