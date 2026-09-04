"""Release check for the desktop build.

The application never updates itself.  It asks GitHub for the latest published
release and, when that release is newer than the running build, hands the tag
and its notes back so the user can be pointed at the Release page.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from PySide6.QtCore import QCoreApplication, QObject, QUrl, Signal
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkProxyFactory,
    QNetworkReply,
    QNetworkRequest,
)

from shared.branding import user_agent

logger = logging.getLogger(__name__)

RELEASES_API = "https://api.github.com/repos/ChouChiu/Purivox/releases/latest"
RELEASES_PAGE = "https://github.com/ChouChiu/Purivox/releases/latest"
_TRANSFER_TIMEOUT_MS = 15_000
_LEADING_NUMBER = re.compile(r"\d+")


@dataclass(frozen=True, slots=True)
class Release:
    """One published release: its version, its notes, and where to get it."""

    version: str
    notes: str
    url: str


def version_parts(text: str) -> tuple[int, ...]:
    """Read the numeric release out of a version tag, ignoring any suffix.

    `v1.2.0`, `1.2.0` and `1.2.0-rc1` all read as `(1, 2, 0)`: a pre-release
    suffix orders below nothing here, it simply does not count as newer.
    """
    core = text.strip().removeprefix("v").removeprefix("V").split("-")[0].split("+")[0]
    parts: list[int] = []
    for chunk in core.split("."):
        number = _LEADING_NUMBER.match(chunk)
        if number is None:
            break
        parts.append(int(number.group()))
    return tuple(parts)


def is_newer(candidate: str, installed: str) -> bool:
    """Whether `candidate` names a later release than the running build.

    A tag carrying no number at all cannot be compared against a version, so
    it is never offered as an update.
    """
    offered = version_parts(candidate)
    if not offered:
        return False
    running = version_parts(installed)
    width = max(len(offered), len(running))
    return offered + (0,) * (width - len(offered)) > running + (0,) * (width - len(running))


def installed_version() -> str:
    """The running build, read from Qt's identity as the download does."""
    return QCoreApplication.applicationVersion()


def _request() -> QNetworkRequest:
    request = QNetworkRequest(QUrl(RELEASES_API))
    # The API rejects a request without a user agent, and answers the pinned
    # media type rather than whatever the default becomes later.
    request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, user_agent())
    request.setRawHeader(b"Accept", b"application/vnd.github+json")
    request.setAttribute(
        QNetworkRequest.Attribute.RedirectPolicyAttribute,
        QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
    )
    request.setTransferTimeout(_TRANSFER_TIMEOUT_MS)
    return request


def parse_release(payload: bytes) -> Release:
    """Read one release out of the API answer.

    Raises `ValueError` for anything that is not a release document, so a
    proxy's error page fails the check instead of becoming an update.
    """
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ValueError(str(error)) from error
    if not isinstance(document, dict):
        raise ValueError("the release endpoint did not answer with a release")
    tag = str(document.get("tag_name") or "").strip()
    if not tag:
        raise ValueError("the release carries no tag")
    return Release(
        version=tag.removeprefix("v").removeprefix("V"),
        notes=str(document.get("body") or ""),
        url=str(document.get("html_url") or RELEASES_PAGE),
    )


class UpdateChecker(QObject):
    """Asks GitHub for the latest release, one request at a time.

    The reply is read on the GUI thread through `QNetworkAccessManager`, so a
    check never blocks the window it was started from.
    """

    update_available = Signal(object)
    up_to_date = Signal()
    failed = Signal(str)
    finished = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        QNetworkProxyFactory.setUseSystemConfiguration(True)
        self._manager = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None

    @property
    def busy(self) -> bool:
        return self._reply is not None

    def check(self) -> bool:
        """Start a check, or report that one is already in flight."""
        if self._reply is not None:
            return False
        logger.info("checking for updates")
        self._reply = self._manager.get(_request())
        self._reply.finished.connect(self._reply_finished)
        return True

    def _reply_finished(self) -> None:
        reply = self._reply
        self._reply = None
        if reply is None:
            return
        payload = reply.readAll().data()
        error = reply.error()
        message = reply.errorString()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        reply.deleteLater()
        # The request is over before its outcome is announced: the window
        # answers an available update with a modal dialog, and that must not
        # hold the check open for as long as the user reads it.
        self.finished.emit()
        if status == 404:
            # A project with nothing published answers 404 rather than an empty
            # document, and having no release to offer is not a failed check.
            logger.info("no release has been published yet")
            self.up_to_date.emit()
            return
        try:
            if error != QNetworkReply.NetworkError.NoError:
                raise ValueError(message)
            release = parse_release(payload)
        except ValueError as failure:
            logger.warning("update check failed: %s", failure)
            self.failed.emit(str(failure))
            return
        if is_newer(release.version, installed_version()):
            logger.info("update available: %s", release.version)
            self.update_available.emit(release)
        else:
            logger.info("no update available")
            self.up_to_date.emit()
