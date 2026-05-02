# V1.1 Workbench Frontend & API Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an API-backed result browser on top of V1: read-only endpoints expose run history, run detail, artifacts, and the HTML report; the frontend grows a run-list / detail / artifact / report-viewer flow that consumes only the API.

**Architecture:** Extend `backend/workbench/api.py` with read-only endpoints that source data from the existing `artifacts_index.json` and an extended `run_manifest.json`. Introduce a typed error envelope and a path-resolution helper that prevents escape from `project_root`. Extend `frontend/src/api.ts` with typed clients, then add `RunHistoryPanel`, `RunDetailPanel`, `ArtifactBrowser`, and `ReportViewer` components driven by a small view state in `App.tsx`. No new dependencies (no react-router, no state library).

**Tech Stack:** Python 3.11+, FastAPI, pytest, React 18, Vite, TypeScript, Vitest, Testing Library.

---

## Scope

This plan covers exactly what is in `docs/superpowers/specs/2026-05-01-workbench-frontend-api-enhancements-design.md`. Out of scope: async runs, model/diagnostic expansion, profiling UI, new export formats, cross-project history, upload progress UI. Those go to V1.2+.

## File Structure

- Modify: `backend/workbench/orchestrator.py` — extend `_write_manifest` signature; capture `started_at` and write a "running" manifest before the workflow body executes.
- Create: `backend/workbench/api_errors.py` — `WorkbenchAPIError`, error code constants, FastAPI exception handler registration helper.
- Modify: `backend/workbench/api.py` — register exception handler; add 5 read-only endpoints; add path-resolution helpers.
- Modify: `tests/test_orchestrator_e2e.py` — assert manifest contains `started_at` / `y` / `x`.
- Modify: `tests/test_api.py` — add tests for every new endpoint, error envelope, path escape.
- Create: `tests/test_api_errors.py` — unit tests for the envelope and helper.
- Modify: `frontend/src/api.ts` — typed clients for the 5 new endpoints; envelope-aware error parsing (keeps the existing FastAPI `detail` path for backward compatibility with `POST /runs`).
- Create: `frontend/src/api.test.ts` — unit tests for envelope parsing.
- Modify: `frontend/src/App.tsx` — add view state (`submit | history | detail`); render new panels.
- Create: `frontend/src/runHistory.tsx` — `RunHistoryPanel` component.
- Create: `frontend/src/runDetail.tsx` — `RunDetailPanel` component (includes status, summary, error panel, artifact browser, report viewer).
- Modify: `frontend/src/App.test.tsx` — extend tests with history list, run detail navigation, artifact list, report viewer.
- Modify: `frontend/src/styles.css` — minimal additions for new layouts.

---

## Task 1: Extend run manifest with started_at / y / x

**Files:**
- Modify: `backend/workbench/orchestrator.py`
- Modify: `tests/test_orchestrator_e2e.py`
- Modify: `tests/test_project_run_artifacts.py` (only if it asserts on manifest shape; verify first)

- [ ] **Step 1: Inspect current manifest assertions**

Run: `grep -n "run_manifest\|started_at\|\"y\"\|\"x\":" tests/`

Expected: list of files that assert on manifest. Plan accordingly — the new fields must not break existing assertions. (V1 tests assert on `run_id`, `mode`, `status`, `lineage` only.)

- [ ] **Step 2: Write the failing test in `tests/test_orchestrator_e2e.py`**

Append at the end of the file:

```python
def test_manifest_contains_started_at_y_and_x(tmp_path: Path):
    project_root = tmp_path / "proj"
    create_project(tmp_path, "proj")
    data = project_root / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)

    result = run_workflow(project_root, [data], mode="auto", y="y", x=["x"])

    manifest_path = project_root / "runs" / result["run_id"] / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert "started_at" in manifest
    assert manifest["started_at"].endswith("+00:00") or manifest["started_at"].endswith("Z")
    assert manifest["y"] == "y"
    assert manifest["x"] == ["x"]
    assert manifest["status"] == "completed"
```

Add the imports at the top of the file if missing: `import json`, `import pandas as pd`, `from workbench.orchestrator import run_workflow`, `from workbench.projects import create_project`. Do not duplicate imports already present.

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/test_orchestrator_e2e.py::test_manifest_contains_started_at_y_and_x -v`

Expected: FAIL with `KeyError: 'started_at'` or `assert 'started_at' in manifest` failing.

- [ ] **Step 4: Update `_write_manifest` signature in `backend/workbench/orchestrator.py`**

Replace the existing `_write_manifest` (lines 229-239) with:

```python
def _write_manifest(
    run_root: Path,
    run_id: str,
    mode: str,
    status: str,
    lineage: list[dict[str, str]],
    *,
    started_at: str,
    y: str,
    x: list[str],
) -> None:
    write_json(
        run_root / "run_manifest.json",
        {
            "run_id": run_id,
            "mode": mode,
            "status": status,
            "started_at": started_at,
            "y": y,
            "x": list(x),
            "lineage": lineage,
        },
    )
```

- [ ] **Step 5: Capture started_at and pass it through `run_workflow`**

In `backend/workbench/orchestrator.py`, add `from datetime import datetime, timezone` to the imports.

Replace the body of `run_workflow` (lines 25-48) with:

```python
def run_workflow(
    project_root: Path,
    input_files: list[Path],
    *,
    mode: str,
    y: str,
    x: list[str],
) -> dict[str, str]:
    project_root = Path(project_root)
    config = load_config(project_root / "config.yml")
    run = create_run(project_root, mode=mode)
    started_at = datetime.now(timezone.utc).isoformat()
    _write_manifest(
        run.root,
        run.run_id,
        mode,
        "running",
        _lineage(input_files),
        started_at=started_at,
        y=y,
        x=x,
    )

    try:
        return _run_workflow(
            run.root,
            run.run_id,
            input_files,
            mode,
            y,
            x,
            config,
            started_at,
        )
    except Exception as exc:
        issue = GuardrailIssue(
            Severity.BLOCKER,
            "WORKFLOW_FAILED",
            "Workflow failed before completion.",
            {"error": str(exc)},
        )
        write_json(run.root / "errors.json", {"issues": [issue.to_dict()]})
        _write_manifest(
            run.root,
            run.run_id,
            mode,
            "failed",
            _lineage(input_files),
            started_at=started_at,
            y=y,
            x=x,
        )
        raise
```

- [ ] **Step 6: Thread `started_at` into `_run_workflow` and update its `_write_manifest` calls**

Replace the `_run_workflow` signature (line 51) to add `started_at: str` as the last parameter (after `config: Any`), and update both internal `_write_manifest` calls (the "blocked" calls on lines 103 and 126, and the "completed" call on line 173) to pass `started_at=started_at, y=y, x=x` as keyword args.

Concretely the three changed calls become:

```python
_write_manifest(run_root, run_id, mode, "blocked", _lineage(input_files),
                started_at=started_at, y=y, x=x)
