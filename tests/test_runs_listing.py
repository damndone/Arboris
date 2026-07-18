from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.app import app
from workbench.orchestrator import _lineage, _write_manifest
from workbench.projects import create_project, create_run


def test_run_list_reconciles_a_dead_running_manifest(tmp_path: Path) -> None:
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    _write_manifest(
        run.root,
        run.run_id,
        "auto",
        "running",
        _lineage([tmp_path / "data.csv"]),
        started_at=datetime.now(timezone.utc).isoformat(),
        y="y",
        x=["x"],
    )

    response = TestClient(app).get(
        "/runs",
        params={"project_root": str(project.root)},
    )

    assert response.status_code == 200
    listed = next(item for item in response.json()["runs"] if item["run_id"] == run.run_id)
    assert listed["status"] == "interrupted"
