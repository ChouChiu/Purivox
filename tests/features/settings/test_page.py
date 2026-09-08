from __future__ import annotations

from features.settings.page import SettingsPage
from shared.i18n import SUPPORTED_LANGUAGES


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