```

```python
_write_manifest(run_root, run_id, mode, "blocked", _lineage(input_files),
                started_at=started_at, y=y, x=x)
```

```python
_write_manifest(run_root, run_id, mode, "completed", _lineage(input_files),
                started_at=started_at, y=y, x=x)
```

- [ ] **Step 7: Run the new test**

Run: `pytest tests/test_orchestrator_e2e.py::test_manifest_contains_started_at_y_and_x -v`

Expected: PASS.

- [ ] **Step 8: Run the full backend suite to confirm no regressions**

Run: `pytest -q`

Expected: all tests pass (V1 baseline + the new test). If a V1 test fails because of the new manifest fields, fix the test to be additive (assert on existing fields only) — never weaken the new fields.

- [ ] **Step 9: Commit**

```bash
git add backend/workbench/orchestrator.py tests/test_orchestrator_e2e.py
git commit -m "feat(orchestrator): record started_at / y / x in run manifest"
```

---

## Task 2: API error envelope infrastructure

**Files:**
- Create: `backend/workbench/api_errors.py`
- Create: `tests/test_api_errors.py`
- Modify: `backend/workbench/api.py`

- [ ] **Step 1: Write the failing tests in `tests/test_api_errors.py`**

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from workbench.api_errors import (
    ERROR_RUN_NOT_FOUND,
    WorkbenchAPIError,
    register_error_handlers,
)


def _build_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    def boom() -> dict[str, str]:
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_RUN_NOT_FOUND,
            message="Run abc not found",
            details={"run_id": "abc"},
        )

    return app


def test_workbench_api_error_returns_envelope_with_code_message_details():
    client = TestClient(_build_app())

    response = client.get("/boom")

    assert response.status_code == 404
    payload = response.json()
    assert payload == {
        "error": {
            "code": "RUN_NOT_FOUND",
            "message": "Run abc not found",
            "details": {"run_id": "abc"},
        }
    }


def test_workbench_api_error_default_details_is_empty_dict():
    err = WorkbenchAPIError(404, ERROR_RUN_NOT_FOUND, "missing")

    assert err.details == {}
    assert err.code == "RUN_NOT_FOUND"
    assert err.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api_errors.py -v`

Expected: FAIL with `ModuleNotFoundError: workbench.api_errors`.

- [ ] **Step 3: Create `backend/workbench/api_errors.py`**

```python
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

ERROR_PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
ERROR_RUN_NOT_FOUND = "RUN_NOT_FOUND"
ERROR_ARTIFACT_NOT_FOUND = "ARTIFACT_NOT_FOUND"
ERROR_REPORT_NOT_FOUND = "REPORT_NOT_FOUND"
ERROR_INVALID_PATH = "INVALID_PATH"


class WorkbenchAPIError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details: dict[str, Any] = details or {}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(WorkbenchAPIError)
    async def _handle_workbench_error(
        _request: Request, exc: WorkbenchAPIError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_api_errors.py -v`

Expected: PASS.

- [ ] **Step 5: Wire the handler into the existing app in `backend/workbench/api.py`**

After the `app = FastAPI(...)` line (around line 13), add:

```python
from .api_errors import register_error_handlers

register_error_handlers(app)
```

(Combine the import with the other relative imports at the top of the file.)

- [ ] **Step 6: Run the full backend suite**

Run: `pytest -q`

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/workbench/api_errors.py tests/test_api_errors.py backend/workbench/api.py
git commit -m "feat(api): add WorkbenchAPIError envelope handler"
```

---

## Task 3: GET /runs and GET /runs/{run_id}

**Files:**
- Modify: `backend/workbench/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests at the bottom of `tests/test_api.py`**

```python
def test_list_runs_returns_summary_for_completed_run(tmp_path: Path):
    client = TestClient(app)
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "demo"},
    )
    project_root = response.json()["project_root"]
    data = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)
    with data.open("rb") as handle:
        client.post(
            "/runs",
            data={"project_root": project_root, "mode": "auto", "y": "y", "x": "x"},
            files={"file": ("data.csv", handle, "text/csv")},
        )

    list_response = client.get("/runs", params={"project_root": project_root})

    assert list_response.status_code == 200
    payload = list_response.json()
    assert "runs" in payload
    assert len(payload["runs"]) == 1
    summary = payload["runs"][0]
    assert summary["status"] == "completed"
    assert summary["mode"] == "auto"
    assert summary["y"] == "y"
    assert summary["x"] == ["x"]
    assert "started_at" in summary
    assert "run_id" in summary


def test_list_runs_returns_invalid_path_for_missing_project(tmp_path: Path):
    client = TestClient(app)
    list_response = client.get(
        "/runs", params={"project_root": str(tmp_path / "does_not_exist")}
    )

    assert list_response.status_code == 404
    assert list_response.json() == {
        "error": {
            "code": "PROJECT_NOT_FOUND",
            "message": f"Project not found: {tmp_path / 'does_not_exist'}",
            "details": {"project_root": str(tmp_path / "does_not_exist")},
        }
    }


def test_get_run_detail_returns_artifact_counts(tmp_path: Path):
    client = TestClient(app)
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "demo"},
    )
    project_root = response.json()["project_root"]
    data = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)
    with data.open("rb") as handle:
        run_response = client.post(
            "/runs",
            data={"project_root": project_root, "mode": "auto", "y": "y", "x": "x"},
            files={"file": ("data.csv", handle, "text/csv")},
        )
    run_id = run_response.json()["run_id"]

    detail_response = client.get(
        f"/runs/{run_id}", params={"project_root": project_root}
    )

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["run_id"] == run_id
    assert detail["status"] == "completed"
    assert detail["y"] == "y"
    assert detail["x"] == ["x"]
    assert "artifact_counts" in detail
    assert isinstance(detail["artifact_counts"], dict)
    assert sum(detail["artifact_counts"].values()) > 0
    assert detail["errors"] == {"issues": []}


def test_get_run_detail_returns_run_not_found(tmp_path: Path):
    client = TestClient(app)
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "demo"},
    )
    project_root = response.json()["project_root"]

    detail_response = client.get(
        "/runs/missing-run", params={"project_root": project_root}
    )

    assert detail_response.status_code == 404
    assert detail_response.json()["error"]["code"] == "RUN_NOT_FOUND"


def test_get_run_detail_rejects_path_escape(tmp_path: Path):
    client = TestClient(app)
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "demo"},
    )
    project_root = response.json()["project_root"]

    detail_response = client.get(
        "/runs/..%2Fescape", params={"project_root": project_root}
    )

    assert detail_response.status_code == 400
    assert detail_response.json()["error"]["code"] == "INVALID_PATH"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -v -k "list_runs or run_detail or path_escape"`

