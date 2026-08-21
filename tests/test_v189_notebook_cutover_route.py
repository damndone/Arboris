from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tests.test_notebook_support import make_project
from tests.test_v189_agent_notebook_cutover import _cutover
from workbench.api import app
from workbench.app import configure_notebook_cutover_identity_resolver
from workbench.http.agent_routes import (
    AgentNotebookCutoverCompileRequest,
    register_agent_notebook_cutover_authority,
)
from workbench.http.notebook_routes import NotebookCutoverCompileRequest


_IDENTITY_BINDINGS: dict[str | None, tuple[str, str, str | None]] = {}


@pytest.fixture(autouse=True)
def _server_owned_identity_bindings():
    _IDENTITY_BINDINGS.clear()
    configure_notebook_cutover_identity_resolver(
        lambda _request, _project_ref, _claimed_session_ref, notebook_id: _IDENTITY_BINDINGS[notebook_id]
    )
    yield
    _IDENTITY_BINDINGS.clear()
    configure_notebook_cutover_identity_resolver(None)


def _create_notebook(client: TestClient, project: Path) -> dict[str, object]:
    response = client.post(
        "/notebooks",
        params={"project_root": str(project)},
        json={
            "title": "Notebook cutover route test",
            "created_by": "principal:notebook-test",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _fields() -> dict[str, object]:
    return {
        "capability_id": "fixture.contracts.capability",
        "target_ref": "dataset:fixture:1",
        "data_snapshot_ref": "dataset:snapshot:1",
        "data_snapshot_digest": "a" * 64,
        "requested_effect": "read",
        "sensitivity": "public",
        "analysis_mode": "descriptive",
    }


def _bind_identity(
    notebook_id: str,
    session_ref: str,
    project_ref: str | None = None,
) -> None:
    _IDENTITY_BINDINGS[notebook_id] = (
        "principal:notebook-test",
        session_ref,
        project_ref,
    )


def _register(project_ref: str, session_ref: str, notebook_id: str):
    _bind_identity(notebook_id, session_ref)
    _catalog, compiler = _cutover()
    register_agent_notebook_cutover_authority(
        project_ref=project_ref,
        session_ref=session_ref,
        compiler=compiler,
        app_instance=app,
    )
    return compiler


def test_notebook_compile_delegates_shared_compiler_and_preserves_semantic_hash(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path, name="notebook-cutover-project")
    client = TestClient(app)
    notebook = _create_notebook(client, project)
    project_ref = str(notebook["project_id"])
    project_ref = f"project:{project_ref}"
    session_ref = "session:notebook-cutover-equivalent"
    compiler = _register(project_ref, session_ref, str(notebook["notebook_id"]))
    _IDENTITY_BINDINGS[None] = ("principal:notebook-test", session_ref, project_ref)

    notebook_response = client.post(
        f"/notebooks/{notebook['notebook_id']}/cutover/compile",
        params={"project_root": str(project)},
        json={
            "text": "请检查 dataset:fixture:1",
            "actor_ref": "principal:notebook-test",
            "session_ref": session_ref,
            "normalized_fields": _fields(),
        },
    )
    assert notebook_response.status_code == 200, notebook_response.text
    notebook_preview = notebook_response.json()["preview"]

    agent_response = client.post(
        "/agent/cutover/compile",
        json=AgentNotebookCutoverCompileRequest(
            text="请检查 dataset:fixture:1",
            actor_ref="principal:notebook-test",
            session_ref=session_ref,
            project_ref=project_ref,
            normalized_fields=_fields(),
        ).model_dump(),
    )
    assert agent_response.status_code == 200, agent_response.text
    agent_preview = agent_response.json()["preview"]

    assert notebook_preview["entrypoint"] == "notebook"
    assert notebook_preview["semantic_plan_hash"] == agent_preview["semantic_plan_hash"]
    assert notebook_preview["compilation_record_id"] != agent_preview["compilation_record_id"]
    assert compiler.record(notebook_preview["compilation_record_id"]).project_ref == project_ref


def test_notebook_compile_returns_typed_clarifications_for_incomplete_intent(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path, name="notebook-cutover-clarification")
    client = TestClient(app)
    notebook = _create_notebook(client, project)
    project_ref = str(notebook["project_id"])
    project_ref = f"project:{project_ref}"
    session_ref = "session:notebook-cutover-clarification"
    _register(project_ref, session_ref, str(notebook["notebook_id"]))

    response = client.post(
        f"/notebooks/{notebook['notebook_id']}/cutover/compile",
        params={"project_root": str(project)},
        json={
            "text": "请继续分析",
            "actor_ref": "principal:notebook-test",
            "session_ref": session_ref,
            "normalized_fields": {"target_ref": "dataset:fixture:1"},
        },
    )

    assert response.status_code == 200, response.text
    preview = response.json()["preview"]
    assert preview["plan_diff"] == {"status": "clarification_required"}
    assert {item["field"] for item in preview["clarifications"]} >= {
        "capability_id",
        "data_snapshot_ref",
        "data_snapshot_digest",
        "requested_effect",
        "sensitivity",
    }


def test_notebook_compile_is_unbound_fail_closed(tmp_path: Path) -> None:
    project = make_project(tmp_path, name="notebook-cutover-unbound")
    client = TestClient(app)
    notebook = _create_notebook(client, project)
    _bind_identity(str(notebook["notebook_id"]), "session:notebook-cutover-unbound")

    response = client.post(
        f"/notebooks/{notebook['notebook_id']}/cutover/compile",
        params={"project_root": str(project)},
        json={
            "text": "请检查 dataset:fixture:1",
            "actor_ref": "principal:notebook-test",
            "session_ref": "session:notebook-cutover-unbound",
            "normalized_fields": _fields(),
        },
    )

    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "AGENT_NOTEBOOK_CUTOVER_NOT_BOUND"


def test_notebook_compile_rejects_project_notebook_and_scope_mismatch(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path, name="notebook-cutover-scope")
    client = TestClient(app)
    notebook = _create_notebook(client, project)
    project_ref = str(notebook["project_id"])
    project_ref = f"project:{project_ref}"
    session_ref = "session:notebook-cutover-scope"
    _register(project_ref, session_ref, str(notebook["notebook_id"]))
    body = {
        "text": "请检查 dataset:fixture:1",
        "actor_ref": "principal:notebook-test",
        "session_ref": session_ref,
        "normalized_fields": _fields(),
    }

    missing_project = client.post(
        f"/notebooks/{notebook['notebook_id']}/cutover/compile",
        params={"project_root": str(project / "does-not-exist")},
        json=body,
    )
    assert missing_project.status_code == 404
    assert missing_project.json()["error"]["code"] == "PROJECT_NOT_FOUND"

    missing_notebook = client.post(
        "/notebooks/notebook-does-not-exist/cutover/compile",
        params={"project_root": str(project)},
        json=body,
    )
    assert missing_notebook.status_code == 404
    assert missing_notebook.json()["error"]["code"] == "NOTEBOOK_NOT_FOUND"

    mismatched_scope = client.post(
        f"/notebooks/{notebook['notebook_id']}/cutover/compile",
        params={"project_root": str(project)},
        json={**body, "project_ref": "project:outside-notebook"},
    )
    assert mismatched_scope.status_code == 403
    assert mismatched_scope.json()["error"]["code"] == "NOTEBOOK_CUTOVER_SCOPE_MISMATCH"


def test_notebook_compile_rejects_client_identity_not_matching_server_binding(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path, name="notebook-cutover-identity")
    client = TestClient(app)
    notebook = _create_notebook(client, project)
    project_ref = str(notebook["project_id"])
    project_ref = f"project:{project_ref}"
    session_ref = "session:notebook-cutover-identity"
    _register(project_ref, session_ref, str(notebook["notebook_id"]))

    response = client.post(
        f"/notebooks/{notebook['notebook_id']}/cutover/compile",
        params={"project_root": str(project)},
        json={
            "text": "请检查 dataset:fixture:1",
            "actor_ref": "principal:forged",
            "session_ref": session_ref,
            "normalized_fields": _fields(),
        },
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "NOTEBOOK_CUTOVER_IDENTITY_MISMATCH"


def test_notebook_compile_request_forbids_client_authority_fields() -> None:
    base = {
        "text": "请检查 dataset:fixture:1",
        "actor_ref": "principal:notebook-test",
        "session_ref": "session:notebook-cutover-strict",
    }

    with pytest.raises(ValidationError):
        NotebookCutoverCompileRequest(**base, confirmation={"confirmation_id": "forged"})
    with pytest.raises(ValidationError):
        NotebookCutoverCompileRequest(**base, compiled_workflow={"nodes": []})
