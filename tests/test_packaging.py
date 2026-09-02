from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _project_config() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_pyside_project_lists_every_python_source():
    configured = {Path(path) for path in _project_config()["tool"]["pyside6-project"]["files"]}
    sources = {path.relative_to(ROOT) for path in (ROOT / "src").rglob("*.py")}
    missing = sources - configured
    stale = {path for path in configured if not (ROOT / path).is_file()}
    assert not missing, f"Python sources missing from pyside6-project: {sorted(missing)}"
    assert not stale, f"stale pyside6-project entries: {sorted(stale)}"


def test_pyside_project_lists_the_standalone_entry_point():
    """pyside6-deploy resolves the Nuitka entry from this roster, not from src/."""
    configured = {Path(path) for path in _project_config()["tool"]["pyside6-project"]["files"]}
    assert Path("deployment/main.py") in configured


def test_pyside_project_lists_every_translation_source():
    configured = {Path(path) for path in _project_config()["tool"]["pyside6-project"]["files"]}
    catalogues = {path.relative_to(ROOT) for path in (ROOT / "src/resources/i18n").glob("*.ts")}
    assert catalogues
    assert not catalogues - configured, (
        f"translation sources missing from pyside6-project: {sorted(catalogues - configured)}"
    )


def test_every_translation_source_is_compiled():
    """The application loads `.qm`, so an uncompiled `.ts` would ship nothing."""
    uncompiled = [
        path.name
        for path in (ROOT / "src/resources/i18n").glob("*.ts")
        if not path.with_suffix(".qm").is_file()
    ]
    assert not uncompiled, f"translation sources without a compiled catalogue: {uncompiled}"


def test_distribution_includes_runtime_packages_and_documentation():
    config = _project_config()
    assert config["project"]["name"] == "purivox"
    assert config["project"]["scripts"] == {"purivox": "entrypoints.cli:main"}
    assert config["project"]["dynamic"] == ["version"]
    assert config["tool"]["hatch"]["version"]["path"] == "src/app/version.py"
    wheel_packages = set(config["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"])
    assert wheel_packages == {
        "src/app",
        "src/entrypoints",
        "src/features",
        "src/resources",
        "src/shared",
        "src/web",
    }
    sdist_entries = set(config["tool"]["hatch"]["build"]["targets"]["sdist"]["include"])
    assert {"src", "tests", "deployment", "docs", "README.md", "LICENSE"} <= sdist_entries
