"""Resolve and download one audio track through yt-dlp.

yt-dlp is the whole of what this module knows about the sites it reaches: which
formats they offer, how they throttle and how often their extraction changes are
its problem.  Ours is the shape of the answer — one audio file on disk that
`read_audio` can open, and one record describing where it came from.

The download keeps the best audio stream the site offers.  With ffmpeg present
that stream is converted to WAV, which SoundFile reads directly; without it the
container is kept as it arrived and Qt Multimedia decodes it, which is the same
fallback every other unsupported container already takes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yt_dlp
from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor
from yt_dlp.utils import DownloadCancelled, DownloadError, ExtractorError

from shared.processing import CancellationToken, ProcessingCancelled, ProgressCallback
from shared.progress import report_progress

logger = logging.getLogger(__name__)

SEARCH_LIMIT = 10
"""How many candidates a keyword search asks for."""

# The site names a track; this is only how much of that name becomes a filename.
_FILENAME_TEMPLATE = "%(title).80B [%(id)s].%(ext)s"
_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)
# The transfer is the long part of a fetch, so it owns most of the bar and
# leaves the tail to conversion, which reports nothing until it is over.
_TRANSFER_CEILING = 90


@dataclass(frozen=True, slots=True)
class Track:
    """One track a link or a search resolved to, before anything is downloaded."""

    url: str
    identifier: str
    title: str
    uploader: str = ""
    duration: float = 0.0


@dataclass(frozen=True, slots=True)
class FetchedTrack:
    """A downloaded track and the file it landed in."""

    track: Track
    path: Path


class DownloadUnavailable(RuntimeError):
    """yt-dlp could not reach or extract what was asked for."""


def looks_like_url(text: str) -> bool:
    """Whether the input names a page to fetch rather than words to search for."""
    return bool(_SCHEME.match(text.strip()))


def ffmpeg_available() -> bool:
    """Whether yt-dlp can run ffmpeg, which decides the container we keep.

    Asked of yt-dlp rather than of `PATH`: it also honours its own configured
    location, and it is the side that would run the converter.
    """
    return bool(FFmpegPostProcessor().available)


def _options(**extra: object) -> dict[str, object]:
    """The options every call shares: quiet, non-interactive, no console bar."""
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": logger,
        **extra,
    }


def _track(entry: dict) -> Track | None:
    """Read one search entry, skipping anything that is not a playable track.

    A search shelf also carries channels and playlists, which arrive without a
    title and cannot be downloaded as audio.
    """
    url = str(entry.get("url") or entry.get("webpage_url") or "")
    title = str(entry.get("title") or "")
    if not url or not title:
        return None
    return Track(
        url=url,
        identifier=str(entry.get("id") or ""),
        title=title,
        uploader=str(entry.get("uploader") or entry.get("channel") or ""),
        duration=float(entry.get("duration") or 0.0),
    )


def search(query: str, limit: int = SEARCH_LIMIT) -> tuple[Track, ...]:
    """Search YouTube for `query` and return what it offers, without downloading.

    Only the flat listing is read, so this costs one request rather than one per
    result.  Raises `DownloadUnavailable` when the site cannot be reached.
    """
    query = query.strip()
    if not query:
        raise ValueError("a search needs something to search for")
    options = _options(extract_flat="in_playlist", skip_download=True)
    logger.info("searching for %r", query)
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            listing = downloader.extract_info(f"ytsearch{max(1, limit)}:{query}", download=False)
    except (DownloadError, ExtractorError) as error:
        raise DownloadUnavailable(str(error)) from error
    entries = (listing or {}).get("entries") or ()
    found = tuple(track for entry in entries if (track := _track(entry)) is not None)
    logger.info("search returned %d results", len(found))
    return found


def _postprocessors() -> list[dict[str, str]]:
    if not ffmpeg_available():
        # Qt Multimedia decodes what arrives; the pipeline resamples anyway.
        logger.info("ffmpeg is unavailable; keeping the downloaded container as it is")
        return []
    return [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}]


def _cancellation_filter(token: CancellationToken | None):
    """Let a cancellation land during extraction, not only during transfer.

    The progress hook runs once bytes are moving, and nothing before that: a
    link that resolves to many entries spends that whole time in extraction,
    where a cancel would otherwise go unseen until the first transfer started.
    yt-dlp calls this for every entry it considers.
    """
    if token is None:
        return None

    def accept(_info: dict, *, incomplete: bool = False) -> str | None:
        if token.cancelled:
            raise DownloadCancelled("the download was cancelled")
        return None

    return accept


def _progress_hook(
    callback: ProgressCallback | None,
    token: CancellationToken | None,
    fallback: str,
):
    def hook(status: dict) -> None:
        if token is not None and token.cancelled:
            # yt-dlp re-raises this one rather than reporting it as a failure,
            # so it is the only exception that reliably stops a transfer here.
            raise DownloadCancelled("the download was cancelled")
        if callback is None or status.get("status") != "downloading":
            return
        total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
        done = status.get("downloaded_bytes") or 0
        if not total:
            return
        percent = min(_TRANSFER_CEILING, int(done * _TRANSFER_CEILING / total))
        # The title only becomes known once extraction is over, so the link
        # stands in for it until the first block arrives.
        name = (status.get("info_dict") or {}).get("title") or fallback
        report_progress(callback, percent, "download_progress", name=name)

    return hook


def fetch(
    url: str,
    directory: Path,
    token: CancellationToken | None = None,
    progress: ProgressCallback | None = None,
) -> FetchedTrack:
    """Download the audio of one page into `directory` and describe what landed.

    The path is read back from yt-dlp rather than rebuilt from the template: the
    name is decided by metadata this side never sees, and conversion changes the
    extension after the file is written.
    """
    directory.mkdir(parents=True, exist_ok=True)
    if progress is not None:
        report_progress(progress, 0, "download_resolving")
    options = _options(
        format="bestaudio/best",
        outtmpl={"default": str(directory / _FILENAME_TEMPLATE)},
        postprocessors=_postprocessors(),
        progress_hooks=[_progress_hook(progress, token, url)],
        match_filter=_cancellation_filter(token),
        # A link is one track.  YouTube hands out watch URLs carrying a `list`
        # of its own — a radio mix is hundreds of entries — and without this
        # yt-dlp downloads the whole of it rather than the song that was asked
        # for.
        noplaylist=True,
    )
    logger.info("downloading %s", url)
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.sanitize_info(downloader.extract_info(url, download=True))
    except DownloadCancelled as cancelled:
        raise ProcessingCancelled from cancelled
    except (DownloadError, ExtractorError) as error:
        raise DownloadUnavailable(str(error)) from error
    if token is not None:
        token.raise_if_cancelled()
    downloads = (info or {}).get("requested_downloads") or ()
    if not downloads or not downloads[0].get("filepath"):
        raise DownloadUnavailable(f"nothing was downloaded from {url}")
    path = Path(str(downloads[0]["filepath"]))
    track = Track(
        url=str(info.get("webpage_url") or url),
        identifier=str(info.get("id") or ""),
        title=str(info.get("title") or path.stem),
        uploader=str(info.get("uploader") or info.get("channel") or ""),
        duration=float(info.get("duration") or 0.0),
    )
    if progress is not None:
        report_progress(progress, 100, "download_saved", name=path.name)
    logger.info("downloaded %s to %s", track.title, path)
    return FetchedTrack(track=track, path=path)
