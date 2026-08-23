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


def test_distribution_includes_runtime_packages_and_documentation():
    config = _project_config()
    assert config["project"]["dynamic"] == ["version"]
    assert config["tool"]["hatch"]["version"]["path"] == "src/app/version.py"
    wheel_packages = set(config["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"])
    assert wheel_packages == {
        "src/app",
        "src/entrypoints",
        "src/features",
        "src/resources",
        "src/shared",
    }
    sdist_entries = set(config["tool"]["hatch"]["build"]["targets"]["sdist"]["include"])
    assert {"src", "tests", "deployment", "docs", "README.md", "LICENSE"} <= sdist_entries
