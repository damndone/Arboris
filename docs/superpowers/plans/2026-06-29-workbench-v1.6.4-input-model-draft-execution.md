# Workbench v1.6.4 Input to Model Draft Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the v1.6.4 Graph-first MVP where an eligible executed model node opens as a saveable, validateable `InputNode -> ModelNode` PipelineDraft and executes as a source-model child run.

**Architecture:** Add a backend `PipelineDraftStore` plus validation/execution service under `backend/workbench/lineage/`, expose draft-specific APIs from `backend/workbench/api.py`, and keep `/runs/{run_id}/rerun` as direct node rerun only. Add a dedicated frontend `/pipeline-drafts/:draftId` route with a fixed two-node draft graph, controlled model-params PATCH flow, server-backed validation, and execute navigation back to lineage.

**Tech Stack:** FastAPI + Pydantic backend, filesystem JSON store, existing Workbench run/rerun machinery, React + React Router frontend, Vitest and pytest, project gate via `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh`.

---

## Source Spec

- Spec: `docs/superpowers/specs/2026-06-29-workbench-v1.6.4-input-model-draft-execution-design.md`
- Base release: `v1.6.3` / `origin/main` at `bc7a40f`
- Worktree: `.worktrees/workbench-v1.6.4`
- Branch: `codex/workbench-v1.6.4`

## File Structure

Backend files:

- Create: `backend/workbench/lineage/pipeline_drafts.py`
  - Owns Pydantic models, error codes, executable-content hash, path-safe server ids, atomic JSON store, validation helpers, execution dedupe records, and the short draft execution lock.
- Modify: `backend/workbench/api.py`
  - Adds `/pipeline-drafts/from-node`, `GET /pipeline-drafts/{draft_id}`, `PATCH /pipeline-drafts/{draft_id}`, `/validate`, and `/execute`.
  - Keeps `/runs/{run_id}/rerun` unchanged as the public direct rerun API.
- Modify: `backend/workbench/lineage/op_contract.py`
  - Add reusable schema helpers only if needed for full-map params validation. Do not add per-estimator branches.
- Test: `tests/test_pipeline_drafts_store.py`
  - Store, hash, path safety, atomic writes, optimistic concurrency.
- Test: `tests/test_pipeline_drafts_api.py`
  - API behavior, fail-closed source checks, strong validation, execute dedupe, executed snapshot/provenance.
- Test: `tests/test_rerun_endpoint.py`
  - Regression that `/runs/{run_id}/rerun` rejects draft fields and still supports direct rerun.

Frontend files:

- Modify: `frontend/src/api.ts`
  - Add PipelineDraft types and client functions.
- Modify: `frontend/src/api.test.ts`
  - Client request/response tests.
- Create: `frontend/src/pipelineDrafts/types.ts`
  - Frontend-local types for draft graph rendering and UI state.
- Create: `frontend/src/pipelineDrafts/DraftGraphRoute.tsx`
  - Route container for `/pipeline-drafts/:draftId`.
- Create: `frontend/src/pipelineDrafts/DraftGraphRoute.test.tsx`
  - Route loading, save/validate/execute state machine tests.
- Create: `frontend/src/pipelineDrafts/DraftGraphCanvas.tsx`
  - Fixed `InputNode -> ModelNode` display.
- Create: `frontend/src/pipelineDrafts/DraftGraphCanvas.test.tsx`
  - Fixed graph and read-only input node tests.
- Create: `frontend/src/pipelineDrafts/ModelNodeInspector.tsx`
  - Controlled editable-schema params editor using `renderControl`.
- Create: `frontend/src/pipelineDrafts/ModelNodeInspector.test.tsx`
  - `base_draft_hash` PATCH and conflict behavior tests.
- Modify: `frontend/src/App.tsx`
  - Add route `/pipeline-drafts/:draftId`.
- Modify: `frontend/src/lineage/graph/NodeActionMenu.tsx`
  - Add canonical "Open as Draft Graph" action for eligible executed model nodes.
- Modify: `frontend/src/lineage/graph/NodeActionMenu.test.tsx`
  - Eligibility and navigation tests.
- Modify: `frontend/src/runResult.tsx` or `frontend/src/runDetail.tsx`
  - Add optional run-level shortcut only when exactly one eligible model node can be resolved; otherwise route to lineage.
- Test: existing route/run tests updated as needed.

Docs:

- Modify: `docs/dev-browser-smoke.md`
  - Add v1.6.4 smoke script.

## Task 0: Baseline and Worktree Setup

**Files:**
- Read: `docs/superpowers/specs/2026-06-29-workbench-v1.6.4-input-model-draft-execution-design.md`
- Read: `backend/workbench/api.py`
- Read: `frontend/src/api.ts`

- [ ] **Step 1: Verify main and current release base**

Run:

```bash
git status --short --branch
git rev-parse --short HEAD
git log --oneline --max-count=5
```

Expected:

```text
main is at the reviewed spec commits above v1.6.3
scratch/untracked files are not staged
```

- [ ] **Step 2: Create the isolated v1.6.4 worktree**

Run:

```bash
git worktree add .worktrees/workbench-v1.6.4 -b codex/workbench-v1.6.4
```

Expected:

```text
Preparing worktree (new branch 'codex/workbench-v1.6.4')
HEAD is now at <current-head>
```

- [ ] **Step 3: Prove baseline gate before implementation**

Run from `.worktrees/workbench-v1.6.4`:

```bash
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh
```

Expected:

```text
>>> GATE PASSED
```

If this fails, stop and report. Do not start implementation on a failing baseline.

## Task 1: PipelineDraft Models, Hashing, and Store

**Files:**
- Create: `backend/workbench/lineage/pipeline_drafts.py`
- Test: `tests/test_pipeline_drafts_store.py`

- [ ] **Step 1: Write store/hash/path-safety tests**

Create `tests/test_pipeline_drafts_store.py` with these tests:

```python
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from workbench.lineage.pipeline_drafts import (
    DRAFT_SCHEMA_VERSION,
    DraftHashConflict,
    PipelineDraftStore,
    compute_executable_draft_hash,
    new_draft_id,
)


def _draft() -> dict:
    return {
        "draft_id": "draft_abc123",
        "schema_version": DRAFT_SCHEMA_VERSION,
        "created_at": "2026-06-29T00:00:00Z",
        "updated_at": "2026-06-29T00:00:00Z",
        "status": "draft",
        "created_from": {
            "source_type": "run",
            "source_run_id": "run_source",
            "source_model_node_id": "model_node",
            "source_op_node_id": "model_op",
            "source_node_hash": "h_source",
            "source_context_fingerprint": "ctx_source",
            "source_input_fingerprint": "input_source",
        },
        "graph": {
            "nodes": [
                {
                    "node_id": "input_1",
                    "node_type": "input.dataset",
                    "source_type": "run_input",
                    "run_input_id": "run_source",
                    "schema_fingerprint": "schema_1",
                    "input_fingerprint": "input_source",
                    "row_count": 10,
                    "column_count": 3,
                    "columns_summary": [{"name": "y"}, {"name": "x1"}, {"name": "x2"}],
                    "status": "bound",
                },
                {
                    "node_id": "model_1",
                    "node_type": "model",
                    "model_family": "regression",
                    "model_type": "ols",
                    "schema_id": "ols@v1",
                    "editable_schema": [{"key": "x", "kind": "columns", "label": "X"}],
                    "editable_schema_hash": "schema_hash",
                    "source_ref": {
                        "source_run_id": "run_source",
                        "source_model_node_id": "model_node",
                        "source_op_node_id": "model_op",
                        "source_node_hash": "h_source",
                        "source_context_fingerprint": "ctx_source",
                    },
                    "source_params": {"x": ["x1"]},
                    "params": {"x": ["x1"]},
                },
            ],
            "edges": [{"from": "input_1", "to": "model_1"}],
        },
        "default_execution_mode": "rerun_child",
    }


def test_draft_id_is_path_safe() -> None:
    for _ in range(20):
        draft_id = new_draft_id()
        assert draft_id.startswith("draft_")
        assert "/" not in draft_id
        assert "\\" not in draft_id
        assert ".." not in draft_id


def test_hash_excludes_volatile_metadata() -> None:
    draft = _draft()
    first = compute_executable_draft_hash(draft)
    changed = copy.deepcopy(draft)
    changed["updated_at"] = "2030-01-01T00:00:00Z"
    changed["status"] = "saving"
    assert compute_executable_draft_hash(changed) == first


def test_hash_changes_when_params_change() -> None:
    draft = _draft()
    changed = copy.deepcopy(draft)
    changed["graph"]["nodes"][1]["params"] = {"x": ["x1", "x2"]}
    assert compute_executable_draft_hash(changed) != compute_executable_draft_hash(draft)


def test_store_roundtrip_and_base_hash_conflict(tmp_path: Path) -> None:
    store = PipelineDraftStore(tmp_path)
    draft = _draft()
    saved = store.create(draft)
    assert saved.draft["draft_id"] == "draft_abc123"
    loaded = store.get("draft_abc123")
    assert loaded.draft_hash == saved.draft_hash
    with pytest.raises(DraftHashConflict):
        store.update_params(
            "draft_abc123",
            model_node_id="model_1",
            base_draft_hash="stale",
            params={"x": ["x2"]},
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/test_pipeline_drafts_store.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'workbench.lineage.pipeline_drafts'
```

- [ ] **Step 3: Implement models, hashing, path-safe ids, atomic store**

Create `backend/workbench/lineage/pipeline_drafts.py` with:

