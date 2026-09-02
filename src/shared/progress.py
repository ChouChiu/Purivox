from __future__ import annotations

from shared.i18n import tr
from shared.processing import ProgressCallback, ProgressEvent


def report_progress(
    callback: ProgressCallback,
    value: int,
    key: str,
    **values: object,
) -> None:
    """Translate and report one progress update through the shared task contract.

    The key and its placeholder values travel alongside the translated message
    because not every shell can translate here: the browser build runs these
    same pipelines without Qt, where `tr` resolves a key to itself.
    """
    callback(
        ProgressEvent(
            value,
            tr(key, **values),
            key,
            tuple((name, str(filled)) for name, filled in values.items()),
        )
    )
