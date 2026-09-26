"""v1.8.9 step 6 — RECODE INTO a new variable, with ranges, as a data operation."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.data_operations import DataColumnCastValidationError, _recode_into_new_column
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

AGE_GROUPS = [
    {"from": {"low": 18, "high": 29}, "to": 1},
    {"from": {"low": 30, "high": 49}, "to": 2},
    {"from": {"low": 50, "high": 120}, "to": 3},
]


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"age": [18, 29, 30, 49.5, 50, np.nan, 77], "city": ["bj", "sh", "bj", "gz", "sh", "bj", None]})


def test_ranges_are_inclusive_and_missing_stays_missing() -> None:
    frame = _frame().assign(age=[18, 29, 30, 45, 50, np.nan, 77])
    out = _recode_into_new_column(frame, {"column": "age", "output": "age_group", "rules": AGE_GROUPS})
    assert out["age_group"].tolist()[:5] == [1, 1, 2, 2, 3]
    assert np.isnan(out["age_group"].tolist()[5])
    assert pd.api.types.is_numeric_dtype(out["age_group"])
    assert out["age"].equals(frame["age"])  # the source is untouched


def test_a_value_between_ranges_is_refused_not_silently_dropped() -> None:
    with pytest.raises(DataColumnCastValidationError, match=r"1 value\(s\) of age match no rule \(e\.g\. 49\.5\)"):
        _recode_into_new_column(_frame(), {"column": "age", "output": "g", "rules": AGE_GROUPS})


def test_else_missing_and_copy_rules() -> None:
    rules = [
        {"from": {"low": 18, "high": 29}, "to": "young"},
        {"from": "missing", "to": "unknown"},
        {"from": "else", "to": "older"},
    ]
    out = _recode_into_new_column(_frame(), {"column": "age", "output": "band", "rules": rules})
    assert out["band"].tolist() == ["young", "young", "older", "older", "older", "unknown", "older"]
    copied = _recode_into_new_column(
        _frame(), {"column": "city", "output": "region", "rules": [{"from": "bj", "to": "north"}, {"from": "else", "to": "copy"}]}
    )
    assert copied["region"].tolist()[:4] == ["north", "sh", "north", "gz"]
    assert pd.isna(copied["region"].tolist()[6])


@pytest.mark.parametrize(
    ("parameters", "fragment"),
    [
        ({"column": "age", "output": "age", "rules": AGE_GROUPS}, "already exists"),
        ({"column": "nope", "output": "g", "rules": AGE_GROUPS}, "nope"),
        ({"column": "city", "output": "g", "rules": [{"from": {"low": 1, "high": 2}, "to": 1}]}, "numeric column"),
        ({"column": "age", "output": "g", "rules": [{"from": {"low": 5, "high": 1}, "to": 1}]}, "low <= high"),
        ({"column": "age", "output": "g", "rules": [{"from": "else", "to": 1}, {"from": 1, "to": 2}]}, "must come last"),
        ({"column": "age", "output": "g", "rules": []}, "non-empty"),
        ({"column": "age", "output": "g", "rules": [{"from": "x", "to": 1}, {"from": "else", "to": 1}]}, "cannot match numeric"),
    ],
)
def test_malformed_recodes_are_refused(parameters, fragment) -> None:
    with pytest.raises(DataColumnCastValidationError, match=fragment):
        _recode_into_new_column(_frame(), parameters)


def test_recode_through_preview_and_confirm_creates_a_child_dataset(tmp_path) -> None:
    rng = np.random.default_rng(3)
    frame = pd.DataFrame({"y": rng.normal(size=80), "age": rng.integers(18, 90, 80)})
    source = tmp_path / "d.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "p")
    run_id = run_workflow(project.root, [source], mode="auto", model_type="ols", y="y", x=["age"])["run_id"]
    client = TestClient(app)
    params = {"project_root": str(project.root)}
    body = {
        "source_run_id": run_id, "source_node_id": "stage:raw", "source_artifact_id": "raw_d.csv",
        "operation": "recode",
        "parameters": {"column": "age", "output": "age_group", "rules": AGE_GROUPS},
    }
    preview = client.post("/data-operations/transform/preview", params=params, json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["preview"]["output_columns"] == ["y", "age", "age_group"]
    confirmed = client.post(
        "/data-operations/transform/confirm", params=params,
        json={**body, "preview_fingerprint": preview.json()["preview"]["fingerprint"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    child = confirmed.json()["effect"]["child_node_id"]
    rows = client.get(f"/runs/{run_id}/datasets/rows", params={**params, "node_id": child, "limit": 80}).json()
    groups = {row["age"]: row["age_group"] for row in rows["rows"]}
    assert all(groups[age] == (1 if age <= 29 else 2 if age <= 49 else 3) for age in groups)
    nodes = [item["node_id"] for item in client.get(f"/runs/{run_id}/datasets", params=params).json()["datasets"]]
    assert child in nodes


def test_a_refused_preview_tells_the_user_why(tmp_path) -> None:
    frame = pd.DataFrame({"y": [1.0, 2.0, 3.0], "age": [20, 40.5, 60]})
    source = tmp_path / "d.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "why")
    run_id = run_workflow(project.root, [source], mode="auto", model_type="ols", y="y", x=["age"])["run_id"]
    response = TestClient(app).post(
        "/data-operations/transform/preview",
        params={"project_root": str(project.root)},
        json={
            "source_run_id": run_id, "source_node_id": "stage:raw", "source_artifact_id": "raw_d.csv",
            "operation": "recode",
            "parameters": {"column": "age", "output": "g", "rules": [{"from": {"low": 0, "high": 40}, "to": 1}, {"from": {"low": 41, "high": 99}, "to": 2}]},
        },
    )
    assert response.status_code == 422
    assert "1 value(s) of age match no rule (e.g. 40.5)" in response.json()["error"]["message"]
