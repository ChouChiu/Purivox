"""Remember what was downloaded, so a link is fetched at most once.

A downloaded track is an input to a job, not a temporary: it is picked again
when the same recording is processed a second time, and losing it means fetching
it again over the network.  It therefore lives in the application's data
directory rather than in a cache the system is free to clear, and an index
beside it records what each file is, because a filename cannot say which link it
came from.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QSaveFile, QStandardPaths

from shared.download.media import FetchedTrack, Track

logger = logging.getLogger(__name__)

INDEX_NAME = "downloads.json"
_INDEX_VERSION = 1


@dataclass(frozen=True, slots=True)
class CachedTrack:
    """One downloaded track: where it came from and where it now sits."""

    track: Track
    path: Path
    size: int = 0
    downloaded: str = ""

    @property
    def exists(self) -> bool:
        return self.path.is_file()


def download_directory() -> Path:
    """Where downloads are kept, under the application's own data directory."""
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    base = Path(location) if location else Path.home() / ".local/share/purivox"
    return base / "downloads"


def _as_document(entries: tuple[CachedTrack, ...]) -> dict[str, object]:
    return {
        "version": _INDEX_VERSION,
        "entries": [
            {
                "url": entry.track.url,
                "id": entry.track.identifier,
                "title": entry.track.title,
                "uploader": entry.track.uploader,
                "duration": entry.track.duration,
                "path": str(entry.path),
                "size": entry.size,
                "downloaded": entry.downloaded,
            }
            for entry in entries
        ],
    }


def _as_entry(record: dict) -> CachedTrack | None:
    path = str(record.get("path") or "")
    url = str(record.get("url") or "")
    if not path or not url:
        return None
    return CachedTrack(
        track=Track(
            url=url,
            identifier=str(record.get("id") or ""),
            title=str(record.get("title") or Path(path).stem),
            uploader=str(record.get("uploader") or ""),
            duration=float(record.get("duration") or 0.0),
        ),
        path=Path(path),
        size=int(record.get("size") or 0),
        downloaded=str(record.get("downloaded") or ""),
    )


class DownloadCache:
    """The index of downloaded tracks, read once and written on every change.

    Entries whose file has gone — deleted by hand, or moved — are dropped when
    the index is read, so the list never offers a path that is not there.
    """

    def __init__(self, directory: Path | None = None):
        self.directory = directory or download_directory()
        self.index = self.directory / INDEX_NAME
        self._entries: tuple[CachedTrack, ...] = ()
        self.reload()

    def reload(self) -> tuple[CachedTrack, ...]:
        """Re-read the index from disk, dropping entries that no longer exist."""
        self._entries = tuple(entry for entry in self._read() if entry.exists)
        return self._entries

    def _read(self) -> tuple[CachedTrack, ...]:
        if not self.index.is_file():
            return ()
        try:
            document = json.loads(self.index.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            # A hand-edited or half-written index is not worth failing a dialog
            # over: the files are still there to be picked with the file dialog.
            logger.warning("could not read the download index: %s", error)
            return ()
        records = document.get("entries") if isinstance(document, dict) else None
        if not isinstance(records, list):
            return ()
        return tuple(
            entry
            for record in records
            if isinstance(record, dict) and (entry := _as_entry(record)) is not None
        )

    def entries(self) -> tuple[CachedTrack, ...]:
        """The remembered downloads, newest first."""
        return self._entries

    def find(self, url: str) -> CachedTrack | None:
        """The entry already holding `url`, if its file is still there.

        The link the user pasted is rarely the one that was recorded: YouTube
        adds a `list` to a watch URL, and yt-dlp answers with the canonical one.
        The video id appears in every form of the link, so it settles the match
        that a string comparison would miss and send back over the network.
        """
        wanted = url.strip()
        for entry in self._entries:
            identifier = entry.track.identifier
            if entry.track.url == wanted or (identifier and identifier in wanted):
                return entry
        return None

    def remember(self, fetched: FetchedTrack) -> CachedTrack:
        """Record one download, replacing any earlier entry for the same link."""
        entry = CachedTrack(
            track=fetched.track,
            path=fetched.path,
            size=fetched.path.stat().st_size if fetched.path.is_file() else 0,
            downloaded=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        kept = tuple(item for item in self._entries if item.track.url != entry.track.url)
        self._entries = (entry, *kept)
        self._write()
        return entry

    def forget(self, entry: CachedTrack, delete_file: bool = False) -> None:
        """Drop one entry from the index, and optionally the file with it."""
        self._entries = tuple(item for item in self._entries if item.path != entry.path)
        if delete_file:
            entry.path.unlink(missing_ok=True)
        self._write()

    def _write(self) -> None:
        """Write the index whole, or leave the previous one in place."""
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(_as_document(self._entries), ensure_ascii=False, indent=2)
        file = QSaveFile(str(self.index))
        if not file.open(QSaveFile.OpenModeFlag.WriteOnly | QSaveFile.OpenModeFlag.Text):
            logger.warning("could not open the download index for writing: %s", file.errorString())
            return
        file.write(payload.encode("utf-8"))
        if not file.commit():
            logger.warning("could not write the download index: %s", file.errorString())
