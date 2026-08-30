from __future__ import annotations

from shared.i18n import tr
from shared.processing import ProgressCallback, ProgressEvent


def report_progress(
    callback: ProgressCallback,
    value: int,
    key: str,
    **values: object,
) -> None:
    """Translate and report one progress update through the shared task contract."""
    callback(ProgressEvent(value, tr(key, **values)))
