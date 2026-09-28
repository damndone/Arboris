# V1.2.2 Async Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Convert run submission to asynchronous execution and stream workflow progress to the run detail view with Server-Sent Events.

**Architecture:** The FastAPI `/run` endpoint creates a run directory, writes a running manifest, and dispatches `_bg_run` to a single-worker executor managed by `EventManager`. `_run_workflow` accepts an optional `on_step` callback that emits step events, while `GET /runs/{run_id}/events` streams history and live events to the frontend. The React detail view subscribes with `EventSource` only while a run is `running`.

**Tech Stack:** Python 3.11+, FastAPI, pytest, ThreadPoolExecutor, Server-Sent Events, React 18, TypeScript, Vite, Vitest, Testing Library.

---

## File Structure

**Backend:**
- Create: `backend/workbench/events.py` - in-process run event manager, subscribers, sequence numbers, and single-worker slot state
- Modify: `backend/workbench/api.py` - async `/run`, `_bg_run`, interrupted-run detection, and `/runs/{run_id}/events`
- Modify: `backend/workbench/orchestrator.py` - optional `on_step` callback in `_run_workflow`
- Modify: `tests/test_api.py` - async submission, 429, SSE, and interrupted-state coverage
- Modify: `tests/test_orchestrator_e2e.py` - `on_step` normal and blocked workflow coverage

**Frontend:**
- Modify: `frontend/src/api.ts` - `RunProgressEvent`, `RunProgressCallbacks`, and `connectRunEvents`
- Modify: `frontend/src/api.test.ts` - EventSource subscription tests
- Modify: `frontend/src/runDetail.tsx` - progress panel and live event subscription
- Modify: `frontend/src/styles.css` - progress list styles
- Modify: `frontend/src/App.test.tsx` - update run submission/detail tests for running state

---

## Task 1: Backend Event Manager

**Files:**
- Create: `backend/workbench/events.py`
- Test: `tests/test_api.py`

- [x] **Step 1: Add API tests for async run lifecycle**

Add tests that submit a run and assert:

```python
resp = client.post(
    "/run",
    data={"project_root": str(project_root), "mode": "auto", "y": "y", "x": "x"},
    files={"file": ("data.csv", csv_bytes, "text/csv")},
)
assert resp.status_code == 200
body = resp.json()
assert body["status"] == "running"
assert body["run_id"]
```

Add a second test that reserves the single worker slot and expects:

```python
assert resp.status_code == 429
assert resp.json()["detail"] == "A run is already in progress."
```

- [x] **Step 2: Run backend API tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_api.py -q
```

Expected before implementation: tests fail because `/run` still runs synchronously and `backend.workbench.events` does not exist.

- [x] **Step 3: Create `backend/workbench/events.py`**

Implement:

```python
class EventManager:
    def __init__(self, max_workers: int = 1) -> None: ...
    def try_acquire_slot(self) -> bool: ...
    def mark_active(self, run_id: str) -> None: ...
    def release_slot(self, run_id: str | None) -> None: ...
    def is_active(self, run_id: str) -> bool: ...
    @property
    def executor(self) -> ThreadPoolExecutor: ...
    def register_run(self, run_id: str) -> None: ...
    def subscribe(self, run_id: str) -> tuple[queue.Queue, list[dict]]: ...
    def unsubscribe(self, run_id: str, subscriber: queue.Queue) -> None: ...
    def emit(self, run_id: str, fields: dict) -> None: ...
    def emit_terminal(self, run_id: str, status: str, message: str) -> None: ...
    def schedule_cleanup(self, run_id: str, delay: int = 60) -> None: ...
    def _reset_for_testing(self) -> None: ...
```

Add:

```python
_event_manager: Optional[EventManager] = None

def get_event_manager() -> EventManager:
    global _event_manager
    if _event_manager is None:
        _event_manager = EventManager(max_workers=1)
    return _event_manager
```

- [x] **Step 4: Run backend tests for event manager consumers**

Run:

```bash
.venv/bin/python -m pytest tests/test_api.py -q
```

Expected after this task: event-manager import errors are gone; async endpoint tests may still fail until Task 2.

---

## Task 2: Async `/run` Endpoint

**Files:**
- Modify: `backend/workbench/api.py`
- Modify: `backend/workbench/orchestrator.py`
- Test: `tests/test_api.py`

- [x] **Step 1: Refactor imports in `api.py`**

Add imports:

```python
import asyncio
import json
import queue
from datetime import datetime, timezone

