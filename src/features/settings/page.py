from __future__ import annotations

from PySide6.QtCore import Signal
from qfluentwidgets import (
    FluentIcon,
    OptionsSettingCard,
    PrimaryPushSettingCard,
    SwitchSettingCard,
    TitleLabel,
)

from features.settings.updates import installed_version
from shared.config import cfg
from shared.i18n import tr
from shared.ui import Lane, PageScrollArea


class SettingsPage(PageScrollArea):
    update_check_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self.checking_updates = False
        self.title = TitleLabel()
        self.layout.addWidget(self.title)
        self.language_card = OptionsSettingCard(
            cfg.language, FluentIcon.LANGUAGE, "", texts=["中文", "English", "日本語", "한국어"]
        )
        self.theme_card = OptionsSettingCard(
            cfg.theme, FluentIcon.BRUSH, "", texts=["Light", "Dark", "Auto"]
        )
        self.log_level_card = OptionsSettingCard(
            cfg.log_level,
            FluentIcon.DEVELOPER_TOOLS,
            "",
            texts=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        )
        self.update_now_card = PrimaryPushSettingCard("", FluentIcon.UPDATE, "", "")
        self.update_card = SwitchSettingCard(FluentIcon.SYNC, "", configItem=cfg.check_updates)
        self.update_now_card.clicked.connect(self.update_check_requested)
        self.add_card(self.language_card)
        self.add_card(self.theme_card)
        self.add_card(self.log_level_card, Lane.SECONDARY)
        self.add_card(self.update_now_card, Lane.SECONDARY)
        self.add_card(self.update_card, Lane.SECONDARY)
        self.layout.addStretch()

    def set_checking_updates(self, checking: bool) -> None:
        """Report a check in flight, and keep the button from starting a second."""
        self.checking_updates = checking
        self.update_now_card.button.setEnabled(not checking)
        self._retranslate_update_status()

    def _retranslate_update_status(self) -> None:
        if self.checking_updates:
            self.update_now_card.setContent(tr("update_checking"))
        else:
            self.update_now_card.setContent(tr("update_installed", version=installed_version()))

    def retranslate(self) -> None:
        self.title.setText(tr("nav_settings"))
        self.language_card.card.setTitle(tr("lang_label"))
        self.theme_card.card.setTitle(tr("theme_label"))
        self.log_level_card.card.setTitle(tr("log_level_label"))
        self.log_level_card.card.setContent(tr("log_level_description"))
        self.update_now_card.setTitle(tr("update_now"))
        self.update_now_card.button.setText(tr("update_now_button"))
        self._retranslate_update_status()
        self.update_card.setTitle(tr("update_check"))
        self.update_card.setContent(tr("update_check_description"))
