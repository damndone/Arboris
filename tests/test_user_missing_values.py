"""v1.8.9 step 4 — user-declared missing-value codes (SPSS "Missing Values").

Survey data routinely encodes "no answer" as -99 or 999. Without a way to
declare that, the code enters the model as a real value and every estimate that
touches the column is wrong while the run completes normally.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project
from workbench.services.run_service import _normalize_labels


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(20260925)
    n = 240
    educ = rng.integers(9, 20, n).astype(float)
    wage = 5 + 1.2 * educ + rng.normal(0, 2, n)
    frame = pd.DataFrame({"wage": wage.round(3), "educ": educ, "hours": rng.normal(40, 5, n).round(2)})
    frame.loc[:7, "educ"] = -99
    frame.loc[8:10, "hours"] = 999
    return frame


def _run(tmp_path: Path, name: str, frame: pd.DataFrame, **kwargs) -> Path:
    source = tmp_path / f"{name}.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, name)
    outcome = run_workflow(
        project.root, [source], mode="auto", model_type="ols", y="wage", x=["educ", "hours"], **kwargs
    )
    assert outcome["status"] == "completed", outcome
    return project.root / "runs" / outcome["run_id"]


def _ols(run_root: Path) -> dict:
    return read_json(run_root / "model_results" / "ols_1.json")


def _estimate(result: dict, term: str) -> float:
    coefficients = result["coefficients"]
    if isinstance(coefficients, dict):
        return float(coefficients[term]["estimate"])
    return float(next(item for item in coefficients if item["term"] == term)["estimate"])


def test_declared_codes_are_treated_as_missing_and_match_blank_cells(tmp_path) -> None:
    frame = _frame()
    declared = _run(
        tmp_path,
        "declared",
        frame,
        labels={"user_missing_values": {"educ": [-99], "hours": [999]}},
    )
    blanked = frame.replace({"educ": {-99: np.nan}, "hours": {999: np.nan}})
    reference = _run(tmp_path, "reference", blanked)

    assert _ols(declared)["nobs"] == _ols(reference)["nobs"] < len(frame)
    assert _estimate(_ols(declared), "educ") == pytest.approx(_estimate(_ols(reference), "educ"), rel=1e-12)


def test_the_run_says_how_many_values_each_code_removed(tmp_path) -> None:
    run_root = _run(
        tmp_path,
        "reported",
        _frame(),
        labels={"user_missing_values": {"educ": [-99, {"low": 900, "high": 999}], "hours": [999]}},
    )

    applied = read_json(run_root / "measurement" / "user_missing.json")
    assert applied["columns"]["educ"]["converted"] == 8
    assert applied["columns"]["hours"]["converted"] == 3
    issues = read_json(run_root / "errors.json")["issues"]
    notices = {issue["variables"][0]: issue for issue in issues if issue["code"] == "USER_MISSING_APPLIED"}
    assert notices["educ"]["evidence"]["converted"] == 8
    assert notices["hours"]["evidence"]["converted"] == 3


def test_a_run_without_declarations_is_unchanged(tmp_path) -> None:
    run_root = _run(tmp_path, "plain", _frame())

    assert not (run_root / "measurement" / "user_missing.json").exists()
    issues = read_json(run_root / "errors.json")["issues"]
    assert not [issue for issue in issues if issue["code"] == "USER_MISSING_APPLIED"]
    # Undeclared, the code is data: the model sees all rows.
    assert _ols(run_root)["nobs"] == len(_frame())


def test_a_declaration_for_an_absent_column_fails_the_run(tmp_path) -> None:
    source = tmp_path / "absent.csv"
    _frame().to_csv(source, index=False)
    project = create_project(tmp_path, "absent")
    with pytest.raises(ValueError, match="not_a_column"):
        run_workflow(
            project.root,
            [source],
            mode="auto",
            model_type="ols",
            y="wage",
            x=["educ"],
            labels={"user_missing_values": {"not_a_column": [-99]}},
        )


@pytest.mark.parametrize(
    "declaration",
    [
        {"educ": -99},
        {"educ": []},
        {"educ": [float("nan")]},
        {"educ": [{"low": 5}]},
        {"educ": [{"low": 9, "high": 1}]},
        {"educ": [[1, 2]]},
        {"": [1]},
    ],
)
def test_malformed_declarations_are_refused(declaration) -> None:
    with pytest.raises(ValueError, match="user_missing_values"):
        _normalize_labels({"user_missing_values": declaration})


def test_declarations_round_trip_through_normalization() -> None:
    normalized = _normalize_labels(
        {"user_missing_values": {"educ": [-99, "NA", {"low": 900, "high": 999}]}}
    )
    assert normalized["user_missing_values"] == {
        "educ": [-99, "NA", {"low": 900, "high": 999}]
    }
    assert json.loads(json.dumps(normalized)) == normalized
