from __future__ import annotations

from shared.i18n import install_language
from shared.progress import report_progress


def test_a_progress_event_carries_its_key_beside_the_translated_text():
    """The desktop shows the message; the browser translates the key itself."""
    events = []
    report_progress(events.append, 42, "stage_render_clip", current=3, total=12, name="a.wav")
    install_language("en_us")
    report_progress(events.append, 42, "stage_render_clip", current=3, total=12, name="a.wav")

    chinese, english = events
    assert chinese.value == english.value == 42
    assert chinese.message != english.message
    assert "a.wav" in chinese.message and "a.wav" in english.message
    assert chinese.key == english.key == "stage_render_clip"
    assert dict(chinese.values) == {"current": "3", "total": "12", "name": "a.wav"}
