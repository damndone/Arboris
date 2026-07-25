from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from tests.test_data_column_cast import _source_project
from workbench.app import app
from workbench.statistical_exploration import ExplorationSpec, execute_exploration


def test_scatter_result_drops_only_rows_missing_either_plot_value() -> None:
    frame = pd.DataFrame({"pfl": [1.0, 2.0, None], "spending": [10.0, None, 30.0]})
    result = execute_exploration(
        frame,
        ExplorationSpec(
            operation="scatter",
            selected_columns=("pfl", "spending"),
            options={"x_column": "pfl", "y_column": "spending"},
        ),
    )

    assert result["plot"]["x_column"] == "pfl"
    assert result["plot"]["y_column"] == "spending"
    assert result["plot"]["plotted_row_count"] == 1


def test_scatter_confirm_creates_one_registered_figure_artifact(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"pfl": [1.0, 2.0, None], "spending": [10.0, None, 30.0]}),
    )
    request = {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "operation": "scatter",
        "selected_columns": ["pfl", "spending"],
        "filters": [],
        "options": {"x_column": "pfl", "y_column": "spending"},
    }
    with TestClient(app) as client:
        preview = client.post(
            "/statistical-explorations/preview",
            params={"project_root": str(project)},
            json=request,
        ).json()["preview"]
        body = {**request, "preview_fingerprint": preview["fingerprint"]}
        first = client.post(
            "/statistical-explorations/confirm",
            params={"project_root": str(project)},
            json=body,
        )
        second = client.post(
            "/statistical-explorations/confirm",
            params={"project_root": str(project)},
            json=body,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["plot"] == second.json()["plot"]
    plot = first.json()["plot"]
    assert plot["plotted_row_count"] == 1
    assert (project / "runs" / run_id / plot["path"]).is_file()
    records = json.loads((project / "runs" / run_id / "artifacts_index.json").read_text())["artifacts"]
    figures = [item for item in records if item["artifact_id"] == plot["artifact_id"]]
    assert len(figures) == 1
    assert figures[0]["artifact_type"] == "figure"
