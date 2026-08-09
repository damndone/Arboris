from __future__ import annotations

import json

import pytest

from workbench.engine.packs.multiple_comparisons import (
    MultipleComparisonsPackError,
    run_games_howell,
    run_scheffe,
)


GROUPS = {
    "control": [1.0, 1.2, 0.9, 1.1, 1.0, 1.1],
    "treatment_a": [2.0, 2.1, 1.9, 2.2, 2.0],
    "treatment_b": [3.0, 3.5, 2.7, 3.1],
}


def test_scheffe_returns_pairwise_family_and_explicit_f_distribution() -> None:
    result = run_scheffe(GROUPS, alpha=0.05)

    assert result["operation_id"] == "multiple_comparisons.scheffe"
    assert result["status"] == "completed"
    payload = result["result"]
    assert payload["method"] == "scheffe"
    assert payload["family"] == "all_group_pairs"
    assert payload["group_count"] == 3
    assert payload["degrees_of_freedom_within"] == sum(map(len, GROUPS.values())) - 3
    assert len(payload["comparisons"]) == 3
    assert all(row["distribution"] == "F" for row in payload["comparisons"])
    assert all(0.0 <= row["p_value"] <= 1.0 for row in payload["comparisons"])
    json.dumps(result, allow_nan=False)


def test_games_howell_handles_unequal_sizes_and_variances_without_tukey_aliasing() -> None:
    result = run_games_howell(GROUPS, alpha=0.10)

    assert result["operation_id"] == "multiple_comparisons.games_howell"
    payload = result["result"]
    assert payload["method"] == "games_howell"
    assert payload["critical_distribution"] == "studentized_range"
    assert len(payload["comparisons"]) == 3
    assert all(row["distribution"] == "studentized_range" for row in payload["comparisons"])
    assert all(row["degrees_of_freedom"] > 0.0 for row in payload["comparisons"])
    assert any(row["p_value"] < 0.001 for row in payload["comparisons"])
    assert any(
        row["p_value"] != row["welch_p_value"]
        for row in payload["comparisons"]
    )


def test_games_howell_makes_small_welch_df_fallback_explicit() -> None:
    result = run_games_howell({"wide": [0.0, 10.0], "narrow": [0.0, 1.0]})

    comparison = result["result"]["comparisons"][0]
    assert comparison["degrees_of_freedom"] < 2.0
    assert comparison["p_value_backend"] == "scipy_studentized_range_df_lt_2"
    assert 0.0 <= comparison["p_value"] <= 1.0


@pytest.mark.parametrize("method", [run_scheffe, run_games_howell])
def test_multiple_comparisons_rejects_invalid_input_and_constant_gh_group(method) -> None:
    with pytest.raises(MultipleComparisonsPackError):
        method({"only": [1.0, 2.0]})
    with pytest.raises(MultipleComparisonsPackError):
        method({"a": [1.0, 1.0], "b": [2.0, 3.0]})
    with pytest.raises(MultipleComparisonsPackError):
        method(GROUPS, alpha=1.0)


def test_multiple_comparisons_is_deterministic_and_rejects_unsafe_payloads() -> None:
    first = run_scheffe(GROUPS)
    second = run_scheffe(dict(reversed(list(GROUPS.items()))))
    assert first == second
    serialized = json.dumps(first, allow_nan=False)
    assert '"raw_rows"' not in serialized
    assert '"observations"' not in serialized
