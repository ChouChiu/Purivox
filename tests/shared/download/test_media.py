"""The link-to-file half of downloading, with yt-dlp replaced by a stand-in.

No test reaches a real host, so `YoutubeDL` is swapped for a fake that answers
the shapes the real one was measured to produce: a flat search listing that also
carries channels, and a download whose final path is only known afterwards.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from yt_dlp.utils import DownloadError

from shared.download import media
from shared.download.media import (
    DownloadUnavailable,
    fetch,
    looks_like_url,
    search,
)
from shared.processing import CancellationToken, ProcessingCancelled, ProgressEvent


class FakeYoutubeDL:
    """Stand in for `yt_dlp.YoutubeDL`, recording what it was asked for."""

    def __init__(self, answer, options):
        self.answer = answer
        self.options = options
        self.asked: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_unused) -> bool:
        return False

    def sanitize_info(self, info):
        return info

    def extract_info(self, url, download=False):
        self.asked.append(url)
        if callable(self.answer):
            return self.answer(self, url, download)
        return self.answer


@pytest.fixture
def fake_yt_dlp(monkeypatch):
    """Install a fake `YoutubeDL` and hand back the instance it created."""
    created: list[FakeYoutubeDL] = []

    def install(answer):
        def factory(options):
            downloader = FakeYoutubeDL(answer, options)
            created.append(downloader)
            return downloader

        monkeypatch.setattr(media.yt_dlp, "YoutubeDL", factory)
        return created

    return install


def test_a_link_is_told_apart_from_keywords():
    assert looks_like_url("https://www.youtube.com/watch?v=abc")
    assert looks_like_url("https://music.youtube.com/watch?v=abc")
    assert not looks_like_url("aimer zankyosanka")
    assert not looks_like_url("")


def test_a_search_skips_what_cannot_be_downloaded(fake_yt_dlp):
    """A search shelf also lists channels and playlists, which carry no title."""
    fake_yt_dlp(
        {
            "entries": [
                {
                    "id": "song",
                    "title": "A Song",
                    "url": "https://example.invalid/song",
                    "duration": 182,
                    "uploader": "A Channel",
                },
                {"id": "chan", "title": None, "url": "https://example.invalid/browse/chan"},
                {"id": "empty", "title": "No link", "url": ""},
            ]
        }
    )

    results = search("something")

    assert [track.identifier for track in results] == ["song"]
    assert results[0].title == "A Song"
    assert results[0].uploader == "A Channel"
    assert results[0].duration == pytest.approx(182.0)


def test_a_search_asks_for_the_number_of_results_it_was_given(fake_yt_dlp):
    created = fake_yt_dlp({"entries": []})

    assert search("hello", 4) == ()
    assert created[0].asked == ["ytsearch4:hello"]


def test_a_search_needs_something_to_search_for():
    with pytest.raises(ValueError):
        search("   ")


def test_an_unreachable_site_is_reported_rather_than_raised_raw(fake_yt_dlp):
    def explode(*_unused):
        raise DownloadError("the site said no")

    fake_yt_dlp(explode)

    with pytest.raises(DownloadUnavailable, match="the site said no"):
        search("anything")


def _downloaded(path: Path, **extra):
    return {
        "id": "abc",
        "title": "A Song",
        "uploader": "A Channel",
        "duration": 61,
        "webpage_url": "https://example.invalid/watch",
        "requested_downloads": [{"filepath": str(path)}],
        **extra,
    }


def test_a_fetch_reads_the_final_path_back_from_yt_dlp(tmp_path, monkeypatch, fake_yt_dlp):
    """Conversion renames the file, so the output template cannot say where it is."""
    monkeypatch.setattr(media, "ffmpeg_available", lambda: True)
    landed = tmp_path / "A Song [abc].wav"
    landed.write_bytes(b"")
    fake_yt_dlp(_downloaded(landed))

    fetched = fetch("https://example.invalid/watch", tmp_path)

    assert fetched.path == landed
    assert fetched.track.title == "A Song"
    assert fetched.track.url == "https://example.invalid/watch"


def test_a_fetch_converts_to_wav_only_when_ffmpeg_is_there(tmp_path, monkeypatch, fake_yt_dlp):
    landed = tmp_path / "track.webm"
    landed.write_bytes(b"")

    monkeypatch.setattr(media, "ffmpeg_available", lambda: False)
    created = fake_yt_dlp(_downloaded(landed))
    fetch("https://example.invalid/watch", tmp_path)
    assert created[0].options["postprocessors"] == []

    monkeypatch.setattr(media, "ffmpeg_available", lambda: True)
    fetch("https://example.invalid/watch", tmp_path)
    assert created[1].options["postprocessors"][0]["preferredcodec"] == "wav"


def test_a_fetch_reports_progress_under_the_transfer_ceiling(tmp_path, monkeypatch, fake_yt_dlp):
    """The tail of the bar belongs to conversion, which reports nothing."""
    monkeypatch.setattr(media, "ffmpeg_available", lambda: False)
    landed = tmp_path / "track.webm"
    landed.write_bytes(b"")

    def answer(downloader, _url, _download):
        hook = downloader.options["progress_hooks"][0]
        hook({"status": "downloading", "downloaded_bytes": 500, "total_bytes": 1000})
        hook(
            {
                "status": "downloading",
                "downloaded_bytes": 1000,
                "total_bytes": 1000,
                "info_dict": {"title": "A Song"},
            }
        )
        return _downloaded(landed)

    fake_yt_dlp(answer)
    events: list[ProgressEvent] = []
    fetch("https://example.invalid/watch", tmp_path, progress=events.append)

    keys = [event.key for event in events]
    assert keys == [
        "download_resolving",
        "download_progress",
        "download_progress",
        "download_saved",
    ]
    assert [event.value for event in events] == [0, 45, 90, 100]
    assert dict(events[2].values)["name"] == "A Song"


def test_a_cancelled_fetch_raises_the_shared_cancellation(tmp_path, monkeypatch, fake_yt_dlp):
    monkeypatch.setattr(media, "ffmpeg_available", lambda: False)
    token = CancellationToken()

    def answer(downloader, _url, _download):
        token.cancel()
        downloader.options["progress_hooks"][0]({"status": "downloading"})
        raise AssertionError("the hook should have stopped the download")

    fake_yt_dlp(answer)

    with pytest.raises(ProcessingCancelled):
        fetch("https://example.invalid/watch", tmp_path, token)


def test_a_download_that_produced_nothing_is_an_error(tmp_path, monkeypatch, fake_yt_dlp):
    monkeypatch.setattr(media, "ffmpeg_available", lambda: False)
    fake_yt_dlp({"id": "abc", "title": "A Song", "requested_downloads": []})

    with pytest.raises(DownloadUnavailable):
        fetch("https://example.invalid/watch", tmp_path)


def test_a_link_is_one_track_not_the_playlist_it_carries(tmp_path, monkeypatch, fake_yt_dlp):
    """A watch URL often carries a `list`; a radio mix is hundreds of entries."""
    monkeypatch.setattr(media, "ffmpeg_available", lambda: False)
    landed = tmp_path / "track.webm"
    landed.write_bytes(b"")
    created = fake_yt_dlp(_downloaded(landed))

    fetch("https://example.invalid/watch?v=abc&list=RDabc", tmp_path)

    assert created[0].options["noplaylist"] is True


def test_a_cancellation_lands_during_extraction_too(tmp_path, monkeypatch, fake_yt_dlp):
    """Nothing calls the progress hook until bytes move; extraction can be long."""
    monkeypatch.setattr(media, "ffmpeg_available", lambda: False)
    token = CancellationToken()

    def answer(downloader, _url, _download):
        token.cancel()
        downloader.options["match_filter"]({"id": "abc"}, incomplete=True)
        raise AssertionError("the filter should have stopped the extraction")

    fake_yt_dlp(answer)

    with pytest.raises(ProcessingCancelled):
        fetch("https://example.invalid/watch", tmp_path, token)


def test_extraction_runs_unfiltered_when_nothing_can_cancel_it(tmp_path, monkeypatch, fake_yt_dlp):
    monkeypatch.setattr(media, "ffmpeg_available", lambda: False)
    landed = tmp_path / "track.webm"
    landed.write_bytes(b"")
    created = fake_yt_dlp(_downloaded(landed))

    fetch("https://example.invalid/watch", tmp_path)

    assert created[0].options["match_filter"] is None
