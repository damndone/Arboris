"""v1.8.9 step 6 — Data view: browse dataset nodes, edit variable metadata."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.projects import create_project
from workbench.tabular_io import write_statistical

client = TestClient(app)

LABELS = {
    "variable_labels": {"educ": "受教育年限", "region": "地区"},
    "value_labels": {"region": {"1": "北方", "2": "南方", "3": "西部"}},
    "measurement_level": {"region": "nominal"},
    "user_missing_values": {"educ": [-99]},
}


def _wait(project_root: Path, run_id: str) -> dict:
    for _ in range(400):
        detail = client.get(f"/runs/{run_id}", params={"project_root": str(project_root)}).json()
        if detail.get("status") in {"completed", "failed", "blocked"}:
            return detail
        time.sleep(0.1)
    raise AssertionError("run did not finish")


@pytest.fixture(scope="module")
def labelled(tmp_path_factory) -> tuple[Path, str, pd.DataFrame]:
    tmp_path = tmp_path_factory.mktemp("data-view")
    rng = np.random.default_rng(12)
    n = 150
    frame = pd.DataFrame(
        {
            "wage": rng.normal(20, 4, n).round(3),
            "educ": rng.integers(9, 20, n).astype(float),
            "region": rng.integers(1, 4, n).astype(float),
            "hours": rng.normal(40, 5, n).round(1),
        }
    )
    frame.loc[:4, "educ"] = -99
    frame.loc[10:12, "hours"] = np.nan
    path = tmp_path / "survey.sav"
    write_statistical(frame, LABELS, path, "sav")
    project = create_project(tmp_path, "p")
    created = client.post(
        "/runs",
        data={"project_root": str(project.root), "mode": "auto", "model_type": "ols", "y": "wage", "x": "educ"},
        files={"file": ("survey.sav", io.BytesIO(path.read_bytes()), "application/octet-stream")},
    )
    run_id = created.json()["run_id"]
    assert _wait(project.root, run_id)["status"] == "completed"
    return project.root, run_id, frame


def _get(project_root: Path, path: str, **params) -> dict:
    response = client.get(path, params={"project_root": str(project_root), **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_the_run_lists_its_dataset_nodes(labelled) -> None:
    root, run_id, _frame = labelled
    datasets = _get(root, f"/runs/{run_id}/datasets")["datasets"]
    assert [item["node_id"] for item in datasets][:2] == ["stage:raw", "stage:cleaned"]


def test_rows_page_with_raw_codes_and_nulls(labelled) -> None:
    root, run_id, frame = labelled
    page = _get(root, f"/runs/{run_id}/datasets/rows", node_id="stage:raw", offset=0, limit=20)
    assert page["total_rows"] == len(frame)
    assert page["columns"] == ["wage", "educ", "region", "hours"]
    assert len(page["rows"]) == 20 and page["row_numbers"][:3] == [1, 2, 3]
    assert page["rows"][0]["educ"] == -99  # the grid shows what the file holds
    assert page["rows"][10]["hours"] is None


def test_sorting_is_a_view_and_keeps_row_numbers(labelled) -> None:
    root, run_id, frame = labelled
    page = _get(root, f"/runs/{run_id}/datasets/rows", node_id="stage:raw", limit=5, sort_by="wage", descending=True)
    assert [row["wage"] for row in page["rows"]] == sorted(frame["wage"], reverse=True)[:5]
    top = int(frame["wage"].idxmax()) + 1
    assert page["row_numbers"][0] == top
    unsorted = _get(root, f"/runs/{run_id}/datasets/rows", node_id="stage:raw", limit=1)
    assert unsorted["row_numbers"] == [1]


def test_variables_carry_metadata_and_exclude_declared_codes_from_statistics(labelled) -> None:
    root, run_id, frame = labelled
    variables = {v["name"]: v for v in _get(root, f"/runs/{run_id}/datasets/variables", node_id="stage:raw")["variables"]}
    educ = variables["educ"]
    assert educ["variable_label"] == "受教育年限"
    assert educ["user_missing_values"] == [-99]
    assert educ["declared_missing_matches"] == 5
    assert educ["min"] >= 9  # -99 is not a valid education value
    assert educ["mean"] == pytest.approx(frame.loc[frame.educ != -99, "educ"].mean())
    region = variables["region"]
    assert region["value_labels"] == {"1": "北方", "2": "南方", "3": "西部"}
    assert region["measurement_level"] == "nominal"
    assert sum(item["count"] for item in region["values"]) == len(frame)
    assert variables["hours"]["missing"] == 3


@pytest.mark.parametrize(
    ("params", "fragment"),
    [
        ({"node_id": "stage:raw", "limit": 0}, "limit"),
        ({"node_id": "stage:raw", "limit": 501}, "limit"),
        ({"node_id": "stage:raw", "sort_by": "nope"}, "unknown column"),
        ({"node_id": "model:ols_1"}, "dataset_stage"),
    ],
)
def test_bad_page_requests_are_refused(labelled, params, fragment) -> None:
    root, run_id, _frame = labelled
    response = client.get(f"/runs/{run_id}/datasets/rows", params={"project_root": str(root), **params})
    assert response.status_code == 422
    assert fragment in response.json()["error"]["message"]


def test_a_metadata_edit_becomes_a_new_run_and_keeps_other_declarations(labelled) -> None:
    root, run_id, _frame = labelled
    response = client.post(
        f"/runs/{run_id}/metadata",
        params={"project_root": str(root)},
        json={
            "labels": {
                "value_labels": {"region": {"1": "North", "2": "South", "3": "West"}},
                # hours is not in the model: legal in the Variable view.
                "measurement_level": {"hours": "scale"},
                "user_missing_values": {"hours": [0]},
            }
        },
    )
    assert response.status_code == 200, response.text
    child = response.json()["run_id"]
    assert _wait(root, child)["status"] == "completed"
    labels = json.loads((root / "runs" / child / "run_inputs.json").read_text())["form"]["labels"]
    assert labels["value_labels"]["region"]["2"] == "South"
    assert labels["measurement_level"] == {"region": "nominal", "hours": "scale"}
    assert labels["user_missing_values"] == {"educ": [-99], "hours": [0]}
    assert labels["variable_labels"]["educ"] == "受教育年限"

    removed = client.post(
        f"/runs/{child}/metadata",
        params={"project_root": str(root)},
        json={"labels": {"user_missing_values": {"hours": None}, "variable_labels": {"region": None}}},
    )
    assert removed.status_code == 200, removed.text
    grandchild = removed.json()["run_id"]
    assert _wait(root, grandchild)["status"] == "completed"
    labels = json.loads((root / "runs" / grandchild / "run_inputs.json").read_text())["form"]["labels"]
    assert labels["user_missing_values"] == {"educ": [-99]}
    assert "region" not in labels["variable_labels"]


@pytest.mark.parametrize(
    ("labels", "status"),
    [
        ({"colour": {"x": "y"}}, 422),
        ({"user_missing_values": {"not_a_column": [1]}}, 422),
        ({"measurement_level": {"not_a_column": "nominal"}}, 422),
    ],
)
def test_invalid_metadata_edits_are_refused(labelled, labels, status) -> None:
    root, run_id, _frame = labelled
    response = client.post(f"/runs/{run_id}/metadata", params={"project_root": str(root)}, json={"labels": labels})
    assert response.status_code == status, response.text
