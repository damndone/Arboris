from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench.agent.events import AgentEventStream
from workbench.agent.session import JsonlSessionRepository
from workbench.app import app
from workbench.projects import create_project
from workbench.services.run_deletion import (
    RunDeletionConfirmationError,
    RunDeletionService,
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_json_lines(path: Path, *values: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{json.dumps(value)}\n" for value in values), encoding="utf-8"
    )


def _make_run(
    project_root: Path,
    run_id: str,
    *,
    rerun_of: str | None = None,
    status: str = "completed",
) -> Path:
    root = project_root / "runs" / run_id
    root.mkdir(parents=True)
    _write_json(root / "run_manifest.json", {"run_id": run_id, "status": status})
    _write_json(root / "run_inputs.json", {"rerun_of": rerun_of})
    _write_json(
        root / "artifacts_index.json",
        {
            "schema_version": 1,
            "artifacts": [
                {"artifact_id": "result", "artifact_type": "model_result", "path": "model.json"},
                {"artifact_id": "plot", "artifact_type": "figure", "path": "figure.png"},
            ],
        },
    )
    (root / "model.json").write_text("{}", encoding="utf-8")
    (root / "figure.png").write_bytes(b"not-a-real-png")
    reports = root / "reports"
    reports.mkdir()
    (reports / "report.html").write_text("<html></html>", encoding="utf-8")
    return root


def _make_run_scoped_agent_history(project_root: Path, run_id: str) -> str:
    storage_root = project_root / "workbench"
    sessions = JsonlSessionRepository(storage_root)
    events = AgentEventStream(storage_root)
    session_id = "agent_chain_delete_test"
    sessions.create_session(session_id, chain_id="chain:delete-test", role="chain")
    sessions.append(
        session_id,
        "custom_message",
        {
            "message_type": "agent_context",
            "metadata": {"run_id": run_id},
        },
    )
    events.emit(session_id, "session_created", {"run_id": run_id})
    return session_id


def test_preview_blocks_deleting_a_run_with_descendants(tmp_path: Path) -> None:
    project = create_project(tmp_path, "demo")
    _make_run(project.root, "run_parent")
    _make_run(project.root, "run_child", rerun_of="run_parent")

    preview = RunDeletionService(project.root).preview("run_parent")

    assert preview.deletable is False
    assert preview.blocking_descendant_run_ids == ("run_child",)


def test_delete_leaf_removes_run_artifacts_and_exclusive_agent_history(tmp_path: Path) -> None:
    project = create_project(tmp_path, "demo")
    run_root = _make_run(project.root, "run_leaf")
    session_id = _make_run_scoped_agent_history(project.root, "run_leaf")
    service = RunDeletionService(project.root)

    preview = service.preview("run_leaf")

    assert preview.deletable is True
    assert preview.artifact_counts == {"figure": 1, "model_result": 1}
    assert preview.report_count == 1
    assert preview.agent_session_ids == (session_id,)
    assert preview.agent_event_session_ids == (session_id,)

    with pytest.raises(RunDeletionConfirmationError, match="confirmation"):
        service.delete(
            "run_leaf",
            expected_fingerprint=preview.fingerprint,
            confirmation_run_id="wrong-run",
        )
    assert run_root.is_dir()

    receipt = service.delete(
        "run_leaf",
        expected_fingerprint=preview.fingerprint,
        confirmation_run_id="run_leaf",
    )

    assert receipt.run_id == "run_leaf"
    assert not run_root.exists()
    assert not (project.root / "workbench" / "agent-sessions" / f"{session_id}.jsonl").exists()
    assert not (project.root / "workbench" / "agent-sessions" / f"{session_id}.meta.json").exists()
    assert not (project.root / "workbench" / "agent-events" / f"{session_id}.jsonl").exists()


def test_delete_rejects_a_stale_preview_before_mutating(tmp_path: Path) -> None:
    project = create_project(tmp_path, "demo")
    run_root = _make_run(project.root, "run_leaf")
    service = RunDeletionService(project.root)
    preview = service.preview("run_leaf")
    _make_run(project.root, "run_new_child", rerun_of="run_leaf")

    with pytest.raises(RunDeletionConfirmationError, match="changed"):
        service.delete(
            "run_leaf",
            expected_fingerprint=preview.fingerprint,
            confirmation_run_id="run_leaf",
        )

    assert run_root.is_dir()


def test_delete_leaf_removes_only_exclusive_run_scoped_control_records(
    tmp_path: Path,
) -> None:
    project = create_project(tmp_path, "demo")
    _make_run(project.root, "run_leaf")
    workbench_root = project.root / "workbench"
    _write_json_lines(
        workbench_root / "proposals" / "proposal_leaf.jsonl",
        {"target": {"run_id": "run_leaf"}, "record_type": "revision"},
        {"target": {"run_id": "run_leaf"}, "record_type": "confirmation"},
    )
    _write_json_lines(
        workbench_root / "operation-records" / "operation_leaf.jsonl",
        {"target": {"run_id": "run_leaf"}, "status": "completed"},
    )
    shared_proposal = workbench_root / "proposals" / "proposal_shared.jsonl"
    _write_json_lines(
        shared_proposal,
        {"target": {"run_id": "run_leaf"}, "record_type": "revision"},
        {"target": {"run_id": "another_run"}, "record_type": "revision"},
    )

    service = RunDeletionService(project.root)
    preview = service.preview("run_leaf")

    assert preview.proposal_ids == ("proposal_leaf",)
    assert preview.operation_record_ids == ("operation_leaf",)
    assert preview.retained_shared_record_ids == ("proposal:proposal_shared",)

    service.delete(
        "run_leaf",
        expected_fingerprint=preview.fingerprint,
        confirmation_run_id="run_leaf",
    )

    assert not (workbench_root / "proposals" / "proposal_leaf.jsonl").exists()
    assert not (workbench_root / "operation-records" / "operation_leaf.jsonl").exists()
    assert shared_proposal.exists()


def test_run_deletion_http_flow_requires_bound_confirmation(tmp_path: Path) -> None:
    project = create_project(tmp_path, "demo")
    _make_run(project.root, "run_leaf")

    with TestClient(app) as client:
        preview = client.get(
            "/runs/run_leaf/deletion-preview",
            params={"project_root": str(project.root)},
        )
        assert preview.status_code == 200
        body = preview.json()["preview"]
        assert body["deletable"] is True

        rejected = client.post(
            "/runs/run_leaf/deletion-confirmation",
            params={"project_root": str(project.root)},
            json={
                "fingerprint": body["fingerprint"],
                "confirmation_run_id": "different-run",
            },
        )
        assert rejected.status_code == 409
        assert rejected.json()["error"]["code"] == "RUN_DELETION_CONFIRMATION_REQUIRED"

        confirmed = client.post(
            "/runs/run_leaf/deletion-confirmation",
            params={"project_root": str(project.root)},
            json={
                "fingerprint": body["fingerprint"],
                "confirmation_run_id": "run_leaf",
            },
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["deletion"]["run_id"] == "run_leaf"
        assert not (project.root / "runs" / "run_leaf").exists()
