"""Every state-changing route either records itself in the analysis ledger or
says why it does not. A new route that runs an analysis or changes data fails
here until someone decides."""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import workbench.http as http_package

LIFECYCLE = "recorded at the operation-lifecycle exit (orchestrator), whoever confirmed it"
NO_ANALYSIS = "runs no analysis and changes no data"

EXEMPT: dict[tuple[str, str], str] = {
    # Agent: proposals are records; execution is recorded by the lifecycle.
    ("POST", "/agent/sessions"): NO_ANALYSIS,
    ("POST", "/agent/sessions/{session_id}/analysis-loop/context"): NO_ANALYSIS,
    ("POST", "/agent/sessions/{session_id}/analysis-loop/intents"): NO_ANALYSIS,
    ("POST", "/agent/sessions/{session_id}/analysis-loop/proposals"): NO_ANALYSIS,
    ("POST", "/agent/fork-proposals"): NO_ANALYSIS,
    ("POST", "/agent/sessions/{session_id}/proposals/{proposal_id}/decline"): NO_ANALYSIS,
    ("POST", "/agent/sessions/{session_id}/proposals/{proposal_id}/revise"): NO_ANALYSIS,
    ("POST", "/agent/sessions/{session_id}/proposals/{proposal_id}/confirm"): LIFECYCLE,
    ("POST", "/agent/sessions/{session_id}/operations/{record_id}/reconcile"): LIFECYCLE,
    ("POST", "/agent/sessions/{session_id}/turns"): "read-only workflows it runs are recorded by the lifecycle",
    ("POST", "/agent/sessions/{session_id}/abort"): NO_ANALYSIS,
    # Typed UI data operations that run through the operation lifecycle.
    ("POST", "/data-operations/column-cast/confirm"): LIFECYCLE,
    ("POST", "/data-operations/columns-cast/confirm"): LIFECYCLE,
    ("POST", "/data-operations/code-execute/confirm"): LIFECYCLE,
    ("POST", "/data-operations/code-execute/risk-authorize"): NO_ANALYSIS,
    ("POST", "/data-operations/column-cast/preview"): "preview only",
    ("POST", "/data-operations/columns-cast/preview"): "preview only",
    ("POST", "/data-operations/feature-recipe/preview"): "preview only",
    ("POST", "/data-operations/transform/preview"): "preview only",
    ("POST", "/data-operations/code-execute/preview"): "preview only",
    ("POST", "/statistical-explorations/preview"): "preview only",
    ("POST", "/statistical-explorations/ols-context"): NO_ANALYSIS,
    ("POST", "/runs/arma-garch/transform-preflight"): "preview only",
    ("POST", "/uploads/preview"): "preview only",
    ("POST", "/runs/{run_id}/datasets/export/preview"): "preview only",
    # Drafts are edited freely; only executing one runs anything.
    ("POST", "/pipeline-drafts/from-node"): NO_ANALYSIS,
    ("POST", "/pipeline-drafts/genesis"): NO_ANALYSIS,
    ("PATCH", "/pipeline-drafts/{draft_id}"): NO_ANALYSIS,
    ("PATCH", "/pipeline-drafts/{draft_id}/nodes/{node_id}"): NO_ANALYSIS,
    ("DELETE", "/pipeline-drafts/{draft_id}"): "an unexecuted draft holds no result",
    ("POST", "/pipeline-drafts/{draft_id}/validate"): NO_ANALYSIS,
    # Notebook: planning and bookkeeping; dispatch is recorded.
    ("POST", "/notebooks"): NO_ANALYSIS,
    ("POST", "/notebooks/projection"): NO_ANALYSIS,
    ("POST", "/notebooks/projection/from-run-dataset"): NO_ANALYSIS,
    ("PUT", "/notebooks/{notebook_id}/focus"): NO_ANALYSIS,
    ("POST", "/notebooks/{notebook_id}/context/compile"): NO_ANALYSIS,
    ("DELETE", "/notebooks/{notebook_id}/planning/{attempt_id}"): NO_ANALYSIS,
    ("POST", "/notebooks/{notebook_id}/options/propose"): NO_ANALYSIS,
    ("POST", "/notebooks/{notebook_id}/options/{option_id}/revalidate"): NO_ANALYSIS,
    ("POST", "/notebooks/{notebook_id}/options/{option_id}/confirm"): "confirmation only; dispatch is recorded",
    ("POST", "/notebooks/{notebook_id}/options/{option_id}/authorize-execution"): NO_ANALYSIS,
    ("POST", "/notebooks/{notebook_id}/options/{option_id}/decision"): NO_ANALYSIS,
    ("POST", "/notebooks/{notebook_id}/options/{option_id}/execute"): "completion bookkeeping for a dispatched run",
    # Settings, providers, memory, comparisons, reports of existing results.
    ("PUT", "/projects/egress/policy"): NO_ANALYSIS,
    ("PATCH", "/projects/egress/columns"): NO_ANALYSIS,
    ("POST", "/compare-nodes"): NO_ANALYSIS,
    ("DELETE", "/compare-nodes/{compare_id}"): NO_ANALYSIS,
    ("POST", "/llm/providers"): NO_ANALYSIS,
    ("PUT", "/llm/providers/{provider_id}"): NO_ANALYSIS,
    ("POST", "/llm/providers/{provider_id}/activate"): NO_ANALYSIS,
    ("DELETE", "/llm/providers/{provider_id}"): NO_ANALYSIS,
    ("POST", "/llm/providers/{provider_id}/models/refresh"): NO_ANALYSIS,
    ("POST", "/llm/providers/{provider_id}/probe"): NO_ANALYSIS,
    ("POST", "/llm/chat"): "narrates existing results",
    ("POST", "/domain-memory/settings/confirmations"): NO_ANALYSIS,
    ("PUT", "/domain-memory/settings/global"): NO_ANALYSIS,
    ("PUT", "/domain-memory/settings/project"): NO_ANALYSIS,
    ("POST", "/domain-memory/libraries/{library}/archive/confirmations"): NO_ANALYSIS,
    ("POST", "/domain-memory/libraries/{library}/archive"): NO_ANALYSIS,
    ("POST", "/domain-memory/retrieve"): NO_ANALYSIS,
    ("POST", "/domain-memory/candidates"): NO_ANALYSIS,
    ("POST", "/domain-memory/candidates/{candidate_id}/approve"): NO_ANALYSIS,
    ("POST", "/domain-memory/review/candidates/{candidate_id}"): NO_ANALYSIS,
    ("POST", "/domain-memory/review/memories/{memory_id}/state"): NO_ANALYSIS,
    ("POST", "/domain-memory/review/memories/{memory_id}/restore"): NO_ANALYSIS,
    ("POST", "/projects"): NO_ANALYSIS,
    ("POST", "/uploads"): "stores a file; the run that uses it is recorded",
    ("POST", "/runs/{run_id}/cancel"): "a cancelled run produces no result",
    ("POST", "/runs/{run_id}/report/export"): "exports an existing report",
    ("POST", "/runs/{run_id}/report/result-table-export"): "exports existing results",
    ("POST", "/runs/{run_id}/ai-reports"): "narrates existing results",
}


