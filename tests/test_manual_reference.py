"""The manual's reference pages match the registries they are generated from."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _generator():
    spec = importlib.util.spec_from_file_location("generate_manual_reference", ROOT / "scripts" / "generate_manual_reference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reference_pages_are_up_to_date() -> None:
    generator = _generator()
    stale = [
        name
        for name, text in generator.render().items()
        if not (generator.REFERENCE / name).exists() or (generator.REFERENCE / name).read_text(encoding="utf-8") != text
    ]
    assert stale == [], (
        f"regenerate with: PYTHONPATH=backend .venv/bin/python scripts/generate_manual_reference.py ({stale})"
    )


def test_every_manual_link_resolves() -> None:
    import re

    manual = ROOT / "docs" / "manual"
    broken = [
        (str(page.relative_to(manual)), link)
        for page in manual.rglob("*.md")
        for link in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", page.read_text(encoding="utf-8"))
        if not link.startswith(("http://", "https://")) and not (page.parent / link).resolve().exists()
    ]
    assert broken == []