Expected: FAIL — endpoints don't exist yet.

- [ ] **Step 3: Add helpers and endpoints to `backend/workbench/api.py`**

Add to the imports:

```python
from .api_errors import (
    ERROR_INVALID_PATH,
    ERROR_PROJECT_NOT_FOUND,
    ERROR_RUN_NOT_FOUND,
    WorkbenchAPIError,
)
from .artifacts import read_json
```

Add these helpers below `_write_upload`:

```python
def _resolve_project_runs_dir(project_root: str) -> Path:
    project = Path(project_root).resolve()
    runs_dir = project / "runs"
    if not runs_dir.is_dir():
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_PROJECT_NOT_FOUND,
            message=f"Project not found: {project}",
            details={"project_root": str(project)},
        )
    return runs_dir


def _resolve_run_root(project_root: str, run_id: str) -> Path:
    runs_dir = _resolve_project_runs_dir(project_root)
    candidate = (runs_dir / run_id).resolve()
    try:
        candidate.relative_to(runs_dir.resolve())
    except ValueError as exc:
        raise WorkbenchAPIError(
            status_code=400,
            code=ERROR_INVALID_PATH,
            message="run_id must resolve inside the project's runs directory",
            details={"run_id": run_id},
        ) from exc
    if not candidate.is_dir():
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_RUN_NOT_FOUND,
            message=f"Run not found: {run_id}",
            details={"run_id": run_id, "project_root": project_root},
        )
    return candidate


def _read_manifest(run_root: Path) -> dict:
    manifest_path = run_root / "run_manifest.json"
    if not manifest_path.is_file():
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_RUN_NOT_FOUND,
            message=f"run_manifest.json missing for run: {run_root.name}",
            details={"run_id": run_root.name},
        )
    return read_json(manifest_path)


def _summarize_manifest(manifest: dict) -> dict:
    return {
        "run_id": manifest.get("run_id"),
        "status": manifest.get("status"),
        "mode": manifest.get("mode"),
        "started_at": manifest.get("started_at"),
        "y": manifest.get("y"),
        "x": manifest.get("x"),
    }


def _artifact_counts(run_root: Path) -> dict[str, int]:
    index_path = run_root / "artifacts_index.json"
    if not index_path.is_file():
        return {}
    index = read_json(index_path)
    counts: dict[str, int] = {}
    for record in index.get("artifacts", []):
        artifact_type = record.get("artifact_type", "unknown")
        counts[artifact_type] = counts.get(artifact_type, 0) + 1
    return counts
```

Add these endpoints below the helpers:

```python
@app.get("/runs")
def list_runs_endpoint(project_root: str) -> dict:
    runs_dir = _resolve_project_runs_dir(project_root)
    summaries: list[dict] = []
    for entry in sorted(runs_dir.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        manifest_path = entry / "run_manifest.json"
        if not manifest_path.is_file():
            continue
        summaries.append(_summarize_manifest(read_json(manifest_path)))
    return {"runs": summaries}


@app.get("/runs/{run_id}")
def get_run_endpoint(run_id: str, project_root: str) -> dict:
    run_root = _resolve_run_root(project_root, run_id)
    manifest = _read_manifest(run_root)
    summary = _summarize_manifest(manifest)
    errors_path = run_root / "errors.json"
    errors = read_json(errors_path) if errors_path.is_file() else {"issues": []}
    return {
        **summary,
        "lineage": manifest.get("lineage", []),
        "artifact_counts": _artifact_counts(run_root),
        "errors": errors,
    }
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_api.py -v -k "list_runs or run_detail or path_escape"`

Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `pytest -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/workbench/api.py tests/test_api.py
git commit -m "feat(api): add /runs list and /runs/{run_id} detail endpoints"
```

---

## Task 4: Artifact list and download endpoints

**Files:**
- Modify: `backend/workbench/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests at the bottom of `tests/test_api.py`**

```python
def test_list_artifacts_groups_by_type(tmp_path: Path):
    client = TestClient(app)
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "demo"},
    )
    project_root = response.json()["project_root"]
    data = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)
    with data.open("rb") as handle:
        run_response = client.post(
            "/runs",
            data={"project_root": project_root, "mode": "auto", "y": "y", "x": "x"},
            files={"file": ("data.csv", handle, "text/csv")},
        )
    run_id = run_response.json()["run_id"]

    artifacts_response = client.get(
        f"/runs/{run_id}/artifacts", params={"project_root": project_root}
    )

    assert artifacts_response.status_code == 200
    payload = artifacts_response.json()
    assert "groups" in payload
    by_type = {group["artifact_type"]: group for group in payload["groups"]}
    assert "report" in by_type
    assert "model_result" in by_type
    report_items = by_type["report"]["items"]
    assert any(item["artifact_id"] == "report_html" for item in report_items)
    for group in payload["groups"]:
        for item in group["items"]:
            assert "artifact_id" in item
            assert "path" in item
            assert "step" in item


def test_download_artifact_returns_file_with_attachment_disposition(tmp_path: Path):
    client = TestClient(app)
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "demo"},
    )
    project_root = response.json()["project_root"]
    data = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)
    with data.open("rb") as handle:
        run_response = client.post(
            "/runs",
            data={"project_root": project_root, "mode": "auto", "y": "y", "x": "x"},
            files={"file": ("data.csv", handle, "text/csv")},
        )
    run_id = run_response.json()["run_id"]

    download_response = client.get(
        f"/runs/{run_id}/artifacts/report_html",
        params={"project_root": project_root},
    )

    assert download_response.status_code == 200
    assert "attachment" in download_response.headers["content-disposition"]
    assert b"<html" in download_response.content.lower()


def test_download_artifact_returns_artifact_not_found(tmp_path: Path):
    client = TestClient(app)
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "demo"},
    )
    project_root = response.json()["project_root"]
    data = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)
    with data.open("rb") as handle:
        run_response = client.post(
            "/runs",
            data={"project_root": project_root, "mode": "auto", "y": "y", "x": "x"},
            files={"file": ("data.csv", handle, "text/csv")},
        )
    run_id = run_response.json()["run_id"]

    download_response = client.get(
        f"/runs/{run_id}/artifacts/does_not_exist",
        params={"project_root": project_root},
    )

    assert download_response.status_code == 404
    assert download_response.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -v -k "list_artifacts or download_artifact"`

Expected: FAIL — endpoints don't exist yet.

- [ ] **Step 3: Add helpers and endpoints to `backend/workbench/api.py`**

Add to the imports:

```python
from fastapi.responses import FileResponse
from .api_errors import ERROR_ARTIFACT_NOT_FOUND
```

Add helpers below `_artifact_counts`:

```python
def _read_artifact_records(run_root: Path) -> list[dict]:
    index_path = run_root / "artifacts_index.json"
    if not index_path.is_file():
        return []
    return list(read_json(index_path).get("artifacts", []))