def _mutating_routes():
    for module_info in pkgutil.iter_modules(http_package.__path__):
        module = importlib.import_module(f"workbench.http.{module_info.name}")
        router = getattr(module, "router", None)
        if router is None:
            continue
        for route in router.routes:
            for method in sorted(getattr(route, "methods", set()) & {"POST", "PUT", "PATCH", "DELETE"}):
                yield method, route.path, route.endpoint


def test_every_state_changing_route_is_recorded_or_exempt() -> None:
    unaccounted = []
    recorded_and_exempt = []
    for method, path, endpoint in _mutating_routes():
        recorded = "record_ui_action(" in inspect.getsource(endpoint)
        exempt = (method, path) in EXEMPT
        if recorded and exempt:
            recorded_and_exempt.append((method, path))
        elif not recorded and not exempt:
            unaccounted.append((method, path))
    assert unaccounted == [], "record these in the analysis ledger or exempt them with a reason"
    assert recorded_and_exempt == []


def test_the_exemptions_name_real_routes() -> None:
    routes = {(method, path) for method, path, _ in _mutating_routes()}
    assert set(EXEMPT) - routes == set()


def test_ui_data_changes_enter_the_ledger(tmp_path) -> None:
    import numpy as np
    import pandas as pd
    from fastapi.testclient import TestClient

    from tests.test_data_recode import AGE_GROUPS
    from workbench import analysis_ledger
    from workbench.api import app
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project

    rng = np.random.default_rng(3)
    source = tmp_path / "d.csv"
    pd.DataFrame({"y": rng.normal(size=80), "age": rng.integers(18, 90, 80)}).to_csv(source, index=False)
    project = create_project(tmp_path, "p")
    run_id = run_workflow(project.root, [source], mode="auto", model_type="ols", y="y", x=["age"])["run_id"]
    client = TestClient(app)
    params = {"project_root": str(project.root)}
    body = {
        "source_run_id": run_id, "source_node_id": "stage:raw", "source_artifact_id": "raw_d.csv",
        "operation": "recode", "parameters": {"column": "age", "output": "age_group", "rules": AGE_GROUPS},
    }
    preview = client.post("/data-operations/transform/preview", params=params, json=body).json()["preview"]
    confirmed = client.post(
        "/data-operations/transform/confirm", params=params, json={**body, "preview_fingerprint": preview["fingerprint"]}
    )
    assert confirmed.status_code == 200, confirmed.text
    edited = client.post(
        f"/runs/{run_id}/metadata", params=params, json={"labels": {"variable_labels": {"age": "年龄"}}}
    )
    assert edited.status_code == 200, edited.text
    # The metadata edit re-estimates in the background; let it finish so the
    # run slot is free for the next test.
    import time

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status = client.get(f"/runs/{edited.json()['run_id']}", params=params).json().get("status")
        if status in {"completed", "failed", "cancelled", "succeeded"}:
            break
        time.sleep(0.1)

    entries = analysis_ledger.read(project.root)
    assert [(entry["source"], entry["steps"][0]["category"], entry["actor"]) for entry in entries] == [
        ("POST /data-operations/transform/confirm", "data_change", "user"),
        ("POST /runs/{run_id}/metadata", "metadata_change", "user"),
    ]
    assert all(entry["changes_data"] for entry in entries)
    assert entries[1]["produced_run_id"] == edited.json()["run_id"]
