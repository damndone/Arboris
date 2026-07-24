"""Gate 1 Task 5 — rerun and fork inherit the source run's family.

Driven through the real POST /runs and POST /runs/{id}/rerun endpoints. A mocked
rerun would prove only that the helper works; the thing worth proving is that the
production creation path actually calls it, on both generations.
"""
import io
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api import app
from workbench.lineage.run_family import (
    migrate_project_families,
    read_run_family_membership,
    resolve_run_family,
)
from workbench.projects import create_project

client = TestClient(app)


def _csv() -> bytes:
    rows = "\n".join(f"{1 + 2 * i},{i}" for i in range(35))
    return ("y,x\n" + rows + "\n").encode()


def _wait_terminal(project_root: Path, run_id: str, tries: int = 120) -> str:
    terminal = {"completed", "failed", "cancelled", "interrupted", "partial"}
    body: dict = {}
    for _ in range(tries):
        body = client.get(f"/runs/{run_id}", params={"project_root": str(project_root)}).json()
        if body.get("status") in terminal:
            return body["status"]
        time.sleep(0.1)
    return body.get("status", "")


def _create_run(project_root: Path) -> str:
    resp = client.post(
        "/runs",
        data={
            "project_root": str(project_root),
            "mode": "auto",
            "model_type": "ols",
            "y": "y",
            "x": "x",
        },
        files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")},
    )
    run_id = resp.json()["run_id"]
    _wait_terminal(project_root, run_id)
    return run_id


def _model_node_id(project_root: Path, run_id: str) -> str:
    graph = client.get(f"/runs/{run_id}/graph", params={"project_root": str(project_root)}).json()
    return next(n["id"] for n in graph["nodes"].values() if n.get("stage") == "model")


def _rerun(project_root: Path, run_id: str, covariance: str) -> str:
    resp = client.post(
        f"/runs/{run_id}/rerun",
        params={"project_root": str(project_root)},
        json={
            "from_node": _model_node_id(project_root, run_id),
            "op_overrides": {"covariance": covariance},
        },
    )
    assert resp.status_code == 200, resp.text
    child = resp.json()["run_id"]
    _wait_terminal(project_root, child)
    return child


def test_rerun_and_fork_keep_the_parent_family(tmp_path: Path) -> None:
    project = create_project(tmp_path, "demo")
    parent = _create_run(project.root)
    migrate_project_families(project.root, created_by="test")
    parent_family = resolve_run_family(project.root, parent).run_family_id

    child = _rerun(project.root, parent, "unadjusted")
    grandchild = _rerun(project.root, child, "robust")

    assert resolve_run_family(project.root, child).run_family_id == parent_family
    assert resolve_run_family(project.root, grandchild).run_family_id == parent_family
    for run_id in (child, grandchild):
        membership = read_run_family_membership(project.root / "runs" / run_id)
        assert membership is not None
        assert membership["bound_by"] == "rerun_inheritance"


def test_inheritance_does_not_rescan_ancestry(tmp_path: Path, monkeypatch) -> None:
    """A child's family comes from its parent's record, not from the forest."""
    project = create_project(tmp_path, "demo")
    parent = _create_run(project.root)
    migrate_project_families(project.root, created_by="test")
    parent_family = resolve_run_family(project.root, parent).run_family_id

    from workbench.lineage import run_family as run_family_module

    calls: list[str] = []
    original = run_family_module.legacy_family_anchor

    def _counting(runs_root, run_id):  # type: ignore[no-untyped-def]
        calls.append(run_id)
        return original(runs_root, run_id)

    monkeypatch.setattr(run_family_module, "legacy_family_anchor", _counting)
    child = _rerun(project.root, parent, "unadjusted")

    assert resolve_run_family(project.root, child).run_family_id == parent_family
    assert calls == []


def test_a_second_root_run_starts_its_own_family(tmp_path: Path) -> None:
    """Inheritance is for children only; an unrelated root run is its own line."""
    project = create_project(tmp_path, "demo")
    first = _create_run(project.root)
    migrate_project_families(project.root, created_by="test")
    first_family = resolve_run_family(project.root, first).run_family_id

    second = _create_run(project.root)
    second_family = resolve_run_family(project.root, second).run_family_id

    assert second_family != first_family
    assert second_family.startswith("run-family:")
    membership = json.loads(
        (project.root / "runs" / second / "run_family.json").read_text()
    )
    assert membership["bound_by"] == "create_run"