from fastapi.responses import FileResponse, StreamingResponse

from .artifacts import read_json, write_json
from .domain import GuardrailIssue, Severity
from .events import get_event_manager
from .orchestrator import _lineage, _run_workflow, _write_manifest, run_workflow
from .projects import create_project, create_run
```

- [x] **Step 2: Change `/run` to dispatch background work**

Replace the synchronous `TemporaryDirectory` path with:

```python
events = get_event_manager()
if not events.try_acquire_slot():
    raise HTTPException(status_code=429, detail="A run is already in progress.")

run = create_run(root, mode=mode)
started_at = datetime.now(timezone.utc).isoformat()
uploads_dir = run.root / "_uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)
saved_path = uploads_dir / Path(file.filename or "upload.csv").name
await _write_upload(file, saved_path, max_upload_bytes)
_write_manifest(run.root, run.run_id, mode, "running", _lineage([saved_path]), started_at=started_at, y=y, x=x_columns)
events.register_run(run.run_id)
events.mark_active(run.run_id)
events.executor.submit(_bg_run, run.root, run.run_id, saved_path, mode, y, x_columns, started_at)
return {"run_id": run.run_id, "status": "running"}
```

- [x] **Step 3: Add `_bg_run` helper**

Implement `_bg_run` so it:

1. Loads config from the project root.
2. Maps `on_step` statuses to event names.
3. Calls `_run_workflow(..., on_step=_on_step)`.
4. Emits `workflow_completed`, `workflow_blocked`, or `workflow_failed`.
5. Releases the worker slot in `finally`.

- [x] **Step 4: Run targeted backend tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_api.py -q
```

Expected: async submit and 429 tests pass; SSE tests may still fail until Task 3.

---

## Task 3: SSE Endpoint and Interrupted Runs

**Files:**
- Modify: `backend/workbench/api.py`
- Test: `tests/test_api.py`

- [x] **Step 1: Add tests for SSE event stream**

Add tests that:

1. Register a run and emit a terminal event.
2. Call `/runs/{run_id}/events`.
3. Assert `text/event-stream` response and an SSE frame containing `workflow_completed`.

Expected frame shape:

```text
event: workflow_completed
data: {"event": "workflow_completed", ...}
```

- [x] **Step 2: Add `_sse_frame`**

Implement:

```python
def _sse_frame(event: dict) -> str:
    return f"event: {event['event']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
```

- [x] **Step 3: Add `/runs/{run_id}/events`**

Implement:

```python
@app.get("/runs/{run_id}/events")
async def run_events_endpoint(run_id: str, project_root: str):
    run_root = _resolve_run_root(project_root, run_id)
    manifest = _read_manifest(run_root)
    events = get_event_manager()
    status = _mark_interrupted_if_dead(run_root, manifest)
    if status == "interrupted":
        events.register_run(run_id)
        events.emit_terminal(run_id, "interrupted", "Server stopped before completion.")
    sub_queue, snapshot = events.subscribe(run_id)
    ...
```

The generator first yields `snapshot`, then waits for queue events with a 30 second heartbeat.

- [x] **Step 4: Add interrupted detection**

Implement `_mark_interrupted_if_dead(run_root, manifest)`:

```python
if manifest.get("status") == "running" and not events.is_active(run_id):
    write_json(run_root / "errors.json", {"issues": [issue.to_dict()]})
    _write_manifest(..., status="interrupted", ...)
    manifest["status"] = "interrupted"
    return "interrupted"
```

Call it from run detail and SSE endpoints.