def _group_artifacts(records: list[dict]) -> list[dict]:
    by_type: dict[str, list[dict]] = {}
    for record in records:
        artifact_type = record.get("artifact_type", "unknown")
        by_type.setdefault(artifact_type, []).append(
            {
                "artifact_id": record.get("artifact_id"),
                "path": record.get("path"),
                "artifact_type": artifact_type,
                "step": record.get("step"),
                "sha256": record.get("sha256"),
            }
        )
    return [
        {"artifact_type": artifact_type, "items": items}
        for artifact_type, items in sorted(by_type.items())
    ]


def _resolve_artifact_path(run_root: Path, record: dict) -> Path:
    relative = record.get("path")
    if not isinstance(relative, str) or relative == "":
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_ARTIFACT_NOT_FOUND,
            message="Artifact has no path",
            details={"artifact_id": record.get("artifact_id")},
        )
    candidate = (run_root / relative).resolve()
    try:
        candidate.relative_to(run_root.resolve())
    except ValueError as exc:
        raise WorkbenchAPIError(
            status_code=400,
            code=ERROR_INVALID_PATH,
            message="Artifact path resolved outside run root",
            details={"artifact_id": record.get("artifact_id")},
        ) from exc
    if not candidate.is_file():
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_ARTIFACT_NOT_FOUND,
            message=f"Artifact file missing on disk: {relative}",
            details={"artifact_id": record.get("artifact_id")},
        )
    return candidate
```

Add endpoints below the existing run endpoints:

```python
@app.get("/runs/{run_id}/artifacts")
def list_artifacts_endpoint(run_id: str, project_root: str) -> dict:
    run_root = _resolve_run_root(project_root, run_id)
    records = _read_artifact_records(run_root)
    return {"groups": _group_artifacts(records)}


@app.get("/runs/{run_id}/artifacts/{artifact_id}")
def download_artifact_endpoint(
    run_id: str, artifact_id: str, project_root: str
) -> FileResponse:
    run_root = _resolve_run_root(project_root, run_id)
    records = _read_artifact_records(run_root)
    matched = next(
        (record for record in records if record.get("artifact_id") == artifact_id),
        None,
    )
    if matched is None:
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_ARTIFACT_NOT_FOUND,
            message=f"Artifact not found: {artifact_id}",
            details={"artifact_id": artifact_id, "run_id": run_id},
        )
    path = _resolve_artifact_path(run_root, matched)
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/octet-stream",
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_api.py -v -k "list_artifacts or download_artifact"`

Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `pytest -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/workbench/api.py tests/test_api.py
git commit -m "feat(api): add artifact list and download endpoints"
```

---

## Task 5: Report endpoint

**Files:**
- Modify: `backend/workbench/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests at the bottom of `tests/test_api.py`**

```python
def test_get_report_returns_html(tmp_path: Path):
    client = TestClient(app)
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "demo"},
    )
    project_root = response.json()["project_root"]
    data = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)
    with data.open("rb") as handle:
        run_response = client.post(
            "/runs",
            data={"project_root": project_root, "mode": "auto", "y": "y", "x": "x"},
            files={"file": ("data.csv", handle, "text/csv")},
        )
    run_id = run_response.json()["run_id"]

    report_response = client.get(
        f"/runs/{run_id}/report", params={"project_root": project_root}
    )

    assert report_response.status_code == 200
    assert report_response.headers["content-type"].startswith("text/html")
    assert b"<html" in report_response.content.lower()


def test_get_report_returns_report_not_found_when_missing(tmp_path: Path):
    from workbench.projects import create_project, create_run

    create_project(tmp_path, "demo")
    project_root = tmp_path / "demo"
    run = create_run(project_root, mode="auto")

    client = TestClient(app)
    report_response = client.get(
        f"/runs/{run.run_id}/report", params={"project_root": str(project_root)}
    )

    assert report_response.status_code == 404
    assert report_response.json()["error"]["code"] == "REPORT_NOT_FOUND"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -v -k "get_report"`

Expected: FAIL — endpoint doesn't exist yet.

- [ ] **Step 3: Add the endpoint to `backend/workbench/api.py`**

Add to the imports:

```python
from .api_errors import ERROR_REPORT_NOT_FOUND
```

Add the endpoint below `download_artifact_endpoint`:

```python
@app.get("/runs/{run_id}/report")
def get_report_endpoint(run_id: str, project_root: str) -> FileResponse:
    run_root = _resolve_run_root(project_root, run_id)
    report_path = run_root / "reports" / "report.html"
    if not report_path.is_file():
        raise WorkbenchAPIError(
            status_code=404,
            code=ERROR_REPORT_NOT_FOUND,
            message="report.html not found for this run",
            details={"run_id": run_id},
        )
    return FileResponse(report_path, media_type="text/html")
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_api.py -v -k "get_report"`

Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `pytest -q`

Expected: all tests pass. Record total test count and report to user (e.g., "62 passed").

- [ ] **Step 6: Commit**

```bash
git add backend/workbench/api.py tests/test_api.py
git commit -m "feat(api): add /runs/{run_id}/report endpoint"
```

---

## Task 6: Frontend API client extension

**Files:**
- Modify: `frontend/src/api.ts`
- Create: `frontend/src/api.test.ts`

- [ ] **Step 1: Write the failing tests in `frontend/src/api.test.ts`**

