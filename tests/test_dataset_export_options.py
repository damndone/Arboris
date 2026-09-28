"""v1.8.9 trust round — export what the user chooses, the way Stata lets them."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyreadstat
import pytest
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.orchestrator import run_workflow
from workbench.projects import create_project
from workbench.services.data_export import export_dataset, preview_export
from workbench.tabular_io import StatisticalFileError

LABELS = {
    "variable_labels": {"educ": "受教育年限", "region": "地区"},
    "value_labels": {"region": {"1": "北方", "2": "南方", "3": "西部"}},
    "measurement_level": {"region": "nominal"},
    "user_missing_values": {"educ": [-99]},
}


@pytest.fixture(scope="module")
def labelled(tmp_path_factory) -> tuple[Path, str]:
    tmp_path = tmp_path_factory.mktemp("export-options")
    rng = np.random.default_rng(4)
    frame = pd.DataFrame(
        {
            "wage": rng.normal(20, 4, 50).round(2),
            "educ": rng.integers(9, 20, 50).astype(float),
            "region": rng.integers(1, 4, 50),
        }
    )
    frame.loc[:2, "educ"] = -99
    source = tmp_path / "w.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "p")
    outcome = run_workflow(project.root, [source], mode="auto", model_type="ols", y="wage", x=["educ"], labels=LABELS)
    assert outcome["status"] == "completed", outcome
    return project.root, outcome["run_id"]


def _file(root: Path, run_id: str, exported: dict) -> Path:
    [path] = (root / "runs" / run_id / "exports" / "data").rglob(exported["filename"])
    return path


def test_variables_order_and_rows_are_the_users_choice(labelled) -> None:
    root, run_id = labelled
    exported = export_dataset(root, run_id, "stage:raw", {
        "format": "dta", "columns": ["region", "wage"],
        "filters": [{"column": "wage", "op": "ge", "value": 20}],
    })
    data, meta = pyreadstat.read_dta(str(_file(root, run_id, exported)))
    assert list(data.columns) == ["region", "wage"]
    assert (data["wage"] >= 20).all() and exported["report"]["rows"] == len(data) < 50
    assert meta.variable_value_labels["region"] == {1: "北方", 2: "南方", 3: "西部"}


@pytest.mark.parametrize(("version", "release"), [(13, b"117"), (14, b"118"), (15, b"119")])
def test_the_stata_version_is_the_one_asked_for(labelled, version: int, release: bytes) -> None:
    root, run_id = labelled
    exported = export_dataset(root, run_id, "stage:raw", {"format": "dta", "dta_version": version, "columns": ["wage"]})
    assert release in _file(root, run_id, exported).read_bytes()[:60]


def test_stata_13_refuses_names_and_labels_it_cannot_hold(labelled) -> None:
    root, run_id = labelled
    preview = preview_export(root, run_id, "stage:raw", {"format": "dta", "dta_version": 13})
    assert any("Stata 13" in note["message"] for note in preview["notes"])
    with pytest.raises(StatisticalFileError, match="Stata 14-18"):
        export_dataset(root, run_id, "stage:raw", {"format": "dta", "dta_version": 13})


def test_the_default_dta_is_readable_by_stata_14_to_18(labelled) -> None:
    root, run_id = labelled
    exported = export_dataset(root, run_id, "stage:raw", "dta")
    assert b"118" in _file(root, run_id, exported).read_bytes()[:60]


def test_value_labels_as_text_or_not_at_all(labelled) -> None:
    root, run_id = labelled
    as_text = export_dataset(root, run_id, "stage:raw", {"format": "dta", "columns": ["region"], "value_labels": "strings"})
    data, meta = pyreadstat.read_dta(str(_file(root, run_id, as_text)))
    assert set(data["region"]) <= {"北方", "南方", "西部"} and not meta.variable_value_labels
    codes = export_dataset(root, run_id, "stage:raw", {"format": "sav", "columns": ["region"], "value_labels": "none"})
    data, meta = pyreadstat.read_sav(str(_file(root, run_id, codes)))
    assert not meta.variable_value_labels and set(data["region"]) <= {1, 2, 3}
    assert any(note["field"] == "value_labels" and "as chosen" in note["message"] for note in codes["report"]["notes"])


def test_missing_codes_become_missing_or_stay_as_values(labelled) -> None:
    root, run_id = labelled
    missing = export_dataset(root, run_id, "stage:raw", {"format": "dta", "columns": ["educ"]})
    kept = export_dataset(root, run_id, "stage:raw", {"format": "dta", "columns": ["educ"], "missing_codes": "keep_codes"})
    missing_data, _ = pyreadstat.read_dta(str(_file(root, run_id, missing)))
    kept_data, _ = pyreadstat.read_dta(str(_file(root, run_id, kept)))
    assert missing_data["educ"].isna().sum() == 3 and (missing_data["educ"] == -99).sum() == 0
    assert (kept_data["educ"] == -99).sum() == 3
    assert any("kept as ordinary values" in note["message"] for note in kept["report"]["notes"])


def test_csv_and_excel_say_what_they_cannot_hold(labelled) -> None:
    root, run_id = labelled
    csv = export_dataset(root, run_id, "stage:raw", {"format": "csv", "filename": "工资数据"})
    assert csv["filename"] == "工资数据.csv"
    data = pd.read_csv(_file(root, run_id, csv))
    assert set(data["region"]) <= {"北方", "南方", "西部"}  # labels replace codes: CSV has no label sets
    fields = {note["field"] for note in csv["report"]["notes"]}
    assert {"variable_labels", "value_labels", "measurement_level", "user_missing_values"} <= fields
    xlsx = export_dataset(root, run_id, "stage:raw", {"format": "xlsx", "columns": ["wage", "educ"]})
    assert list(pd.read_excel(_file(root, run_id, xlsx)).columns) == ["wage", "educ"]


def test_the_preview_shows_the_file_without_writing_it(labelled) -> None:
    root, run_id = labelled
    exports = root / "runs" / run_id / "exports"
    before = sorted(exports.rglob("*")) if exports.exists() else []
    preview = preview_export(root, run_id, "stage:raw", {
        "format": "sav", "columns": ["educ", "region"], "filters": [{"column": "region", "op": "eq", "value": 2}],
    })
    assert preview["column_names"] == ["educ", "region"]
    assert 0 < preview["rows"] < 50 and len(preview["sample"]) == min(5, preview["rows"])
    assert all(row["region"] == 2 for row in preview["sample"])
    assert preview["source_rows"] == 50
    assert (sorted(exports.rglob("*")) if exports.exists() else []) == before


def test_the_http_routes_preview_and_export_with_options(labelled) -> None:
    root, run_id = labelled
    client = TestClient(app)
    params = {"project_root": str(root)}
    body = {"node_id": "stage:raw", "format": "dta", "columns": ["wage"], "filename": "wages-only"}
    preview = client.post(f"/runs/{run_id}/datasets/export/preview", params=params, json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["filename"] == "wages-only.dta"
    exported = client.post(f"/runs/{run_id}/datasets/export", params=params, json=body)
    assert exported.status_code == 200, exported.text
    assert exported.json()["filename"] == "wages-only.dta"
    refused = client.post(f"/runs/{run_id}/datasets/export/preview", params=params,
                          json={**body, "columns": ["salary"]})
    assert refused.status_code == 422 and "salary" in refused.json()["error"]["message"]


def test_export_notes_write_missing_codes_as_a_person_would() -> None:
    import pandas as pd

    from workbench.tabular_io import prepare_export

    frame = pd.DataFrame({"age": [30.0, -100.0, -98.0, 45.0], "happy": [1.0, 9.0, 2.0, 1.0]})
    labels = {"user_missing_values": {"age": [{"low": -100, "high": -10}], "happy": [9]}}
    notes = [note["message"] for note in prepare_export(frame, labels, "dta").report.notes]

    assert "2 value(s) matching -100 to -10 written as missing: Stata has no user-missing codes" in notes
    assert "1 value(s) matching 9 written as missing: Stata has no user-missing codes" in notes
    assert not any("{" in note for note in notes)
