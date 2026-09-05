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
    auto_find = ConfigItem("Reference", "AutoFind", True, BoolValidator())
    output_tracks = OptionsConfigItem(
        "Reference",
        "OutputTracks",
        OutputTracks.VOCAL.value,
        OptionsValidator([choice.value for choice in OutputTracks]),
    )
    model = OptionsConfigItem(
        "Neural",
        "Model",
        "mdxnet_1",
        OptionsValidator(["mdxnet_1", "mdxnet_main", "kim_vocal", "kuielab_b"]),
    )
    check_updates = ConfigItem("Updates", "CheckAtStartup", False, BoolValidator())


cfg = AppConfig()


def load_config() -> None:
    directory = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    path = Path(directory or Path.home() / ".config/purivox") / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    qconfig.load(str(path), cfg)