```python
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

DRAFT_SCHEMA_VERSION = "pipeline_draft.v1"
EXECUTED_DRAFT_FILENAME = "executed_pipeline_draft.json"
_DRAFT_ID_RE = re.compile(r"^draft_[A-Za-z0-9_-]{8,64}$")


class PipelineDraftError(ValueError):
    code = "PIPELINE_DRAFT_ERROR"


class DraftNotFound(PipelineDraftError):
    code = "DRAFT_NOT_FOUND"


class DraftHashConflict(PipelineDraftError):
    code = "DRAFT_HASH_CONFLICT"


class DraftPathError(PipelineDraftError):
    code = "INVALID_DRAFT_ID"


class InputDatasetNode(BaseModel):
    node_id: str
    node_type: Literal["input.dataset"]
    source_type: Literal["run_input", "upload"]
    run_input_id: str | None = None
    upload_sha: str | None = None
    dataset_snapshot_id: str | None = None
    schema_fingerprint: str
    input_fingerprint: str
    row_count: int | None = None
    column_count: int | None = None
    columns_summary: list[dict[str, Any]] = Field(default_factory=list)
    status: Literal["bound", "missing", "invalid"] = "bound"


class SourceRef(BaseModel):
    source_run_id: str
    source_model_node_id: str
    source_op_node_id: str
    source_node_hash: str
    source_context_fingerprint: str


class ModelDraftNode(BaseModel):
    node_id: str
    node_type: Literal["model"]
    model_family: str
    model_type: str
    schema_id: str
    editable_schema: list[dict[str, Any]]
    editable_schema_hash: str
    source_ref: SourceRef
    source_params: dict[str, Any]
    params: dict[str, Any]


class CreatedFrom(BaseModel):
    source_type: Literal["run"]
    source_run_id: str
    source_model_node_id: str
    source_op_node_id: str
    source_node_hash: str
    source_context_fingerprint: str
    source_input_fingerprint: str


class PipelineDraftV1(BaseModel):
    draft_id: str
    schema_version: Literal["pipeline_draft.v1"]
    created_at: str
    updated_at: str
    status: str = "draft"
    created_from: CreatedFrom | None = None
    graph: dict[str, Any]
    default_execution_mode: Literal["rerun_child", "new_run"] = "rerun_child"


@dataclass(frozen=True)
class StoredDraft:
    draft: dict[str, Any]
    draft_hash: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_draft_id() -> str:
    return f"draft_{uuid.uuid4().hex}"


def validate_draft_id(draft_id: str) -> None:
    if not _DRAFT_ID_RE.match(draft_id):
        raise DraftPathError(f"Invalid draft_id: {draft_id!r}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def executable_payload(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": draft.get("schema_version"),
        "created_from": draft.get("created_from"),
        "graph": draft.get("graph"),
        "default_execution_mode": draft.get("default_execution_mode"),
    }


def compute_executable_draft_hash(draft: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(executable_payload(draft)).encode("utf-8")).hexdigest()


def schema_hash(editable_schema: list[dict[str, Any]]) -> str:
    return hashlib.sha256(canonical_json(editable_schema).encode("utf-8")).hexdigest()


class PipelineDraftStore:
    def __init__(self, project_root: Path):
        self.root = project_root
        self.drafts_dir = project_root / "data" / "pipeline_drafts"
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _path(self, draft_id: str) -> Path:
        validate_draft_id(draft_id)
        return self.drafts_dir / f"{draft_id}.json"

    def _lock_for(self, draft_id: str) -> threading.Lock:
        validate_draft_id(draft_id)
        with self._locks_guard:
            return self._locks.setdefault(draft_id, threading.Lock())

    def _write_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, sort_keys=True, indent=2, ensure_ascii=False)
                fh.write("\n")
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def create(self, draft: dict[str, Any]) -> StoredDraft:
        PipelineDraftV1(**draft)
        path = self._path(str(draft["draft_id"]))
        if path.exists():
            raise DraftHashConflict("draft already exists")
        self._write_atomic(path, draft)
        return StoredDraft(draft=draft, draft_hash=compute_executable_draft_hash(draft))

    def get(self, draft_id: str) -> StoredDraft:
        path = self._path(draft_id)
        if not path.is_file():
            raise DraftNotFound(draft_id)
        draft = json.loads(path.read_text(encoding="utf-8"))
        PipelineDraftV1(**draft)
        return StoredDraft(draft=draft, draft_hash=compute_executable_draft_hash(draft))

    def update_params(
        self,
        draft_id: str,
        *,
        model_node_id: str,
        base_draft_hash: str,
        params: dict[str, Any],
    ) -> StoredDraft:
        with self._lock_for(draft_id):
            stored = self.get(draft_id)
            if stored.draft_hash != base_draft_hash:
                raise DraftHashConflict("base_draft_hash does not match current draft")
            draft = stored.draft
            model_node = next(
                (
                    node
                    for node in draft["graph"]["nodes"]
                    if node.get("node_type") == "model" and node.get("node_id") == model_node_id
                ),
                None,
            )
            if model_node is None:
                raise ValueError("MISSING_MODEL_NODE")
            model_node["params"] = params
            draft["updated_at"] = utc_now()
            PipelineDraftV1(**draft)
            self._write_atomic(self._path(draft_id), draft)
            return StoredDraft(draft=draft, draft_hash=compute_executable_draft_hash(draft))

    def execution_lock(self, draft_id: str) -> threading.Lock:
        return self._lock_for(draft_id)
```

- [ ] **Step 4: Run store tests**

Run:

```bash
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/test_pipeline_drafts_store.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 5: Commit Task 1**

```bash
git add backend/workbench/lineage/pipeline_drafts.py tests/test_pipeline_drafts_store.py
git commit -m "feat(lineage): add pipeline draft store"
```

## Task 2: Draft Validation Service

**Files:**
- Modify: `backend/workbench/lineage/pipeline_drafts.py`
- Test: `tests/test_pipeline_drafts_store.py`

- [ ] **Step 1: Add validation tests**

Append to `tests/test_pipeline_drafts_store.py`:

```python
from workbench.lineage.pipeline_drafts import (
    validate_draft_for_execution,
)


def test_validate_passes_exact_input_to_model_shape() -> None:
    result = validate_draft_for_execution(_draft(), execution_mode="rerun_child")
    assert result["ok"] is True
    assert result["status"] == "valid"
    assert result["executable"] is True
    assert result["validated_draft_hash"] == compute_executable_draft_hash(_draft())
    assert result["validated_execution_mode"] == "rerun_child"


def test_validate_blocks_new_run() -> None:
    result = validate_draft_for_execution(_draft(), execution_mode="new_run")
    assert result["ok"] is False
    assert result["status"] == "blocked"
    assert result["executable"] is False
    assert result["checks"][0]["code"] == "NEW_RUN_EXECUTION_NOT_ENABLED"
    assert "validated_draft_hash" not in result


def test_validate_blocks_missing_created_from_for_rerun_child() -> None:
    draft = _draft()
    draft.pop("created_from")
    result = validate_draft_for_execution(draft, execution_mode="rerun_child")
    assert result["ok"] is False
    assert any(c["code"] == "CREATED_FROM_REQUIRED_FOR_RERUN_CHILD" for c in result["checks"])


def test_validate_blocks_source_ref_mismatch() -> None:
    draft = _draft()
    draft["graph"]["nodes"][1]["source_ref"]["source_node_hash"] = "different"
    result = validate_draft_for_execution(draft, execution_mode="rerun_child")
    assert result["ok"] is False
    assert any(c["code"] == "MODEL_SOURCE_REF_MISMATCH" for c in result["checks"])


def test_validate_blocks_invalid_graph_shape() -> None:
    draft = _draft()
    draft["graph"]["edges"] = []
    result = validate_draft_for_execution(draft, execution_mode="rerun_child")
    assert result["ok"] is False
    assert any(c["code"] == "INVALID_DRAFT_GRAPH_SHAPE" for c in result["checks"])
```

- [ ] **Step 2: Run tests to verify failures**

Run:

```bash
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/test_pipeline_drafts_store.py -q
```

Expected:

```text
ImportError: cannot import name 'validate_draft_for_execution'
```

- [ ] **Step 3: Implement validation helpers**

Add to `backend/workbench/lineage/pipeline_drafts.py`:

```python
def check(code: str, message: str, *, node_id: str | None = None, level: str = "error", blocking: bool = True) -> dict[str, Any]:
    out = {"code": code, "level": level, "message": message, "blocking": blocking}
    if node_id is not None:
        out["node_id"] = node_id
    return out


def _nodes_by_type(draft: dict[str, Any], node_type: str) -> list[dict[str, Any]]:
    return [n for n in draft.get("graph", {}).get("nodes", []) if n.get("node_type") == node_type]