```typescript
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  ApiError,
  fetchRunDetail,
  fetchRuns,
  fetchRunArtifacts,
  reportUrl,
  artifactDownloadUrl,
} from "./api";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

test("fetchRuns sends project_root query and returns runs array", async () => {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
    jsonResponse({
      runs: [
        {
          run_id: "abc",
          status: "completed",
          mode: "auto",
          started_at: "2026-05-01T00:00:00+00:00",
          y: "y",
          x: ["x"],
        },
      ],
    })
  );

  const result = await fetchRuns("/tmp/demo");

  expect(fetch).toHaveBeenCalledWith("/runs?project_root=%2Ftmp%2Fdemo");
  expect(result.runs).toHaveLength(1);
  expect(result.runs[0].run_id).toBe("abc");
});

test("fetchRunDetail returns artifact_counts and errors", async () => {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
    jsonResponse({
      run_id: "abc",
      status: "completed",
      mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00",
      y: "y",
      x: ["x"],
      lineage: [],
      artifact_counts: { report: 1, model_result: 1 },
      errors: { issues: [] },
    })
  );

  const detail = await fetchRunDetail("/tmp/demo", "abc");

  expect(fetch).toHaveBeenCalledWith(
    "/runs/abc?project_root=%2Ftmp%2Fdemo"
  );
  expect(detail.artifact_counts.report).toBe(1);
  expect(detail.errors.issues).toEqual([]);
});

test("fetchRunArtifacts returns groups array", async () => {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
    jsonResponse({
      groups: [
        {
          artifact_type: "report",
          items: [
            {
              artifact_id: "report_html",
              path: "reports/report.html",
              artifact_type: "report",
              step: "reporting",
              sha256: "deadbeef",
            },
          ],
        },
      ],
    })
  );

  const result = await fetchRunArtifacts("/tmp/demo", "abc");

  expect(result.groups[0].artifact_type).toBe("report");
  expect(result.groups[0].items[0].artifact_id).toBe("report_html");
});

test("error envelope is parsed into ApiError with code and details", async () => {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
    jsonResponse(
      {
        error: {
          code: "RUN_NOT_FOUND",
          message: "Run xyz not found",
          details: { run_id: "xyz" },
        },
      },
      404
    )
  );

  await expect(fetchRunDetail("/tmp/demo", "xyz")).rejects.toMatchObject({
    name: "ApiError",
    status: 404,
    code: "RUN_NOT_FOUND",
    message: "Run xyz not found",
  });
});

test("legacy FastAPI detail string is still parsed (POST /runs upload limit)", async () => {
  (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
    jsonResponse(
      { detail: "Uploaded file exceeds project size limit." },
      413
    )
  );

  await expect(fetchRuns("/tmp/demo")).rejects.toMatchObject({
    name: "ApiError",
    status: 413,
    message: "Uploaded file exceeds project size limit.",
  });
});

test("artifactDownloadUrl encodes project_root and ids", () => {
  const url = artifactDownloadUrl("/tmp/demo", "abc 123", "report_html");
  expect(url).toBe(
    "/runs/abc%20123/artifacts/report_html?project_root=%2Ftmp%2Fdemo"
  );
});

test("reportUrl encodes project_root", () => {
  const url = reportUrl("/tmp/demo", "abc");
  expect(url).toBe("/runs/abc/report?project_root=%2Ftmp%2Fdemo");
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- src/api.test.ts`

Expected: FAIL — `fetchRuns`, `fetchRunDetail`, `fetchRunArtifacts`, `reportUrl`, `artifactDownloadUrl` are not exported.

- [ ] **Step 3: Extend `frontend/src/api.ts`**

Add the new types after `RunResponse`:

```typescript
export type RunSummary = {
  run_id: string;
  status: string;
  mode: string;
  started_at: string | null;
  y: string | null;
  x: string[] | null;
};

export type RunDetail = RunSummary & {
  lineage: Array<{ source: string; artifact_id: string }>;
  artifact_counts: Record<string, number>;
  errors: { issues: Array<Record<string, unknown>> };
};

export type ArtifactItem = {
  artifact_id: string;
  path: string;
  artifact_type: string;
  step: string;
  sha256: string;
};

export type ArtifactGroup = {
  artifact_type: string;
  items: ArtifactItem[];
};

export type RunsListResponse = { runs: RunSummary[] };
export type ArtifactsResponse = { groups: ArtifactGroup[] };

export type ApiErrorEnvelope = {
  code: string;
  message: string;
  details: Record<string, unknown>;
};
```

Replace the existing `ApiError` class with:

```typescript
export class ApiError extends Error {
  status: number;
  code: string | null;
  detail: unknown;

  constructor(
    status: number,
    message: string,
    code: string | null = null,
    detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}
```

Replace the existing `readResponse` function with envelope-aware parsing:

```typescript
function isEnvelope(body: unknown): body is { error: ApiErrorEnvelope } {
  if (!body || typeof body !== "object") return false;
  const error = (body as { error?: unknown }).error;
  if (!error || typeof error !== "object") return false;
  return "code" in error && "message" in error;
}

async function readResponse<T>(response: Response): Promise<T> {
  if (response.ok) {
    return response.json() as Promise<T>;
  }
  let detail: unknown;
  let parsedMessage: string | null = null;
  let code: string | null = null;
  try {
    const body = await response.json();
    if (isEnvelope(body)) {
      detail = body.error.details;
      parsedMessage = body.error.message;
      code = body.error.code;
    } else if (body && typeof body === "object" && "detail" in body) {
      detail = (body as { detail: unknown }).detail;
      parsedMessage = extractDetailMessage(detail);
    }
  } catch {
    // Body was empty or non-JSON — fall through to generic message.
  }
  const message = parsedMessage ?? `Request failed with status ${response.status}`;
  throw new ApiError(response.status, message, code, detail);
}
```

Append the new client functions and URL helpers at the end of `frontend/src/api.ts`:

```typescript
export async function fetchRuns(projectRoot: string): Promise<RunsListResponse> {
  const url = `/runs?project_root=${encodeURIComponent(projectRoot)}`;
  const response = await fetch(url);
  return readResponse<RunsListResponse>(response);
}

export async function fetchRunDetail(
  projectRoot: string,
  runId: string,
): Promise<RunDetail> {
  const url = `/runs/${encodeURIComponent(runId)}?project_root=${encodeURIComponent(projectRoot)}`;
  const response = await fetch(url);
  return readResponse<RunDetail>(response);
}

export async function fetchRunArtifacts(
  projectRoot: string,
  runId: string,
): Promise<ArtifactsResponse> {
  const url = `/runs/${encodeURIComponent(runId)}/artifacts?project_root=${encodeURIComponent(projectRoot)}`;
  const response = await fetch(url);
  return readResponse<ArtifactsResponse>(response);
}

export function artifactDownloadUrl(
  projectRoot: string,
  runId: string,
  artifactId: string,
): string {
  return `/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId)}?project_root=${encodeURIComponent(projectRoot)}`;
}

export function reportUrl(projectRoot: string, runId: string): string {
  return `/runs/${encodeURIComponent(runId)}/report?project_root=${encodeURIComponent(projectRoot)}`;
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npm test -- src/api.test.ts`

Expected: PASS.

- [ ] **Step 5: Run all frontend tests**

Run: `cd frontend && npm test`

