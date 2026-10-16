from __future__ import annotations

from features.settings.page import THEME_KEYS, SettingsPage
from shared.i18n import SUPPORTED_LANGUAGES, install_language, tr


def test_the_language_card_offers_every_supported_language(qtbot):
    """`OptionsSettingCard` zips its texts with the options and drops the rest.

    A language added to `SUPPORTED_LANGUAGES` without a name here would be
    unreachable from the interface, and nothing else would say so.
    """
    page = SettingsPage()
    qtbot.addWidget(page)
    card = page.language_card
    buttons = card.buttonGroup.buttons()

    assert [button.property(card.configName) for button in buttons] == list(SUPPORTED_LANGUAGES)
    assert all(button.text() for button in buttons)


def test_the_theme_choices_and_the_switch_speak_the_interface_language(qtbot):
    """Fluent words both through its own catalogue, which this app does not ship."""
    page = SettingsPage()
    qtbot.addWidget(page)

    def shown() -> tuple[list[str], str]:
        page.retranslate()
        buttons = page.theme_card.buttonGroup.buttons()
        return [button.text() for button in buttons], page.update_card.switchButton.getText()

    install_language("zh_cn")
    chinese = shown()
    install_language("en_us")
    english = shown()

    assert english == ([tr(key) for key in THEME_KEYS], tr("switch_off"))
    assert chinese[0] != english[0] and chinese[1] != english[1]
    page.update_card.setChecked(True)
    assert page.update_card.switchButton.getText() == tr("switch_on")
