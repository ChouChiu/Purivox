from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
MARKDOWN_LINK = re.compile(r"\[[^]]+]\(([^)]+)\)")


def test_internal_markdown_links_resolve():
    documents = (
        ROOT / "README.md",
        ROOT / "README_EN.md",
        *(ROOT / "docs").glob("*.md"),
    )
    broken: list[str] = []
    for document in documents:
        for target in MARKDOWN_LINK.findall(document.read_text(encoding="utf-8")):
            if "://" in target or target.startswith(("#", "mailto:")):
                continue
            relative_target = target.split("#", 1)[0]
            if relative_target and not (document.parent / relative_target).resolve().exists():
                broken.append(f"{document.relative_to(ROOT)} -> {target}")
    assert not broken, "broken internal documentation links:\n" + "\n".join(broken)


def test_readme_links_every_technical_document():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    missing = [
        path.name
        for path in (ROOT / "docs").glob("*.md")
        if path.name != "README.md" and f"docs/{path.name}" not in readme
    ]
    assert not missing, f"technical documents not linked from README.md: {missing}"


def test_readmes_link_to_each_other():
    chinese_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    english_readme = (ROOT / "README_EN.md").read_text(encoding="utf-8")

    assert 'href="README_EN.md"' in chinese_readme
    assert 'href="README.md"' in english_readme
