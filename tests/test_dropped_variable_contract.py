from __future__ import annotations

import pytest

from pathlib import Path

import pandas as pd

from workbench.orchestrator import _check_dropped_variables


def test_structured_did_covariate_metadata_prevents_false_dropped_status(tmp_path: Path) -> None:
    frame = pd.DataFrame({"y": [1.0, 2.0, 3.0], "policy_intensity": [0.1, 0.2, 0.3]})
    issues: list[dict] = []
    dropped = _check_dropped_variables(
        ["policy_intensity"],
        [("cs_did_1", {"model_type": "cs_did", "coefficients": {"ATT": {"estimate": 1.0}}})],
        frame,
        issues,
        tmp_path,
        model_declared_variables={"policy_intensity"},
    )
    assert dropped == []
    assert issues == []


def test_missing_structured_did_covariate_is_still_reported_as_dropped(tmp_path: Path) -> None:
    frame = pd.DataFrame({"y": [1.0, 2.0, 3.0], "policy_intensity": [0.1, 0.2, 0.3]})
    dropped = _check_dropped_variables(
        ["policy_intensity"],
        [("cs_did_1", {"model_type": "cs_did", "coefficients": {"ATT": {"estimate": 1.0}}})],
        frame,
        [],
        tmp_path,
        model_declared_variables=set(),
    )
    assert dropped[0]["reason"] == "perfect_collinearity"


@pytest.mark.parametrize("column", ["region", "o'brien", 'say "hi"', "back\\slash", "both'\"quotes"])
def test_a_categorical_column_is_found_whatever_its_name_quotes(tmp_path, column):
    """The term is the estimator's own quoting (formula_terms.quote_column), so
    a categorical whose name needs escaping is not reported as dropped."""
    import pandas as pd

    from workbench.formula_terms import quote_column
    from workbench.orchestrator._column_checks import _check_dropped_variables

    frame = pd.DataFrame({column: ["a", "b", "a", "b"], "y": [1.0, 2.0, 3.0, 4.0]})
    coefficients = {"Intercept": {}, f"C({quote_column(column)})[T.b]": {}}
    dropped = _check_dropped_variables(
        [column], [("ols_1", {"coefficients": coefficients})], frame, [], tmp_path, categorical_vars={column},
    )
    assert dropped == []
