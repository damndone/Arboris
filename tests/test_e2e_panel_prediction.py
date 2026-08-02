"""End-to-end panel + prediction flow through the HTTP API.

Proves the V1.5.4.2 wiring (Tasks 1-5) works through real run execution:

  POST /runs with user-supplied entity_col/time_col -> panel_ols runs to
    "completed" (panel override consumed end-to-end).

  POST /runs with prediction_model_type=prediction_ridge -> the prediction
    request-over-config path runs sklearn, registers the prediction_ridge_1
    artifact, and GET /runs/{id}/artifacts/prediction_ridge_1 returns JSON
    with model_type == "prediction_ridge".

Mirrors tests/test_e2e_imputation_flow.py for client/project/poll/fetch.
"""
import io
import time
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from workbench.api import app

pytest.importorskip("linearmodels")
pytest.importorskip("sklearn")


def _panel_csv() -> bytes:
    import random
    rng = random.Random(7)
    rows = []
    for firm in ("A", "B", "C", "D", "E", "F", "G", "H"):
        base = {"A": 10, "B": 20, "C": 30, "D": 40,
                "E": 15, "F": 25, "G": 35, "H": 45}[firm]
        for yr in (2018, 2019, 2020, 2021, 2022):
            rows.append({"firm": firm, "yr": yr,
                         "profit": base + (yr - 2018) * 2.0 + rng.uniform(-1, 1),
                         "rnd": base / 2 + (yr - 2018) + rng.uniform(-0.5, 0.5)})
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _linear_csv() -> bytes:
    import random
    rng = random.Random(11)
    xs = [float(i) for i in range(60)]
    ys = [3.0 + 1.5 * x + rng.uniform(-0.5, 0.5) for x in xs]
    return pd.DataFrame({"y": ys, "x": xs}).to_csv(index=False).encode()


def _wait_terminal(client: TestClient, project_root: str, run_id: str,
                   deadline_s: float = 60.0) -> str:
    t0 = time.monotonic()
    while time.monotonic() - t0 < deadline_s:
        status = client.get(
            f"/runs/{run_id}", params={"project_root": project_root}
        ).json().get("status")
        if status in {"completed", "failed", "blocked"}:
            time.sleep(0.2)
            return status
        time.sleep(0.2)
    raise TimeoutError(f"run {run_id} did not finish within {deadline_s}s")


def test_e2e_panel_with_user_columns(tmp_path: Path):
    client = TestClient(app)
    project_root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "panel"}
    ).json()["project_root"]

    res = client.post(
        "/runs",
        data={
            "project_root": project_root,
            "mode": "auto",
            "model_type": "panel_ols",
            "y": "profit",
            "x": "rnd",
            "entity_col": "firm",
            "time_col": "yr",
        },
        files={"file": ("panel.csv", io.BytesIO(_panel_csv()), "text/csv")},
    )
    assert res.status_code == 200, res.text
    run_id = res.json()["run_id"]
    assert _wait_terminal(client, project_root, run_id) == "completed"


def test_e2e_prediction_artifact_fetchable(tmp_path: Path):
    client = TestClient(app)
    project_root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "pred"}
    ).json()["project_root"]

    res = client.post(
        "/runs",
        data={
            "project_root": project_root,
            "mode": "auto",
            "model_type": "auto",
            "y": "y",
            "x": "x",
            "prediction_model_type": "prediction_ridge",
            "prediction_cv_folds": "3",
            "prediction_data_structure": "iid",
        },
        files={"file": ("lin.csv", io.BytesIO(_linear_csv()), "text/csv")},
    )
    assert res.status_code == 200, res.text
    run_id = res.json()["run_id"]
    assert _wait_terminal(client, project_root, run_id) == "completed"

    groups = client.get(
        f"/runs/{run_id}/artifacts", params={"project_root": project_root}
    ).json()["groups"]
    artifact_ids = [it["artifact_id"] for g in groups for it in g["items"]]
    assert "prediction_ridge_1" in artifact_ids, artifact_ids

    resp = client.get(
        f"/runs/{run_id}/artifacts/prediction_ridge_1",
        params={"project_root": project_root},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["model_type"] == "prediction_ridge", body
