from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent

from shared.ui import AudioDropLineEdit, AudioDropListWidget, dropped_audio_paths


def _mime(*paths: str) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
    return mime


def _drop(widget, *paths: str) -> QDropEvent:
    # A drag event only borrows its mime data, so the QMimeData has to outlive
    # the handler call; letting it be a temporary crashes the interpreter.
    mime = _mime(*paths)
    event = QDropEvent(
        QPointF(1, 1),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.dropEvent(event)
    return event


def test_only_local_audio_files_are_offered():
    assert dropped_audio_paths(_mime("/tmp/live.wav", "/tmp/notes.txt", "/tmp/take.FLAC")) == [
        Path("/tmp/live.wav"),
        Path("/tmp/take.FLAC"),
    ]
    remote = QMimeData()
    remote.setUrls([QUrl("https://example.com/live.wav")])
    assert dropped_audio_paths(remote) == []
    assert dropped_audio_paths(QMimeData()) == []


def test_line_edit_reports_the_first_dropped_file(qtbot):
    edit = AudioDropLineEdit()
    qtbot.addWidget(edit)
    assert edit.acceptDrops()
    with qtbot.waitSignal(edit.file_dropped) as dropped:
        assert _drop(edit, "/tmp/live.wav", "/tmp/other.wav").isAccepted()
    assert dropped.args == ["/tmp/live.wav"]


def test_line_edit_ignores_a_drag_without_audio(qtbot):
    edit = AudioDropLineEdit()
    qtbot.addWidget(edit)
    mime = _mime("/tmp/notes.txt")
    enter = QDragEnterEvent(
        QPointF(1, 1).toPoint(),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    edit.dragEnterEvent(enter)
    assert not enter.isAccepted()
    assert not _drop(edit, "/tmp/notes.txt").isAccepted()


def test_list_widget_reports_every_dropped_file(qtbot):
    sources = AudioDropListWidget()
    qtbot.addWidget(sources)
    with qtbot.waitSignal(sources.files_dropped) as dropped:
        _drop(sources, "/tmp/a.wav", "/tmp/readme.md", "/tmp/b.mp3")
    assert dropped.args == [["/tmp/a.wav", "/tmp/b.mp3"]]
