from __future__ import annotations

import pytest

from shared.processing import CancellationToken, ProcessingCancelled
from shared.progress import report_progress


def test_cancellation_token_is_idempotent_and_raises():
    token = CancellationToken()
    assert not token.cancelled
    token.cancel()
    token.cancel()
    assert token.cancelled
    with pytest.raises(ProcessingCancelled):
        token.raise_if_cancelled()


def test_report_progress_uses_the_shared_translation_contract():
    events = []
    report_progress(events.append, 90, "zh_cn", "saving")
    assert [(event.value, event.message) for event in events] == [(90, "正在保存输出文件...")]
