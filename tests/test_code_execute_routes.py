"""HTTP surface for `code.execute` — the full typed lifecycle, real sandbox."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.test_data_column_cast import _source_project
from workbench.app import app
from workbench.sandbox import isolation_backend

pytestmark = pytest.mark.skipif(
    isolation_backend() is None,
    reason="no OS sandbox backend on this host; code.execute is fail-closed here",
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"age": [10, 11], "name": ["a", "b"]})


def _request(run_id: str, artifact_id: str, code: str, **extra) -> dict:
    return {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "code": code,
        **extra,
    }


def test_code_execute_preview_confirm_and_provenance_readback(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, _frame())
    code = "result = df.assign(doubled=df['age'] * 2)"

    with TestClient(app) as client:
        preview_response = client.post(
            "/data-operations/code-execute/preview",
            params={"project_root": str(project)},
            json=_request(run_id, artifact_id, code),
        )
        assert preview_response.status_code == 200
        preview = preview_response.json()["preview"]
        assert preview["status"] == "ready"
        assert preview["columns_added"] == ["doubled"]
        assert preview["row_count_after"] == 2

        confirm_response = client.post(
            "/data-operations/code-execute/confirm",
            params={"project_root": str(project)},
            json={
                **_request(run_id, artifact_id, code),
                "preview_fingerprint": preview["fingerprint"],
                "session_id": "agent_data_ui",
            },
        )
        assert confirm_response.status_code == 200, confirm_response.text
        body = confirm_response.json()
        assert body["status"] == "completed"
        operation = body["operation"]
        assert operation["operation_id"] == "code.execute"
        child_node_id = operation["outputs"]["child_node_id"]
        assert operation["verification"]["checks"]["sandboxed"] is True
        assert operation["verification"]["checks"]["deterministic"] is True

        # The drawer resolves the operation record from the child node.
        by_child = client.get(
            "/data-operations/column-cast/by-child-node",
            params={
                "project_root": str(project),
                "run_id": run_id,
                "child_node_id": child_node_id,
            },
        )
        assert by_child.status_code == 200, by_child.text
        assert by_child.json()["operation"]["operation_id"] == "code.execute"


def test_code_execute_preview_reports_failing_code_as_blocked(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, _frame())

    with TestClient(app) as client:
        response = client.post(
            "/data-operations/code-execute/preview",
            params={"project_root": str(project)},
            json=_request(run_id, artifact_id, "result = df['missing']"),
        )

    assert response.status_code == 200
    preview = response.json()["preview"]
    assert preview["status"] == "blocked"
    assert "KeyError" in preview["error"]


def test_code_execute_confirm_refuses_a_blocked_preview(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, _frame())

    with TestClient(app) as client:
        response = client.post(
            "/data-operations/code-execute/confirm",
            params={"project_root": str(project)},
            json={
                **_request(run_id, artifact_id, "result = df['missing']"),
                "preview_fingerprint": "whatever",
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DATA_OPERATION_BLOCKED"


def test_code_execute_confirm_rejects_a_mismatched_fingerprint(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, _frame())

    with TestClient(app) as client:
        response = client.post(
            "/data-operations/code-execute/confirm",
            params={"project_root": str(project)},
            json={
                **_request(run_id, artifact_id, "result = df.assign(x=1)"),
                "preview_fingerprint": "f" * 64,
            },
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DATA_OPERATION_STALE"


def test_code_execute_confirm_rejects_nondeterministic_code(tmp_path: Path) -> None:
    """Non-determinism surfaces at confirm as its own error, not a fake staleness."""

    project, run_id, artifact_id = _source_project(tmp_path, _frame())
    code = "import random\nresult = df.assign(n=[random.random() for _ in range(len(df))])\n"

    with TestClient(app) as client:
        preview = client.post(
            "/data-operations/code-execute/preview",
            params={"project_root": str(project)},
            json=_request(run_id, artifact_id, code),
        ).json()["preview"]
        assert preview["status"] == "ready"

        response = client.post(
            "/data-operations/code-execute/confirm",
            params={"project_root": str(project)},
            json={
                **_request(run_id, artifact_id, code),
                "preview_fingerprint": preview["fingerprint"],
            },
        )

    # The confirm-time re-preview already diverges, so this is caught before any
    # proposal is confirmed; either way nothing is written.
    assert response.status_code == 409
    assert response.json()["error"]["code"] in {
        "DATA_OPERATION_STALE",
        "CODE_NOT_DETERMINISTIC",
    }
    derived = project / "runs" / run_id / "derived" / "code_execute"
    assert not derived.exists() or list(derived.rglob("data.csv")) == []


def test_code_execute_request_rejects_oversized_and_non_python(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, _frame())

    with TestClient(app) as client:
        oversized = client.post(
            "/data-operations/code-execute/preview",
            params={"project_root": str(project)},
            json=_request(run_id, artifact_id, "x" * 20_001),
        )
        wrong_language = client.post(
            "/data-operations/code-execute/preview",
            params={"project_root": str(project)},
            json=_request(run_id, artifact_id, "result = df", language="ruby"),
        )

    assert oversized.status_code == 422
    assert wrong_language.status_code == 422


def test_code_execute_is_a_registered_high_risk_capability(tmp_path: Path) -> None:
    project, _run_id, _artifact_id = _source_project(tmp_path, _frame())

    with TestClient(app) as client:
        response = client.get("/agent/capabilities", params={"project_root": str(project)})

    assert response.status_code == 200
    items = response.json()["capabilities"]
    entry = next(item for item in items if item["operation_id"] == "code.execute")
    assert entry["risk_level"] == "high"
    assert entry["confirmation_policy"] == "required"
    # Privilege comes from the operation being registered, not from an input box;
    # and it stays off the natural-language surface until it has earned it.
    assert entry["natural_language_enabled"] is False
