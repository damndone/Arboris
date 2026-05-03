# V1.2.0 Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Harden the V1.1 codebase by adding artifact registry schema/version, report iframe sandbox, artifact error visibility with Retry, and legacy run compatibility tests.

**Architecture:** Backend changes add a `_read_artifacts_index` helper in `api.py` that validates `schema_version` on every registry read, and add `schema_version: 1` to orchestrator writes. Frontend changes upgrade the artifact loading state machine from a two-state to a three-state discriminated union with Retry, and add `sandbox` to the report iframe. New test files cover legacy run compatibility and report content safety.

**Tech Stack:** Python 3.11+, FastAPI, pytest, React 18, Vite, TypeScript, Vitest, Testing Library.

---

## File Structure

**Backend:**
- Modify: `backend/workbench/api_errors.py` — add `ERROR_REGISTRY_VERSION_UNSUPPORTED`, `ERROR_REGISTRY_VERSION_INVALID`
- Modify: `backend/workbench/api.py` — add `_read_artifacts_index` helper, replace `_read_artifact_records` / `_artifact_counts` / download endpoint to use it
- Modify: `backend/workbench/orchestrator.py` — add `schema_version: 1` when writing `artifacts_index.json` at run start (in `create_run` path via `projects.py`)
- Modify: `tests/test_api.py` — add 6 registry version test cases
- Modify: `tests/test_api_errors.py` — add 2 new error code envelope tests
- Modify: `tests/test_orchestrator_e2e.py` — add assertion on `schema_version: 1`
- Create: `tests/test_legacy_run_compat.py` — V1 and broken-artifact fixture + endpoint assertions
- Create: `tests/test_report_no_scripts.py` — render minimal report and scan for scripts/events

**Frontend:**
- Modify: `frontend/src/runDetail.tsx` — three-state artifact state machine + `sandbox` on iframe
- Modify: `frontend/src/App.test.tsx` — artifact error + Retry test, iframe sandbox test

---

## Task 1: Artifact registry schema/version

**Files:**
- Modify: `backend/workbench/api_errors.py`
- Modify: `backend/workbench/api.py`
- Modify: `backend/workbench/projects.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_api_errors.py`
- Modify: `tests/test_orchestrator_e2e.py`

- [x] **Step 1: Add error code constants to `api_errors.py`**

Append after `ERROR_INVALID_PATH`:

```python
ERROR_REGISTRY_VERSION_UNSUPPORTED = "REGISTRY_VERSION_UNSUPPORTED"
ERROR_REGISTRY_VERSION_INVALID = "REGISTRY_VERSION_INVALID"
```

Total file after edit — 14 lines of constants, no structural changes.

- [x] **Step 2: Write failing tests in `tests/test_api.py`**

Append after the last line. These tests cover the `_read_artifacts_index` helper and the three call sites (list, count, download). Each test creates a project with `TestClient`, then writes an `artifacts_index.json` fixture directly to disk.

