import os
from xml.etree import ElementTree

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QStandardPaths
from qfluentwidgets import ConfigItem

from resources import resource_path
from shared.config import AppConfig, cfg, config_path
from shared.i18n import DEFAULT_LANGUAGE, install_language

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QStandardPaths.setTestModeEnabled(True)


def pytest_addoption(parser):
    parser.addoption("--runslow", action="store_true", help="run 15-minute acceptance benchmarks")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runslow"):
        return
    skip = pytest.mark.skip(reason="use --runslow to run resource-intensive acceptance tests")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def installed_translation(qapp):
    """Start every test from the default translation.

    Translations are application state, so a test that switches language would
    otherwise leak that choice into whatever runs next.
    """
    install_language(DEFAULT_LANGUAGE)
    return qapp


@pytest.fixture(autouse=True)
def default_settings(qapp):
    """Start every test from the default settings, in memory and on disk.

    `cfg.set` saves as it goes, and test mode only moves the file under
    `~/.qttest`: without this a choice made by one test - or by one run - is
    what the next one starts from.
    """
    for item in vars(AppConfig).values():
        if isinstance(item, ConfigItem):
            item.blockSignals(True)
            item.value = item.defaultValue
            item.blockSignals(False)
    config_path().unlink(missing_ok=True)
    yield cfg
    # pytest-qt closes a test's widgets with deleteLater, which only a running
    # event loop carries out.  Deleting them here keeps every window a test
    # built from lingering, still connected to `cfg`, into the tests after it.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.fixture(scope="session")
def translation_keys() -> frozenset[str]:
    """Every key the catalogues define; test_i18n holds the five files to one set."""
    document = ElementTree.fromstring(
        resource_path(f"i18n/{DEFAULT_LANGUAGE}.ts").read_text(encoding="utf-8")
    )
    return frozenset(message.findtext("source") for message in document.iter("message"))
