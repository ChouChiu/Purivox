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

THEME_KEYS = tuple(f"theme_{option}" for option in cfg.theme.options)


class SwitchCard(SwitchSettingCard):
    """A switch that words its state in the application language.

    Fluent names the two states through its own catalogue, which this
    application does not install, so every locale read "On" and "Off".
    """

    def setValue(self, isChecked: bool) -> None:
        super().setValue(isChecked)
        self.retranslate_state()

    def retranslate_state(self) -> None:
        self.switchButton.setText(tr("switch_on" if self.isChecked() else "switch_off"))


def _retranslate_options(card: OptionsSettingCard, keys: tuple[str, ...]) -> None:
    for button, key in zip(card.buttonGroup.buttons(), keys, strict=True):
        button.setText(tr(key))
        if button.isChecked():
            card.choiceLabel.setText(button.text())
            card.choiceLabel.adjustSize()


class SettingsPage(PageScrollArea):
    update_check_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self.checking_updates = False
        self.title = TitleLabel()
        self.layout.addWidget(self.title)
        self.language_card = OptionsSettingCard(
            cfg.language,
            FluentIcon.LANGUAGE,
            "",
            texts=["简体中文", "正體中文", "English", "日本語", "한국어"],
        )
        self.theme_card = OptionsSettingCard(
            cfg.theme, FluentIcon.BRUSH, "", texts=[tr(key) for key in THEME_KEYS]
        )
        self.log_level_card = OptionsSettingCard(
            cfg.log_level,
            FluentIcon.DEVELOPER_TOOLS,
            "",
            texts=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        )
        self.update_now_card = PrimaryPushSettingCard("", FluentIcon.UPDATE, "", "")
        self.update_card = SwitchCard(FluentIcon.SYNC, "", configItem=cfg.check_updates)
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
        _retranslate_options(self.theme_card, THEME_KEYS)
        self.log_level_card.card.setTitle(tr("log_level_label"))
        self.log_level_card.card.setContent(tr("log_level_description"))
        self.update_now_card.setTitle(tr("update_now"))
        self.update_now_card.button.setText(tr("update_now_button"))
        self._retranslate_update_status()
        self.update_card.setTitle(tr("update_check"))
        self.update_card.setContent(tr("update_check_description"))
        self.update_card.retranslate_state()
