"""E1/E4 — make the development-control systems enforce their own use.

The failure this closes: governance that is opt-in gets skipped, which is the
exact class of mistake it exists to prevent. Both checks here are *absence*
triggered — they fire because something required is missing, not because a
governance file happened to be edited.

E1  `require_devline_for_changes` — a changed feature file must be covered by a
    started, intact devline whose Context Pack claims that path.
E4  `enabled_rule_markers` — the test markers of currently enabled mechanical
    rules, so the gate can run them and "enabled" means "enforced", not "written".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .events import verify_log
from .promotion import read_global_rules

# Product feature surface. A change here is what a devline is meant to precede.
FEATURE_PREFIXES = ("backend/workbench/", "frontend/src/")
# Governance code is not product feature; it is covered by its own control line
# and must not require a second devline to edit.
FEATURE_EXCLUDED_PREFIXES = ("backend/workbench/development_control/",)

DEVLINES_DIRNAME = ".agent/devlines"


def feature_surface_paths(changed_paths: list[str]) -> list[str]:
    """Return only the changed paths that are product feature code."""

    surface: list[str] = []
    for path in changed_paths:
        normalized = path.strip()
        if not normalized:
            continue
        if not normalized.startswith(FEATURE_PREFIXES):
            continue
        if normalized.startswith(FEATURE_EXCLUDED_PREFIXES):
            continue
        surface.append(normalized)
    return surface


def _covers(affected_path: str, changed_path: str) -> bool:
    """A manifest affected_path covers a changed file only on a real path boundary.

    `.../notebook/` covers `.../notebook/store.py` but not `.../notebook_evil/x`.
    A bare file entry covers only itself.
    """

    claim = affected_path.strip()
    if not claim:
        return False
    if claim == changed_path:
        return True
    prefix = claim if claim.endswith("/") else claim + "/"
    return changed_path.startswith(prefix)


def _intact_devline_claims(repo_root: Path) -> list[tuple[str, list[str]]]:
    """Every devline whose event chain verifies, with its claimed affected paths.

    A line whose chain does not verify is ignored: a tampered or half-written
    line must not be able to authorise feature work.
    """

    import json

    devlines_root = repo_root / DEVLINES_DIRNAME
    claims: list[tuple[str, list[str]]] = []
    if not devlines_root.is_dir():
        return claims
    for line_dir in sorted(devlines_root.iterdir()):
        if not line_dir.is_dir():
            continue
        manifest_path = line_dir / "context-pack.manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            verify_log(devlines_root, line_dir.name)
        except Exception:
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        request = manifest.get("request")
        if not isinstance(request, dict):
            continue
        affected = request.get("affected_paths") or []
        if isinstance(affected, list):
            claims.append((line_dir.name, [str(p) for p in affected]))
    return claims


def require_devline_for_changes(repo_root: Path | str, changed_paths: list[str]) -> list[str]:
    """Return one violation string per feature change lacking a covering devline.

    Empty list means the change set is authorised. A non-empty list is a hard
    gate failure: start a devline before touching that surface.
    """

    repo_root = Path(repo_root)
    surface = feature_surface_paths(changed_paths)
    if not surface:
        return []
    claims = _intact_devline_claims(repo_root)

    violations: list[str] = []
    for changed in surface:
        covered_by = next(
            (line for line, affected in claims if any(_covers(a, changed) for a in affected)),
            None,
        )
        if covered_by is None:
            violations.append(
                f"{changed} is feature code with no started devline covering it. "
                "Start one before changing it: "
                f"scripts/devline_control.py start --line <id> --affected-path <prefix>"
            )
    return violations


def enabled_rule_markers(control_dir: Path | str) -> list[dict[str, Any]]:
    """E4 — the (rule_id, test_marker) of every enabled mechanical global rule.

    The gate runs each marker so an enabled rule is enforced rather than merely
    documented. Behavior rules carry no marker and are skipped here.
    """

    # Only mechanical policies reach an enabled global rule (behavior rules take
    # the proposal path), so every enabled rule that carries a test_marker is one
    # the gate can enforce. There is no `kind` field on the persisted rule.
    rules = read_global_rules(Path(control_dir))
    markers: list[dict[str, Any]] = []
    for rule in rules.get("rules", []):
        marker = rule.get("test_marker")
        if rule.get("status") == "enabled" and isinstance(marker, str) and marker:
            markers.append({"rule_id": rule.get("rule_id"), "test_marker": marker})
    return markers
