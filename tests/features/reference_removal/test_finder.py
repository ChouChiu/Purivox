from pathlib import Path

from features.reference_removal.finder import filename_similarity, find_best_match


def test_source_finder(tmp_path: Path):
    stage = tmp_path / "Artist - Song.wav"
    stage.touch()
    expected = tmp_path / "Artist - Song instrumental.flac"
    expected.touch()
    (tmp_path / "unrelated.mp3").touch()
    assert filename_similarity("ABC", "abc") == 1
    assert find_best_match(stage).path == expected


def test_source_finder_excludes_source_alias(tmp_path: Path):
    stage = tmp_path / "Artist - Song.wav"
    stage.touch()
    (tmp_path / "Artist - Song instrumental.wav").symlink_to(stage)
    assert not find_best_match(stage).found


def test_source_finder_excludes_generated_output(tmp_path: Path):
    stage = tmp_path / "Artist - Song.wav"
    stage.touch()
    (tmp_path / "Artist - Song_vocals.wav").touch()
    (tmp_path / "Artist - Song 消音.wav").touch()
    (tmp_path / "Artist - Song_backing.wav").touch()
    assert not find_best_match(stage).found


def test_source_finder_still_accepts_a_source_named_after_the_backing_track(
    tmp_path: Path,
):
    """The word for the backing track names the input, so it must not be skipped."""
    stage = tmp_path / "Artist - Song.wav"
    stage.touch()
    source = tmp_path / "Artist - Song 垫音.wav"
    source.touch()
    assert find_best_match(stage).path == source.resolve()