Expected: all tests pass (including existing `App.test.tsx` — the new `ApiError` constructor signature is backward-compatible because the `code` parameter defaults to `null`).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api.ts frontend/src/api.test.ts
git commit -m "feat(frontend): add typed clients for run/artifact/report endpoints"
```

---

## Task 7: Frontend run history and run detail views

**Files:**
- Create: `frontend/src/runHistory.tsx`
- Create: `frontend/src/runDetail.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/src/styles.css`

This task introduces the run-history and run-detail views without the artifact browser or report viewer (those land in Task 8). The detail view shows status, summary, lineage, artifact counts, and an errors panel.

- [ ] **Step 1: Write the failing tests in `frontend/src/App.test.tsx`**

Append at the end of the file:

```typescript
test("history tab fetches and lists runs for the current project", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      runs: [
        {
          run_id: "run-2",
          status: "completed",
          mode: "auto",
          started_at: "2026-05-01T01:00:00+00:00",
          y: "y",
          x: ["x"],
        },
        {
          run_id: "run-1",
          status: "blocked",
          mode: "auto",
          started_at: "2026-05-01T00:00:00+00:00",
          y: "y",
          x: ["x"],
        },
      ],
    })
  );

  render(<App />);
  await fillProject();

  fireEvent.click(screen.getByRole("tab", { name: "History" }));

  await waitFor(() => {
    expect(screen.getByText("run-1")).toBeInTheDocument();
  });
  expect(screen.getByText("run-2")).toBeInTheDocument();
  expect(screen.getByText("Blocked")).toBeInTheDocument();
});

test("clicking a history row loads run detail with errors", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      runs: [
        {
          run_id: "run-1",
          status: "blocked",
          mode: "auto",
          started_at: "2026-05-01T00:00:00+00:00",
          y: "y",
          x: ["x"],
        },
      ],
    })
  );
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "run-1",
      status: "blocked",
      mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00",
      y: "y",
      x: ["x"],
      lineage: [{ source: "/tmp/demo/data.csv", artifact_id: "raw_data.csv" }],
      artifact_counts: { metadata: 2, profile: 1 },
      errors: {
        issues: [
          {
            severity: "BLOCKER",
            code: "DATA_QUALITY",
            message: "Bad column",
            evidence: {},
          },
        ],
      },
    })
  );

  render(<App />);
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));
  await waitFor(() => screen.getByText("run-1"));

  fireEvent.click(screen.getByText("run-1"));

  await waitFor(() => {
    expect(
      screen.getByRole("heading", { name: /run detail/i })
    ).toBeInTheDocument();
  });
  expect(screen.getByText("Bad column")).toBeInTheDocument();
  expect(screen.getByText("DATA_QUALITY")).toBeInTheDocument();
});

test("history tab surfaces RUN_NOT_FOUND envelope in error panel", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse(
      {
        error: {
          code: "PROJECT_NOT_FOUND",
          message: "Project not found",
          details: {},
        },
      },
      404
    )
  );

  render(<App />);
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
  expect(screen.getByRole("alert")).toHaveTextContent("PROJECT_NOT_FOUND");
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test`

Expected: the three new tests FAIL (no `History` tab exists).

- [ ] **Step 3: Create `frontend/src/runHistory.tsx`**

```typescript
import { useEffect, useState } from "react";
import {
  ApiError,
  fetchRuns,
  type RunSummary,
} from "./api";

type Props = {
  projectRoot: string;
  onSelect: (runId: string) => void;
  onError: (message: string) => void;
};

function statusBadgeClass(status: string): string {
  if (status === "completed") return "badge badge-ok";
  if (status === "blocked" || status === "failed") return "badge badge-warn";
  return "badge badge-neutral";
}

