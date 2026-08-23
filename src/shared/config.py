from __future__ import annotations

import shutil
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


class AppConfig(QConfig):
    language = OptionsConfigItem(
        "General",
        "Language",
        "zh_cn",
        OptionsValidator(["zh_cn", "en_us", "ja_jp", "ko_kr"]),
    )
    theme = OptionsConfigItem(
        "General", "Theme", "auto", OptionsValidator(["light", "dark", "auto"])
    )
    log_level = OptionsConfigItem(
        "General",
        "LogLevel",
        "INFO",
        OptionsValidator(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]),
    )
    auto_find = ConfigItem("Reference", "AutoFind", True, BoolValidator())
    center_extraction = ConfigItem("Reference", "CenterExtraction", False, BoolValidator())
    weak_vocal_protection = ConfigItem("Reference", "WeakVocalProtection", False, BoolValidator())
    model = OptionsConfigItem(
        "Neural",
        "Model",
        "mdxnet_1",
        OptionsValidator(["mdxnet_1", "mdxnet_main", "kim_vocal", "kuielab_b"]),
    )
    check_updates = ConfigItem("Updates", "CheckAtStartup", False, BoolValidator())


cfg = AppConfig()


def _legacy_config_paths() -> tuple[Path, ...]:
    generic = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericConfigLocation)
    root = Path(generic or Path.home() / ".config")
    return (
        root / "Audio Station" / "Audio Station" / "config.json",
        root / "audio-station" / "config.json",
    )


def load_config() -> None:
    directory = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    path = Path(directory or Path.home() / ".config/purivox") / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if (
        not path.exists()
        and path.parent.name == "Purivox"
        and (
            legacy := next(
                (candidate for candidate in _legacy_config_paths() if candidate.is_file()), None
            )
        )
        is not None
    ):
        shutil.copy2(legacy, path)
    qconfig.load(str(path), cfg)
