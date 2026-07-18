from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.artifacts import read_json
from workbench.app import app
from workbench.events import get_event_manager
from workbench.orchestrator import _lineage, _write_manifest
from workbench.projects import create_project, create_run


def test_background_run_cancel_checkpoint_terminalises_as_interrupted(tmp_path: Path, monkeypatch) -> None:
    import workbench.services.run_service as service

    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    upload = run.root / "input.csv"
    upload.write_text("y,x\n1,1\n", encoding="utf-8")
    _write_manifest(
        run.root,
        run.run_id,
        "auto",
        "running",
        _lineage([upload]),
        started_at=datetime.now(timezone.utc).isoformat(),
        y="y",
        x=["x"],
    )
    events = get_event_manager()
    assert events.try_acquire_slot()
    events.register_run(run.run_id, run.root / "workflow_log.jsonl")
    events.mark_active(run.run_id)
    assert events.request_cancel(run.run_id)

    def fake_workflow(*args, **kwargs):
        from workbench.engine.context import RunInterruptionRequested

        raise RunInterruptionRequested(kwargs["stop_reason"]() or "cancelled")

    monkeypatch.setattr(service, "_run_workflow", fake_workflow)
    service._bg_run(
        run.root,
        run.run_id,
        upload,
        "auto",
        "y",
        ["x"],
        datetime.now(timezone.utc).isoformat(),
        model_type="ols",
    )

    manifest = read_json(run.root / "run_manifest.json")
    assert manifest["status"] == "interrupted"
    issue = read_json(run.root / "errors.json")["issues"][0]
    assert issue["code"] == "WORKFLOW_CANCELLED"
    assert not events.is_active(run.run_id)


def test_cancel_endpoint_requests_cooperative_stop_for_active_run(tmp_path: Path) -> None:
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    upload = run.root / "input.csv"
    upload.write_text("y,x\n1,1\n", encoding="utf-8")
    _write_manifest(
        run.root,
        run.run_id,
        "auto",
        "running",
        _lineage([upload]),
        started_at=datetime.now(timezone.utc).isoformat(),
        y="y",
        x=["x"],
    )
    events = get_event_manager()
    assert events.try_acquire_slot()
    events.register_run(run.run_id, run.root / "workflow_log.jsonl")
    events.mark_active(run.run_id)
    try:
        response = TestClient(app).post(
            f"/runs/{run.run_id}/cancel",
            params={"project_root": str(project.root)},
        )
        assert response.status_code == 200
        assert response.json() == {"run_id": run.run_id, "status": "cancelling"}
        assert events.is_cancel_requested(run.run_id)
    finally:
        events.release_slot(run.run_id)