def _validate_graph_shape(draft: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    inputs = _nodes_by_type(draft, "input.dataset")
    models = _nodes_by_type(draft, "model")
    edges = draft.get("graph", {}).get("edges", [])
    if len(inputs) != 1:
        checks.append(check("MISSING_INPUT_NODE", "Draft must contain exactly one input.dataset node."))
    if len(models) != 1:
        checks.append(check("MISSING_MODEL_NODE", "Draft must contain exactly one model node."))
    if len(edges) != 1 or len(inputs) != 1 or len(models) != 1 or edges[0].get("from") != inputs[0].get("node_id") or edges[0].get("to") != models[0].get("node_id"):
        checks.append(check("INVALID_DRAFT_GRAPH_SHAPE", "v1.6.4 supports only InputNode -> ModelNode."))
    for node in draft.get("graph", {}).get("nodes", []):
        if node.get("node_type") not in {"input.dataset", "model"}:
            checks.append(check("UNKNOWN_DRAFT_NODE_TYPE", f"Unsupported draft node_type {node.get('node_type')!r}.", node_id=node.get("node_id")))
    return checks


def _editable_keys(model: dict[str, Any]) -> set[str]:
    return {str(item.get("key")) for item in model.get("editable_schema", []) if item.get("key")}


def _validate_params(model: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    allowed = _editable_keys(model)
    for key in model.get("params", {}):
        if key not in allowed:
            checks.append(check("NON_EDITABLE_FIELD_PATCH", f"Field {key!r} is not editable.", node_id=model.get("node_id")))
    return checks


def _validate_source_ref(draft: dict[str, Any], model: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    created = draft.get("created_from")
    if not created:
        checks.append(check("CREATED_FROM_REQUIRED_FOR_RERUN_CHILD", "rerun_child drafts require created_from."))
        return checks
    source_ref = model.get("source_ref") or {}
    pairs = {
        "source_run_id": "source_run_id",
        "source_model_node_id": "source_model_node_id",
        "source_op_node_id": "source_op_node_id",
        "source_node_hash": "source_node_hash",
        "source_context_fingerprint": "source_context_fingerprint",
    }
    for left, right in pairs.items():
        if source_ref.get(left) != created.get(right):
            checks.append(check("MODEL_SOURCE_REF_MISMATCH", f"Model source_ref {left} does not match created_from.", node_id=model.get("node_id")))
            break
    return checks


def validate_draft_for_execution(draft: dict[str, Any], *, execution_mode: str | None = None) -> dict[str, Any]:
    mode = execution_mode or draft.get("default_execution_mode")
    checks: list[dict[str, Any]] = []
    try:
        PipelineDraftV1(**draft)
    except ValidationError as exc:
        checks.append(check("UNSUPPORTED_DRAFT_SCHEMA_VERSION", str(exc)))
    checks.extend(_validate_graph_shape(draft))
    models = _nodes_by_type(draft, "model")
    inputs = _nodes_by_type(draft, "input.dataset")
    if models:
        checks.extend(_validate_params(models[0]))
        checks.extend(_validate_source_ref(draft, models[0]))
        if models[0].get("editable_schema_hash") != schema_hash(models[0].get("editable_schema", [])):
            checks.append(check("MODEL_SCHEMA_UNSUPPORTED", "editable_schema_hash does not match snapshotted editable_schema.", node_id=models[0].get("node_id")))
    if inputs and inputs[0].get("status") != "bound":
        checks.append(check("INPUT_BINDING_MISSING", "InputNode is not bound.", node_id=inputs[0].get("node_id")))
    if mode == "new_run":
        checks.append(check("NEW_RUN_EXECUTION_NOT_ENABLED", "new_run execution is reserved for a future version."))
    elif mode != "rerun_child":
        checks.append(check("NEW_RUN_EXECUTION_NOT_ENABLED", f"Unsupported execution_mode {mode!r}."))
    if mode == "rerun_child" and not any(c["code"] == "NEW_RUN_EXECUTION_NOT_ENABLED" for c in checks):
        # v1.6.4 rerun_child product loop requires Compare source availability.
        if not draft.get("created_from"):
            pass
    blocking = [c for c in checks if c["blocking"]]
    executable = not blocking and mode == "rerun_child"
    result: dict[str, Any] = {
        "ok": executable,
        "status": "valid" if executable else ("blocked" if any(c["code"] == "NEW_RUN_EXECUTION_NOT_ENABLED" for c in checks) else "invalid"),
        "executable": executable,
        "checks": checks,
        "resolved_execution": {
            "execution_mode": mode,
            "compare_source_available": executable,
            "rerun_from_run_id": (draft.get("created_from") or {}).get("source_run_id"),
            "rerun_from_model_node_id": (draft.get("created_from") or {}).get("source_model_node_id"),
            "rerun_from_op_node_id": (draft.get("created_from") or {}).get("source_op_node_id"),
        },
        "validated_at": utc_now(),
    }
    if executable:
        result["validated_draft_hash"] = compute_executable_draft_hash(draft)
        result["validated_execution_mode"] = mode
    return result
```

- [ ] **Step 4: Run validation tests**

Run:

```bash
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/test_pipeline_drafts_store.py -q
```

Expected:

```text
9 passed
```

- [ ] **Step 5: Commit Task 2**

```bash
git add backend/workbench/lineage/pipeline_drafts.py tests/test_pipeline_drafts_store.py
git commit -m "feat(lineage): validate pipeline drafts"
```

## Task 3: Backend PipelineDraft API - create/read/patch/validate

**Files:**
- Modify: `backend/workbench/api.py`
- Modify: `backend/workbench/lineage/pipeline_drafts.py`
- Test: `tests/test_pipeline_drafts_api.py`

- [ ] **Step 1: Write API tests for create/read/patch/validate**

Create `tests/test_pipeline_drafts_api.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api import app


def _client() -> TestClient:
    return TestClient(app)


def _create_completed_run(client: TestClient, tmp_path: Path) -> tuple[str, str]:
    csv = tmp_path / "input.csv"
    csv.write_text("y,x1,x2\n1,1,2\n2,2,3\n3,3,4\n4,4,5\n", encoding="utf-8")
    with csv.open("rb") as fh:
        response = client.post(
            "/runs",
            data={"project_root": str(tmp_path), "mode": "auto", "model_type": "ols", "y": "y", "x": "x1"},
            files={"file": ("input.csv", fh, "text/csv")},
        )
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    # Mark the synchronously-created manifest completed for API-level tests that do not
    # exercise the background worker.
    manifest_path = tmp_path / "runs" / run_id / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["status"] = "completed"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return run_id, str(tmp_path)


def test_from_node_creates_draft_and_get_reads_hash(tmp_path: Path) -> None:
    client = _client()
    run_id, project_root = _create_completed_run(client, tmp_path)
    graph = client.get(f"/runs/{run_id}/graph", params={"project_root": project_root}).json()
    model = next(n for n in graph["nodes"] if n.get("stage") == "model")
    body = {
        "source_run_id": run_id,
        "source_model_node_id": model["id"],
        "source_op_node_id": model["id"],
        "source_node_hash": model["node_hash"],
        "source_context_fingerprint": model.get("context_fingerprint") or model["node_hash"],
    }
    response = client.post("/pipeline-drafts/from-node", params={"project_root": project_root}, json=body)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["draft"]["default_execution_mode"] == "rerun_child"
    assert payload["draft_hash"]
    draft_id = payload["draft"]["draft_id"]
    get_response = client.get(f"/pipeline-drafts/{draft_id}", params={"project_root": project_root})
    assert get_response.status_code == 200
    assert get_response.json()["draft_hash"] == payload["draft_hash"]


def test_patch_requires_base_hash_and_validate_returns_hash(tmp_path: Path) -> None:
    client = _client()
    run_id, project_root = _create_completed_run(client, tmp_path)
    graph = client.get(f"/runs/{run_id}/graph", params={"project_root": project_root}).json()
    model = next(n for n in graph["nodes"] if n.get("stage") == "model")
    create = client.post(
        "/pipeline-drafts/from-node",
        params={"project_root": project_root},
        json={
            "source_run_id": run_id,
            "source_model_node_id": model["id"],
            "source_op_node_id": model["id"],
            "source_node_hash": model["node_hash"],
            "source_context_fingerprint": model.get("context_fingerprint") or model["node_hash"],
        },
    ).json()
    draft_id = create["draft"]["draft_id"]
    stale = client.patch(
        f"/pipeline-drafts/{draft_id}",
        params={"project_root": project_root},
        json={"model_node_id": "model_1", "base_draft_hash": "stale", "params": {"x": ["x1", "x2"]}},
    )
    assert stale.status_code == 409
    ok = client.patch(
        f"/pipeline-drafts/{draft_id}",
        params={"project_root": project_root},
        json={"model_node_id": "model_1", "base_draft_hash": create["draft_hash"], "params": {"x": ["x1", "x2"]}},
    )
    assert ok.status_code == 200, ok.text
    validate = client.post(
        f"/pipeline-drafts/{draft_id}/validate",
        params={"project_root": project_root},
        json={"execution_mode": "rerun_child"},
    )
    assert validate.status_code == 200
    assert validate.json()["validated_draft_hash"] == ok.json()["draft_hash"]
```

- [ ] **Step 2: Run tests to verify failures**

Run:

```bash
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/test_pipeline_drafts_api.py -q
```

Expected:

```text
404 Not Found for /pipeline-drafts/from-node
```

- [ ] **Step 3: Add request/response models and helper functions in `api.py`**

Add imports near existing lineage imports:

```python
from .lineage.pipeline_drafts import (
    DraftHashConflict,
    DraftNotFound,
    PipelineDraftStore,
    compute_executable_draft_hash,
    new_draft_id,
    schema_hash,
    utc_now,
    validate_draft_for_execution,
)
```

Add Pydantic models near `RerunRequest`:

```python
class PipelineDraftFromNodeRequest(BaseModel):
    source_run_id: str
    source_model_node_id: str
    source_op_node_id: str
    source_node_hash: str
    source_context_fingerprint: str


class PipelineDraftPatchRequest(BaseModel):
    model_node_id: str
    base_draft_hash: str
    params: dict[str, Any]


class PipelineDraftValidateRequest(BaseModel):
    execution_mode: Literal["rerun_child", "new_run"] | None = None
```

Add helpers:

```python
def _pipeline_draft_store(project_root: str) -> PipelineDraftStore:
    return PipelineDraftStore(Path(project_root))


def _draft_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DraftNotFound):
        return HTTPException(status_code=404, detail="DRAFT_NOT_FOUND")
    if isinstance(exc, DraftHashConflict):
        return HTTPException(status_code=409, detail="DRAFT_HASH_CONFLICT")
    return HTTPException(status_code=422, detail=str(exc))
```

- [ ] **Step 4: Implement from-node/read/patch/validate endpoints**

Add to `backend/workbench/api.py` before the direct rerun endpoint:

```python
@app.post("/pipeline-drafts/from-node")
def create_pipeline_draft_from_node(project_root: str, body: PipelineDraftFromNodeRequest) -> dict[str, Any]:
    root = Path(project_root)
    runs_root = _resolve_project_runs_dir(project_root)
    run_root = _resolve_run_root(project_root, body.source_run_id)
    manifest = _read_manifest(run_root)
    graph = GraphStore(runs_root=runs_root).read(body.source_run_id)
    node = graph.nodes.get(body.source_op_node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="SOURCE_MODEL_NODE_NOT_FOUND")
    node_hash = getattr(node, "node_hash", None) or getattr(node, "hash", None) or body.source_node_hash
    if str(node_hash) != body.source_node_hash:
        raise HTTPException(status_code=409, detail="SOURCE_NODE_HASH_MISMATCH")
    contract = resolve_operation_contract(stage=node.stage.value if node.stage else None, manifest=manifest)
    if contract is None:
        raise HTTPException(status_code=422, detail="MODEL_NODE_NOT_ELIGIBLE")
    inputs = read_run_inputs(run_root)
    draft_id = new_draft_id()
    now = utc_now()
    editable_schema = _backfill_schema_values(contract.editable_schema, inputs["form"])
    source_params = {item["key"]: item.get("value") for item in editable_schema if item.get("key")}
    draft = {
        "draft_id": draft_id,
        "schema_version": "pipeline_draft.v1",
        "created_at": now,
        "updated_at": now,
        "status": "draft",
        "created_from": {
            "source_type": "run",
            "source_run_id": body.source_run_id,
            "source_model_node_id": body.source_model_node_id,
            "source_op_node_id": body.source_op_node_id,
            "source_node_hash": body.source_node_hash,
            "source_context_fingerprint": body.source_context_fingerprint,
            "source_input_fingerprint": inputs["upload"]["sha256"],
        },
        "graph": {
            "nodes": [
                {
                    "node_id": "input_1",
                    "node_type": "input.dataset",
                    "source_type": "run_input",
                    "run_input_id": body.source_run_id,
                    "schema_fingerprint": inputs.get("dag_hash") or inputs["upload"]["sha256"],
                    "input_fingerprint": inputs["upload"]["sha256"],
                    "columns_summary": [{"name": key} for key in sorted(inputs["form"])],
                    "status": "bound",
                },
                {
                    "node_id": "model_1",
                    "node_type": "model",
                    "model_family": "regression",
                    "model_type": contract.op_type,
                    "schema_id": contract.schema_id,
                    "editable_schema": editable_schema,
                    "editable_schema_hash": schema_hash(editable_schema),
                    "source_ref": {
                        "source_run_id": body.source_run_id,
                        "source_model_node_id": body.source_model_node_id,
                        "source_op_node_id": body.source_op_node_id,
                        "source_node_hash": body.source_node_hash,
                        "source_context_fingerprint": body.source_context_fingerprint,
                    },
                    "source_params": source_params,
                    "params": source_params,
                },
            ],
            "edges": [{"from": "input_1", "to": "model_1"}],
        },
        "default_execution_mode": "rerun_child",
    }
    try:
        stored = _pipeline_draft_store(project_root).create(draft)
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return {"draft": stored.draft, "draft_hash": stored.draft_hash}


@app.get("/pipeline-drafts/{draft_id}")
def get_pipeline_draft(draft_id: str, project_root: str) -> dict[str, Any]:
    try:
        stored = _pipeline_draft_store(project_root).get(draft_id)
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return {"draft": stored.draft, "draft_hash": stored.draft_hash}


@app.patch("/pipeline-drafts/{draft_id}")
def patch_pipeline_draft(draft_id: str, project_root: str, body: PipelineDraftPatchRequest) -> dict[str, Any]:
    try:
        stored = _pipeline_draft_store(project_root).update_params(
            draft_id,
            model_node_id=body.model_node_id,
            base_draft_hash=body.base_draft_hash,
            params=body.params,
        )
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return {"draft": stored.draft, "draft_hash": stored.draft_hash}


@app.post("/pipeline-drafts/{draft_id}/validate")
def validate_pipeline_draft(draft_id: str, project_root: str, body: PipelineDraftValidateRequest) -> dict[str, Any]:
    try:
        stored = _pipeline_draft_store(project_root).get(draft_id)
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return validate_draft_for_execution(stored.draft, execution_mode=body.execution_mode)
```

- [ ] **Step 5: Run API tests**

Run:

```bash
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/test_pipeline_drafts_api.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 6: Commit Task 3**

```bash
git add backend/workbench/api.py backend/workbench/lineage/pipeline_drafts.py tests/test_pipeline_drafts_api.py
git commit -m "feat(api): add pipeline draft create validate endpoints"
```

## Task 4: Execute Draft API and Rerun Child Integration

**Files:**
- Modify: `backend/workbench/api.py`
- Modify: `backend/workbench/lineage/pipeline_drafts.py`
- Test: `tests/test_pipeline_drafts_api.py`
- Test: `tests/test_rerun_endpoint.py`

- [ ] **Step 1: Add execute tests**

Append to `tests/test_pipeline_drafts_api.py`:

```python
def test_execute_rejects_new_run_and_stale_hash(tmp_path: Path) -> None:
    client = _client()
    run_id, project_root = _create_completed_run(client, tmp_path)
    graph = client.get(f"/runs/{run_id}/graph", params={"project_root": project_root}).json()
    model = next(n for n in graph["nodes"] if n.get("stage") == "model")
    create = client.post(
        "/pipeline-drafts/from-node",
        params={"project_root": project_root},
        json={
            "source_run_id": run_id,
            "source_model_node_id": model["id"],
            "source_op_node_id": model["id"],
            "source_node_hash": model["node_hash"],
            "source_context_fingerprint": model.get("context_fingerprint") or model["node_hash"],
        },
    ).json()
    draft_id = create["draft"]["draft_id"]
    new_run = client.post(
        f"/pipeline-drafts/{draft_id}/execute",
        params={"project_root": project_root},
        json={"validated_draft_hash": create["draft_hash"], "execution_mode": "new_run"},
    )
    assert new_run.status_code == 409
    assert new_run.json()["detail"] == "NEW_RUN_EXECUTION_NOT_ENABLED"
    stale = client.post(
        f"/pipeline-drafts/{draft_id}/execute",
        params={"project_root": project_root},
        json={"validated_draft_hash": "stale", "execution_mode": "rerun_child"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "VALIDATED_DRAFT_HASH_MISMATCH"


def test_execute_writes_snapshot_and_returns_deduped_on_retry(tmp_path: Path) -> None:
    client = _client()
    run_id, project_root = _create_completed_run(client, tmp_path)
    graph = client.get(f"/runs/{run_id}/graph", params={"project_root": project_root}).json()
    model = next(n for n in graph["nodes"] if n.get("stage") == "model")
    create = client.post(
        "/pipeline-drafts/from-node",
        params={"project_root": project_root},
        json={
            "source_run_id": run_id,
            "source_model_node_id": model["id"],
            "source_op_node_id": model["id"],
            "source_node_hash": model["node_hash"],
            "source_context_fingerprint": model.get("context_fingerprint") or model["node_hash"],
        },
    ).json()
    draft_id = create["draft"]["draft_id"]
    validation = client.post(
        f"/pipeline-drafts/{draft_id}/validate",
        params={"project_root": project_root},
        json={"execution_mode": "rerun_child"},
    ).json()
    request = {"validated_draft_hash": validation["validated_draft_hash"], "execution_mode": "rerun_child"}
    first = client.post(f"/pipeline-drafts/{draft_id}/execute", params={"project_root": project_root}, json=request)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["execution_mode"] == "rerun_child"
    assert body["produced_lineage"]["rerun_from_run_id"] == run_id
    assert (tmp_path / "runs" / body["run_id"] / "executed_pipeline_draft.json").is_file()
    second = client.post(f"/pipeline-drafts/{draft_id}/execute", params={"project_root": project_root}, json=request)
    assert second.status_code == 200
    assert second.json()["run_id"] == body["run_id"]
    assert second.json()["deduped"] is True
```

Append to `tests/test_rerun_endpoint.py`:

```python
def test_direct_rerun_rejects_pipeline_draft_payload_fields(tmp_path: Path):
    client = TestClient(app)
    response = client.post(
        "/runs/run_missing/rerun",
        params={"project_root": str(tmp_path)},
        json={
            "from_node": "model:1",
            "op_overrides": {},
            "draft_id": "draft_abc",
            "validated_draft_hash": "hash",
        },
    )
    assert response.status_code in {400, 422}
```

- [ ] **Step 2: Run tests to verify execute endpoint fails**

Run:

```bash
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/test_pipeline_drafts_api.py tests/test_rerun_endpoint.py::test_direct_rerun_rejects_pipeline_draft_payload_fields -q
```

Expected:

```text
404 Not Found for /pipeline-drafts/{draft_id}/execute
```

- [ ] **Step 3: Add execute request model and dedupe support**

Add to `pipeline_drafts.py`:

```python
@dataclass(frozen=True)
class DedupeRecord:
    run_id: str
    executed_draft_hash: str


def dedupe_path(self, draft_id: str, key: str) -> Path:
    validate_draft_id(draft_id)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return self.drafts_dir / f"{draft_id}.{digest}.execution.json"


def get_dedupe(self, draft_id: str, key: str) -> DedupeRecord | None:
    path = self.dedupe_path(draft_id, key)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return DedupeRecord(
        run_id=payload["run_id"],
        executed_draft_hash=payload["executed_draft_hash"],
    )


def record_dedupe(
    self,
    draft_id: str,
    key: str,
    *,
    run_id: str,
    executed_draft_hash: str,
) -> None:
    self._write_atomic(
        self.dedupe_path(draft_id, key),
        {"run_id": run_id, "executed_draft_hash": executed_draft_hash},
    )
```

Add these methods inside the existing `PipelineDraftStore` class created in Task 1.

- [ ] **Step 4: Implement execute endpoint**

Add model to `api.py`:

```python
class PipelineDraftExecuteRequest(BaseModel):
    validated_draft_hash: str
    execution_mode: Literal["rerun_child", "new_run"]
    idempotency_key: str | None = None
```

Add endpoint:

```python
@app.post("/pipeline-drafts/{draft_id}/execute")
def execute_pipeline_draft(draft_id: str, project_root: str, body: PipelineDraftExecuteRequest) -> dict[str, Any]:
    if body.execution_mode == "new_run":
        raise HTTPException(status_code=409, detail="NEW_RUN_EXECUTION_NOT_ENABLED")
    store = _pipeline_draft_store(project_root)
    first = store.get(draft_id)
    if first.draft_hash != body.validated_draft_hash:
        raise HTTPException(status_code=409, detail="VALIDATED_DRAFT_HASH_MISMATCH")
    lock = store.execution_lock(draft_id)
    with lock:
        current = store.get(draft_id)
        if current.draft_hash != body.validated_draft_hash:
            raise HTTPException(status_code=409, detail="VALIDATED_DRAFT_HASH_MISMATCH")
        validation = validate_draft_for_execution(current.draft, execution_mode=body.execution_mode)
        if not validation.get("executable"):
            raise HTTPException(status_code=409, detail="VALIDATION_REQUIRED")
        if validation.get("validated_execution_mode") != body.execution_mode:
            raise HTTPException(status_code=409, detail="VALIDATION_REQUIRED")
        dedupe_key = body.idempotency_key or f"{draft_id}:{body.validated_draft_hash}:{body.execution_mode}"
        existing = store.get_dedupe(draft_id, dedupe_key)
        if existing is not None:
            return {
                "ok": True,
                "run_id": existing.run_id,
                "draft_id": draft_id,
                "executed_draft_hash": existing.executed_draft_hash,
                "execution_mode": "rerun_child",
                "deduped": True,
                "produced_lineage": validation["resolved_execution"],
                "focus": {"status": "pending_index", "run_id": existing.run_id, "poll": validation["resolved_execution"]},
            }
        draft = current.draft
        model = next(n for n in draft["graph"]["nodes"] if n.get("node_type") == "model")
        source = draft["created_from"]
        run_root = _resolve_run_root(project_root, source["source_run_id"])
        inputs = read_run_inputs(run_root)
        upload_bytes = verify_upload(Path(project_root), inputs["upload"]["sha256"]).read_bytes()
        op_overrides = {
            key: value
            for key, value in model["params"].items()
            if model["source_params"].get(key) != value
        }
        started_at = datetime.now(timezone.utc).isoformat()
        run_level_rerun_from = run_rerun_from_from_context(
            request_id=f"draft:{draft_id}",
            owner_run_id=source["source_run_id"],
            op_node_id=source["source_op_node_id"],
            node_hash=source["source_node_hash"],
            context_fingerprint=source["source_context_fingerprint"],
        )

        def before_dispatch(new_run_id: str) -> None:
            run_dir = Path(project_root) / "runs" / new_run_id
            executed_hash = compute_executable_draft_hash(draft)
            (run_dir / "executed_pipeline_draft.json").write_text(
                json.dumps(
                    {
                        "executed_at": utc_now(),
                        "source_draft_id": draft_id,
                        "executed_draft_hash": executed_hash,
                        "execution_request": {
                            "execution_mode": "rerun_child",
                            "validated_draft_hash": body.validated_draft_hash,
                        },
                        "draft": draft,
                    },
                    sort_keys=True,
                    indent=2,
                ),
                encoding="utf-8",
            )
            store.record_dedupe(draft_id, dedupe_key, run_id=new_run_id, executed_draft_hash=executed_hash)

        events = get_event_manager()
        if not events.try_acquire_slot():
            raise HTTPException(status_code=429, detail="A run is already in progress.")
        try:
            result = _submit_run(
                Path(project_root),
                form={**inputs["form"], **{k: json.dumps(v) if isinstance(v, (list, dict)) else str(v) for k, v in op_overrides.items()}},
                upload_bytes=upload_bytes,
                upload_filename=inputs["upload"].get("filename") or "upload.csv",
                started_at=started_at,
                rerun_of=source["source_run_id"],
                from_node=source["source_op_node_id"],
                rerun_reason="pipeline_draft",
                op_overrides=op_overrides,
                rerun_from=run_level_rerun_from,
                before_dispatch=before_dispatch,
            )
        except Exception:
            events.release_slot(None)
            raise
        executed = store.get_dedupe(draft_id, dedupe_key)
        assert executed is not None
        return {
            "ok": True,
            "run_id": result["run_id"],
            "draft_id": draft_id,
            "executed_draft_hash": executed.executed_draft_hash,
            "execution_mode": "rerun_child",
            "produced_lineage": {
                "rerun_from_run_id": source["source_run_id"],
                "rerun_from_model_node_id": source["source_model_node_id"],
                "rerun_from_op_node_id": source["source_op_node_id"],
            },
            "focus": {
                "status": "pending_index",
                "run_id": result["run_id"],
                "poll": {
                    "rerun_from_run_id": source["source_run_id"],
                    "rerun_from_model_node_id": source["source_model_node_id"],
                    "rerun_from_op_node_id": source["source_op_node_id"],
                },
            },
        }
```

- [ ] **Step 5: Run execute tests**

Run:

```bash
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/test_pipeline_drafts_api.py tests/test_rerun_endpoint.py::test_direct_rerun_rejects_pipeline_draft_payload_fields -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 6: Commit Task 4**

```bash
git add backend/workbench/api.py backend/workbench/lineage/pipeline_drafts.py tests/test_pipeline_drafts_api.py tests/test_rerun_endpoint.py
git commit -m "feat(api): execute pipeline drafts as child runs"
```

## Task 5: Frontend API Types and Client Functions

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/api.test.ts`

- [ ] **Step 1: Add API client tests**

Append to `frontend/src/api.test.ts`:

```ts
import {
  createPipelineDraftFromNode,
  executePipelineDraft,
  getPipelineDraft,
  patchPipelineDraftParams,
  validatePipelineDraft,
} from "./api";

test("pipeline draft client calls draft endpoints", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify({ draft: { draft_id: "draft_1" }, draft_hash: "h1" }), { status: 200 });
  }));
  await createPipelineDraftFromNode("/tmp/project", {
    source_run_id: "run_1",
    source_model_node_id: "model_1",
    source_op_node_id: "op_1",
    source_node_hash: "hash_1",
    source_context_fingerprint: "ctx_1",
  });
  await getPipelineDraft("/tmp/project", "draft_1");
  await patchPipelineDraftParams("/tmp/project", "draft_1", {
    model_node_id: "model_1",
    base_draft_hash: "h1",
    params: { x: ["x1"] },
  });
  await validatePipelineDraft("/tmp/project", "draft_1", "rerun_child");
  await executePipelineDraft("/tmp/project", "draft_1", {
    validated_draft_hash: "h1",
    execution_mode: "rerun_child",
  });
  expect(calls.map((c) => c.url).join("\n")).toContain("/pipeline-drafts/from-node");
  expect(calls.map((c) => c.url).join("\n")).toContain("/pipeline-drafts/draft_1");
  expect(calls.map((c) => c.url).join("\n")).toContain("/pipeline-drafts/draft_1/validate");
  expect(calls.map((c) => c.url).join("\n")).toContain("/pipeline-drafts/draft_1/execute");
});
```

- [ ] **Step 2: Run the frontend API test to verify failure**

Run:

```bash
cd frontend && npm test -- src/api.test.ts -t "pipeline draft client calls draft endpoints" --runInBand
```

Expected:

```text
export 'createPipelineDraftFromNode' not found
```

- [ ] **Step 3: Add PipelineDraft types and client functions**

Append to `frontend/src/api.ts`:

```ts
export type DraftExecutionMode = "rerun_child" | "new_run";

export type PipelineDraftNode =
  | {
      node_id: string;
      node_type: "input.dataset";
      source_type: "run_input" | "upload";
      run_input_id?: string;
      input_fingerprint: string;
      schema_fingerprint: string;
      row_count?: number;
      column_count?: number;
      columns_summary?: Array<{ name: string; dtype?: string }>;
      status: "bound" | "missing" | "invalid";
    }
  | {
      node_id: string;
      node_type: "model";
      model_family: string;
      model_type: string;
      schema_id: string;
      editable_schema: unknown[];
      editable_schema_hash: string;
      source_ref: Record<string, string>;
      source_params: Record<string, unknown>;
      params: Record<string, unknown>;
    };

export type PipelineDraftV1 = {
  draft_id: string;
  schema_version: "pipeline_draft.v1";
  created_at: string;
  updated_at: string;
  status: string;
  created_from?: Record<string, string>;
  graph: { nodes: PipelineDraftNode[]; edges: Array<{ from: string; to: string }> };
  default_execution_mode: DraftExecutionMode;
};

export type PipelineDraftResponse = { draft: PipelineDraftV1; draft_hash: string };

export type DraftValidationResult = {
  ok: boolean;
  status: "valid" | "invalid" | "blocked";
  executable: boolean;
  checks: Array<{ code: string; level: "error" | "warning" | "info"; message: string; node_id?: string; blocking: boolean }>;
  resolved_execution: {
    execution_mode: DraftExecutionMode;
    compare_source_available: boolean;
    rerun_from_run_id?: string;
    rerun_from_model_node_id?: string;
    rerun_from_op_node_id?: string;
  };
  validated_execution_mode?: DraftExecutionMode;
  validated_draft_hash?: string;
  validated_at: string;
};

export type DraftExecutionResult = {
  ok: boolean;
  run_id: string;
  draft_id: string;
  executed_draft_hash: string;
  execution_mode: "rerun_child";
  deduped?: boolean;
  produced_lineage: {
    rerun_from_run_id: string;
    rerun_from_model_node_id: string;
    rerun_from_op_node_id: string;
  };
  focus: {
    status: "ready" | "pending_index";
    run_id: string;
    target_model_node_id?: string;
    poll?: {
      rerun_from_run_id: string;
      rerun_from_model_node_id: string;
      rerun_from_op_node_id: string;
    };
  };
};

export async function createPipelineDraftFromNode(
  projectRoot: string,
  body: {
    source_run_id: string;
    source_model_node_id: string;
    source_op_node_id: string;
    source_node_hash: string;
    source_context_fingerprint: string;
  },
): Promise<PipelineDraftResponse> {
  const response = await fetch(apiUrl(`/pipeline-drafts/from-node?project_root=${encodeURIComponent(projectRoot)}`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readResponse<PipelineDraftResponse>(response);
}

export async function getPipelineDraft(projectRoot: string, draftId: string): Promise<PipelineDraftResponse> {
  const response = await fetch(apiUrl(`/pipeline-drafts/${encodeURIComponent(draftId)}?project_root=${encodeURIComponent(projectRoot)}`));
  return readResponse<PipelineDraftResponse>(response);
}

export async function patchPipelineDraftParams(
  projectRoot: string,
  draftId: string,
  body: { model_node_id: string; base_draft_hash: string; params: Record<string, unknown> },
): Promise<PipelineDraftResponse> {
  const response = await fetch(apiUrl(`/pipeline-drafts/${encodeURIComponent(draftId)}?project_root=${encodeURIComponent(projectRoot)}`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readResponse<PipelineDraftResponse>(response);
}

export async function validatePipelineDraft(projectRoot: string, draftId: string, executionMode: DraftExecutionMode): Promise<DraftValidationResult> {
  const response = await fetch(apiUrl(`/pipeline-drafts/${encodeURIComponent(draftId)}/validate?project_root=${encodeURIComponent(projectRoot)}`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ execution_mode: executionMode }),
  });
  return readResponse<DraftValidationResult>(response);
}

export async function executePipelineDraft(
  projectRoot: string,
  draftId: string,
  body: { validated_draft_hash: string; execution_mode: DraftExecutionMode; idempotency_key?: string },
): Promise<DraftExecutionResult> {
  const response = await fetch(apiUrl(`/pipeline-drafts/${encodeURIComponent(draftId)}/execute?project_root=${encodeURIComponent(projectRoot)}`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return readResponse<DraftExecutionResult>(response);
}
```

- [ ] **Step 4: Run API client tests**

Run:

```bash
cd frontend && npm test -- src/api.test.ts -t "pipeline draft client calls draft endpoints" --runInBand
```

Expected:

```text
1 test passed
```

- [ ] **Step 5: Commit Task 5**

```bash
git add frontend/src/api.ts frontend/src/api.test.ts
git commit -m "feat(frontend): add pipeline draft api client"
```

## Task 6: Draft Graph View and State Machine

**Files:**
- Create: `frontend/src/pipelineDrafts/DraftGraphCanvas.tsx`
- Create: `frontend/src/pipelineDrafts/DraftGraphCanvas.test.tsx`
- Create: `frontend/src/pipelineDrafts/ModelNodeInspector.tsx`
- Create: `frontend/src/pipelineDrafts/ModelNodeInspector.test.tsx`
- Create: `frontend/src/pipelineDrafts/DraftGraphRoute.tsx`
- Create: `frontend/src/pipelineDrafts/DraftGraphRoute.test.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write canvas tests**

Create `frontend/src/pipelineDrafts/DraftGraphCanvas.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { DraftGraphCanvas } from "./DraftGraphCanvas";
import type { PipelineDraftV1 } from "../api";

const draft: PipelineDraftV1 = {
  draft_id: "draft_1",
  schema_version: "pipeline_draft.v1",
  created_at: "",
  updated_at: "",
  status: "draft",
  graph: {
    nodes: [
      { node_id: "input_1", node_type: "input.dataset", source_type: "run_input", run_input_id: "run_1", input_fingerprint: "i", schema_fingerprint: "s", status: "bound" },
      { node_id: "model_1", node_type: "model", model_family: "regression", model_type: "ols", schema_id: "ols@v1", editable_schema: [], editable_schema_hash: "h", source_ref: {}, source_params: {}, params: {} },
    ],
    edges: [{ from: "input_1", to: "model_1" }],
  },
  default_execution_mode: "rerun_child",
};

test("renders fixed InputNode to ModelNode graph", () => {
  render(<DraftGraphCanvas draft={draft} selectedNodeId="input_1" onSelectNode={() => {}} />);
  expect(screen.getByText("Input Dataset")).toBeInTheDocument();
  expect(screen.getByText("Model")).toBeInTheDocument();
  expect(screen.getByText("input_1 -> model_1")).toBeInTheDocument();
});
```

- [ ] **Step 2: Implement canvas**

Create `frontend/src/pipelineDrafts/DraftGraphCanvas.tsx`:

```tsx
import type { PipelineDraftV1 } from "../api";

export function DraftGraphCanvas({
  draft,
  selectedNodeId,
  onSelectNode,
}: {
  draft: PipelineDraftV1;
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
}) {
  const input = draft.graph.nodes.find((n) => n.node_type === "input.dataset");
  const model = draft.graph.nodes.find((n) => n.node_type === "model");
  const edge = draft.graph.edges[0];
  return (
    <section aria-label="Draft graph" className="draft-graph">
      <button type="button" aria-pressed={selectedNodeId === input?.node_id} onClick={() => input && onSelectNode(input.node_id)}>
        <strong>Input Dataset</strong>
        <span>{input && "run_input_id" in input ? input.run_input_id : ""}</span>
      </button>
      <div aria-label="Draft edge">{edge ? `${edge.from} -> ${edge.to}` : "No edge"}</div>
      <button type="button" aria-pressed={selectedNodeId === model?.node_id} onClick={() => model && onSelectNode(model.node_id)}>
        <strong>Model</strong>
        <span>{model && "model_type" in model ? model.model_type : ""}</span>
      </button>
    </section>
  );
}
```

- [ ] **Step 3: Write inspector tests**

Create `frontend/src/pipelineDrafts/ModelNodeInspector.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { ModelNodeInspector } from "./ModelNodeInspector";

test("saves full params with base_draft_hash", () => {
  const onSave = vi.fn();
  render(
    <ModelNodeInspector
      draftHash="h1"
      node={{
        node_id: "model_1",
        node_type: "model",
        model_family: "regression",
        model_type: "ols",
        schema_id: "ols@v1",
        editable_schema: [{ key: "model_type", kind: "select", label: "Model", value: "ols", options: ["ols", "logit"] }],
        editable_schema_hash: "schema",
        source_ref: {},
        source_params: { model_type: "ols" },
        params: { model_type: "ols" },
      }}
      onSave={onSave}
    />,
  );
  fireEvent.change(screen.getByLabelText("Model"), { target: { value: "logit" } });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  expect(onSave).toHaveBeenCalledWith({
    model_node_id: "model_1",
    base_draft_hash: "h1",
    params: { model_type: "logit" },
  });
});
```

- [ ] **Step 4: Implement model inspector**

Create `frontend/src/pipelineDrafts/ModelNodeInspector.tsx`:

```tsx
import { useState } from "react";
import type { PipelineDraftNode } from "../api";
import { renderControl } from "../lineage/controls/controlFactory";
import type { EditableControl } from "../lineage/api/graphViewTypes";

type ModelNode = Extract<PipelineDraftNode, { node_type: "model" }>;

export function ModelNodeInspector({
  node,
  draftHash,
  onSave,
}: {
  node: ModelNode;
  draftHash: string;
  onSave: (body: { model_node_id: string; base_draft_hash: string; params: Record<string, unknown> }) => void;
}) {
  const [params, setParams] = useState<Record<string, unknown>>(node.params);
  const controls = node.editable_schema as EditableControl[];
  const withValues = controls.map((control) => ({
    ...control,
    value: params[control.key] ?? control.value,
  }));
  return (
    <section aria-label="Model node inspector">
      <h2>ModelNode</h2>
      <dl>
        <dt>Model type</dt>
        <dd>{node.model_type}</dd>
        <dt>Schema</dt>
        <dd>{node.schema_id}</dd>
      </dl>
      {withValues.map((control) => (
        <label key={control.key}>
          {renderControl(control, (key, value) => setParams((prev) => ({ ...prev, [key]: value })))}
        </label>
      ))}
      <button type="button" onClick={() => setParams(node.source_params)}>
        Reset to source
      </button>
      <button type="button" onClick={() => onSave({ model_node_id: node.node_id, base_draft_hash: draftHash, params })}>
        Save changes
      </button>
    </section>
  );
}
```

- [ ] **Step 5: Write route test for save/validate/execute button states**

Create `frontend/src/pipelineDrafts/DraftGraphRoute.test.tsx`:

```tsx
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DraftGraphRoute } from "./DraftGraphRoute";
import * as api from "../api";

vi.mock("../api");

test("loads draft and keeps execute disabled until validated current hash", async () => {
  vi.mocked(api.getPipelineDraft).mockResolvedValue({
    draft_hash: "h1",
    draft: {
      draft_id: "draft_1",
      schema_version: "pipeline_draft.v1",
      created_at: "",
      updated_at: "",
      status: "draft",
      graph: {
        nodes: [
          { node_id: "input_1", node_type: "input.dataset", source_type: "run_input", run_input_id: "run_1", input_fingerprint: "i", schema_fingerprint: "s", status: "bound" },
          { node_id: "model_1", node_type: "model", model_family: "regression", model_type: "ols", schema_id: "ols@v1", editable_schema: [], editable_schema_hash: "schema", source_ref: {}, source_params: {}, params: {} },
        ],
        edges: [{ from: "input_1", to: "model_1" }],
      },
      default_execution_mode: "rerun_child",
    },
  });
  vi.mocked(api.validatePipelineDraft).mockResolvedValue({
    ok: true,
    status: "valid",
    executable: true,
    checks: [],
    resolved_execution: { execution_mode: "rerun_child", compare_source_available: true },
    validated_execution_mode: "rerun_child",
    validated_draft_hash: "h1",
    validated_at: "",
  });
  render(
    <MemoryRouter initialEntries={["/pipeline-drafts/draft_1?project_root=/tmp/project"]}>
      <Routes><Route path="/pipeline-drafts/:draftId" element={<DraftGraphRoute />} /></Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByText("Input Dataset")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Execute Draft" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Validate" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Execute Draft" })).toBeEnabled());
});
```

- [ ] **Step 6: Implement draft route**

Create `frontend/src/pipelineDrafts/DraftGraphRoute.tsx`:

```tsx
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  executePipelineDraft,
  getPipelineDraft,
  patchPipelineDraftParams,
  validatePipelineDraft,
  type DraftValidationResult,
  type PipelineDraftV1,
} from "../api";
import { DraftGraphCanvas } from "./DraftGraphCanvas";
import { ModelNodeInspector } from "./ModelNodeInspector";

export function DraftGraphRoute() {
  const { draftId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const projectRoot = searchParams.get("project_root") ?? "";
  const [draft, setDraft] = useState<PipelineDraftV1 | null>(null);
  const [draftHash, setDraftHash] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [unsaved, setUnsaved] = useState(false);
  const [validation, setValidation] = useState<DraftValidationResult | null>(null);

  useEffect(() => {
    getPipelineDraft(projectRoot, draftId).then((res) => {
      setDraft(res.draft);
      setDraftHash(res.draft_hash);
      setSelectedNodeId(res.draft.graph.nodes[0]?.node_id ?? null);
    });
  }, [projectRoot, draftId]);

  const selectedNode = useMemo(
    () => draft?.graph.nodes.find((node) => node.node_id === selectedNodeId) ?? null,
    [draft, selectedNodeId],
  );
  const validatedHash = validation?.validated_draft_hash;
  const canExecute = Boolean(draft && !unsaved && validation?.status === "valid" && validatedHash === draftHash);

  if (!draft) return <section className="panel">Loading draft…</section>;

  return (
    <section className="panel" aria-label="Draft Graph">
      <div className="panel-heading">
        <h2>Draft Graph</h2>
        <span>{draft.draft_id}</span>
      </div>
      <div className="draft-toolbar">
        <span>{unsaved ? "Unsaved" : validation && validatedHash !== draftHash ? "Validation stale" : "Saved"}</span>
        <button
          type="button"
          disabled={unsaved}
          onClick={async () => setValidation(await validatePipelineDraft(projectRoot, draftId, "rerun_child"))}
        >
          Validate
        </button>
        <button
          type="button"
          disabled={!canExecute}
          onClick={async () => {
            const result = await executePipelineDraft(projectRoot, draftId, {
              validated_draft_hash: validatedHash ?? "",
              execution_mode: "rerun_child",
            });
            const params = new URLSearchParams({ project_root: projectRoot, tab: "lineage" });
            if (result.focus.target_model_node_id) params.set("focus", result.focus.target_model_node_id);
            navigate(`/runs/${result.run_id}?${params.toString()}`);
          }}
        >
          Execute Draft
        </button>
      </div>
      <DraftGraphCanvas draft={draft} selectedNodeId={selectedNodeId} onSelectNode={setSelectedNodeId} />
      {selectedNode?.node_type === "input.dataset" && (
        <section aria-label="Input node inspector">
          <h2>InputNode</h2>
          <p>{selectedNode.run_input_id}</p>
          <p>{selectedNode.input_fingerprint}</p>
        </section>
      )}
      {selectedNode?.node_type === "model" && (
        <ModelNodeInspector
          node={selectedNode}
          draftHash={draftHash}
          onSave={async (body) => {
            const res = await patchPipelineDraftParams(projectRoot, draftId, body);
            setDraft(res.draft);
            setDraftHash(res.draft_hash);
            setValidation(null);
            setUnsaved(false);
          }}
        />
      )}
      {validation && (
        <section aria-label="Validation panel">
          {validation.checks.map((check) => <p key={check.code}>{check.code}: {check.message}</p>)}
        </section>
      )}
    </section>
  );
}
```

- [ ] **Step 7: Add route in App**

Modify imports in `frontend/src/App.tsx`:

```ts
import { DraftGraphRoute } from "./pipelineDrafts/DraftGraphRoute";
```

Add route:

```tsx
<Route path="pipeline-drafts/:draftId" element={<DraftGraphRoute />} />
```

- [ ] **Step 8: Run route tests**

Run:

```bash
cd frontend && npm test -- src/pipelineDrafts --runInBand
```

Expected:

```text
all pipelineDrafts tests pass
```

- [ ] **Step 9: Commit Task 6**

```bash
git add frontend/src/App.tsx frontend/src/pipelineDrafts
git commit -m "feat(frontend): add draft graph view"
```

## Task 7: Entry Points from Lineage and Run Overview

**Files:**
- Modify: `frontend/src/lineage/graph/NodeActionMenu.tsx`
- Modify: `frontend/src/lineage/graph/NodeActionMenu.test.tsx`
- Modify: `frontend/src/runResult.tsx` or `frontend/src/runDetail.tsx`

- [ ] **Step 1: Add NodeActionMenu test for Open as Draft Graph**

Append to `frontend/src/lineage/graph/NodeActionMenu.test.tsx`:

```tsx
it("opens an eligible model node as a draft graph", async () => {
  const navigate = vi.fn();
  const seed = makeOwnerResolutionSeedFixture();
  const selected = seed.forest.nodes.find((n) => n.nodeKey === seed.uniqueModelNodeKey)!;
  vi.mocked(useNavigate).mockReturnValue(navigate);
  vi.mocked(api.createPipelineDraftFromNode).mockResolvedValue({
    draft: { draft_id: "draft_1" } as any,
    draft_hash: "h1",
  });
  render(
    <ForestContext.Provider
      value={{ forest: seed.forest, activeRunId: seed.ownerRunId, setActiveRunId: vi.fn() }}
    >
      <NodeOperationContextProvider node={selected}>
        <NodeActionMenu
          node={selected}
          model={seed.graphModel}
          onShowJson={vi.fn()}
          projectRoot="/tmp/project"
        />
      </NodeOperationContextProvider>
    </ForestContext.Provider>,
  );
  fireEvent.click(screen.getByRole("button", { name: /open as draft graph/i }));
  await waitFor(() => expect(navigate).toHaveBeenCalledWith("/pipeline-drafts/draft_1?project_root=%2Ftmp%2Fproject"));
});
```

If `makeOwnerResolutionSeedFixture()` does not expose `uniqueModelNodeKey` and `ownerRunId`, extend that fixture in `frontend/src/lineage/api/nodeOperationContext.ts` so the test selects a uniquely owned eligible model node. Do not select by array position, active head, parent, or `runs[0]`.

- [ ] **Step 2: Implement canonical node action**

In `NodeActionMenu.tsx`, import `createPipelineDraftFromNode` and `useNavigate`, then add a button only when `resolvedContext?.ok` and the node has editable schema:

```tsx
const canOpenDraft =
  resolvedContext?.ok &&
  resolvedContext.context.operation_target.editable_schema?.length;

async function onOpenDraftGraph() {
  if (!canOpenDraft || !resolvedContext?.ok) return;
  const context = resolvedContext.context;
  const result = await createPipelineDraftFromNode(projectRoot, {
    source_run_id: context.operation_target.owner_run_id,
    source_model_node_id: context.selection.node_id,
    source_op_node_id: context.operation_target.op_node_id,
    source_node_hash: context.operation_target.node_hash,
    source_context_fingerprint: context.context_fingerprint,
  });
  navigate(`/pipeline-drafts/${result.draft.draft_id}?project_root=${encodeURIComponent(projectRoot)}`);
}
```

Render:

```tsx
{canOpenDraft && (
  <button type="button" onClick={onOpenDraftGraph}>
    Open as Draft Graph
  </button>
)}
```

- [ ] **Step 3: Add run overview shortcut only if existing data makes uniqueness explicit**

If `runResult.tsx` or `runDetail.tsx` does not already have enough graph/headset context to prove exactly one eligible model node, do not add a run-level shortcut in this task. Add a small note to `docs/dev-browser-smoke.md`:

```markdown
Run-level Open in Graph remains deferred until the route can prove exactly one eligible model node without guessing.
```

This satisfies the spec because the run-level shortcut is allowed but not required.

- [ ] **Step 4: Run action tests**

Run:

```bash
cd frontend && npm test -- src/lineage/graph/NodeActionMenu.test.tsx --runInBand
```

Expected:

```text
all NodeActionMenu tests pass
```

- [ ] **Step 5: Commit Task 7**

```bash
git add frontend/src/lineage/graph/NodeActionMenu.tsx frontend/src/lineage/graph/NodeActionMenu.test.tsx docs/dev-browser-smoke.md
git commit -m "feat(lineage): open model nodes as draft graphs"
```

## Task 8: Focus / Pending Poll Integration

**Files:**
- Modify: `frontend/src/workbench/WorkbenchRouteContainer.tsx`
- Modify: `frontend/src/workbench/WorkbenchRouteContainer.test.tsx`
- Modify: `frontend/src/pipelineDrafts/DraftGraphRoute.tsx`
- Test: `frontend/src/pipelineDrafts/DraftGraphRoute.test.tsx`

- [ ] **Step 1: Add pending-index route test**

Extend `DraftGraphRoute.test.tsx`:

```tsx
test("execute pending_index navigates to lineage without requiring target node id", async () => {
  const navigate = vi.fn();
  vi.mocked(useNavigate).mockReturnValue(navigate);
  vi.mocked(api.getPipelineDraft).mockResolvedValue(makeDraftResponse({ draftHash: "h1" }));
  vi.mocked(api.validatePipelineDraft).mockResolvedValue({
    ok: true,
    status: "valid",
    executable: true,
    checks: [],
    resolved_execution: {
      execution_mode: "rerun_child",
      compare_source_available: true,
      rerun_from_run_id: "run_parent",
      rerun_from_model_node_id: "model_parent",
      rerun_from_op_node_id: "op_parent",
    },
    validated_draft_hash: "h1",
    validated_execution_mode: "rerun_child",
    validated_at: "2026-06-29T00:00:00Z",
  });
  vi.mocked(api.executePipelineDraft).mockResolvedValue({
    ok: true,
    run_id: "run_child",
    draft_id: "draft_1",
    executed_draft_hash: "h1",
    execution_mode: "rerun_child",
    produced_lineage: {
      rerun_from_run_id: "run_parent",
      rerun_from_model_node_id: "model_parent",
      rerun_from_op_node_id: "op_parent",
    },
    focus: {
      status: "pending_index",
      run_id: "run_child",
      poll: {
        rerun_from_run_id: "run_parent",
        rerun_from_model_node_id: "model_parent",
        rerun_from_op_node_id: "op_parent",
      },
    },
  });
  render(<DraftGraphRoute projectRoot="/tmp/project" draftId="draft_1" />);
  await screen.findByText(/input dataset/i);
  fireEvent.click(screen.getByRole("button", { name: /validate/i }));
  await screen.findByText(/valid/i);
  fireEvent.click(screen.getByRole("button", { name: /execute draft/i }));
  await waitFor(() =>
    expect(navigate).toHaveBeenCalledWith(
      "/runs/run_child?project_root=%2Ftmp%2Fproject&tab=lineage&pending_source_run_id=run_parent&pending_source_model_node_id=model_parent&pending_source_op_node_id=op_parent",
    ),
  );
});
```

- [ ] **Step 2: Implement pending poll query params**

In `DraftGraphRoute.tsx`, when execute returns pending_index, navigate with source poll identifiers:

```ts
if (result.focus.status === "pending_index" && result.focus.poll) {
  params.set("pending_source_run_id", result.focus.poll.rerun_from_run_id);
  params.set("pending_source_model_node_id", result.focus.poll.rerun_from_model_node_id);
  params.set("pending_source_op_node_id", result.focus.poll.rerun_from_op_node_id);
}
```

- [ ] **Step 3: Reuse existing WorkbenchRouteContainer pending focus behavior**

Inspect `frontend/src/workbench/WorkbenchRouteContainer.tsx` existing `produced_lineage` handling from v1.6.3. If it already polls by rerun_from op node, add support for the three query params. If it only handles in-memory responses, add a small parser:

```ts
const pendingPoll = {
  rerun_from_run_id: searchParams.get("pending_source_run_id"),
  rerun_from_model_node_id: searchParams.get("pending_source_model_node_id"),
  rerun_from_op_node_id: searchParams.get("pending_source_op_node_id"),
};
```

Use it only to poll the new child run for the produced node; do not infer source from active head, parent, run order, or `runs[0]`.

- [ ] **Step 4: Run pending poll tests**

Run:

```bash
cd frontend && npm test -- src/pipelineDrafts/DraftGraphRoute.test.tsx src/workbench/WorkbenchRouteContainer.test.tsx --runInBand
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 5: Commit Task 8**

```bash
git add frontend/src/pipelineDrafts/DraftGraphRoute.tsx frontend/src/pipelineDrafts/DraftGraphRoute.test.tsx frontend/src/workbench/WorkbenchRouteContainer.tsx frontend/src/workbench/WorkbenchRouteContainer.test.tsx
git commit -m "feat(workbench): focus draft child runs from produced lineage"
```

## Task 9: Guardrails and Regression Tests

**Files:**
- Test: `tests/test_pipeline_drafts_api.py`
- Test: `frontend/src/pipelineDrafts/DraftGraphRoute.test.tsx`
- Test: `frontend/src/lineage/graph/NodeActionMenu.test.tsx`

- [ ] **Step 1: Add backend guardrail tests**

Append to `tests/test_pipeline_drafts_api.py`:

```python
def test_validate_does_not_create_run_or_artifacts(tmp_path: Path) -> None:
    client = _client()
    run_id, project_root = _create_completed_run(client, tmp_path)
    draft = _create_draft_from_first_model_node(client, project_root, run_id)
    runs_dir = Path(project_root) / "runs"
    before = {p.name for p in runs_dir.iterdir() if p.is_dir()}

    response = client.post(
        f"/pipeline-drafts/{draft['draft']['draft_id']}/validate",
        params={"project_root": project_root},
        json={"execution_mode": "rerun_child"},
    )

    assert response.status_code == 200, response.text
    after = {p.name for p in runs_dir.iterdir() if p.is_dir()}
    assert after == before
    assert not list(runs_dir.glob("*/executed_pipeline_draft.json"))


def test_from_node_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    client = _client()
    run_id, project_root = _create_completed_run(client, tmp_path)
    graph = client.get(f"/runs/{run_id}/graph", params={"project_root": project_root}).json()
    model = next(n for n in graph["nodes"] if n.get("stage") == "model")

    response = client.post(
        "/pipeline-drafts/from-node",
        params={"project_root": project_root},
        json={
            "source_run_id": run_id,
            "source_model_node_id": model["id"],
            "source_op_node_id": model["id"],
            "source_node_hash": "wrong",
            "source_context_fingerprint": model.get("context_fingerprint") or model["node_hash"],
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "SOURCE_NODE_HASH_MISMATCH"


def test_execute_revalidates_after_lock(tmp_path: Path) -> None:
    client = _client()
    run_id, project_root = _create_completed_run(client, tmp_path)
    draft = _create_draft_from_first_model_node(client, project_root, run_id)
    draft_id = draft["draft"]["draft_id"]
    validation = client.post(
        f"/pipeline-drafts/{draft_id}/validate",
        params={"project_root": project_root},
        json={"execution_mode": "rerun_child"},
    ).json()
    patched = client.patch(
        f"/pipeline-drafts/{draft_id}",
        params={"project_root": project_root},
        json={
            "model_node_id": "model_1",
            "base_draft_hash": validation["validated_draft_hash"],
            "params": {"x": ["x1"]},
        },
    )
    assert patched.status_code == 200, patched.text

    response = client.post(
        f"/pipeline-drafts/{draft_id}/execute",
        params={"project_root": project_root},
        json={
            "validated_draft_hash": validation["validated_draft_hash"],
            "execution_mode": "rerun_child",
        },
    )

    assert response.status_code == 409
    assert response.json()["code"] == "VALIDATED_DRAFT_HASH_MISMATCH"
```

Add `_create_draft_from_first_model_node(client, project_root, run_id)` near `_create_completed_run()` if Task 3 did not already add it. It must call `/runs/{run_id}/graph`, pick the node with `stage == "model"`, and POST `/pipeline-drafts/from-node` with that node's explicit source fields.

- [ ] **Step 2: Add frontend guardrail tests**

Add tests for:

```tsx
test("Validate is disabled while local edits are unsaved", async () => {
  vi.mocked(api.getPipelineDraft).mockResolvedValue(makeDraftResponse({ draftHash: "h1" }));
  render(<DraftGraphRoute projectRoot="/tmp/project" draftId="draft_1" />);
  fireEvent.click(await screen.findByRole("button", { name: /model/i }));
  fireEvent.change(screen.getByLabelText(/alpha/i), { target: { value: "0.01" } });
  expect(screen.getByRole("button", { name: /save changes/i })).toBeEnabled();
  expect(screen.getByRole("button", { name: /validate/i })).toBeDisabled();
  expect(screen.getByRole("button", { name: /execute draft/i })).toBeDisabled();
});

test("DRAFT_HASH_CONFLICT reloads draft and marks validation stale", async () => {
  vi.mocked(api.getPipelineDraft)
    .mockResolvedValueOnce(makeDraftResponse({ draftHash: "h1" }))
    .mockResolvedValueOnce(makeDraftResponse({ draftHash: "h2" }));
  vi.mocked(api.patchPipelineDraftParams).mockRejectedValue(
    new api.ApiError(409, "DRAFT_HASH_CONFLICT", "Draft changed on the server"),
  );
  render(<DraftGraphRoute projectRoot="/tmp/project" draftId="draft_1" />);
  fireEvent.click(await screen.findByRole("button", { name: /model/i }));
  fireEvent.change(screen.getByLabelText(/alpha/i), { target: { value: "0.01" } });
  fireEvent.click(screen.getByRole("button", { name: /save changes/i }));
  await waitFor(() => expect(api.getPipelineDraft).toHaveBeenCalledTimes(2));
  expect(screen.getByText(/validation stale/i)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /execute draft/i })).toBeDisabled();
});
```

- [ ] **Step 3: Run focused regression tests**

Run:

```bash
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/test_pipeline_drafts_api.py tests/test_rerun_endpoint.py -q
cd frontend && npm test -- src/pipelineDrafts src/lineage/graph/NodeActionMenu.test.tsx --runInBand
```

Expected:

```text
backend selected tests pass
frontend selected tests pass
```

- [ ] **Step 4: Commit Task 9**

```bash
git add tests/test_pipeline_drafts_api.py frontend/src/pipelineDrafts frontend/src/lineage/graph/NodeActionMenu.test.tsx
git commit -m "test(lineage): lock pipeline draft guardrails"
```

## Task 10: Browser Smoke Documentation and Full Gate

**Files:**
- Modify: `docs/dev-browser-smoke.md`

- [ ] **Step 1: Add v1.6.4 browser smoke section**

Append:

```markdown
## V1.6.4 Input -> Model Draft Execution Smoke

1. Start backend/frontend normally.
2. Open an existing completed run with an eligible model node.
3. Open the Lineage tab and select the model node.
4. Click `Open as Draft Graph`.
5. Verify `/pipeline-drafts/{draft_id}` loads and shows exactly `Input Dataset -> Model`.
6. Verify InputNode inspector is read-only.
7. Select ModelNode, change one editable_schema field, and click `Save changes`.
8. Verify Validate is enabled and Execute is disabled.
9. Click `Validate`; verify a valid result enables Execute for the current hash.
10. Click `Execute Draft`.
11. Verify navigation to the child run lineage view.
12. If the focus is pending, verify polling resolves using source run/model/op identifiers.
13. Select the produced child model node and verify `Compare with source` is available.
14. Verify direct `/runs/{run_id}/rerun` still works from the operation section.
```

- [ ] **Step 2: Run backend focused suite**

Run:

```bash
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 .venv/bin/python -m pytest tests/test_pipeline_drafts_store.py tests/test_pipeline_drafts_api.py tests/test_rerun_endpoint.py -q
```

Expected:

```text
all selected backend tests pass
```

- [ ] **Step 3: Run frontend focused suite**

Run:

```bash
cd frontend && npm test -- src/api.test.ts src/pipelineDrafts src/lineage/graph/NodeActionMenu.test.tsx src/workbench/WorkbenchRouteContainer.test.tsx --runInBand
```

Expected:

```text
all selected frontend tests pass
```

- [ ] **Step 4: Run full gate**

Run from `.worktrees/workbench-v1.6.4`:

```bash
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh
```

Expected:

```text
>>> GATE PASSED
```

- [ ] **Step 5: Commit final docs if changed**

```bash
git add docs/dev-browser-smoke.md
git commit -m "docs: add v1.6.4 draft smoke"
```

Skip this commit if `docs/dev-browser-smoke.md` was already committed in Task 7.

## Plan Self-Review

Spec coverage:

- PipelineDraft JSON store, path-safe ids, atomic writes, executable-content hash: Tasks 1 and 9.
- Strong Validate and no dry-run behavior: Tasks 2, 3, 9.
- Dedicated API set from-node/GET/PATCH/validate/execute: Tasks 3 and 4.
- `validated_draft_hash`, `validated_execution_mode`, `base_draft_hash`, and execution lock ordering: Tasks 3, 4, 9.
- `new_run` reserved but disabled: Tasks 2, 4.
- Dedicated Draft Graph View: Task 6.
- Canonical node-level entrypoint: Task 7.
- Pending focus / Compare source bridge: Task 8.
- Browser smoke and full gate: Task 10.

Placeholder scan:

- No task uses forbidden placeholder phrases.
- Any step that says "inspect existing behavior" includes a concrete fallback or stop rule.

Type consistency:

- Backend uses `source_context_fingerprint`, `validated_execution_mode`, `base_draft_hash`, `deduped`, and `editable_schema_hash` consistently with the amended spec.
- Frontend PATCH body matches backend PATCH body.
- Execute route binds `execution_mode` to the validation result and dedupe response includes `deduped?: boolean`.
