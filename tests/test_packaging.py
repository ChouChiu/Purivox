"""A source file ships only if the packaging finds it.

The wheel lists its top-level packages by hand and does not complain about a
missing one; the build simply leaves the code out.  The PyInstaller spec finds
every top-level package under src/ itself, so it has no roster to check.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from app.version import __version__

ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "src"


def _project_config() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _top_level_packages() -> set[str]:
    return {path.parent.name for path in SOURCE.glob("*/__init__.py")}


def test_the_wheel_ships_every_top_level_package():
    wheel = _project_config()["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert {Path(entry).name for entry in wheel} == _top_level_packages()


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


def test_the_site_reads_only_assets_its_own_build_fingerprinted():
    """A fixed file name outlives the deploy that changed it.

    The catalogues and the Pyodide archive used to sit in `web/public/` under
    names that never change, so GitHub Pages' cache could hand a fresh bundle the
    previous catalogue: every key the page had gained since resolved to itself and
    the raw `stage_stack` showed on screen. Importing them instead lets Vite put a
    content hash in the name, which is what this pins.
    """
    offenders = [
        f"{path.relative_to(ROOT)}: {line.strip()}"
        for path in sorted((ROOT / "web/src").rglob("*.ts*"))
        for line in path.read_text(encoding="utf-8").splitlines()
        if "BASE_URL}i18n" in line or "BASE_URL}purivox-src.zip" in line
    ]
    assert not offenders, "generated assets must be imported, not fetched by name"


def test_the_browser_build_carries_the_application_version():
    """The site's header reads its version from package.json, the desktop from version.py."""
    package = json.loads((ROOT / "web/package.json").read_text(encoding="utf-8"))
    assert package["version"] == __version__
