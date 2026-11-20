"""Summaries: bounded read-only context projection. (public values)."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any


_MAX_GROUPS_PROJECTED = 12


def _bounded_test_by_group(block: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "column": block.get("column"),
        "estimated_groups": block.get("estimated_groups"),
        "groups": [
            {key: group.get(key) for key in ("key", "nobs", "status", "reason") if group.get(key) is not None}
            for group in (block.get("groups") or [])[:_MAX_GROUPS_PROJECTED] if isinstance(group, Mapping)
        ],
        "adjustment_across_groups": block.get("adjustment_across_groups"),
        "comparing_groups": block.get("comparing_groups"),
    }


_PUBLIC_RESULT_DENIED_KEYS = frozenset(
    {
        "_omitted_item_count",
        "data",
        "dataset",
        "file",
        "filename",
        "path",
        "raw_rows",
        "rows",
        "records",
        "rendered_path",
        "residuals",
        "source_rows",
        "row_ids",
        "fitted_values",
        "values",
    }
)


@dataclass
class _PublicResultBudget:
    """One aggregate budget for a public artifact projection."""

    remaining_items: int = 96
    remaining_string_characters: int = 2048
    remaining_key_characters: int = 1600
    omitted_items: int = 0


def _bounded_public_result_value(
    value: Any,
    *,
    depth: int = 0,
    budget: _PublicResultBudget | None = None,
    max_depth: int = 4,
) -> Any:
    """Keep a numerical result compact and reject row-shaped/raw payload fields."""

    budget = budget or _PublicResultBudget()
    if budget.remaining_items <= 0:
        budget.omitted_items += 1
        return "[omitted: result item budget]"
    budget.remaining_items -= 1
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        limit = min(300, budget.remaining_string_characters)
        if limit <= 0:
            budget.omitted_items += 1
            return "[omitted: result string budget]"
        # Charge what is kept, not the cap: charging the cap let seven short
        # labels exhaust the budget and blank out every later test name.
        budget.remaining_string_characters -= min(len(value), limit)
        if len(value) > limit:
            budget.omitted_items += 1
        return value[:limit]
    if depth >= max_depth:
        budget.omitted_items += 1
        return "[omitted: nesting limit]"
    if isinstance(value, list):
        bounded_list: list[Any] = []
        for item in value:
            if len(bounded_list) >= 16 or budget.remaining_items <= 0:
                budget.omitted_items += 1
                break
            if isinstance(item, (dict, list, str, int, float, bool)) or item is None:
                bounded_list.append(
                    _bounded_public_result_value(item, depth=depth + 1, budget=budget, max_depth=max_depth)
                )
        return bounded_list
    if not isinstance(value, dict):
        budget.omitted_items += 1
        return "[omitted: unsupported value]"
    bounded: dict[str, Any] = {}
    omissions_at_entry = budget.omitted_items
    for key in sorted(value):
        if not isinstance(key, str):
            continue
        normalized = key.lower()
        if normalized in _PUBLIC_RESULT_DENIED_KEYS or normalized.startswith("raw_"):
            continue
        if (
            len(bounded) >= 24
            or budget.remaining_items <= 0
            or budget.remaining_key_characters <= 0
        ):
            budget.omitted_items += 1
            break
        key_limit = min(64, budget.remaining_key_characters)
        bounded_key = key[:key_limit]
        budget.remaining_key_characters -= len(bounded_key)
        if len(key) > key_limit:
            budget.omitted_items += 1
        if bounded_key in bounded:
            budget.omitted_items += 1
            continue
        bounded[bounded_key] = _bounded_public_result_value(
            value[key], depth=depth + 1, budget=budget, max_depth=max_depth
        )
    omitted_here = budget.omitted_items - omissions_at_entry
    if omitted_here:
        bounded["_omitted_item_count"] = omitted_here
    return bounded
