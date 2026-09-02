"""The browser build runs the same pipelines under Pyodide, which has no Qt.

`test_architecture.py` locks the layering; this locks the other boundary the
browser depends on - that nothing on the `web.bridge` import graph needs Qt.
Both fail loudly the moment an import creeps back in.
"""

from __future__ import annotations

import subprocess
import sys

_SCRIPT = """
import importlib
import sys


class BlockQt:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "PySide6" or fullname.startswith("PySide6."):
            raise ImportError("PySide6 is not available in the browser build")
        return None


sys.meta_path.insert(0, BlockQt())
for name in ("web.bridge", "web.limits", "web.timeline"):
    importlib.import_module(name)
assert not [name for name in sys.modules if name.startswith("PySide6")], "Qt was imported"
print("ok")
"""


def test_the_browser_entry_points_import_without_qt():
    finished = subprocess.run(
        [sys.executable, "-c", _SCRIPT], capture_output=True, text=True, check=False
    )
    assert finished.returncode == 0, finished.stderr
    assert finished.stdout.strip().endswith("ok")


def test_progress_reporting_survives_without_a_translation_catalogue():
    """`tr` resolves a key to itself there, so the key has to reach the page."""
    finished = subprocess.run(
        [
            sys.executable,
            "-c",
            _SCRIPT.replace(
                'print("ok")',
                """
from shared.processing import ProgressEvent
from shared.progress import report_progress

seen = []
report_progress(seen.append, 42, "stage_render_clip", current=3, total=12, name="song.wav")
event, = seen
assert isinstance(event, ProgressEvent)
assert event.value == 42
assert event.key == "stage_render_clip"
assert dict(event.values) == {"current": "3", "total": "12", "name": "song.wav"}
print("ok")
""",
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert finished.returncode == 0, finished.stderr
    assert finished.stdout.strip().endswith("ok")
