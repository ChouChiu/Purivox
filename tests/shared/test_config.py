from pathlib import Path

from PySide6.QtCore import QStandardPaths

from shared import config


def test_load_config_uses_only_the_purivox_config_location(monkeypatch, tmp_path: Path):
    app_config = tmp_path / "Purivox"
    requested_locations = []
    loaded = []

    def writable_location(location):
        requested_locations.append(location)
        if location != QStandardPaths.StandardLocation.AppConfigLocation:
            raise AssertionError(f"unexpected config location: {location}")
        return str(app_config)

    monkeypatch.setattr(config.QStandardPaths, "writableLocation", writable_location)
    monkeypatch.setattr(
        config.qconfig,
        "load",
        lambda path, settings: loaded.append((Path(path), settings)),
    )

    config.load_config()

    assert requested_locations == [QStandardPaths.StandardLocation.AppConfigLocation]
    assert loaded == [(app_config / "config.json", config.cfg)]
