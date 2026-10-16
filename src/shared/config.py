from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths
from qfluentwidgets import (
    BoolValidator,
    ConfigItem,
    OptionsConfigItem,
    OptionsValidator,
    QConfig,
    qconfig,
)

from shared.i18n import SUPPORTED_LANGUAGES
from shared.jobs import OutputTracks
from shared.logging import LOG_LEVELS


class AppConfig(QConfig):
    language = OptionsConfigItem(
        "General",
        "Language",
        SUPPORTED_LANGUAGES[0],
        OptionsValidator(list(SUPPORTED_LANGUAGES)),
    )
    theme = OptionsConfigItem(
        "General", "Theme", "auto", OptionsValidator(["light", "dark", "auto"])
    )
    log_level = OptionsConfigItem(
        "General",
        "LogLevel",
        "INFO",
        OptionsValidator(list(LOG_LEVELS)),
    )
    output_tracks = OptionsConfigItem(
        "Reference",
        "OutputTracks",
        OutputTracks.VOCAL.value,
        OptionsValidator([choice.value for choice in OutputTracks]),
    )
    check_updates = ConfigItem("Updates", "CheckAtStartup", False, BoolValidator())


cfg = AppConfig()


def config_path() -> Path:
    """Where the settings live: `config.json` in the platform's application config folder."""
    directory = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    return Path(directory or Path.home() / ".config/purivox") / "config.json"


def load_config() -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    qconfig.load(str(path), cfg)
