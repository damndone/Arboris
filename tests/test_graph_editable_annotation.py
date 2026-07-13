import io
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api import app
from workbench.projects import create_project
from workbench.http._deps import _backfill_schema_values

client = TestClient(app)


def test_backfill_x_columns_into_editable_schema():
    schema = [{"key": "x", "kind": "columns", "label": "Regressors (X)"}]
    result = _backfill_schema_values(schema, {"x": "x1, x2"})
    assert result == [
        {
            "key": "x",
            "kind": "columns",
            "label": "Regressors (X)",
            "value": ["x1", "x2"],
            "options": ["x1", "x2"],
        }
    ]


def _csv() -> bytes:
    rows = "\n".join(f"{1 + 2 * i},{i}" for i in range(35))
    return ("y,x\n" + rows + "\n").encode()


def _run(project_root: Path) -> str:
    run_id = client.post(
        "/runs",
        data={"project_root": str(project_root), "mode": "auto",
              "model_type": "ols", "y": "y", "x": "x"},
        files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")},
    ).json()["run_id"]
    terminal = {"completed", "failed", "cancelled", "interrupted", "partial", "blocked"}
    for _ in range(100):
        b = client.get(f"/runs/{run_id}", params={"project_root": str(project_root)}).json()
        if b.get("status") in terminal:
            break
        time.sleep(0.1)
    return run_id


def test_model_node_is_annotated_editable(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    run_id = _run(project.root)
    graph = client.get(f"/runs/{run_id}/graph", params={"project_root": str(project.root)}).json()
    model = next(n for n in graph["nodes"].values() if n.get("stage") == "model")
    assert model["editable"] is True
    assert model["op_type"] == "ols"
    assert model["schema_id"] == "ols@v1"
    assert isinstance(model["editable_schema"], list)
    assert model["editable_schema_source"] == "capabilities"


def test_non_model_node_not_editable(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    run_id = _run(project.root)
    graph = client.get(f"/runs/{run_id}/graph", params={"project_root": str(project.root)}).json()
    non = next(n for n in graph["nodes"].values() if n.get("stage") != "model")
    assert non.get("editable", False) is False


def test_annotation_not_written_back_to_graph_json(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    run_id = _run(project.root)
    client.get(f"/runs/{run_id}/graph", params={"project_root": str(project.root)})
    raw = json.loads((project.root / "runs" / run_id / "graph.json").read_text())
    for node in raw["nodes"].values():
        assert "editable_schema" not in node  # Guardrail #7: decorate-only
        assert "editable" not in node
