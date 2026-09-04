"""The one window a release check opens."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget
from qfluentwidgets import MessageBoxBase, SubtitleLabel, TextBrowser

from features.settings.updates import Release
from shared.i18n import tr

_DIALOG_WIDTH = 520
_NOTES_HEIGHT = 280


class UpdateDialog(MessageBoxBase):
    """What the new release changed, and the button that goes and gets it.

    Nothing is downloaded here: the dialog reports the release and hands the
    user over to its page, which is the whole of the update path.

    The mask is drawn over `parent`, so the window it belongs to is not
    optional the way it is for an ordinary widget.
    """

    def __init__(self, release: Release, parent: QWidget):
        super().__init__(parent)
        self.release = release
        self.title_label = SubtitleLabel(tr("update_title", version=release.version), self)
        self.notes = TextBrowser(self)
        self.notes.setOpenExternalLinks(True)
        # Release notes are written as Markdown, and Qt's own reader renders
        # them - a second Markdown implementation here would be one too many.
        self.notes.setMarkdown(release.notes.strip() or tr("update_notes_empty"))
        self.notes.setMinimumHeight(_NOTES_HEIGHT)
        self.viewLayout.addWidget(self.title_label)
        self.viewLayout.addWidget(self.notes)
        self.widget.setFixedWidth(_DIALOG_WIDTH)
        self.yesButton.setText(tr("update_open_release"))
        self.cancelButton.setText(tr("update_later"))
