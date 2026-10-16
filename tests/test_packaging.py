"""A source file ships only if every packaging roster names it.

The wheel lists top-level packages, `pyside6-deploy` reads the PySide project
roster file by file, and Nuitka includes the packages its spec names.  None of
them complains about a missing entry; the build simply leaves the code out.
"""

from __future__ import annotations

import configparser
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "src"


def _project_config() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _top_level_packages() -> set[str]:
    return {path.parent.name for path in SOURCE.glob("*/__init__.py")}


def test_the_wheel_ships_every_top_level_package():
    wheel = _project_config()["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert {Path(entry).name for entry in wheel} == _top_level_packages()


def test_the_standalone_build_includes_every_top_level_package():
    spec = configparser.ConfigParser()
    spec.read(ROOT / "pysidedeploy.spec", encoding="utf-8")
    included = set(re.findall(r"--include-package=(\w+)\b", spec["nuitka"]["extra_args"]))
    missing = _top_level_packages() - included
    assert not missing, f"pysidedeploy.spec does not include: {sorted(missing)}"


def test_the_pyside_project_lists_every_source_and_the_entry_shim():
    configured = {Path(path) for path in _project_config()["tool"]["pyside6-project"]["files"]}
    expected = {
        *(path.relative_to(ROOT) for path in SOURCE.rglob("*.py")),
        *(path.relative_to(ROOT) for path in (SOURCE / "resources/i18n").glob("*.ts")),
        # pyside6-deploy resolves the Nuitka entry from this roster, not from src/.
        Path("deployment/main.py"),
    }
    assert not expected - configured, (
        f"missing from pyside6-project: {sorted(expected - configured)}"
    )
    stale = {path for path in configured if not (ROOT / path).is_file()}
    assert not stale, f"stale pyside6-project entries: {sorted(stale)}"


def test_every_translation_source_is_compiled():
    """The application loads `.qm`, so an uncompiled `.ts` would ship nothing."""
    uncompiled = [
        path.name
        for path in (SOURCE / "resources/i18n").glob("*.ts")
        if not path.with_suffix(".qm").is_file()
    ]
    assert not uncompiled, f"translation sources without a compiled catalogue: {uncompiled}"


def test_the_console_script_and_version_point_at_real_code():
    config = _project_config()
    module, function = config["project"]["scripts"]["purivox"].split(":")
    source = (SOURCE / module.replace(".", "/")).with_suffix(".py").read_text(encoding="utf-8")
    assert f"def {function}(" in source
    assert (ROOT / config["tool"]["hatch"]["version"]["path"]).is_file()
