from __future__ import annotations

from qfluentwidgets import SwitchButton

from shared.audio import AUDIO_EXTENSIONS

AUDIO_FILE_FILTER = "Audio (" + " ".join(f"*{suffix}" for suffix in AUDIO_EXTENSIONS) + ")"
WAV_FILE_FILTER = "WAV (*.wav)"


def sync_dependent_switch(primary: SwitchButton, dependent: SwitchButton) -> None:
    """Keep a switch that only makes sense while another one is on in step."""
    enabled = primary.isChecked()
    if not enabled:
        dependent.setChecked(False)
    dependent.setEnabled(enabled)
