"""Summaries: bounded read-only context projection. (diagnostics)."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import Any
from ...artifacts import sha256_file
from ..context_compiler import read_context_artifact_index, resolve_registered_artifact
from .summaries_public_values import (
    _PUBLIC_RESULT_DENIED_KEYS,
    _PublicResultBudget,
)


def _bounded_node(node: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "id",
        "kind",
        "stage",
        "display_label",
        "parent_stage_id",
        "branch_id",
        "trust",
    )
    return {key: node[key] for key in allowed if key in node}


def _resolve_verified_registered_artifact(
    run_root: Path,
    *,
    artifact_id: str,
    expected_type: str,
) -> tuple[dict[str, Any], str] | None:
    """Resolve a known artifact id and verify its registered content digest."""

    resolved = resolve_registered_artifact(run_root, artifact_id)
    if resolved is None:
        return None
    artifact_type, registered_sha256, payload = resolved
    if artifact_type != expected_type or not isinstance(registered_sha256, str):
        return None
    if re.fullmatch(r"[0-9a-f]{64}", registered_sha256) is None:
        return None
    try:
        index = read_context_artifact_index(run_root)
    except (OSError, ValueError):
        return None
    entries = index.get("artifacts") if isinstance(index, dict) else None
    entry = next(
        (
            item
            for item in entries or ()
            if isinstance(item, dict) and item.get("artifact_id") == artifact_id
        ),
        None,
    )
    relative_path = entry.get("path") if isinstance(entry, dict) else None
    if not isinstance(relative_path, str) or Path(relative_path).is_absolute():
        return None
    try:
        resolved_root = run_root.resolve()
        path = (run_root / relative_path).resolve()
        path.relative_to(resolved_root)
        if not path.is_file() or sha256_file(path) != registered_sha256:
            return None
    except (OSError, ValueError):
        return None
    return payload, registered_sha256


def _bounded_diagnostics(preview: dict[str, Any], *, persisted=()) -> tuple[dict[str, Any], list[str]]:
    allowed = (
        "available",
        "preview_contract_version",
        "source_schema_version",
        "preview_status",
        "contract_warnings",
        "run_lifecycle_status",
        "run_status",
        "trust_label",
        "trust_counts",
        "primary_reasons",
        "diagnostic_highlights",
        "interpretation_restrictions",
        "recommended_actions",
    )
    diagnostics = {key: preview[key] for key in allowed if key in preview}
    omitted_sections = ["artifact_manifest", "coefficient_risk"]

    # These are existing producer scalars, not a new diagnostic or a reliability
    # verdict. Never project a list: an unfamiliar diagnostic may contain a row
    # array under an unfamiliar field name. Risk summaries precede bulky detail.
    budget = _PublicResultBudget(remaining_items=64, remaining_string_characters=1024,
                                 remaining_key_characters=800)

    def small_summary(value, depth=0):
        if not isinstance(value, dict):
            budget.omitted_items += 1
            return {}
        result = {}
        priority = {"cooks_distance", "influence", "weak_instruments", "status", "severity", "error",
                    "n_high", "n_severe", "threshold", "leverage_max"}
        items = sorted(value.items(), key=lambda item: item[0] not in priority)
        for index, (key, item) in enumerate(items):
            if len(result) >= 24 or budget.remaining_items <= 0 or budget.remaining_key_characters <= 0:
                budget.omitted_items += len(items) - index
                break
            if (not isinstance(key, str) or len(key) > 64 or len(key) > budget.remaining_key_characters
                    or isinstance(item, (list, tuple)) or key.lower() in _PUBLIC_RESULT_DENIED_KEYS
                    or key.lower().startswith("raw_")):
                budget.omitted_items += 1
                continue
            if isinstance(item, dict):
                if depth >= 4:
                    budget.omitted_items += 1
                    continue
                result[key] = small_summary(item, depth + 1)
            elif isinstance(item, str):
                limit = min(300, budget.remaining_string_characters)
                if not limit:
                    budget.omitted_items += 1
                    continue
                result[key] = item[:limit]
                budget.remaining_string_characters -= len(result[key])
                budget.omitted_items += int(len(item) > limit)
            elif item is None or isinstance(item, (bool, int)) or isinstance(item, float) and math.isfinite(item):
                result[key] = item
            else:
                budget.omitted_items += 1
                continue
            budget.remaining_items -= 1
            budget.remaining_key_characters -= len(key)
        return result

    if persisted:
        diagnostics["persisted_diagnostics"] = []
        for evidence in persisted[:2]:
            public = {key: value for key, value in evidence.items() if key != "summary"}
            if "summary" in evidence:
                before = budget.omitted_items
                public["summary"] = small_summary(evidence["summary"])
                public["omitted_field_count"] = budget.omitted_items - before
            diagnostics["persisted_diagnostics"].append(public)

    identity = preview.get("model_identity")
    if isinstance(identity, dict):
        diagnostics["model_identity"] = {
            key: identity[key]
            for key in (
                "primary_model_id",
                "model_label",
                "model_type",
                "y_variable",
                "n_observations",
                "x_variable_count",
            )
            if key in identity
        }

    for key, limit in (
        ("contract_warnings", 8),
        ("diagnostic_highlights", 8),
        ("interpretation_restrictions", 8),
    ):
        values = diagnostics.get(key)
        if not isinstance(values, list) or len(values) <= limit:
            continue
        diagnostics[key] = values[:limit]
        omitted_sections.append(key)
        diagnostics.setdefault("omitted_item_counts", {})[key] = len(values) - limit

    return diagnostics, omitted_sections


@dataclass(frozen=True)
class RecipeResultProjection:
    """A family whose public result comes from its recipe contract.

    Structurally different from `FamilyEvidenceSpec`: this path builds the
    projection from a registered artifact via the family's recipe contract, so
    only the artifact id and the unavailable reason vary. Declaring those two
    keeps the entry condition a lookup rather than a family name in an `if`.
    """

    artifact_id: str
    unavailable_reason_code: str


RECIPE_RESULT_PROJECTIONS: dict[str, RecipeResultProjection] = {
    "time_series.ets": RecipeResultProjection(
        artifact_id="ets_1",
        unavailable_reason_code="ETS_PUBLIC_RESULT_UNAVAILABLE",
    ),
}
