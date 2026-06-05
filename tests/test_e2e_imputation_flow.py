"""End-to-end imputation flow through the HTTP API — closes the integration
seam the frontend depends on but unit tests skip:

  POST /runs (imputation={"method":"mice"}, real execution, data with NaNs)
    -> MICE runs -> imputation_summary artifact registered
    -> GET /runs/{id}/artifacts                 (presence, mirrors UI list)
    -> GET /runs/{id}/artifacts/imputation_summary  (the fetchArtifactJson seam)
       returns valid JSON the ImputationSummary panel renders.

test_api_runs_imputation monkeypatches the executor (never runs MICE) and
test_imputation_summary_artifact bypasses the API + the download endpoint, so
neither covers this path.
"""
import io
import json
import time
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from workbench.api import app


def _missing_data_csv() -> bytes:
    ys = [1.0 + 2.0 * i for i in range(40)]
    xs = [float(i) for i in range(40)]
    for i in (5, 11, 17, 23):
        ys[i] = None
    for i in (7, 13, 19, 29):
        xs[i] = None
    frame = pd.DataFrame({"y": ys, "x": xs, "firm_id": list(range(100, 140))})
    return frame.to_csv(index=False).encode()


def _wait_terminal(client: TestClient, project_root: str, run_id: str,
                   deadline_s: float = 30.0) -> str:
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


def test_imputation_run_via_api_produces_fetchable_summary_artifact(tmp_path: Path):
    client = TestClient(app)
    project_root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "demo"}
    ).json()["project_root"]

    res = client.post(
        "/runs",
        data={
            "project_root": project_root,
            "mode": "auto",
            "y": "y",
            "x": "x",
            "imputation": json.dumps({"method": "mice"}),
        },
        files={"file": ("d.csv", io.BytesIO(_missing_data_csv()), "text/csv")},
    )
    assert res.status_code == 200, res.text
    run_id = res.json()["run_id"]
    assert _wait_terminal(client, project_root, run_id) == "completed"

    # 1. Presence: the artifacts list carries imputation_summary — this is
    #    exactly the check runResult.tsx does before fetching.
    groups = client.get(
        f"/runs/{run_id}/artifacts", params={"project_root": project_root}
    ).json()["groups"]
    artifact_ids = [it["artifact_id"] for g in groups for it in g["items"]]
    assert "imputation_summary" in artifact_ids, artifact_ids

    # 2. The fetchArtifactJson seam: GET the single artifact, expect JSON the
    #    ImputationSummary panel can render.
    resp = client.get(
        f"/runs/{run_id}/artifacts/imputation_summary",
        params={"project_root": project_root},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schema_version"] == 1
    assert body["method"] == "mice"
    assert body["status"] == "completed"
    assert body["output_artifact"] == "imputed_dataset"
    assert body["input_artifact"] == "cleaned_dataset"


def test_no_imputation_request_produces_no_summary_artifact(tmp_path: Path):
    """Negative/empty-state guard: a run WITHOUT imputation must NOT register
    an imputation_summary artifact, so the UI panel stays hidden and the
    GET endpoint 404s (fetchArtifactJson -> catch -> undefined)."""
    client = TestClient(app)
    project_root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "demo"}
    ).json()["project_root"]

    # Clean, complete data, no imputation field.
    frame = pd.DataFrame(
        {"y": [1.0 + 2.0 * i for i in range(35)], "x": list(range(35))}
    )
    res = client.post(
        "/runs",
        data={"project_root": project_root, "mode": "auto", "y": "y", "x": "x"},
        files={"file": ("d.csv", io.BytesIO(frame.to_csv(index=False).encode()), "text/csv")},
    )
    run_id = res.json()["run_id"]
    assert _wait_terminal(client, project_root, run_id) == "completed"

    groups = client.get(
        f"/runs/{run_id}/artifacts", params={"project_root": project_root}
    ).json()["groups"]
    artifact_ids = [it["artifact_id"] for g in groups for it in g["items"]]
    assert "imputation_summary" not in artifact_ids

    resp = client.get(
        f"/runs/{run_id}/artifacts/imputation_summary",
        params={"project_root": project_root},
    )
    assert resp.status_code == 404
