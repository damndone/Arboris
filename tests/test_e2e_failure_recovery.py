"""End-to-end: explicit failure -> recommended_actions injected ->
FailureCard would render -> primary action carries form_overrides for
one-click recovery -> recovery run succeeds.

This is an API-level e2e (not a browser test) because the frontend
form_overrides handling is a pure React state update covered by the
slice-3 component test (FailureCard.test.tsx). The integration assertion
here is: the backend ships the exact `recommended_actions` payload the
frontend expects to receive, and re-submitting with the primary action's
form_overrides actually recovers.

NB: GuardrailIssue.to_dict() serializes evidence under `evidence`
(backend/workbench/domain.py), NOT `details`.
"""
import io
import time
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.artifacts import read_json
from workbench.projects import create_project


def _wait_terminal(client: TestClient, project_root: str, run_id: str,
                   deadline_s: float = 30.0) -> str:
    t0 = time.monotonic()
    while time.monotonic() - t0 < deadline_s:
        detail = client.get(f"/runs/{run_id}", params={"project_root": project_root})
        status = detail.json().get("status")
        if status in {"completed", "failed", "blocked"}:
            # Give the background thread a moment to release its slot.
            time.sleep(0.2)
            return status
        time.sleep(0.2)
    raise TimeoutError(f"run {run_id} did not finish within {deadline_s}s")


def _post_run(client: TestClient, project_root: str, model_type: str,
              payload: bytes) -> str:
    res = client.post(
        "/runs",
        data={
            "project_root": project_root,
            "mode": "auto",
            "model_type": model_type,
            "y": "y",
            "x": "x",
        },
        files={"file": ("d.csv", io.BytesIO(payload), "text/csv")},
    )
    assert res.status_code == 200, res.text
    return res.json()["run_id"]


def test_explicit_logit_failure_offers_one_click_rerun_auto(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    project_root = str(project.root)
    client = TestClient(app)

    # 1. /capabilities lists logit -> the frontend would render it as an option.
    caps = client.get("/capabilities").json()
    assert any(m["key"] == "logit" for m in caps["model_types"]), caps

    # 2. Submit a run with explicit logit on continuous y -> must fail
    #    (1.5.3.2 contract: explicit failure, no silent OLS fallback).
    frame = pd.DataFrame({
        "y": [1.5 * i for i in range(40)],
        "x": list(range(40)),
        "firm_id": list(range(100, 140)),
    })
    payload = frame.to_csv(index=False).encode()
    run_id = _post_run(client, project_root, "logit", payload)
    status = _wait_terminal(client, project_root, run_id)
    assert status == "failed", f"expected failed, got {status}"

    # 3. errors.json carries the recommended_actions payload under `evidence`.
    errors = read_json(project.root / "runs" / run_id / "errors.json")
    blockers = [i for i in errors["issues"]
                if i.get("code") == "MODEL_FIT_FAILED" and i.get("severity") == "BLOCKER"]
    assert blockers, f"expected a BLOCKER MODEL_FIT_FAILED, got {errors}"
    actions = blockers[0]["evidence"].get("recommended_actions", [])
    primary = next(a for a in actions if a["severity"] == "primary")
    assert primary["key"] == "rerun_auto"
    assert primary["form_overrides"] == {"model_type": "auto"}

    # 4. Apply the recovery (re-run with the primary action's form_overrides)
    #    and assert it completes.
    recovery_model_type = primary["form_overrides"]["model_type"]
    run_id2 = _post_run(client, project_root, recovery_model_type, payload)
    status2 = _wait_terminal(client, project_root, run_id2)
    assert status2 == "completed", f"recovery run expected completed, got {status2}"