```python
def test_artifacts_index_missing_schema_version_is_ok(tmp_path: Path):
    """Old V1 index with no schema_version → treated as v1, parsed normally."""
    from workbench.api import _read_artifacts_index
    from workbench.projects import create_project

    project = tmp_path / "proj"
    create_project(tmp_path, "proj")
    run_root = project / "runs" / "r1"
    run_root.mkdir(parents=True)
    # Write old-style index without schema_version
    index = {"artifacts": [{"artifact_id": "a", "path": "a.txt", "artifact_type": "data", "step": "ingest", "sha256": "x"}]}
    (run_root / "artifacts_index.json").write_text(json.dumps(index), encoding="utf-8")
    (run_root / "a.txt").write_text("content", encoding="utf-8")

    data = _read_artifacts_index(run_root)
    assert len(data["artifacts"]) == 1
    assert data["artifacts"][0]["artifact_id"] == "a"


def test_artifacts_index_version_1_is_ok(tmp_path: Path):
    """New index with schema_version: 1 → parsed normally."""
    from workbench.api import _read_artifacts_index
    from workbench.projects import create_project

    project = tmp_path / "proj"
    create_project(tmp_path, "proj")
    run_root = project / "runs" / "r1"
    run_root.mkdir(parents=True)
    index = {"schema_version": 1, "artifacts": [{"artifact_id": "a", "path": "a.txt", "artifact_type": "data", "step": "ingest", "sha256": "x"}]}
    (run_root / "artifacts_index.json").write_text(json.dumps(index), encoding="utf-8")
    (run_root / "a.txt").write_text("content", encoding="utf-8")

    data = _read_artifacts_index(run_root)
    assert len(data["artifacts"]) == 1


def test_artifacts_index_version_2_rejected(tmp_path: Path):
    """Future version 2 → 500 REGISTRY_VERSION_UNSUPPORTED."""
    from workbench.api import _read_artifacts_index
    from workbench.api_errors import WorkbenchAPIError
    from workbench.projects import create_project

    project = tmp_path / "proj"
    create_project(tmp_path, "proj")
    run_root = project / "runs" / "r1"
    run_root.mkdir(parents=True)
    index = {"schema_version": 2, "artifacts": []}
    (run_root / "artifacts_index.json").write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(WorkbenchAPIError) as exc:
        _read_artifacts_index(run_root)
    assert exc.value.code == "REGISTRY_VERSION_UNSUPPORTED"


def test_artifacts_index_version_string_rejected(tmp_path: Path):
    """Non-integer schema_version → 500 REGISTRY_VERSION_INVALID."""
    from workbench.api import _read_artifacts_index
    from workbench.api_errors import WorkbenchAPIError
    from workbench.projects import create_project

    project = tmp_path / "proj"
    create_project(tmp_path, "proj")
    run_root = project / "runs" / "r1"
    run_root.mkdir(parents=True)
    index = {"schema_version": "1", "artifacts": []}
    (run_root / "artifacts_index.json").write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(WorkbenchAPIError) as exc:
        _read_artifacts_index(run_root)
    assert exc.value.code == "REGISTRY_VERSION_INVALID"


def test_artifacts_index_version_zero_rejected(tmp_path: Path):
    """schema_version 0 → 500 REGISTRY_VERSION_INVALID."""
    from workbench.api import _read_artifacts_index
    from workbench.api_errors import WorkbenchAPIError
    from workbench.projects import create_project

    project = tmp_path / "proj"
    create_project(tmp_path, "proj")
    run_root = project / "runs" / "r1"
    run_root.mkdir(parents=True)
    index = {"schema_version": 0, "artifacts": []}
    (run_root / "artifacts_index.json").write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(WorkbenchAPIError) as exc:
        _read_artifacts_index(run_root)
    assert exc.value.code == "REGISTRY_VERSION_INVALID"


def test_artifacts_list_and_download_use_schema_validated_index(completed_run):
    """The three consumer functions use _read_artifacts_index under the hood.
    A normal run produces schema_version=1, so the existing happy-path
    tests for list, detail, and download continue to pass.  This test adds
    explicit coverage that the helper is wired into the download call path."""
    client, project_root, run_id = completed_run

    # list_artifacts returns normally
    list_resp = client.get(
        f"/runs/{run_id}/artifacts", params={"project_root": project_root}
    )
    assert list_resp.status_code == 200
    assert "groups" in list_resp.json()

    # download returns normally
    dl_resp = client.get(
        f"/runs/{run_id}/artifacts/report_html",
        params={"project_root": project_root},
    )
    assert dl_resp.status_code == 200
```

Add `import json` to the top of `tests/test_api.py` if not already present.

- [x] **Step 3: Run the failing tests**

Run: `.venv/bin/pytest tests/test_api.py -v -k "artifacts_index"`

Expected: FAIL — `_read_artifacts_index` is not defined in `api.py`.

- [x] **Step 4: Write failing tests in `tests/test_api_errors.py`**

Append after `test_workbench_api_error_default_details_is_empty_dict`:

```python
def test_registry_version_unsupported_has_correct_code():
    from workbench.api_errors import ERROR_REGISTRY_VERSION_UNSUPPORTED

    assert ERROR_REGISTRY_VERSION_UNSUPPORTED == "REGISTRY_VERSION_UNSUPPORTED"
```

