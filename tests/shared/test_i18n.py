from __future__ import annotations

import ast
import gc
from pathlib import Path
from xml.etree import ElementTree

from PySide6.QtCore import QTranslator

from resources import resource_path
from shared.i18n import (
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
    TRANSLATION_CONTEXT,
    current_language,
    install_language,
    tr,
)


def _source_catalogue(language: str) -> dict[str, str]:
    """Read one Qt Linguist `.ts` file, the editable source of every UI string."""
    document = ElementTree.fromstring(
        resource_path(f"i18n/{language}.ts").read_text(encoding="utf-8")
    )
    contexts = {context.findtext("name"): context for context in document.findall("context")}
    assert set(contexts) == {TRANSLATION_CONTEXT}, f"unexpected contexts in {language}.ts"
    return {
        message.findtext("source"): message.findtext("translation")
        for message in contexts[TRANSLATION_CONTEXT].findall("message")
    }


def _compiled_catalogue(language: str) -> QTranslator:
    """Load a `.qm` the way the application does, by path so Qt owns the data."""
    translator = QTranslator()
    assert translator.load(str(resource_path(f"i18n/{language}.qm")))
    return translator


def test_translation_catalogues_have_identical_keys():
    catalogues = [_source_catalogue(language) for language in SUPPORTED_LANGUAGES]
    assert catalogues
    assert all(catalogue.keys() == catalogues[0].keys() for catalogue in catalogues[1:])
    assert all(all(catalogue.values()) for catalogue in catalogues)


def test_compiled_catalogues_are_current():
    """A stale `.qm` would ship strings that no longer match the `.ts` sources."""
    stale: list[str] = []
    for language in SUPPORTED_LANGUAGES:
        compiled = _compiled_catalogue(language)
        stale.extend(
            f"{language}:{key}"
            for key, text in _source_catalogue(language).items()
            if compiled.translate(TRANSLATION_CONTEXT, key) != text
        )
    assert not stale, (
        "compiled translations differ from their sources; regenerate them with "
        f"pyside6-lrelease: {stale}"
    )


def test_installed_catalogues_survive_garbage_collection():
    """Qt borrows in-memory catalogues, so a dropped buffer reads another language."""
    rendered = {}
    for language in SUPPORTED_LANGUAGES:
        install_language(language)
        rendered[language] = tr("params")
    gc.collect()
    for language, text in rendered.items():
        install_language(language)
        assert tr("params") == text
    assert len(set(rendered.values())) == len(SUPPORTED_LANGUAGES)


def test_all_supported_languages_render_and_interpolate():
    for language in SUPPORTED_LANGUAGES:
        assert install_language(language) == language
        assert current_language() == language
        assert tr("params")
        assert tr("done_status", path="/tmp/a.wav").endswith("/tmp/a.wav")
        assert "{path}" not in tr("done_status", path="/tmp/a.wav")


def test_unknown_language_falls_back_to_the_default():
    assert install_language("xx_yy") == DEFAULT_LANGUAGE
    fallback = tr("params")
    install_language(DEFAULT_LANGUAGE)
    assert fallback == tr("params")


def test_unknown_key_translates_to_itself():
    assert tr("no_such_translation_key") == "no_such_translation_key"


def test_english_mr_terms_match_product_workflows():
    install_language("en_us")
    assert tr("nav_mr") == "Vocal Isolation"
    assert tr("mr_tab_single") == "Single"
    assert tr("mr_tab_full_stage") == "Full Stage"
    assert tr("mr_single_title") == "Single Vocal Isolation"
    assert tr("nav_full_stage") == "Full Stage Vocal Isolation"


def test_japanese_and_korean_mr_terms_are_unambiguous():
    install_language("ja_jp")
    assert tr("nav_mr") == "ライブボーカル抽出"
    assert tr("stage_clip_enabled") == "処理"
    assert tr("stage_unmatched_label") == "トーク / 広告 / 空き時間"

    install_language("ko_kr")
    assert tr("nav_mr") == "라이브 보컬 추출"
    assert tr("stage_clip_enabled") == "처리"
    assert tr("stage_confidence") == "매칭 신뢰도"


def _literal_keys() -> set[str]:
    """Collect every translation key written as a literal in the sources.

    `tr()` takes the key first, and `report_progress()` after the callback and
    percentage, so both are read here: a progress key is just as user-visible.
    """
    positions = {"tr": 0, "report_progress": 2}
    keys: set[str] = set()
    for path in Path("src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            index = positions.get(node.func.id)
            if index is None or len(node.args) <= index:
                continue
            argument = node.args[index]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                keys.add(argument.value)
    return keys


def test_every_literal_key_exists_in_every_locale():
    catalogues = [_source_catalogue(language) for language in SUPPORTED_LANGUAGES]
    missing = sorted(
        key for key in _literal_keys() if any(key not in catalogue for catalogue in catalogues)
    )
    assert not missing, f"translation keys missing from some locales: {missing}"
