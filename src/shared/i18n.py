from __future__ import annotations

from pathlib import Path

from resources import resource_path

try:
    from PySide6.QtCore import QByteArray, QCoreApplication, QTranslator
except ImportError:
    # The browser build runs the same pipelines under Pyodide, which has no Qt.
    # Only `tr()` is on that path, and it degrades to the untranslated key;
    # anything that actually needs a catalogue still fails loudly below.
    QByteArray = QCoreApplication = QTranslator = None  # type: ignore[assignment]

SUPPORTED_LANGUAGES = ("zh_cn", "en_us", "ja_jp", "ko_kr")
DEFAULT_LANGUAGE = SUPPORTED_LANGUAGES[0]
# Every UI string lives in one Qt Linguist context keyed by short identifiers
# rather than by source text, so a message can be reworded in every locale
# without touching the call sites.
TRANSLATION_CONTEXT = "Purivox"

# QTranslator.load() only *borrows* an in-memory catalogue, so anything read
# from bytes is cached next to the translator that reads it; a dropped buffer
# does not fail loudly, it returns another language's strings.
_catalogues: dict[str, tuple[QTranslator, QByteArray | None]] = {}
_installed: QTranslator | None = None
_language = DEFAULT_LANGUAGE


def _normalise_language(language: str) -> str:
    return language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def _translator(language: str) -> QTranslator:
    """Load the compiled `.qm` catalogue for one language, once per process."""
    if QTranslator is None:
        raise RuntimeError("Qt is required to load a compiled translation")
    cached = _catalogues.get(language)
    if cached is not None:
        return cached[0]
    resource = resource_path(f"i18n/{language}.qm")
    translator = QTranslator()
    data: QByteArray | None = None
    if isinstance(resource, Path):
        # Qt reads the file into memory it owns, which is the only form that
        # cannot be invalidated by the caller.
        loaded = translator.load(str(resource))
    else:
        # Resources reached through a non-filesystem loader have no path to
        # hand Qt, so keep the borrowed buffer alive for as long as its reader.
        data = QByteArray(resource.read_bytes())
        loaded = translator.load(data)
    if not loaded:
        raise RuntimeError(f"could not load the compiled translation for {language}")
    _catalogues[language] = (translator, data)
    return translator


def install_language(language: str) -> str:
    """Install one language as the application translation and return its code."""
    global _installed, _language
    code = _normalise_language(language)
    application = QCoreApplication.instance() if QCoreApplication is not None else None
    if application is None:
        raise RuntimeError("a QCoreApplication must exist before installing a translation")
    translator = _translator(code)
    if translator is _installed:
        return code
    if _installed is not None:
        application.removeTranslator(_installed)
    application.installTranslator(translator)
    _installed = translator
    _language = code
    return code


def current_language() -> str:
    return _language


def tr(key: str, **values: object) -> str:
    """Translate one key into the installed language and fill its placeholders.

    An unknown key translates to itself, which keeps a missing string visible
    instead of blank - never rely on that as a way to pass literal text.  The
    browser build has no Qt and therefore no catalogue, so every key resolves
    that way there; `ProgressEvent` carries the key and its values separately
    so the page can translate what the pipeline could not.
    """
    text = key if QCoreApplication is None else QCoreApplication.translate(TRANSLATION_CONTEXT, key)
    for name, value in values.items():
        text = text.replace("{" + name + "}", str(value))
    return text