- [x] **Step 5: Write failing test in `tests/test_orchestrator_e2e.py`**

Append after `test_manifest_contains_started_at_y_and_x`:

```python
def test_new_run_artifacts_index_has_schema_version(tmp_path: Path):
    project_root = tmp_path / "proj"
    create_project(tmp_path, "proj")
    data = project_root / "data.csv"
    pd.DataFrame(
        {"y": [1 + 2 * i for i in range(35)], "x": list(range(35))}
    ).to_csv(data, index=False)

    result = run_workflow(project_root, [data], mode="auto", y="y", x=["x"])

    index_path = project_root / "runs" / result["run_id"] / "artifacts_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index.get("schema_version") == 1
```

- [x] **Step 6: Add `_read_artifacts_index` helper and replace call sites in `api.py`**

In the import block, add the new error codes:

```python
from .api_errors import (
    ERROR_ARTIFACT_NOT_FOUND,
    ERROR_INVALID_PATH,
    ERROR_PROJECT_NOT_FOUND,
    ERROR_REGISTRY_VERSION_INVALID,
    ERROR_REGISTRY_VERSION_UNSUPPORTED,
    ERROR_REPORT_NOT_FOUND,
    ERROR_RUN_NOT_FOUND,
    WorkbenchAPIError,
)
```

Add `SUPPORTED_REGISTRY_VERSION` and `_read_artifacts_index` after `_artifact_counts`:

```python
SUPPORTED_REGISTRY_VERSION = 1


def _read_artifacts_index(run_root: Path) -> dict:
    index_path = run_root / "artifacts_index.json"
    if not index_path.is_file():
        return {"artifacts": []}
    data = read_json(index_path)
    raw = data.get("schema_version", 1)
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise WorkbenchAPIError(
            status_code=500,
            code=ERROR_REGISTRY_VERSION_INVALID,
            message="artifacts_index.json schema_version is not an integer",
            details={"found": raw, "type": type(raw).__name__},
        )
    if raw < 1:
        raise WorkbenchAPIError(
            status_code=500,
            code=ERROR_REGISTRY_VERSION_INVALID,
            message=f"artifacts_index.json schema_version must be >= 1, got {raw}",
            details={"found": raw},
        )
    if raw > SUPPORTED_REGISTRY_VERSION:
        raise WorkbenchAPIError(
            status_code=500,
            code=ERROR_REGISTRY_VERSION_UNSUPPORTED,
            message=f"artifacts_index.json schema_version {raw} not supported",
            details={"found": raw, "supported": SUPPORTED_REGISTRY_VERSION},
        )
    return data
```

Replace `_artifact_counts` body to use `_read_artifacts_index` instead of direct `read_json`:

```python
def _artifact_counts(run_root: Path) -> dict[str, int]:
    index = _read_artifacts_index(run_root)
    counts: dict[str, int] = {}
    for record in index.get("artifacts", []):
        artifact_type = record.get("artifact_type", "unknown")
        counts[artifact_type] = counts.get(artifact_type, 0) + 1
    return counts
```

Replace `_read_artifact_records` body:

```python
def _read_artifact_records(run_root: Path) -> list[dict]:
    return list(_read_artifacts_index(run_root).get("artifacts", []))
```

No changes needed to `_group_artifacts`, `_resolve_artifact_path`, or the endpoints themselves — they call `_read_artifact_records` which now goes through the validated helper.

- [x] **Step 7: Add `schema_version: 1` to project creation in `projects.py`**

In `projects.py` around line 76, change:

```python
write_json(root / "artifacts_index.json", {"artifacts": []})
```

to:

```python
write_json(root / "artifacts_index.json", {"schema_version": 1, "artifacts": []})
```

- [x] **Step 8: Run tests**

Run: `.venv/bin/pytest -q`

Expected: all tests pass (75 + new registry tests).

- [x] **Step 9: Commit**

```bash
git add backend/workbench/api_errors.py backend/workbench/api.py backend/workbench/projects.py tests/test_api.py tests/test_api_errors.py tests/test_orchestrator_e2e.py
git commit -m "feat(artifacts): add registry schema_version validation"
```