- [x] **Step 5: Run backend API tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_api.py -q
```

Expected: async, SSE, 429, and interrupted tests pass.

---

## Task 4: Orchestrator Step Callbacks

**Files:**
- Modify: `backend/workbench/orchestrator.py`
- Modify: `tests/test_orchestrator_e2e.py`

- [x] **Step 1: Add `on_step` tests**

Add a normal workflow test:

```python
events: list[tuple[str, str, str]] = []
result = run_workflow(project_root, [data], mode="auto", y="y", x=["x"], on_step=lambda *e: events.append(e))
assert result["status"] == "completed"
assert ("ingestion", "start", "Ingesting files...") in events
assert any(step == "export" and status == "complete" for step, status, _ in events)
```

Add a blocked workflow test that asserts:

```python
assert any(step == "validation" and status == "blocked" for step, status, _ in events)
```

- [x] **Step 2: Add optional callback argument**

Update `_run_workflow` signature:

```python
def _run_workflow(..., on_step: Callable[[str, str, str], None] | None = None) -> dict[str, Any]:
```

Preserve public `run_workflow` compatibility by passing `on_step` through only when provided.

- [x] **Step 3: Emit step events**

Emit `start` and `complete` around:

```text
ingestion, schema, cleaning, profiling, validation, routing, model_check, estimation, visualization, narrative, reporting, export
```

Emit `blocked` before returning blocked results for validation or model column failures.

- [x] **Step 4: Run orchestrator tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_orchestrator_e2e.py -q
```

Expected: callback tests pass and existing workflow tests remain green.

---

## Task 5: Frontend EventSource Client and Progress UI

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/api.test.ts`
- Modify: `frontend/src/runDetail.tsx`
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/App.test.tsx`

- [x] **Step 1: Add EventSource client tests**

Mock `global.EventSource` and assert:

```typescript
const cleanup = connectRunEvents("/tmp/proj", "run1", callbacks);
source.listeners.step_start({ data: JSON.stringify({ step: "ingestion", message: "Ingesting files..." }) });
expect(callbacks.onStepStart).toHaveBeenCalledWith("ingestion", "Ingesting files...");
cleanup();
expect(source.close).toHaveBeenCalled();
```

Add a terminal event assertion:

```typescript
source.listeners.workflow_completed({ data: JSON.stringify({ status: "completed", message: "Workflow completed" }) });
expect(callbacks.onTerminal).toHaveBeenCalledWith("completed", "Workflow completed");
expect(source.close).toHaveBeenCalled();
```

- [x] **Step 2: Add `connectRunEvents`**

In `frontend/src/api.ts`, add:

```typescript
export type RunProgressEvent = {
  event: "step_start" | "step_complete" | "step_blocked" | "workflow_completed" | "workflow_blocked" | "workflow_failed" | "workflow_interrupted";
  run_id: string;
  sequence: number;
  timestamp: string;
  step: string | null;
  message: string;
  status: string | null;
};
```

Implement EventSource listeners for step and terminal events.

- [x] **Step 3: Add progress state to `RunDetailPanel`**

Add:

```typescript
type StepStatus = "pending" | "running" | "completed" | "blocked";
type StepProgress = { step: string; label: string; status: StepStatus };
```

Use a fixed `PROGRESS_STEPS` list and subscribe when `detail?.status === "running"`.

- [x] **Step 4: Render progress panel**

Render:

```tsx
{isLive && (
  <section className="progress-panel" aria-label="run progress">
    <h3 className="subhead">Progress</h3>
    <ol className="progress-list">
      {progressSteps.map((s) => (
        <li key={s.step} className={`progress-step ${s.status}`}>
          <span className={`progress-dot ${s.status}`} />
          {s.label}
        </li>
      ))}
    </ol>
  </section>
)}
```

- [x] **Step 5: Add CSS**

Add `.progress-panel`, `.progress-list`, `.progress-step`, and `.progress-dot` classes with distinct visual states for pending, running, completed, and blocked.

- [x] **Step 6: Run frontend tests**

Run:

```bash
npm test
```

Expected: frontend tests pass.

---

## Task 6: Final Verification

**Files:**
- Verify only

- [x] **Step 1: Run backend test suite**

Run:

```bash
.venv/bin/python -m pytest tests -q
```

Expected: all backend tests pass.

- [x] **Step 2: Run frontend test suite**

Run:

```bash
npm test
```

Expected: all frontend tests pass.

- [x] **Step 3: Inspect git history**

Run:

```bash
git log --oneline --max-count=3
```

Expected:

```text
95f9e8e test: add V1.2.2 regression tests (async/SSE/on_step/EventSource)
8052738 feat: async background runs + SSE progress (V1.2.2)
5314ecb feat(frontend): add HashRouter, URL-driven project_root, and run history pagination
```

- [x] **Step 4: Record version boundary**

V1.2.1 boundary: `5314ecb`

V1.2.2 boundary: `95f9e8e`
