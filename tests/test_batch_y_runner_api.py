from pathlib import Path

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.artifacts import read_json
from workbench.projects import create_project


X_VARS = [
    "x1_budget",
    "x2_exposure",
    "x3_quality",
    "x4_time_on_task",
    "x5_team_size",
    "x6_prior_level",
    "x7_region_code",
    "x8_treatment",
    "x9_complexity",
    "x10_interaction_proxy",
]

Y_LIST = ["continuous_score_y", "binary_success_y", "count_events_y"]


def _write_batch_fixture(path: Path) -> None:
    rng = np.random.default_rng(20260506)
    n = 180
    x1 = rng.normal(0, 1, n)
    exposure = rng.integers(80, 220, n)
    quality = rng.normal(0, 1, n)
    treatment = rng.binomial(1, 0.45, n)

    binary_prob = 1 / (1 + np.exp(-(-0.2 + 0.45 * x1 + 0.2 * treatment)))
    count_lambda = exposure * np.exp(-4.4 + 0.35 * x1 + 0.2 * treatment)

    frame = pd.DataFrame(
        {
            "continuous_score_y": 50 + 7 * x1 + 3 * quality + rng.normal(0, 2, n),
            "binary_success_y": rng.binomial(1, binary_prob, n),
            "count_events_y": rng.poisson(count_lambda).astype(int),
            "x1_budget": x1,
            "x2_exposure": exposure,
            "x3_quality": quality,
            "x4_time_on_task": rng.integers(15, 180, n),
            "x5_team_size": rng.normal(8, 2, n),
            "x6_prior_level": rng.normal(3, 1, n),
            "x7_region_code": rng.choice([1, 2, 3, 4], n),
            "x8_treatment": treatment,
            "x9_complexity": rng.normal(0, 1, n),
            "x10_interaction_proxy": x1 * treatment,
        }
    )
    frame.to_csv(path, index=False)


def test_run_batch_y_workflow_creates_independent_runs(tmp_path: Path):
    from workbench import orchestrator

    source = tmp_path / "batch.csv"
    _write_batch_fixture(source)
    project = create_project(tmp_path, "batch-internal")

    result = orchestrator.run_batch_y_workflow(
        project.root,
        [source],
        mode="auto",
        y_list=Y_LIST,
        x=X_VARS,
    )

    assert result["status"] == "completed"
    assert [item["y"] for item in result["runs"]] == Y_LIST
    assert [item["model_type"] for item in result["runs"]] == [
        "ols_robust",
        "logit",
        "poisson_rate",
    ]
    run_ids = [item["run_id"] for item in result["runs"]]
    assert len(set(run_ids)) == 3

    for item in result["runs"]:
        manifest = read_json(project.root / "runs" / item["run_id"] / "run_manifest.json")
        assert manifest["y"] == item["y"]
        assert manifest["x"] == X_VARS


def test_batch_runs_endpoint_accepts_y_list_and_returns_run_summaries(tmp_path: Path):
    client = TestClient(app)
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "batch-api"},
    )
    project_root = response.json()["project_root"]

    source = tmp_path / "batch.csv"
    _write_batch_fixture(source)

    with source.open("rb") as handle:
        batch_response = client.post(
            "/runs/batch",
            data={
                "project_root": project_root,
                "mode": "auto",
                "y_list": ",".join(Y_LIST),
                "x": ",".join(X_VARS),
            },
            files={"file": ("batch.csv", handle, "text/csv")},
        )

    assert batch_response.status_code == 200
    payload = batch_response.json()
    assert payload["status"] == "completed"
    assert [item["y"] for item in payload["runs"]] == Y_LIST
    assert [item["model_type"] for item in payload["runs"]] == [
        "ols_robust",
        "logit",
        "poisson_rate",
    ]
    assert len({item["run_id"] for item in payload["runs"]}) == 3