function statusLabel(status: string): string {
  if (!status) return "—";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

export function RunHistoryPanel({ projectRoot, onSelect, onError }: Props) {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchRuns(projectRoot)
      .then((response) => {
        if (cancelled) return;
        setRuns(response.runs);
      })
      .catch((error) => {
        if (cancelled) return;
        const message =
          error instanceof ApiError
            ? `[${error.code ?? `HTTP ${error.status}`}] ${error.message}`
            : error instanceof Error
              ? error.message
              : "Failed to load runs";
        onError(message);
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot, onError]);

  if (runs === null) {
    return <p className="muted">Loading runs…</p>;
  }
  if (runs.length === 0) {
    return <p className="muted">No runs in this project yet.</p>;
  }

  return (
    <table className="runs-table" aria-label="run history">
      <thead>
        <tr>
          <th>Run ID</th>
          <th>Status</th>
          <th>Mode</th>
          <th>Started</th>
          <th>Y</th>
          <th>X</th>
        </tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <tr
            key={run.run_id}
            onClick={() => onSelect(run.run_id)}
            className="runs-row"
          >
            <td className="mono">{run.run_id}</td>
            <td>
              <span className={statusBadgeClass(run.status)}>
                {statusLabel(run.status)}
              </span>
            </td>
            <td>{run.mode ?? "—"}</td>
            <td>{run.started_at ?? "—"}</td>
            <td>{run.y ?? "—"}</td>
            <td>{(run.x ?? []).join(", ") || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 4: Create `frontend/src/runDetail.tsx`**

```typescript
import { useEffect, useState } from "react";
import {
  ApiError,
  fetchRunDetail,
  type RunDetail,
} from "./api";

type Props = {
  projectRoot: string;
  runId: string;
  onBack: () => void;
  onError: (message: string) => void;
};

function statusBadgeClass(status: string): string {
  if (status === "completed") return "badge badge-ok";
  if (status === "blocked" || status === "failed") return "badge badge-warn";
  return "badge badge-neutral";
}

function statusLabel(status: string): string {
  if (!status) return "—";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

type IssueRecord = {
  severity?: string;
  code?: string;
  message?: string;
};

export function RunDetailPanel({ projectRoot, runId, onBack, onError }: Props) {
  const [detail, setDetail] = useState<RunDetail | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchRunDetail(projectRoot, runId)
      .then((value) => {
        if (cancelled) return;
        setDetail(value);
      })
      .catch((error) => {
        if (cancelled) return;
        const message =
          error instanceof ApiError
            ? `[${error.code ?? `HTTP ${error.status}`}] ${error.message}`
            : error instanceof Error
              ? error.message
              : "Failed to load run detail";
        onError(message);
      });
    return () => {
      cancelled = true;
    };
  }, [projectRoot, runId, onError]);

  if (detail === null) {
    return <p className="muted">Loading run…</p>;
  }

  const issues = (detail.errors?.issues ?? []) as IssueRecord[];

  return (
    <section className="panel" aria-labelledby="run-detail-heading">
      <div className="panel-heading">
        <h2 id="run-detail-heading">Run detail</h2>
        <button type="button" onClick={onBack}>
          Back to history
        </button>
      </div>
      <dl className="summary-list">
        <div>
          <dt>Run ID</dt>
          <dd className="mono">{detail.run_id}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>
            <span className={statusBadgeClass(detail.status)}>
              {statusLabel(detail.status)}
            </span>
          </dd>
        </div>
        <div>
          <dt>Mode</dt>
          <dd>{detail.mode ?? "—"}</dd>
        </div>
        <div>
          <dt>Started</dt>
          <dd>{detail.started_at ?? "—"}</dd>
        </div>
        <div>
          <dt>Y</dt>
          <dd>{detail.y ?? "—"}</dd>
        </div>
        <div>
          <dt>X</dt>
          <dd>{(detail.x ?? []).join(", ") || "—"}</dd>
        </div>
      </dl>
      <h3 className="subhead">Artifact counts</h3>
      <ul className="path-list" aria-label="artifact counts">
        {Object.entries(detail.artifact_counts).map(([type, count]) => (
          <li key={type} className="mono">
            {type}: {count}
          </li>
        ))}
      </ul>
      {issues.length > 0 && (
        <section className="panel panel-error" role="alert">
          <strong>Issues</strong>
          <ul>
            {issues.map((issue, index) => (
              <li key={index}>
                <strong>{issue.code ?? "ISSUE"}</strong>: {issue.message ?? ""}
              </li>
            ))}
          </ul>
        </section>
      )}
    </section>
  );
}
```

- [ ] **Step 5: Add tab navigation to `frontend/src/App.tsx`**

Add the imports near the top:

```typescript
import { RunHistoryPanel } from "./runHistory";
import { RunDetailPanel } from "./runDetail";
```

Inside `App()`, add a new view-state hook just below the existing `useState` calls:

```typescript
type ViewState = { name: "submit" } | { name: "history" } | { name: "detail"; runId: string };
const [view, setView] = useState<ViewState>({ name: "submit" });
const [historyKey, setHistoryKey] = useState(0);
```

Replace the existing `<main className="workbench-shell">` opening section so it includes a tab strip. Find the `<header className="workbench-header">` block (around lines 128-136) and immediately after the closing `</header>` and the existing `errorMessage` block, add:

```tsx
<nav className="tabs" role="tablist" aria-label="workbench views">
  <button
    type="button"
    role="tab"
    aria-selected={view.name === "submit"}
    onClick={() => setView({ name: "submit" })}
  >
    Submit
  </button>
  <button
    type="button"
    role="tab"
    aria-selected={view.name === "history" || view.name === "detail"}
    disabled={projectRoot === ""}
    onClick={() => {
      setView({ name: "history" });
      setHistoryKey((value) => value + 1);
      setErrorMessage(null);
    }}
  >
    History
  </button>
</nav>
```

Wrap the existing project, run, and last-run panels (the three `<section className="panel">` blocks) so they only render when `view.name === "submit"`. The simplest pattern is:

```tsx
{view.name === "submit" && (
  <>
    {/* existing project panel */}
    {/* existing run panel */}
    {/* existing last-run panel */}
  </>
)}
```

After that fragment, render the history and detail panels:

```tsx
{view.name === "history" && projectRoot && (
  <section className="panel" aria-labelledby="history-heading">
    <div className="panel-heading">
      <h2 id="history-heading">Run history</h2>
      <span>{projectRoot}</span>
    </div>
    <RunHistoryPanel
      key={historyKey}
      projectRoot={projectRoot}
      onSelect={(runId) => setView({ name: "detail", runId })}
      onError={(message) => setErrorMessage(message)}
    />
  </section>
)}
{view.name === "detail" && projectRoot && (
  <RunDetailPanel
    projectRoot={projectRoot}
    runId={view.runId}
    onBack={() => {
      setView({ name: "history" });
      setHistoryKey((value) => value + 1);
      setErrorMessage(null);
    }}
    onError={(message) => setErrorMessage(message)}
  />
)}
```

- [ ] **Step 6: Add minimal CSS to `frontend/src/styles.css`**

Append at the end of the file:

```css
.tabs {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1rem;
}
.tabs button[aria-selected="true"] {
  font-weight: 600;
  border-bottom: 2px solid currentColor;
}
.runs-table {
  width: 100%;
  border-collapse: collapse;
}
.runs-table th,
.runs-table td {
  text-align: left;
  padding: 0.4rem 0.6rem;
  border-bottom: 1px solid #e5e7eb;
}
.runs-row {
  cursor: pointer;
}
.runs-row:hover {
  background: #f3f4f6;
}
```

- [ ] **Step 7: Run the new tests**

Run: `cd frontend && npm test`

Expected: all tests pass — original 6 + new 3 history/detail tests + Task 6's api.test.ts tests.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/runHistory.tsx frontend/src/runDetail.tsx frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/styles.css
git commit -m "feat(frontend): add run history and run detail views"
```

---

## Task 8: Frontend artifact browser and report viewer

**Files:**
- Modify: `frontend/src/runDetail.tsx`
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/src/styles.css`

The artifact browser and report viewer live inside the `RunDetailPanel` so the detail page shows everything for one run. Selecting "View report" toggles the iframe; the artifact list always shows.

- [ ] **Step 1: Write the failing tests in `frontend/src/App.test.tsx`**

Append to the end of the file:

```typescript
test("run detail shows artifact list with download links", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      runs: [
        {
          run_id: "run-1",
          status: "completed",
          mode: "auto",
          started_at: "2026-05-01T00:00:00+00:00",
          y: "y",
          x: ["x"],
        },
      ],
    })
  );
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "run-1",
      status: "completed",
      mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00",
      y: "y",
      x: ["x"],
      lineage: [],
      artifact_counts: { report: 1 },
      errors: { issues: [] },
    })
  );
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      groups: [
        {
          artifact_type: "report",
          items: [
            {
              artifact_id: "report_html",
              path: "reports/report.html",
              artifact_type: "report",
              step: "reporting",
              sha256: "deadbeef",
            },
          ],
        },
      ],
    })
  );

  render(<App />);
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));
  await waitFor(() => screen.getByText("run-1"));
  fireEvent.click(screen.getByText("run-1"));

  await waitFor(() => screen.getByRole("heading", { name: /artifacts/i }));

  const downloadLink = screen.getByRole("link", { name: /report_html/i });
  expect(downloadLink).toHaveAttribute(
    "href",
    "/runs/run-1/artifacts/report_html?project_root=%2Ftmp%2Fdemo",
  );
});

test("view report toggles iframe with report URL", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      runs: [
        {
          run_id: "run-1",
          status: "completed",
          mode: "auto",
          started_at: "2026-05-01T00:00:00+00:00",
          y: "y",
          x: ["x"],
        },
      ],
    })
  );
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "run-1",
      status: "completed",
      mode: "auto",
      started_at: "2026-05-01T00:00:00+00:00",
      y: "y",
      x: ["x"],
      lineage: [],
      artifact_counts: { report: 1 },
      errors: { issues: [] },
    })
  );
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      groups: [
        {
          artifact_type: "report",
          items: [
            {
              artifact_id: "report_html",
              path: "reports/report.html",
              artifact_type: "report",
              step: "reporting",
              sha256: "deadbeef",
            },
          ],
        },
      ],
    })
  );

  render(<App />);
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));
  await waitFor(() => screen.getByText("run-1"));
  fireEvent.click(screen.getByText("run-1"));

  await waitFor(() => screen.getByRole("button", { name: /view report/i }));
  fireEvent.click(screen.getByRole("button", { name: /view report/i }));

  const iframe = screen.getByTitle("Run report") as HTMLIFrameElement;
  expect(iframe.src).toContain(
    "/runs/run-1/report?project_root=%2Ftmp%2Fdemo",
  );
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test`

Expected: the two new tests FAIL — artifact browser and report viewer don't exist yet.

- [ ] **Step 3: Extend `frontend/src/runDetail.tsx`**

At the top of the file, replace the import block with:

```typescript
import { useEffect, useState } from "react";
import {
  ApiError,
  artifactDownloadUrl,
  fetchRunArtifacts,
  fetchRunDetail,
  reportUrl,
  type ArtifactGroup,
  type RunDetail,
} from "./api";
```

Inside `RunDetailPanel`, add two more pieces of state and an effect for artifacts:

```typescript
const [groups, setGroups] = useState<ArtifactGroup[] | null>(null);
const [showReport, setShowReport] = useState(false);

useEffect(() => {
  let cancelled = false;
  fetchRunArtifacts(projectRoot, runId)
    .then((value) => {
      if (cancelled) return;
      setGroups(value.groups);
    })
    .catch((error) => {
      if (cancelled) return;
      const message =
        error instanceof ApiError
          ? `[${error.code ?? `HTTP ${error.status}`}] ${error.message}`
          : error instanceof Error
            ? error.message
            : "Failed to load artifacts";
      onError(message);
    });
  return () => {
    cancelled = true;
  };
}, [projectRoot, runId, onError]);
```

Append to the JSX returned by `RunDetailPanel` (before the closing `</section>`):

```tsx
<section aria-labelledby="report-heading">
  <h3 id="report-heading" className="subhead">
    Report
  </h3>
  <button type="button" onClick={() => setShowReport((value) => !value)}>
    {showReport ? "Hide report" : "View report"}
  </button>
  <a
    className="report-link"
    href={reportUrl(projectRoot, runId)}
    target="_blank"
    rel="noreferrer"
  >
    Open in new tab
  </a>
  {showReport && (
    <iframe
      title="Run report"
      src={reportUrl(projectRoot, runId)}
      className="report-frame"
    />
  )}
</section>
<section aria-labelledby="artifacts-heading">
  <h3 id="artifacts-heading" className="subhead">
    Artifacts
  </h3>
  {groups === null ? (
    <p className="muted">Loading artifacts…</p>
  ) : groups.length === 0 ? (
    <p className="muted">No artifacts recorded.</p>
  ) : (
    groups.map((group) => (
      <div key={group.artifact_type} className="artifact-group">
        <h4>{group.artifact_type}</h4>
        <ul>
          {group.items.map((item) => (
            <li key={item.artifact_id}>
              <a
                href={artifactDownloadUrl(projectRoot, runId, item.artifact_id)}
              >
                {item.artifact_id}
              </a>
              <span className="mono"> · {item.path}</span>
              <span className="muted"> · {item.step}</span>
            </li>
          ))}
        </ul>
      </div>
    ))
  )}
</section>
```

- [ ] **Step 4: Append CSS to `frontend/src/styles.css`**

```css
.report-frame {
  width: 100%;
  height: 600px;
  margin-top: 0.75rem;
  border: 1px solid #d1d5db;
}
.report-link {
  margin-left: 0.75rem;
}
.artifact-group {
  margin-top: 0.75rem;
}
.artifact-group h4 {
  margin: 0 0 0.25rem;
  font-size: 0.95rem;
}
```

- [ ] **Step 5: Run the new tests**

Run: `cd frontend && npm test`

Expected: all frontend tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/runDetail.tsx frontend/src/App.test.tsx frontend/src/styles.css
git commit -m "feat(frontend): add artifact browser and embedded report viewer"
```

---

## Task 9: Closure — full sweep, README note, plan completion

**Files:**
- Modify: `README.md` (only if a result-browser section is missing — verify first)
- Modify: `docs/superpowers/plans/2026-05-01-workbench-frontend-api-enhancements.md`

- [ ] **Step 1: Run the entire backend suite**

Run: `pytest -q`

Expected: all tests pass. Capture and report the final pass count to the user.

- [ ] **Step 2: Run the entire frontend suite**

Run: `cd frontend && npm test`

Expected: all tests pass.

- [ ] **Step 3: Check README for V1.1 surface mention**

Run: `grep -n "/runs?\|run history\|result browser" README.md`

If V1.1 endpoints are not mentioned, add a short "V1.1 Result Browser" subsection under the existing API section listing the five endpoints and noting that the frontend now has a History tab. Keep it under ~12 lines. If they are already mentioned, skip the README change.

- [ ] **Step 4: Mark plan tasks complete**

In this very plan file (`docs/superpowers/plans/2026-05-01-workbench-frontend-api-enhancements.md`), flip every `- [ ]` checkbox to `- [x]` for tasks that are done. (The implementer should keep flipping checkboxes as they go; this step is the final sweep to ensure nothing was missed.)

- [ ] **Step 5: Commit closure**

```bash
git add README.md docs/superpowers/plans/2026-05-01-workbench-frontend-api-enhancements.md
git commit -m "docs: mark V1.1 plan complete"
```

- [ ] **Step 6: Push and open PR (waits for user)**

Do not push or open a PR autonomously. Report to the user: "V1.1 implementation complete. Backend: <N> passed. Frontend: <M> passed. Ready to push and open PR."

---

## Final Verification Checklist

Before reporting completion to the user, confirm all of the following:

- Backend pytest: all tests pass, including new endpoint and error envelope tests.
- Frontend vitest: all tests pass, including api, runHistory, runDetail, and App tests.
- `_write_manifest` writes `started_at` / `y` / `x` and is called at run start (status=`running`), before any blocked/failed/completed transitions.
- `WorkbenchAPIError` envelope is the only error format on V1.1 endpoints (legacy `POST /runs` HTTPException with `detail` is unchanged).
- No `react-router` or state-library dependency was added.
- No new write-side endpoint exists; all V1.1 endpoints are GET.
- Path-resolution helpers reject any input that escapes `project_root`.
- `frontend/src/api.ts` `ApiError` continues to satisfy existing `App.test.tsx` cases (FastAPI `detail` parsing).
