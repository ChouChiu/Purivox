from __future__ import annotations

from qfluentwidgets import FluentIcon, OptionsSettingCard, SwitchSettingCard, TitleLabel

from shared.config import cfg
from shared.i18n import tr
from shared.ui import Lane, PageScrollArea


class SettingsPage(PageScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPage")
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
        self.update_card = SwitchSettingCard(FluentIcon.UPDATE, "", configItem=cfg.check_updates)
        self.update_card.setEnabled(False)
        self.add_card(self.language_card)
        self.add_card(self.theme_card)
        self.add_card(self.log_level_card, Lane.SECONDARY)
        self.add_card(self.update_card, Lane.SECONDARY)
        self.layout.addStretch()

    def retranslate(self) -> None:
        self.title.setText(tr("nav_settings"))
        self.language_card.card.setTitle(tr("lang_label"))
        self.theme_card.card.setTitle(tr("theme_label"))
        self.log_level_card.card.setTitle(tr("log_level_label"))
        self.log_level_card.card.setContent(tr("log_level_description"))
        self.update_card.setTitle(tr("update_check"))
        self.update_card.setContent(tr("update_unavailable"))
