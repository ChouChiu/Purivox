from __future__ import annotations

import hashlib
import os
from pathlib import Path

from PySide6.QtCore import (
    QEventLoop,
    QIODevice,
    QSaveFile,
    QStandardPaths,
    QTimer,
    QUrl,
)
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkProxyFactory,
    QNetworkReply,
    QNetworkRequest,
)

from features.neural_separation.catalog import ModelEntry
from shared.branding import user_agent
from shared.i18n import tr
from shared.processing import (
    CancellationToken,
    ProcessingCancelled,
    ProgressCallback,
    ProgressEvent,
)

_TRANSFER_TIMEOUT_MS = 120_000
_CANCEL_POLL_MS = 100
# The download occupies this slice of the neural job's progress bar.
_PROGRESS_START = 15
_PROGRESS_END = 24


def default_models_dir() -> Path:
    root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    return Path(root or Path.home() / ".local/share/purivox") / "models"


def candidate_model_dirs(override: Path | None = None) -> tuple[Path, ...]:
    candidates: list[Path] = []
    if override:
        candidates.append(override.expanduser())
    if env := os.environ.get("PURIVOX_MODELS"):
        candidates.append(Path(env).expanduser())
    candidates.append(default_models_dir())
    repository_models = Path(__file__).resolve().parents[3] / "models"
    candidates.append(repository_models)
    return tuple(dict.fromkeys(path.resolve() for path in candidates))


def find_model(entry: ModelEntry, override: Path | None = None) -> Path | None:
    for directory in candidate_model_dirs(override):
        candidate = directory / entry.filename
        if candidate.is_file():
            return candidate
    return None


def _request(url: str) -> QNetworkRequest:
    request = QNetworkRequest(QUrl(url))
    request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, user_agent())
    # Release assets redirect to a storage host, and a stalled transfer must
    # fail instead of holding the job open forever.
    request.setAttribute(
        QNetworkRequest.Attribute.RedirectPolicyAttribute,
        QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
    )
    request.setTransferTimeout(_TRANSFER_TIMEOUT_MS)
    return request


def _download(
    entry: ModelEntry,
    destination: Path,
    token: CancellationToken,
    progress: ProgressCallback,
) -> None:
    """Fetch one model, verifying it before it appears at `destination`.

    `QSaveFile` writes beside the destination and renames on `commit()`, so an
    interrupted, truncated or tampered download never becomes a usable model.
    """
    QNetworkProxyFactory.setUseSystemConfiguration(True)
    manager = QNetworkAccessManager()
    output = QSaveFile(str(destination))
    if not output.open(QIODevice.OpenModeFlag.WriteOnly):
        raise RuntimeError(output.errorString())
    reply = manager.get(_request(entry.url))
    digest = hashlib.sha256()
    written = 0
    write_error = ""
    loop = QEventLoop()

    def consume() -> None:
        nonlocal written, write_error
        payload = reply.readAll().data()
        if not payload:
            return
        if output.write(payload) != len(payload):
            write_error = output.errorString()
            reply.abort()
            return
        digest.update(payload)
        written += len(payload)

    def report(received: int, total: int) -> None:
        span = _PROGRESS_END - _PROGRESS_START
        value = _PROGRESS_START + int(span * received / max(total or entry.size, 1))
        progress(ProgressEvent(min(value, _PROGRESS_END), tr("ai_downloading", name=entry.name)))

    def abort_when_cancelled() -> None:
        if token.cancelled:
            reply.abort()

    reply.readyRead.connect(consume)
    reply.downloadProgress.connect(report)
    reply.finished.connect(loop.quit)
    poll = QTimer()
    poll.setInterval(_CANCEL_POLL_MS)
    poll.timeout.connect(abort_when_cancelled)
    poll.start()
    loop.exec()
    poll.stop()
    consume()

    error = reply.error()
    message = reply.errorString()
    reply.deleteLater()
    try:
        token.raise_if_cancelled()
        if write_error:
            raise RuntimeError(write_error)
        if error != QNetworkReply.NetworkError.NoError:
            raise RuntimeError(message)
        if written != entry.size:
            raise RuntimeError("downloaded model size does not match catalog")
        if digest.hexdigest() != entry.sha256:
            raise RuntimeError("downloaded model checksum does not match catalog")
    except BaseException:
        output.cancelWriting()
        output.commit()
        raise
    if not output.commit():
        raise RuntimeError(output.errorString())


def ensure_model(
    entry: ModelEntry,
    override: Path | None,
    token: CancellationToken,
    progress: ProgressCallback,
) -> Path:
    if existing := find_model(entry, override):
        return existing
    directory = (override or default_models_dir()).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / entry.filename
    try:
        _download(entry, destination, token, progress)
    except ProcessingCancelled:
        raise
    except Exception as error:
        raise RuntimeError(tr("ai_download_failed", msg=error)) from error
    return destination