---

## Task 2: Report iframe sandbox

**Files:**
- Modify: `frontend/src/runDetail.tsx`
- Modify: `frontend/src/App.test.tsx`
- Create: `tests/test_report_no_scripts.py`

- [x] **Step 1: Write the failing frontend test in `frontend/src/App.test.tsx`**

Append at the end of the file:

```typescript
test("report iframe has sandbox attribute restricting scripts", async () => {
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
  expect(iframe.getAttribute("sandbox")).toBe("allow-same-origin");
});
```

- [x] **Step 2: Write the backend test in `tests/test_report_no_scripts.py`**

The test renders the Jinja2 template directly with a minimal fixture (avoiding `render_html_report`'s disk and registry side effects), then scans the output HTML.

```python
"""Report output must not contain executable content that
would be blocked by the sandbox attribute."""

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


_TEMPLATE_DIR = Path(__file__).parent.parent / "backend" / "workbench" / "templates"


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )


def _minimal_report() -> dict:
    return {
        "title": "Test Report",
        "facts": ["Fact 1", "Fact 2"],
        "claims": [
            {"claim": "Claim 1", "source_id": "src1", "confidence": 0.95},
        ],
        "warnings": [],
    }


class TestReportContent:
    def test_no_script_tags(self):
        html = _environment().get_template("report.html.j2").render(report=_minimal_report())
        assert "<script" not in html

    def test_no_javascript_uris(self):
        html = _environment().get_template("report.html.j2").render(report=_minimal_report())
        assert "javascript:" not in html.lower()

    def test_no_inline_event_handlers(self):
        html = _environment().get_template("report.html.j2").render(report=_minimal_report())
        assert not re.search(r"\son[a-zA-Z]+\s*=", html, re.IGNORECASE)
```

- [x] **Step 3: Run tests to verify they fail**

Frontend:
```
npm test -- --run src/App.test.tsx
```
Expected: 12 existing pass, sandbox test fails because iframe has no `sandbox` attribute.

Backend:
```
.venv/bin/pytest tests/test_report_no_scripts.py -v
```
Expected: FAIL — `reporting` module path may need adjustment.

- [x] **Step 4: Add sandbox attribute to iframe in `frontend/src/runDetail.tsx`**

Change line 155-159:

```tsx
{showReport && (
  <iframe
    title="Run report"
    src={reportUrl(projectRoot, runId)}
    className="report-frame"
    sandbox="allow-same-origin"
  />
)}
```

- [x] **Step 5: Run all tests**

Frontend: `npm test -- --run` — all 20 pass.
Backend: `.venv/bin/pytest -q` — all existing + new report tests pass.

- [x] **Step 6: Commit**

```bash
git add frontend/src/runDetail.tsx frontend/src/App.test.tsx tests/test_report_no_scripts.py
git commit -m "feat: add iframe sandbox and report content safety test"
```

---

## Task 3: Artifact error visibility with Retry

**Files:**
- Modify: `frontend/src/runDetail.tsx`
- Modify: `frontend/src/App.test.tsx`

- [x] **Step 1: Write the failing test in `frontend/src/App.test.tsx`**

Append at the end of the file:

```typescript
test("artifact fetch error shows retry button; retry succeeds", async () => {
  const fetchMock = fetch as unknown as ReturnType<typeof vi.fn>;

  // createProject, fetchRuns, fetchRunDetail all succeed
  fetchMock.mockResolvedValueOnce(jsonResponse({ project_root: "/tmp/demo" }));
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      runs: [{ run_id: "run-1", status: "completed", mode: "auto", started_at: null, y: null, x: null }],
    })
  );
  fetchMock.mockResolvedValueOnce(
    jsonResponse({
      run_id: "run-1", status: "completed", mode: "auto", started_at: null, y: null, x: null,
      lineage: [], artifact_counts: {}, errors: { issues: [] },
    })
  );

  // fetchRunArtifacts rejects the first time
  fetchMock.mockRejectedValueOnce(new Error("Network failure"));

  render(<App />);
  await fillProject();
  fireEvent.click(screen.getByRole("tab", { name: "History" }));
  await waitFor(() => screen.getByText("run-1"));
  fireEvent.click(screen.getByText("run-1"));

  // Error state should show failure message and retry button
  await waitFor(() => {
    expect(screen.getByText(/failed to load artifacts/i)).toBeInTheDocument();
  });
  const retryButton = screen.getByRole("button", { name: /retry/i });
  expect(retryButton).toBeInTheDocument();

  // Second attempt succeeds
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
              sha256: "x",
            },
          ],
        },
      ],
    })
  );

  fireEvent.click(retryButton);

  await waitFor(() => {
    expect(screen.getByText("report_html")).toBeInTheDocument();
  });
});
```

- [x] **Step 2: Run to verify it fails**

```
npm test -- --run src/App.test.tsx
```

Expected: 12 existing pass, new test fails because the panel doesn't show a retry button.

- [x] **Step 3: Update `frontend/src/runDetail.tsx` — three‑state machine + Retry**

Change the imports to add `useRef` and `useCallback`:

```typescript
import { useCallback, useEffect, useRef, useState } from "react";
```

Keep the existing imports from `./api` as-is.

Replace the `groups` state and `showReport` state. Keep `showReport` as-is. Replace `groups` with a discriminated union:

```typescript
type ArtifactsState =
  | { status: "loading" }
  | { status: "loaded"; groups: ArtifactGroup[] }
  | { status: "error"; message: string };

const [artifactsState, setArtifactsState] = useState<ArtifactsState>({ status: "loading" });
```

Replace the artifacts `useEffect`:

```typescript
const fetchIdRef = useRef(0);

const fetchArtifacts = useCallback(() => {
  const id = ++fetchIdRef.current;
  setArtifactsState({ status: "loading" });
  fetchRunArtifacts(projectRoot, runId)
    .then((value) => {
      if (id !== fetchIdRef.current) return;
      setArtifactsState({ status: "loaded", groups: value.groups });
    })
    .catch((error) => {
      if (id !== fetchIdRef.current) return;
      const message =
        error instanceof ApiError
          ? `[${error.code ?? `HTTP ${error.status}`}] ${error.message}`
          : error instanceof Error
            ? error.message
            : "Unknown error";
      setArtifactsState({ status: "error", message });
    });
}, [projectRoot, runId]);

useEffect(() => {
  fetchArtifacts();
  return () => {
    fetchIdRef.current += 1; // invalidate any in-flight callback
  };
}, [fetchArtifacts]);
```

Replace the JSX for the artifacts section (lines 162-189). The render logic changes from `groups === null / groups.length === 0 / groups.map` to a `switch` on `artifactsState.status`:

```tsx
<section aria-labelledby="artifacts-heading">
  <h3 id="artifacts-heading" className="subhead">
    Artifacts
  </h3>
  {artifactsState.status === "loading" && (
    <p className="muted">Loading artifacts…</p>
  )}
  {artifactsState.status === "loaded" && artifactsState.groups.length === 0 && (
    <p className="muted">No artifacts recorded.</p>
  )}
  {artifactsState.status === "loaded" && artifactsState.groups.length > 0 && (
    artifactsState.groups.map((group) => (
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
  {artifactsState.status === "error" && (
    <div className="panel panel-error" role="alert">
      <p>Failed to load artifacts: {artifactsState.message}</p>
      <button type="button" onClick={fetchArtifacts}>
        Retry
      </button>
    </div>
  )}
</section>
```

Note: The existing passing tests that indirectly trigger artifact fetch (the Task 8 view-report test) will now error out if the 4th mock (fetchRunArtifacts) is missing. **Check the existing test "view report toggles iframe with report URL"** — it mocks 4 calls and the 4th returns `jsonResponse(...)` so it will continue to succeed. The Task 7 test "clicking a history row loads run detail with errors" mocks only 3 calls (no fetchRunArtifacts) but doesn't assert the absence of error panels — it asserts text content and a role="alert" for DATA_QUALITY. The artifact error will put a 2nd alert on the page. The App tests check for `getByText` and heading presence, which should be tolerant. Verify after implementation.

- [x] **Step 4: Run all tests**

```
npm test -- --run
```

Expected: all 21 tests pass (7 api + 11 existing App + 1 sandbox + 1 artifact error/retry + 1 stale).

- [x] **Step 5: Commit**

```bash
git add frontend/src/runDetail.tsx frontend/src/App.test.tsx
git commit -m "feat(frontend): add artifact error state with retry button"
```

---

## Task 4: Legacy run compatibility tests

**Files:**
- Create: `tests/test_legacy_run_compat.py`

- [x] **Step 1: Write the fixture helper and Case A test**

Create `tests/test_legacy_run_compat.py` with a shared fixture that builds a V1-shape run directory (no `started_at/y/x` in manifest, no `schema_version` in index):

```python
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from workbench.api import app


def _v1_run_fixture(tmp_path: Path, *, missing_artifact: bool = False) -> tuple[TestClient, str, str]:
    """Create a project with one V1-shape run (no started_at/y/x, no schema_version).

    Returns (client, project_root, run_id).
    """
    client = TestClient(app)
    resp = client.post("/projects", json={"parent": str(tmp_path), "name": "v1test"})
    project_root = resp.json()["project_root"]
    run_root = Path(project_root) / "runs" / "v1-run"
    run_root.mkdir(parents=True)

    # V1 manifest — no started_at, y, x
    manifest = {
        "run_id": "v1-run",
        "mode": "auto",
        "status": "completed",
        "lineage": [],
    }
    (run_root / "run_manifest.json").write_text(
        __import__("json").dumps(manifest), encoding="utf-8"
    )

    # Index without schema_version
    report_path = run_root / "reports" / "report.html"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("<html><body>OK</body></html>", encoding="utf-8")

    artifacts = [
        {
            "artifact_id": "report_html",
            "path": "reports/report.html",
            "artifact_type": "report",
            "step": "reporting",
            "sha256": "deadbeef",
        },
    ]
    if missing_artifact:
        artifacts.append({
            "artifact_id": "missing_file",
            "path": "data/missing.csv",
            "artifact_type": "data",
            "step": "ingest",
            "sha256": "x",
        })

    (run_root / "artifacts_index.json").write_text(
        __import__("json").dumps({"artifacts": artifacts}), encoding="utf-8"
    )

    return client, project_root, "v1-run"
```

Then Case A — happy path for all 5 endpoints:

```python
class TestV1RunHappyPath:
    """A real V1 run (no started_at/y/x, no schema_version)
    must be fully readable by all V1.1 endpoints."""

    @pytest.fixture
    def v1_run(self, tmp_path: Path):
        return _v1_run_fixture(tmp_path)

    def test_list_runs_returns_null_for_missing_fields(self, v1_run):
        client, project_root, run_id = v1_run
        resp = client.get("/runs", params={"project_root": project_root})
        assert resp.status_code == 200
        runs = resp.json()["runs"]
        assert len(runs) == 1
        r = runs[0]
        assert r["run_id"] == run_id
        assert r["status"] == "completed"
        assert r["started_at"] is None
        assert r["y"] is None
        assert r["x"] is None

    def test_run_detail_returns_null_fields_and_counts(self, v1_run):
        client, project_root, run_id = v1_run
        resp = client.get(f"/runs/{run_id}", params={"project_root": project_root})
        assert resp.status_code == 200
        d = resp.json()
        assert d["run_id"] == run_id
        assert d["started_at"] is None
        assert d["y"] is None
        assert d["x"] is None
        assert "artifact_counts" in d
        assert d["artifact_counts"].get("report") == 1
        assert d["errors"] == {"issues": []}

    def test_list_artifacts_groups_correctly(self, v1_run):
        client, project_root, run_id = v1_run
        resp = client.get(f"/runs/{run_id}/artifacts", params={"project_root": project_root})
        assert resp.status_code == 200
        groups = resp.json()["groups"]
        by_type = {g["artifact_type"]: g for g in groups}
        assert "report" in by_type
        items = by_type["report"]["items"]
        assert any(item["artifact_id"] == "report_html" for item in items)

    def test_download_artifact_returns_file(self, v1_run):
        client, project_root, run_id = v1_run
        resp = client.get(
            f"/runs/{run_id}/artifacts/report_html",
            params={"project_root": project_root},
        )
        assert resp.status_code == 200
        assert "attachment" in resp.headers["content-disposition"]
        assert b"<html" in resp.content.lower()

    def test_get_report_returns_html(self, v1_run):
        client, project_root, run_id = v1_run
        resp = client.get(f"/runs/{run_id}/report", params={"project_root": project_root})
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert b"<html" in resp.content.lower()
```

- [x] **Step 2: Append Case B — broken artifact**

```python
class TestV1RunMissingArtifact:
    """When an artifact record exists but the file is missing on disk,
    list and detail must not fail; download must return 404."""

    @pytest.fixture
    def v1_run_broken(self, tmp_path: Path):
        return _v1_run_fixture(tmp_path, missing_artifact=True)

    def test_list_artifacts_includes_broken_record(self, v1_run_broken):
        client, project_root, run_id = v1_run_broken
        resp = client.get(f"/runs/{run_id}/artifacts", params={"project_root": project_root})
        assert resp.status_code == 200
        groups = resp.json()["groups"]
        all_items = [item for g in groups for item in g["items"]]
        artifact_ids = [item["artifact_id"] for item in all_items]
        assert "missing_file" in artifact_ids

    def test_detail_counts_include_broken_artifact(self, v1_run_broken):
        client, project_root, run_id = v1_run_broken
        resp = client.get(f"/runs/{run_id}", params={"project_root": project_root})
        assert resp.status_code == 200
        assert resp.json()["artifact_counts"].get("data") == 1

    def test_download_missing_returns_404(self, v1_run_broken):
        client, project_root, run_id = v1_run_broken
        resp = client.get(
            f"/runs/{run_id}/artifacts/missing_file",
            params={"project_root": project_root},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "ARTIFACT_NOT_FOUND"
```

- [x] **Step 3: Run tests**

```
.venv/bin/pytest tests/test_legacy_run_compat.py -v
```

Expected: all 8 tests pass.

- [x] **Step 4: Run full suite**

```
.venv/bin/pytest -q
```

Expected: all tests pass (75 existing + 11 = 86).

- [x] **Step 5: Commit**

```bash
git add tests/test_legacy_run_compat.py
git commit -m "test: add legacy V1 run compatibility tests"
```

---

## Task 5: Closure — full sweep + plan completion

**Files:**
- Modify: `docs/superpowers/plans/2026-05-03-workbench-v1.2.0-hardening.md`

- [x] **Step 1: Run the entire backend suite**

Run: `.venv/bin/pytest -q`
Expected: all 86 tests pass. Report count.

- [x] **Step 2: Run the entire frontend suite**

Run: `npm test -- --run`
Expected: all 21 tests pass (7 api + 14 App).

- [x] **Step 3: Mark plan tasks complete**

In this plan file, flip every `- [x]` to `- [x]`.

- [x] **Step 4: Commit closure**

```bash
git add docs/superpowers/plans/2026-05-03-workbench-v1.2.0-hardening.md
git commit -m "docs: mark V1.2.0 plan complete"
```

---

## Final Verification Checklist

Before reporting completion:

- [x] Backend pytest: all 86 tests pass (75 existing + 11 new)
- [x] Frontend vitest: all 21 tests pass (7 api + 14 App)
- [x] `_read_artifacts_index` validates `schema_version` on every registry read
- [x] New runs produce `artifacts_index.json` with `schema_version: 1`
- [x] Old runs (no `schema_version`) are tolerated and treated as v1
- [x] Future versions (2+), non-integer values, and values < 1 are rejected
- [x] `sandbox="allow-same-origin"` on report iframe
- [x] Test scans rendered report HTML for scripts and event handlers
- [x] Artifact error shows retry button; retry rebuilds list
- [x] Legacy V1 runs (null fields) render correctly through all 5 endpoints
