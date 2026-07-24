from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from tests.test_data_column_cast import _source_project
from workbench.app import app
from workbench.lineage.pipeline_drafts import PipelineDraftStore
from workbench.services.draft_service import validate_exploration_context


def test_ols_context_creates_prepopulated_draft_without_running_model(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame(
            {
                "year": [1998, 1998, 2002],
                "outcome": [10.0, 12.0, 20.0],
                "predictor": [1.0, 2.0, 4.0],
            }
        ),
    )
    request = {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "operation": "summarize",
        "selected_columns": ["outcome", "predictor"],
        "filters": [{"column": "year", "operator": "eq", "value": 1998}],
    }
    ols_request = {
        **request,
        "outcome_column": "outcome",
        "predictor_columns": ["predictor"],
    }

    with TestClient(app) as client:
        preview_response = client.post(
            "/statistical-explorations/preview",
            params={"project_root": str(project)},
            json=request,
        )
        assert preview_response.status_code == 200, preview_response.text
        preview = preview_response.json()["preview"]
        spec = preview_response.json()["spec"]
        response = client.post(
            "/statistical-explorations/ols-context",
            params={"project_root": str(project)},
            json={**ols_request, "preview_fingerprint": preview["fingerprint"]},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "draft_created"
    assert body["draft"]["graph"]["nodes"][-1]["params"] == {
        "model_type": "ols",
        "y": "outcome",
        "x": ["predictor"],
    }
    assert body["draft"]["exploration_context"] == {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "source_sha256": preview["source_sha256"],
        "exploration_fingerprint": preview["fingerprint"],
        "filters": request["filters"],
        "spec": spec,
        "outcome_column": "outcome",
        "predictor_columns": ["predictor"],
        "analysis_row_count": 2,
        "filtered_artifact_id": body["draft"]["exploration_context"]["filtered_artifact_id"],
        "filtered_artifact_path": body["draft"]["exploration_context"]["filtered_artifact_path"],
    }
    assert "rows" not in body["draft"]
    assert body["draft"]["default_execution_mode"] == "genesis"
    assert not (project / "runs" / run_id / "model_results").exists()


def test_ols_context_is_blocked_when_source_changes_before_execution(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"outcome": [1.0, 2.0], "predictor": [3.0, 4.0]}),
    )
    request = {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "operation": "summarize",
        "selected_columns": ["outcome", "predictor"],
        "filters": [],
        "outcome_column": "outcome",
        "predictor_columns": ["predictor"],
    }
    with TestClient(app) as client:
        preview = client.post(
            "/statistical-explorations/preview",
            params={"project_root": str(project)},
            json={key: value for key, value in request.items() if key not in {"outcome_column", "predictor_columns"}},
        ).json()["preview"]
        response = client.post(
            "/statistical-explorations/ols-context",
            params={"project_root": str(project)},
            json={**request, "preview_fingerprint": preview["fingerprint"]},
        )
    assert response.status_code == 200, response.text
    draft = PipelineDraftStore(project).get(response.json()["draft"]["draft_id"]).draft
    source_path = project / "runs" / run_id / "data.csv"
    source_path.write_text(source_path.read_text() + "5.0,6.0\n", encoding="utf-8")
    with pytest.raises(HTTPException) as exc_info:
        validate_exploration_context(project, draft)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "STATISTICAL_EXPLORATION_STALE"
