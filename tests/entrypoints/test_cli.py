from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from entrypoints.cli import build_parser, main
from features.stem_split import DEFAULT_CROSSOVER_HZ
from shared.jobs import OutputTracks


def test_reference_command_takes_one_or_more_sources():
    """The number of sources is the only difference between the two old modes."""
    parser = build_parser()

    one = parser.parse_args(["mr", "stage.wav", "song.flac", "out.wav"])
    assert one.sources == [Path("song.flac")]
    assert one.output == Path("out.wav")

    many = parser.parse_args(["mr", "stage.wav", "a.flac", "b.flac", "out.wav"])
    assert many.sources == [Path("a.flac"), Path("b.flac")]
    assert many.output == Path("out.wav")


def test_reference_command_parses_its_settings():
    parser = build_parser()
    assert parser.prog == "purivox"

    defaults = parser.parse_args(["mr", "song.wav", "reference.flac", "output.wav"])
    assert defaults.sigma == 3
    assert defaults.align

    custom = parser.parse_args(
        ["mr", "song.wav", "reference.flac", "output.wav", "--sigma", "8", "--no-align"]
    )
    assert custom.sigma == 8
    assert not custom.align


def test_reference_command_parses_the_export_choice():
    parser = build_parser()

    defaults = parser.parse_args(["mr", "song.wav", "reference.flac", "output.wav"])
    assert defaults.tracks is OutputTracks.VOCAL

    both = parser.parse_args(["mr", "song.wav", "reference.flac", "output.wav", "--tracks", "both"])
    assert both.tracks is OutputTracks.BOTH


def test_reference_command_rejects_an_unknown_export_choice():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["mr", "song.wav", "reference.flac", "out.wav", "--tracks", "nope"])


def test_split_command_takes_one_recording_and_an_optional_folder():
    """A split writes several files, so what it needs is a folder, not a name."""
    parser = build_parser()

    defaults = parser.parse_args(["split", "show.flac"])
    assert defaults.source == Path("show.flac")
    assert defaults.output_dir is None
    assert defaults.crossover == DEFAULT_CROSSOVER_HZ

    custom = parser.parse_args(["split", "show.flac", "stems", "--crossover", "180"])
    assert custom.output_dir == Path("stems")
    assert custom.crossover == 180.0


def test_split_writes_the_stems_of_a_recording(tmp_path: Path, capsys):
    source = tmp_path / "show.wav"
    time = np.arange(8_000) / 8_000
    sf.write(source, np.stack([np.sin(2 * np.pi * 220 * time)] * 2, axis=1), 8_000)

    assert main(["split", str(source)]) == 0

    written = [Path(line) for line in capsys.readouterr().out.split()]
    assert written == sorted(written, key=written.index)
    assert all(path.is_file() for path in written)
    assert {path.parent for path in written} == {tmp_path / "show_stems"}


def test_fetch_command_parses_its_options():
    parser = build_parser()

    defaults = parser.parse_args(["fetch", "https://example.invalid/watch"])
    assert defaults.query == "https://example.invalid/watch"
    assert defaults.out is None
    assert defaults.limit is None
    assert defaults.pick is None
    assert not defaults.list

    listing = parser.parse_args(["fetch", "some words", "--limit", "3", "--pick", "2"])
    assert (listing.limit, listing.pick) == (3, 2)
    assert parser.parse_args(["fetch", "--list"]).query is None


@pytest.fixture
def fetch_cli(tmp_path, monkeypatch):
    """Point the download cache at a temporary directory and stub the network."""
    import shared.download as download
    from shared.download.media import FetchedTrack, Track

    monkeypatch.setattr(download.cache, "download_directory", lambda: tmp_path)
    monkeypatch.setattr(download, "ffmpeg_available", lambda: True)
    calls: dict[str, list] = {"search": [], "fetch": []}

    def stub_search(query, limit):
        calls["search"].append((query, limit))
        return tuple(
            Track(url=f"https://example.invalid/{index}", identifier=str(index), title=f"T{index}")
            for index in range(1, 3)
        )

    def stub_fetch(url, directory, token=None, progress=None):
        calls["fetch"].append(url)
        path = directory / "track.wav"
        path.write_bytes(b"0")
        return FetchedTrack(track=Track(url=url, identifier="x", title="T"), path=path)

    monkeypatch.setattr(download, "search", stub_search)
    monkeypatch.setattr(download, "fetch", stub_fetch)
    return calls


def _fetch(argv):
    from entrypoints.cli import _run_fetch
    from shared.processing import CancellationToken

    return _run_fetch(build_parser().parse_args(["fetch", *argv]), CancellationToken())


def test_fetch_needs_a_link_keywords_or_a_listing(fetch_cli):
    assert _fetch([]) == 2


def test_fetch_lists_search_results_before_downloading_anything(fetch_cli, capsys):
    """Keywords alone describe the choices; --pick is what commits to one."""
    assert _fetch(["some words", "--limit", "5"]) == 0

    assert fetch_cli["search"] == [("some words", 5)]
    assert fetch_cli["fetch"] == []
    printed = capsys.readouterr().out.splitlines()
    assert [line.split("\t")[0] for line in printed] == ["1", "2"]


def test_fetch_downloads_the_picked_search_result(fetch_cli, capsys):
    assert _fetch(["some words", "--pick", "2"]) == 0

    assert fetch_cli["fetch"] == ["https://example.invalid/2"]
    assert capsys.readouterr().out.strip().endswith("track.wav")


def test_fetch_rejects_a_pick_outside_the_results(fetch_cli):
    assert _fetch(["some words", "--pick", "9"]) == 2
    assert fetch_cli["fetch"] == []


def test_fetch_downloads_a_link_without_searching(fetch_cli):
    assert _fetch(["https://example.invalid/watch"]) == 0

    assert fetch_cli["search"] == []
    assert fetch_cli["fetch"] == ["https://example.invalid/watch"]


def test_a_link_already_downloaded_is_not_fetched_twice(fetch_cli, capsys):
    assert _fetch(["https://example.invalid/watch"]) == 0
    capsys.readouterr()

    assert _fetch(["https://example.invalid/watch"]) == 0

    assert fetch_cli["fetch"] == ["https://example.invalid/watch"], (
        "the second call reused the file"
    )
    assert capsys.readouterr().out.strip().endswith("track.wav")


def test_fetch_lists_what_has_been_downloaded(fetch_cli, capsys):
    _fetch(["https://example.invalid/watch"])
    capsys.readouterr()

    assert _fetch(["--list"]) == 0

    assert capsys.readouterr().out.strip().endswith("track.wav")
