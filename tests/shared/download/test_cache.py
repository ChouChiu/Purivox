"""The index that lets a downloaded file be picked again instead of re-fetched."""

from __future__ import annotations

from shared.download.cache import INDEX_NAME, DownloadCache, download_directory
from shared.download.media import FetchedTrack, Track


def _fetched(directory, name="song.wav", url="https://example.invalid/watch"):
    path = directory / name
    path.write_bytes(b"0123456789")
    track = Track(url=url, identifier="abc", title="A Song", uploader="A Channel", duration=61)
    return FetchedTrack(track=track, path=path)


def test_downloads_live_beside_the_application_data(tmp_path):
    assert download_directory().name == "downloads"


def test_a_download_is_remembered_and_found_by_its_link(tmp_path):
    cache = DownloadCache(tmp_path)
    entry = cache.remember(_fetched(tmp_path))

    assert entry.size == 10
    assert entry.downloaded
    found = cache.find("https://example.invalid/watch")
    assert found is not None
    assert found.path == entry.path
    assert found.track.title == "A Song"
    assert cache.find("https://example.invalid/other") is None


def test_the_index_is_read_back_from_disk(tmp_path):
    DownloadCache(tmp_path).remember(_fetched(tmp_path))

    reopened = DownloadCache(tmp_path)

    assert [entry.track.url for entry in reopened.entries()] == ["https://example.invalid/watch"]
    assert reopened.entries()[0].track.duration == 61


def test_re_fetching_the_same_link_replaces_its_entry(tmp_path):
    cache = DownloadCache(tmp_path)
    cache.remember(_fetched(tmp_path, "first.wav"))
    cache.remember(_fetched(tmp_path, "second.wav"))

    assert len(cache.entries()) == 1
    assert cache.entries()[0].path.name == "second.wav"


def test_the_newest_download_is_listed_first(tmp_path):
    cache = DownloadCache(tmp_path)
    cache.remember(_fetched(tmp_path, "old.wav", "https://example.invalid/old"))
    cache.remember(_fetched(tmp_path, "new.wav", "https://example.invalid/new"))

    assert [entry.path.name for entry in cache.entries()] == ["new.wav", "old.wav"]


def test_an_entry_whose_file_is_gone_is_dropped(tmp_path):
    """The list must never offer a path that is not there any more."""
    cache = DownloadCache(tmp_path)
    fetched = _fetched(tmp_path)
    cache.remember(fetched)
    fetched.path.unlink()

    assert DownloadCache(tmp_path).entries() == ()


def test_forgetting_an_entry_can_delete_the_file_with_it(tmp_path):
    cache = DownloadCache(tmp_path)
    entry = cache.remember(_fetched(tmp_path))

    cache.forget(entry, delete_file=True)

    assert not entry.path.exists()
    assert cache.entries() == ()
    assert DownloadCache(tmp_path).entries() == ()


def test_forgetting_can_leave_the_file_alone(tmp_path):
    cache = DownloadCache(tmp_path)
    entry = cache.remember(_fetched(tmp_path))

    cache.forget(entry)

    assert entry.path.exists()
    assert cache.entries() == ()


def test_an_unreadable_index_reads_as_empty(tmp_path):
    """A half-written index is not worth failing a dialog over."""
    (tmp_path / INDEX_NAME).write_text("{ not json", encoding="utf-8")

    assert DownloadCache(tmp_path).entries() == ()


def test_the_same_track_is_found_through_a_differently_shaped_link(tmp_path):
    """YouTube adds a `list` to a watch URL, and yt-dlp records the canonical one."""
    cache = DownloadCache(tmp_path)
    path = tmp_path / "song.wav"
    path.write_bytes(b"0")
    track = Track(
        url="https://www.youtube.com/watch?v=abc123XYZ_v", identifier="abc123XYZ_v", title="A Song"
    )
    cache.remember(FetchedTrack(track=track, path=path))

    for link in (
        "https://www.youtube.com/watch?v=abc123XYZ_v",
        "https://www.youtube.com/watch?v=abc123XYZ_v&list=RDabc123XYZ_v",
        "https://music.youtube.com/watch?v=abc123XYZ_v",
        "https://youtu.be/abc123XYZ_v",
    ):
        assert cache.find(link) is not None, link
    assert cache.find("https://www.youtube.com/watch?v=somethingelse") is None


def test_an_entry_without_an_identifier_still_matches_only_its_own_link(tmp_path):
    cache = DownloadCache(tmp_path)
    path = tmp_path / "song.wav"
    path.write_bytes(b"0")
    track = Track(url="https://example.invalid/watch", identifier="", title="A Song")
    cache.remember(FetchedTrack(track=track, path=path))

    assert cache.find("https://example.invalid/watch") is not None
    assert cache.find("https://example.invalid/other") is None
