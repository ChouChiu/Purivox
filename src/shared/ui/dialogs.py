from __future__ import annotations

from shared.audio import AUDIO_EXTENSIONS

AUDIO_FILE_FILTER = "Audio (" + " ".join(f"*{suffix}" for suffix in AUDIO_EXTENSIONS) + ")"
WAV_FILE_FILTER = "WAV (*.wav)"
