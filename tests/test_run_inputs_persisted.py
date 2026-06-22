import io
import json
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api import app
from workbench.projects import create_project

client = TestClient(app)


def _csv() -> bytes:
    return b"y,x\n1,2\n3,4\n5,6\n"


def test_create_persists_run_inputs_and_cas_upload(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    resp = client.post(
        "/runs",
        data={"project_root": str(project.root), "mode": "auto",
              "model_type": "ols", "y": "y", "x": "x"},
        files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")},
    )
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    run_root = project.root / "runs" / run_id

    inputs = json.loads((run_root / "run_inputs.json").read_text())
    assert inputs["run_input_schema_version"] == 1
    assert inputs["form"]["model_type"] == "ols"
    assert inputs["rerun_of"] is None
    assert inputs["rerun_reason"] == "initial"
    sha = inputs["upload"]["sha256"]
    assert "path" not in inputs["upload"]  # addressed by sha256 only
    assert (project.root / "data" / "uploads" / sha).is_file()
