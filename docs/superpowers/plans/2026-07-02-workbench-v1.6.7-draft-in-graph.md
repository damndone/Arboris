# Workbench v1.6.7 — Draft-in-Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold the standalone Draft Graph into the main lineage forest: select an executed model node → fork a draft child → edit in the detail drawer → validate → execute → the node becomes an executed child in place, with no route navigation. Multiple drafts run in parallel and persist across reload.

**Architecture:** Reuse the existing pipeline-draft backend contract (from-node / patch / validate / execute) unchanged; add two thin endpoints (`GET /pipeline-drafts` list, `DELETE /pipeline-drafts/{id}`) so drafts are first-class, persistent graph citizens. On the frontend, a session `DraftRegistry` (keyed by `draftId`) holds active drafts; a `mergeDraftsIntoModel` layer injects draft nodes+edges into the `GraphViewModel` produced by `forestToGraphViewModel` (anchored by resolving `created_from.source_node_hash` against forest `nodeHash`), so the existing dagre layout positions them. The detail drawer mounts a draft editor (extracted from `ModelNodeInspector`, patch/validate/execute — NOT `OperationSection`, which submits rerun) when a draft node is selected. Pending polling reuses `ForestWorkbench`'s `pendingFocusTarget`, seeded directly from the execute response.

**Tech Stack:** Python 3 / FastAPI / pydantic (backend), React + TypeScript + React Flow + dagre + Vitest (frontend). No new dependencies.

**Reference spec:** `docs/superpowers/specs/2026-07-02-workbench-v1.6.7-draft-in-graph-design.md`

---

## Working rules (read first)

- **Worktree:** all work happens in `.worktrees/workbench-v1.6.7` (branch `workbench-v1.6.7`). Deps are linked (`.venv`, `frontend/node_modules`).
- **Backend tests:** `.venv/bin/python -m pytest <path> -v` from the worktree root.
- **Frontend tests:** `frontend/node_modules/.bin/vitest run <path>` (NOT npx) from the worktree root.
- **Gate before shipping:** `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh` (from the worktree). Golden must be 0-drift — this version adds only list/delete (no artifact/graph changes).
- **Every commit message ends with:**
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  ```
- **Dev-env trap (memory):** never test backend changes via a throwaway `.venv/bin/python` script — the editable install points at the MAIN worktree. Verify backend via pytest (worktree-local) only.

---

## File Structure

**Backend (Slice 1)**
- Modify `backend/workbench/lineage/pipeline_drafts.py` — add `PipelineDraftStore.list()` + `PipelineDraftStore.delete()`.
- Modify `backend/workbench/api.py` — add `GET /pipeline-drafts` + `DELETE /pipeline-drafts/{id}` handlers.
- Test `backend/tests/test_pipeline_draft_store.py` (extend or create) + `backend/tests/test_pipeline_draft_api.py` (extend or create).

**Frontend contract + registry + merge (Slice 2/3)**
- Modify `frontend/src/api.ts` — add `listPipelineDrafts` + `deletePipelineDraft` + `PipelineDraftSummary` type.
- Modify `frontend/src/lineage/api/graphViewTypes.ts` — add `LifecycleState` + `lifecycleState?` / `isDraft?` on `GraphViewNode`.
- Create `frontend/src/lineage/drafts/draftRegistry.ts` — registry state + transitions + hydrate.
- Create `frontend/src/lineage/drafts/draftRegistry.test.ts`.
- Create `frontend/src/lineage/drafts/mergeDraftsIntoModel.ts` — inject draft nodes/edges, anchor resolution.
- Create `frontend/src/lineage/drafts/mergeDraftsIntoModel.test.ts`.

**Frontend UI (Slice 2/4)**
- Modify `frontend/src/lineage/graph/GraphNode.tsx` — render `lifecycleState` visual states.
- Modify `frontend/src/lineage/graph/NodeActionMenu.tsx` — "Fork draft here" (no navigate).
- Create `frontend/src/lineage/detail/sections/DraftEditorSection.tsx` — draft editor (extracted from `ModelNodeInspector`).
- Modify `frontend/src/workbench/WorkbenchRouteContainer.tsx` — mount `DraftRegistry`, merge into `model`, seed pending from execute, hydrate on mount.
- Modify `frontend/src/lineage/header/DetailHeader.tsx` — toolbar row + id truncation + context buttons.

**Do NOT touch:** any estimator / graph / artifact / engine code; `GraphCanvas` dagre layout; `controlFactory` / `OperationSection` internals; existing DraftGraphRoute (kept as deep-link fallback).

---

## Slice 1 — Backend: draft list + delete

### Task 1: `PipelineDraftStore.list()`

**Files:**
- Modify: `backend/workbench/lineage/pipeline_drafts.py`
- Test: `backend/tests/test_pipeline_draft_store.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_pipeline_draft_store.py` (create the file with the imports below if it does not exist):

```python
from pathlib import Path

from workbench.lineage.pipeline_drafts import PipelineDraftStore


def _make_draft(draft_id: str, status: str = "draft", model_type: str = "ols") -> dict:
    return {
        "draft_id": draft_id,
        "schema_version": "pipeline_draft.v1",
        "created_at": "2026-07-02T00:00:00Z",
        "updated_at": "2026-07-02T00:00:00Z",
        "status": status,
        "created_from": {
            "source_type": "run",
            "source_run_id": "run_a",
            "source_model_node_id": "model#0",
            "source_op_node_id": "model#0",
            "source_node_hash": "hash_a",
            "source_context_fingerprint": "ctx_a",
            "source_input_fingerprint": "in_a",
        },
        "graph": {
            "nodes": [
                {"node_type": "model", "node_id": "model#0", "model_type": model_type,
                 "editable_schema": []},
            ],
            "edges": [],
        },
        "default_execution_mode": "rerun_child",
    }


def test_list_empty_returns_empty(tmp_path: Path):
    store = PipelineDraftStore(tmp_path)
    assert store.list() == []


def test_list_returns_summaries(tmp_path: Path):
    store = PipelineDraftStore(tmp_path)
    store.create(_make_draft("d_aaaaaaaa"))
    store.create(_make_draft("d_bbbbbbbb", model_type="logit"))
    summaries = {s["draft_id"]: s for s in store.list()}
    assert set(summaries) == {"d_aaaaaaaa", "d_bbbbbbbb"}
    assert summaries["d_bbbbbbbb"]["model_type"] == "logit"
    assert summaries["d_aaaaaaaa"]["status"] == "draft"
    assert summaries["d_aaaaaaaa"]["source_node_hash"] == "hash_a"
    assert "draft_hash" in summaries["d_aaaaaaaa"]


def test_list_skips_corrupt_json(tmp_path: Path):
    store = PipelineDraftStore(tmp_path)
    store.create(_make_draft("d_aaaaaaaa"))
    (store.drafts_dir / "d_corrupt.json").write_text("{not json", encoding="utf-8")
    ids = {s["draft_id"] for s in store.list()}
    assert ids == {"d_aaaaaaaa"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_pipeline_draft_store.py -v`
Expected: FAIL — `AttributeError: 'PipelineDraftStore' object has no attribute 'list'`

- [ ] **Step 3: Implement `list()`**

Add this method to `PipelineDraftStore` (in `backend/workbench/lineage/pipeline_drafts.py`), right after `get()`:

```python
    def list(self) -> list[dict[str, Any]]:
        """Summaries of every draft json in the store dir (for reload hydrate).

        Skips unreadable / schema-invalid files rather than raising, so one
        corrupt draft never breaks the whole forest.
        """
        if not self.drafts_dir.is_dir():
            return []
        summaries: list[dict[str, Any]] = []
        for path in sorted(self.drafts_dir.glob("*.json")):
            if path.name.endswith(".execution.json"):
                continue
            try:
                draft = json.loads(path.read_text(encoding="utf-8"))
                PipelineDraftV1(**draft)
            except Exception:
                continue
            created_from = draft.get("created_from") or {}
            model_node = next(
                (n for n in draft["graph"]["nodes"] if n.get("node_type") == "model"),
                None,
            )
            summaries.append(
                {
                    "draft_id": draft["draft_id"],
                    "status": draft.get("status", "draft"),
                    "model_type": (model_node or {}).get("model_type"),
                    "source_run_id": created_from.get("source_run_id"),
                    "source_model_node_id": created_from.get("source_model_node_id"),
                    "source_op_node_id": created_from.get("source_op_node_id"),
                    "source_node_hash": created_from.get("source_node_hash"),
                    "draft_hash": compute_executable_draft_hash(draft),
                    "updated_at": draft.get("updated_at"),
                }
            )
        return summaries
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_pipeline_draft_store.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/lineage/pipeline_drafts.py backend/tests/test_pipeline_draft_store.py
git commit -m "feat(drafts): PipelineDraftStore.list() summaries for reload hydrate (v1.6.7 S1)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `PipelineDraftStore.delete()`

**Files:**
- Modify: `backend/workbench/lineage/pipeline_drafts.py`
- Test: `backend/tests/test_pipeline_draft_store.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_pipeline_draft_store.py`:

```python
def test_delete_removes_json_and_dedupe(tmp_path: Path):
    store = PipelineDraftStore(tmp_path)
    store.create(_make_draft("d_aaaaaaaa"))
    # a stray dedupe file for this draft must also go
    dedupe = store.drafts_dir / "d_aaaaaaaa.deadbeef.execution.json"
    dedupe.write_text("{}", encoding="utf-8")
    assert store._path("d_aaaaaaaa").exists()

    store.delete("d_aaaaaaaa")

    assert not store._path("d_aaaaaaaa").exists()
    assert not dedupe.exists()


def test_delete_missing_is_idempotent(tmp_path: Path):
    store = PipelineDraftStore(tmp_path)
    # must not raise
    store.delete("d_missing0")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_pipeline_draft_store.py::test_delete_removes_json_and_dedupe -v`
Expected: FAIL — `AttributeError: ... has no attribute 'delete'`

- [ ] **Step 3: Implement `delete()`**

Add to `PipelineDraftStore`, after `list()`:

```python
    def delete(self, draft_id: str) -> None:
        """Delete a draft json plus its execution/dedupe sidecar files.

        Idempotent: deleting a non-existent draft is a no-op (safe under
        concurrent discard). draft_id is validated to stay inside the store dir.
        """
        validate_draft_id(draft_id)
        lock = self._lock_for(draft_id)
        with lock:
            path = self._path(draft_id)
            if path.exists():
                path.unlink()
            for sidecar in self.drafts_dir.glob(f"{draft_id}.*.execution.json"):
                try:
                    sidecar.unlink()
                except OSError:
                    pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_pipeline_draft_store.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/lineage/pipeline_drafts.py backend/tests/test_pipeline_draft_store.py
git commit -m "feat(drafts): PipelineDraftStore.delete() idempotent json+dedupe cleanup (v1.6.7 S1)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: HTTP `GET /pipeline-drafts` + `DELETE /pipeline-drafts/{id}`

**Files:**
- Modify: `backend/workbench/api.py`
- Test: `backend/tests/test_pipeline_draft_api.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_pipeline_draft_api.py` (create with these imports if absent — mirror the existing draft-api test's client/fixture setup; the snippet below assumes a `client` TestClient and a `project_root` tmp dir with one draft already created via the `/pipeline-drafts/from-node` flow or a store seed):

```python
from workbench.lineage.pipeline_drafts import PipelineDraftStore


def test_list_pipeline_drafts_endpoint(client, project_root, make_draft_dict):
    PipelineDraftStore(Path(project_root)).create(make_draft_dict("d_aaaaaaaa"))
    resp = client.get("/pipeline-drafts", params={"project_root": project_root})
    assert resp.status_code == 200
    body = resp.json()
    assert [d["draft_id"] for d in body["drafts"]] == ["d_aaaaaaaa"]


def test_delete_pipeline_draft_endpoint(client, project_root, make_draft_dict):
    store = PipelineDraftStore(Path(project_root))
    store.create(make_draft_dict("d_aaaaaaaa"))
    resp = client.delete("/pipeline-drafts/d_aaaaaaaa", params={"project_root": project_root})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "draft_id": "d_aaaaaaaa"}
    assert not store._path("d_aaaaaaaa").exists()


def test_delete_missing_draft_is_ok(client, project_root):
    resp = client.delete("/pipeline-drafts/d_missing0", params={"project_root": project_root})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
```

> If the existing draft-api test module lacks `make_draft_dict`/`project_root`/`client` fixtures, add a small `conftest.py`-style fixture in the test file reusing `_make_draft` from Task 1 and FastAPI's `TestClient(app)` with a `tmp_path`-based project root. Keep it consistent with the existing draft-api test if one already exists.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_pipeline_draft_api.py -v -k "list_pipeline_drafts or delete_pipeline_draft or delete_missing_draft"`
Expected: FAIL — 405/404 (route not defined)

- [ ] **Step 3: Add the handlers**

In `backend/workbench/api.py`, add BOTH routes. Place the list route BEFORE the existing `@app.get("/pipeline-drafts/{draft_id}")` so the literal path is not shadowed by the path param:

```python
@app.get("/pipeline-drafts")
def list_pipeline_drafts(project_root: str) -> dict[str, Any]:
    try:
        drafts = _pipeline_draft_store(project_root).list()
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return {"drafts": drafts}
```

And add the delete route (near the other `/pipeline-drafts/{draft_id}` routes):

```python
@app.delete("/pipeline-drafts/{draft_id}")
def delete_pipeline_draft(draft_id: str, project_root: str) -> dict[str, Any]:
    try:
        _pipeline_draft_store(project_root).delete(draft_id)
    except Exception as exc:
        raise _draft_http_error(exc) from exc
    return {"ok": True, "draft_id": draft_id}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_pipeline_draft_api.py -v -k "list_pipeline_drafts or delete_pipeline_draft or delete_missing_draft"`
Expected: PASS (3 tests)

- [ ] **Step 5: Add the FE api.ts client functions**

In `frontend/src/api.ts`, add after `executePipelineDraft`:

```ts
export type PipelineDraftSummary = {
  draft_id: string;
  status: string;
  model_type?: string | null;
  source_run_id?: string | null;
  source_model_node_id?: string | null;
  source_op_node_id?: string | null;
  source_node_hash?: string | null;
  draft_hash: string;
  updated_at?: string | null;
};

export async function listPipelineDrafts(
  projectRoot: string,
): Promise<PipelineDraftSummary[]> {
  const response = await fetch(draftUrl(projectRoot, "/pipeline-drafts"));
  const body = await readResponse<{ drafts: PipelineDraftSummary[] }>(response);
  return body.drafts;
}

export async function deletePipelineDraft(
  projectRoot: string,
  draftId: string,
): Promise<void> {
  const response = await fetch(
    draftUrl(projectRoot, `/pipeline-drafts/${encodeURIComponent(draftId)}`),
    { method: "DELETE" },
  );
  await readResponse<{ ok: boolean }>(response);
}
```

- [ ] **Step 6: Typecheck + commit**

Run: `cd frontend && node_modules/.bin/tsc --noEmit && cd ..`
Expected: no errors

```bash
git add backend/workbench/api.py backend/tests/test_pipeline_draft_api.py frontend/src/api.ts
git commit -m "feat(drafts): GET list + DELETE draft endpoints + FE clients (v1.6.7 S1)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Slice 2 — Frontend: in-graph draft lifecycle (session-scoped)

### Task 4: `LifecycleState` type on graph nodes

**Files:**
- Modify: `frontend/src/lineage/api/graphViewTypes.ts`
- Test: none (pure type addition; covered by consumers)

- [ ] **Step 1: Add the type + node fields**

In `frontend/src/lineage/api/graphViewTypes.ts`, add near the top-level type exports:

```ts
export type LifecycleState =
  | "draft"
  | "validating"
  | "valid"
  | "invalid"
  | "pending"
  | "executed"
  | "failed";
```

Then in `interface GraphViewNode`, in the "forward-compat slots" block, add:

```ts
  // ── v1.6.7 draft-in-graph (undefined for real forest nodes) ──
  isDraft?: boolean;
  lifecycleState?: LifecycleState;
  draftId?: string;
```

- [ ] **Step 2: Typecheck + commit**

Run: `cd frontend && node_modules/.bin/tsc --noEmit && cd ..`
Expected: no errors

```bash
git add frontend/src/lineage/api/graphViewTypes.ts
git commit -m "feat(drafts): LifecycleState + draft slots on GraphViewNode (v1.6.7 S2)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: `DraftRegistry` state + transitions

**Files:**
- Create: `frontend/src/lineage/drafts/draftRegistry.ts`
- Test: `frontend/src/lineage/drafts/draftRegistry.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lineage/drafts/draftRegistry.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  draftReducer,
  emptyRegistry,
  type DraftEntry,
} from "./draftRegistry";
import type { PipelineDraftV1, PipelineDraftSummary } from "../../api";

const draft = (id: string, status = "draft"): PipelineDraftV1 => ({
  draft_id: id,
  schema_version: "pipeline_draft.v1",
  created_at: "t",
  updated_at: "t",
  status,
  created_from: { source_node_hash: "hash_a", source_op_node_id: "model#0" },
  graph: { nodes: [], edges: [] },
  default_execution_mode: "rerun_child",
});

describe("draftReducer", () => {
  it("put creates a draft-state entry", () => {
    const r = draftReducer(emptyRegistry(), {
      type: "put",
      draftId: "d1",
      draft: draft("d1"),
      draftHash: "h1",
    });
    const e = r.get("d1") as DraftEntry;
    expect(e.lifecycleState).toBe("draft");
    expect(e.draftHash).toBe("h1");
  });

  it("patch resets validation and returns to draft state", () => {
    let r = draftReducer(emptyRegistry(), { type: "put", draftId: "d1", draft: draft("d1"), draftHash: "h1" });
    r = draftReducer(r, { type: "validated", draftId: "d1", validation: { status: "valid" } as never, draftHash: "h1" });
    r = draftReducer(r, { type: "patch", draftId: "d1", draft: draft("d1"), draftHash: "h2" });
    const e = r.get("d1") as DraftEntry;
    expect(e.lifecycleState).toBe("draft");
    expect(e.validation).toBeNull();
    expect(e.draftHash).toBe("h2");
  });

  it("validated -> valid/invalid by status", () => {
    let r = draftReducer(emptyRegistry(), { type: "put", draftId: "d1", draft: draft("d1"), draftHash: "h1" });
    r = draftReducer(r, { type: "validated", draftId: "d1", validation: { status: "invalid" } as never, draftHash: "h1" });
    expect((r.get("d1") as DraftEntry).lifecycleState).toBe("invalid");
  });

  it("executing -> pending, then remove drops the entry", () => {
    let r = draftReducer(emptyRegistry(), { type: "put", draftId: "d1", draft: draft("d1"), draftHash: "h1" });
    r = draftReducer(r, { type: "executing", draftId: "d1" });
    expect((r.get("d1") as DraftEntry).lifecycleState).toBe("pending");
    r = draftReducer(r, { type: "remove", draftId: "d1" });
    expect(r.has("d1")).toBe(false);
  });

  it("hydrate loads summaries as draft entries", () => {
    const summaries: PipelineDraftSummary[] = [
      { draft_id: "d1", status: "draft", draft_hash: "h1", source_node_hash: "hash_a", source_op_node_id: "model#0" },
    ];
    const r = draftReducer(emptyRegistry(), { type: "hydrate", summaries });
    expect((r.get("d1") as DraftEntry).lifecycleState).toBe("draft");
    expect((r.get("d1") as DraftEntry).sourceNodeHash).toBe("hash_a");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `frontend/node_modules/.bin/vitest run frontend/src/lineage/drafts/draftRegistry.test.ts`
Expected: FAIL — cannot find module `./draftRegistry`

- [ ] **Step 3: Implement the registry**

Create `frontend/src/lineage/drafts/draftRegistry.ts`:

```ts
// v1.6.7 — DraftRegistry: single source of truth for active in-graph drafts.
// Keyed by draftId (= the persistent server key), so session-created drafts
// and reload-hydrated drafts are homogeneous. See spec §4.1.

import type {
  DraftValidationResult,
  PipelineDraftSummary,
  PipelineDraftV1,
} from "../../api";
import type { LifecycleState } from "../api/graphViewTypes";

export interface DraftEntry {
  draftId: string;
  draft: PipelineDraftV1 | null; // null until first GET (hydrate defers load)
  draftHash: string;
  validation: DraftValidationResult | null;
  lifecycleState: LifecycleState;
  // Anchor is resolved against the live forest by node_hash (see mergeDraftsIntoModel).
  sourceNodeHash: string | null;
  sourceOpNodeId: string | null;
  modelType: string | null;
}

export type DraftRegistry = ReadonlyMap<string, DraftEntry>;

export function emptyRegistry(): DraftRegistry {
  return new Map();
}

export type DraftAction =
  | { type: "put"; draftId: string; draft: PipelineDraftV1; draftHash: string }
  | { type: "patch"; draftId: string; draft: PipelineDraftV1; draftHash: string }
  | { type: "validating"; draftId: string }
  | { type: "validated"; draftId: string; validation: DraftValidationResult; draftHash: string }
  | { type: "executing"; draftId: string }
  | { type: "failed"; draftId: string }
  | { type: "remove"; draftId: string }
  | { type: "hydrate"; summaries: PipelineDraftSummary[] };

function createdFromHash(draft: PipelineDraftV1): string | null {
  return draft.created_from?.source_node_hash ?? null;
}
function createdFromOp(draft: PipelineDraftV1): string | null {
  return draft.created_from?.source_op_node_id ?? null;
}
function modelTypeOf(draft: PipelineDraftV1): string | null {
  const model = draft.graph.nodes.find((n) => n.node_type === "model");
  return (model && "model_type" in model ? (model.model_type as string) : null) ?? null;
}

export function draftReducer(state: DraftRegistry, action: DraftAction): DraftRegistry {
  const next = new Map(state);
  switch (action.type) {
    case "put":
    case "patch": {
      const prev = next.get(action.draftId);
      next.set(action.draftId, {
        draftId: action.draftId,
        draft: action.draft,
        draftHash: action.draftHash,
        validation: null,
        lifecycleState: "draft",
        sourceNodeHash: createdFromHash(action.draft) ?? prev?.sourceNodeHash ?? null,
        sourceOpNodeId: createdFromOp(action.draft) ?? prev?.sourceOpNodeId ?? null,
        modelType: modelTypeOf(action.draft) ?? prev?.modelType ?? null,
      });
      return next;
    }
    case "validating": {
      const prev = next.get(action.draftId);
      if (prev) next.set(action.draftId, { ...prev, lifecycleState: "validating" });
      return next;
    }
    case "validated": {
      const prev = next.get(action.draftId);
      if (prev) {
        next.set(action.draftId, {
          ...prev,
          validation: action.validation,
          draftHash: action.draftHash,
          lifecycleState: action.validation.status === "valid" ? "valid" : "invalid",
        });
      }
      return next;
    }
    case "executing": {
      const prev = next.get(action.draftId);
      if (prev) next.set(action.draftId, { ...prev, lifecycleState: "pending" });
      return next;
    }
    case "failed": {
      const prev = next.get(action.draftId);
      if (prev) next.set(action.draftId, { ...prev, lifecycleState: "failed" });
      return next;
    }
    case "remove": {
      next.delete(action.draftId);
      return next;
    }
    case "hydrate": {
      for (const s of action.summaries) {
        if (next.has(s.draft_id)) continue; // never clobber a live session draft
        next.set(s.draft_id, {
          draftId: s.draft_id,
          draft: null,
          draftHash: s.draft_hash,
          validation: null,
          lifecycleState: "draft",
          sourceNodeHash: s.source_node_hash ?? null,
          sourceOpNodeId: s.source_op_node_id ?? null,
          modelType: s.model_type ?? null,
        });
      }
      return next;
    }
    default:
      return next;
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `frontend/node_modules/.bin/vitest run frontend/src/lineage/drafts/draftRegistry.test.ts`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lineage/drafts/draftRegistry.ts frontend/src/lineage/drafts/draftRegistry.test.ts
git commit -m "feat(drafts): DraftRegistry state + lifecycle transitions + hydrate (v1.6.7 S2)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: `mergeDraftsIntoModel` (inject + anchor resolution)

**Files:**
- Create: `frontend/src/lineage/drafts/mergeDraftsIntoModel.ts`
- Test: `frontend/src/lineage/drafts/mergeDraftsIntoModel.test.ts`

Anchor rule (spec §4.2, verification finding ⑤): resolve `sourceNodeHash` against forest `HeadSetNode.nodeHash` (unique dedup key); fall back to `sourceOpNodeId` → `opNodeId`. No match → skip injection (source not visible).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lineage/drafts/mergeDraftsIntoModel.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { mergeDraftsIntoModel } from "./mergeDraftsIntoModel";
import { emptyRegistry, draftReducer } from "./draftRegistry";
import type { GraphViewModel } from "../api/graphViewTypes";
import type { PipelineDraftV1 } from "../../api";

const forestNode = (over: Partial<Record<string, unknown>> = {}) =>
  ({
    id: "node_a",
    nodeKey: "node_a",
    raw: {},
    stage: "model",
    kind: "model",
    title: "OLS",
    parentStageId: null,
    trust: "ok",
    decisions: [],
    opNodeId: "model#0",
    nodeHash: "hash_a",
    producingStage: null,
    casRef: null,
    runs: ["run_a"],
    ...over,
  }) as never;

const baseModel = (): GraphViewModel => ({
  schemaVersion: 1,
  runId: "run_a",
  legacy: false,
  nodes: [forestNode()],
  edges: [],
  stats: { nodeCount: 1, edgeCount: 0, leafCount: 1, hasDpCount: 0 },
});

const draft = (id: string, hash = "hash_a"): PipelineDraftV1 => ({
  draft_id: id,
  schema_version: "pipeline_draft.v1",
  created_at: "t",
  updated_at: "t",
  status: "draft",
  created_from: { source_node_hash: hash, source_op_node_id: "model#0" },
  graph: { nodes: [{ node_type: "model", node_id: "model#0", model_type: "ols", editable_schema: [] } as never], edges: [] },
  default_execution_mode: "rerun_child",
});

describe("mergeDraftsIntoModel", () => {
  it("injects a draft node + edge anchored by node_hash", () => {
    const reg = draftReducer(emptyRegistry(), { type: "put", draftId: "d1", draft: draft("d1"), draftHash: "h1" });
    const merged = mergeDraftsIntoModel(baseModel(), reg);
    const dn = merged.nodes.find((n) => n.draftId === "d1");
    expect(dn).toBeTruthy();
    expect(dn!.isDraft).toBe(true);
    expect(dn!.nodeKey).toBe("draft:d1");
    expect(dn!.lifecycleState).toBe("draft");
    expect(merged.edges.some((e) => e.source === "node_a" && e.target === "draft:d1")).toBe(true);
  });

  it("fans out multiple drafts from the same source", () => {
    let reg = draftReducer(emptyRegistry(), { type: "put", draftId: "d1", draft: draft("d1"), draftHash: "h1" });
    reg = draftReducer(reg, { type: "put", draftId: "d2", draft: draft("d2"), draftHash: "h2" });
    const merged = mergeDraftsIntoModel(baseModel(), reg);
    expect(merged.nodes.filter((n) => n.isDraft)).toHaveLength(2);
    expect(merged.edges.filter((e) => e.source === "node_a")).toHaveLength(2);
  });

  it("skips a draft whose source is not in the forest (degrade)", () => {
    const reg = draftReducer(emptyRegistry(), { type: "put", draftId: "d1", draft: draft("d1", "hash_missing"), draftHash: "h1" });
    const merged = mergeDraftsIntoModel(baseModel(), reg);
    expect(merged.nodes.some((n) => n.isDraft)).toBe(false);
  });

  it("is a no-op for an empty registry (same node count)", () => {
    const merged = mergeDraftsIntoModel(baseModel(), emptyRegistry());
    expect(merged.nodes).toHaveLength(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `frontend/node_modules/.bin/vitest run frontend/src/lineage/drafts/mergeDraftsIntoModel.test.ts`
Expected: FAIL — cannot find module `./mergeDraftsIntoModel`

- [ ] **Step 3: Implement the merge**

Create `frontend/src/lineage/drafts/mergeDraftsIntoModel.ts`:

```ts
// v1.6.7 — inject active drafts as pending child nodes of their source model
// node. Anchor by node_hash (unique) then opNodeId; skip if source not visible.
// Runs as the final producer of ForestWorkbench's `model` so validNodeKeys
// (derived from model.nodes) includes draft keys — see spec §4.2 ordering.

import type { GraphViewModel, GraphViewNode, HeadSetNode } from "../api/graphViewTypes";
import type { DraftEntry, DraftRegistry } from "./draftRegistry";

function resolveAnchor(
  model: GraphViewModel,
  entry: DraftEntry,
): GraphViewNode | null {
  const nodes = model.nodes as HeadSetNode[];
  if (entry.sourceNodeHash) {
    const byHash = nodes.find((n) => n.nodeHash === entry.sourceNodeHash);
    if (byHash) return byHash;
  }
  if (entry.sourceOpNodeId) {
    const byOp = nodes.find((n) => n.opNodeId === entry.sourceOpNodeId);
    if (byOp) return byOp;
  }
  return null;
}

function draftNode(entry: DraftEntry, anchor: GraphViewNode): GraphViewNode {
  const key = `draft:${entry.draftId}`;
  return {
    id: key,
    nodeKey: key,
    raw: entry.draft ?? { draft_id: entry.draftId },
    stage: anchor.stage,
    kind: "model",
    title: entry.modelType ? `draft · ${entry.modelType}` : "draft",
    parentStageId: anchor.parentStageId,
    trust: "ok",
    decisions: [],
    isDraft: true,
    draftId: entry.draftId,
    lifecycleState: entry.lifecycleState,
  };
}

export function mergeDraftsIntoModel(
  model: GraphViewModel,
  registry: DraftRegistry,
): GraphViewModel {
  if (registry.size === 0) return model;
  const addNodes: GraphViewNode[] = [];
  const addEdges: GraphViewModel["edges"] = [];
  for (const entry of registry.values()) {
    const anchor = resolveAnchor(model, entry);
    if (!anchor) continue; // source not visible → degrade
    const node = draftNode(entry, anchor);
    addNodes.push(node);
    addEdges.push({ id: `${anchor.id}->${node.id}`, source: anchor.id, target: node.id });
  }
  if (addNodes.length === 0) return model;
  const nodes = [...model.nodes, ...addNodes];
  const edges = [...model.edges, ...addEdges];
  return {
    ...model,
    nodes,
    edges,
    stats: { ...model.stats, nodeCount: nodes.length, edgeCount: edges.length },
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `frontend/node_modules/.bin/vitest run frontend/src/lineage/drafts/mergeDraftsIntoModel.test.ts`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lineage/drafts/mergeDraftsIntoModel.ts frontend/src/lineage/drafts/mergeDraftsIntoModel.test.ts
git commit -m "feat(drafts): mergeDraftsIntoModel injects draft nodes anchored by node_hash (v1.6.7 S2)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: `GraphNode` lifecycle visual states

**Files:**
- Modify: `frontend/src/lineage/graph/GraphNode.tsx`
- Test: `frontend/src/lineage/graph/GraphNode.test.tsx`

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/lineage/graph/GraphNode.test.tsx` (reuse the file's existing render helper; the snippet assumes a `renderNode(nodeOverrides)` helper — if the existing test uses a different harness, adapt the render call to match, keeping the assertions):

```tsx
it("tags a draft node with its lifecycle state for styling", () => {
  renderNode({ isDraft: true, draftId: "d1", lifecycleState: "draft", title: "draft · ols" });
  const el = screen.getByTestId("graph-node-lifecycle");
  expect(el).toHaveAttribute("data-lifecycle", "draft");
});

it("marks a pending draft node", () => {
  renderNode({ isDraft: true, draftId: "d1", lifecycleState: "pending", title: "draft · ols" });
  expect(screen.getByTestId("graph-node-lifecycle")).toHaveAttribute("data-lifecycle", "pending");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `frontend/node_modules/.bin/vitest run frontend/src/lineage/graph/GraphNode.test.tsx -t lifecycle`
Expected: FAIL — `data-testid="graph-node-lifecycle"` not found

- [ ] **Step 3: Implement the visual state**

In `frontend/src/lineage/graph/GraphNode.tsx`, read `lifecycleState` off the node and apply a `data-lifecycle` attribute + border/opacity styling on the node's root element. Add near the top of the node body render (adapt to the file's existing node root element — add the attribute and style to it):

```tsx
// v1.6.7 — draft lifecycle visual language (see spec §3).
const LIFECYCLE_STYLE: Record<string, { border: string; opacity: number; glow?: string }> = {
  draft: { border: "2px dashed var(--label-tertiary)", opacity: 0.75 },
  validating: { border: "2px dashed #c98a3a", opacity: 0.9 },
  valid: { border: "2px solid #3a9ac9", opacity: 1 },
  invalid: { border: "2px solid #b03a3a", opacity: 1 },
  pending: { border: "2px solid #c9a03a", opacity: 1, glow: "0 0 14px rgba(201,160,58,.55)" },
  executed: { border: "2px solid #1f6f43", opacity: 1 },
  failed: { border: "2px solid #b03a3a", opacity: 1 },
};
```

Then on the node root element add:

```tsx
data-testid={node.isDraft ? "graph-node-lifecycle" : undefined}
data-lifecycle={node.lifecycleState}
style={{
  ...existingStyle,
  ...(node.lifecycleState
    ? {
        border: LIFECYCLE_STYLE[node.lifecycleState]?.border,
        opacity: LIFECYCLE_STYLE[node.lifecycleState]?.opacity,
        boxShadow: LIFECYCLE_STYLE[node.lifecycleState]?.glow ?? existingStyle.boxShadow,
      }
    : {}),
}}
```

> Keep it additive: real forest nodes have no `lifecycleState`, so the spread is empty and their appearance is unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `frontend/node_modules/.bin/vitest run frontend/src/lineage/graph/GraphNode.test.tsx -t lifecycle`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lineage/graph/GraphNode.tsx frontend/src/lineage/graph/GraphNode.test.tsx
git commit -m "feat(drafts): GraphNode renders draft lifecycle visual states (v1.6.7 S2)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 8: `NodeActionMenu` — "Fork draft here" (no navigation)

**Files:**
- Modify: `frontend/src/lineage/graph/NodeActionMenu.tsx`
- Test: `frontend/src/lineage/graph/NodeActionMenu.test.tsx`

The current `onOpenDraftGraph` calls `createPipelineDraftFromNode` then `navigate(...)`. v1.6.7 replaces the navigation with a registry `put` via a callback prop. The callback is supplied by `ForestWorkbench` (Task 9). Keep the deep-link route intact — only this in-graph entry changes.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/lineage/graph/NodeActionMenu.test.tsx`:

```tsx
it("Fork draft here creates a draft and does NOT navigate", async () => {
  const onForkDraft = vi.fn();
  // render NodeActionMenu with a resolved context that has editable_schema and
  // an onForkDraft prop; mock createPipelineDraftFromNode to resolve a draft.
  // (Reuse the file's existing mount helper; pass onForkDraft.)
  renderMenu({ onForkDraft });
  await userEvent.click(screen.getByRole("button", { name: /actions/i }));
  await userEvent.click(screen.getByTestId("drawer-menu-item-fork-draft-here"));
  expect(onForkDraft).toHaveBeenCalledTimes(1);
  expect(mockNavigate).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `frontend/node_modules/.bin/vitest run frontend/src/lineage/graph/NodeActionMenu.test.tsx -t "Fork draft"`
Expected: FAIL — menu item testid not found

- [ ] **Step 3: Implement**

In `frontend/src/lineage/graph/NodeActionMenu.tsx`:

1. Add a single, clean prop to `NodeActionMenuProps` (the created draft already carries `created_from`, which is everything the registry needs — matches Task 9's `handleForkDraft(created: PipelineDraftResponse)`):

```tsx
import type { PipelineDraftResponse } from "../../api";
// ...
onForkDraft?: (created: PipelineDraftResponse) => void;
```

2. Replace the rendered menu item:

```tsx
{canOpenDraft && (
  <MenuItem
    label="Fork draft here"
    onClick={closeAfter(onForkDraftHere)}
    testId="drawer-menu-item-fork-draft-here"
  />
)}
```

3. Replace `onOpenDraftGraph` with `onForkDraftHere` (no `navigate`, no `useNavigate`):

```tsx
async function onForkDraftHere() {
  if (!canOpenDraft || !resolvedContext?.ok) return;
  const context = resolvedContext.context;
  const result = await createPipelineDraftFromNode(effectiveProjectRoot, {
    source_run_id: context.operation_target.owner_run_id,
    source_model_node_id: context.operation_target.op_node_id,
    source_op_node_id: context.operation_target.op_node_id,
    source_node_hash: context.operation_target.node_hash,
    source_forest_node_key: context.selection.forest_node_key,
    source_context_fingerprint: context.context_fingerprint,
  });
  onForkDraft?.(result);
}
```

4. Gate the item on non-draft nodes: you can only fork from executed nodes (backend enforces `indexed_hash == source_node_hash`). Add `&& !node.isDraft` to the existing `canOpenDraft` expression.

- [ ] **Step 4: Run test to verify it passes**

Run: `frontend/node_modules/.bin/vitest run frontend/src/lineage/graph/NodeActionMenu.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lineage/graph/NodeActionMenu.tsx frontend/src/lineage/graph/NodeActionMenu.test.tsx
git commit -m "feat(drafts): NodeActionMenu 'Fork draft here' writes registry, no navigation (v1.6.7 S2)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 9: `DraftEditorSection` + wire registry/merge/pending into `ForestWorkbench`

**Files:**
- Create: `frontend/src/lineage/detail/sections/DraftEditorSection.tsx`
- Modify: `frontend/src/workbench/WorkbenchRouteContainer.tsx`
- Test: `frontend/src/lineage/detail/sections/DraftEditorSection.test.tsx`

`DraftEditorSection` extracts `ModelNodeInspector`'s editing logic (renders `editable_schema` via `renderControl`, `onSave → patchPipelineDraftParams`) and adds Validate/Execute buttons wired to the registry. Mounted by the drawer only when the selected node `isDraft`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lineage/detail/sections/DraftEditorSection.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DraftEditorSection } from "./DraftEditorSection";

const entry = {
  draftId: "d1",
  draft: {
    draft_id: "d1",
    schema_version: "pipeline_draft.v1",
    created_at: "t", updated_at: "t", status: "draft",
    created_from: { source_node_hash: "hash_a", source_op_node_id: "model#0" },
    graph: { nodes: [{ node_type: "model", node_id: "model#0", model_type: "ols", editable_schema: [] }], edges: [] },
    default_execution_mode: "rerun_child",
  },
  draftHash: "h1",
  validation: null,
  lifecycleState: "draft",
  sourceNodeHash: "hash_a", sourceOpNodeId: "model#0", modelType: "ols",
} as never;

describe("DraftEditorSection", () => {
  it("calls onValidate when Validate is clicked", async () => {
    const onValidate = vi.fn();
    render(<DraftEditorSection entry={entry} onPatch={vi.fn()} onValidate={onValidate} onExecute={vi.fn()} onDiscard={vi.fn()} busy={false} />);
    await userEvent.click(screen.getByRole("button", { name: /validate/i }));
    expect(onValidate).toHaveBeenCalledWith("d1");
  });

  it("disables Execute until valid", () => {
    render(<DraftEditorSection entry={entry} onPatch={vi.fn()} onValidate={vi.fn()} onExecute={vi.fn()} onDiscard={vi.fn()} busy={false} />);
    expect(screen.getByRole("button", { name: /execute/i })).toBeDisabled();
  });

  it("enables Execute when lifecycleState is valid", () => {
    render(<DraftEditorSection entry={{ ...entry, lifecycleState: "valid" }} onPatch={vi.fn()} onValidate={vi.fn()} onExecute={vi.fn()} onDiscard={vi.fn()} busy={false} />);
    expect(screen.getByRole("button", { name: /execute/i })).toBeEnabled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `frontend/node_modules/.bin/vitest run frontend/src/lineage/detail/sections/DraftEditorSection.test.tsx`
Expected: FAIL — cannot find module `./DraftEditorSection`

- [ ] **Step 3: Implement `DraftEditorSection`**

Create `frontend/src/lineage/detail/sections/DraftEditorSection.tsx`:

```tsx
// v1.6.7 — draft editor mounted in the detail drawer for draft nodes.
// Reuses controlFactory's renderControl (like ModelNodeInspector) but wires
// onSave -> patch and adds Validate/Execute against the DraftRegistry.
import { useMemo, useState } from "react";
import type { EditableControl } from "../../api/graphViewTypes";
import { renderControl } from "../../controls/controlFactory";
import type { DraftEntry } from "../../drafts/draftRegistry";
import type { PipelineDraftPatchRequest } from "../../../api";

export interface DraftEditorSectionProps {
  entry: DraftEntry;
  onPatch: (draftId: string, body: PipelineDraftPatchRequest) => void;
  onValidate: (draftId: string) => void;
  onExecute: (draftId: string) => void;
  onDiscard: (draftId: string) => void;
  busy: boolean;
}

export function DraftEditorSection({
  entry, onPatch, onValidate, onExecute, onDiscard, busy,
}: DraftEditorSectionProps) {
  const model = entry.draft?.graph.nodes.find((n) => n.node_type === "model");
  const controls = (model?.editable_schema ?? []) as EditableControl[];
  const [values, setValues] = useState<Record<string, unknown>>(() =>
    Object.fromEntries(controls.map((c) => [c.key, c.value])),
  );
  const dirty = useMemo(
    () => controls.some((c) => values[c.key] !== c.value),
    [controls, values],
  );
  const canExecute = entry.lifecycleState === "valid" && !busy;

  return (
    <section className="draft-editor" aria-label="Draft editor">
      {controls.map((control) =>
        renderControl(control, values[control.key], (v) =>
          setValues((prev) => ({ ...prev, [control.key]: v })),
        ),
      )}
      {entry.validation && entry.validation.checks.length > 0 && (
        <ul className="draft-editor__checks" aria-label="Validation checks">
          {entry.validation.checks.map((c) => (
            <li key={`${c.code}:${c.node_id ?? ""}`}>{c.code}: {c.message}</li>
          ))}
        </ul>
      )}
      <div className="draft-editor__actions">
        <button type="button" disabled={busy || !model} onClick={() =>
          model && onPatch(entry.draftId, {
            model_node_id: model.node_id,
            base_draft_hash: entry.draftHash,
            params: values,
          })
        }>Save</button>
        <button type="button" disabled={busy || dirty} onClick={() => onValidate(entry.draftId)}>
          Validate
        </button>
        <button type="button" disabled={!canExecute} onClick={() => onExecute(entry.draftId)}>
          Execute
        </button>
        <button type="button" disabled={busy} onClick={() => onDiscard(entry.draftId)}>
          Discard
        </button>
      </div>
    </section>
  );
}
```

> `renderControl`'s exact signature: confirm against `controls/controlFactory.tsx` and `ModelNodeInspector.tsx` (which already calls it). If it takes `(control, valueWithValue)` objects rather than `(control, value, onChange)`, mirror `ModelNodeInspector`'s call shape exactly — that file is the source of truth for the control wiring.

- [ ] **Step 4: Wire into `ForestWorkbench`**

In `frontend/src/workbench/WorkbenchRouteContainer.tsx` (`ForestWorkbench`):

1. Add registry state:
```tsx
const [registry, dispatchDraft] = useReducer(draftReducer, undefined, emptyRegistry);
```
2. Merge into the memoized `model` (AFTER `forestToGraphViewModel`, BEFORE `validNodeKeys`):
```tsx
const model = useMemo(() => {
  const base = forest ? forestToGraphViewModel(forest, runId) : null;
  return base ? mergeDraftsIntoModel(base, registry) : null;
}, [forest, runId, registry]);
```
3. Fork handler (passed down to NodeActionMenu via existing provider chain / drawer props):
```tsx
const handleForkDraft = (created: PipelineDraftResponse) => {
  dispatchDraft({ type: "put", draftId: created.draft.draft_id, draft: created.draft, draftHash: created.draft_hash });
};
```
4. Validate handler:
```tsx
const handleValidateDraft = async (draftId: string) => {
  dispatchDraft({ type: "validating", draftId });
  const v = await validatePipelineDraft(projectRoot, draftId, "rerun_child");
  dispatchDraft({ type: "validated", draftId, validation: v, draftHash: v.validated_draft_hash ?? "" });
};
```
5. Execute handler — seed pending from the execute response (mirrors `handleRerun`, NO URL params):
```tsx
const handleExecuteDraft = async (draftId: string) => {
  const entry = registry.get(draftId);
  if (!entry) return;
  dispatchDraft({ type: "executing", draftId });
  const result = await executePipelineDraft(projectRoot, draftId, {
    validated_draft_hash: entry.validation?.validated_draft_hash ?? entry.draftHash,
    execution_mode: "rerun_child",
  });
  setActiveRunId(result.focus.run_id);
  setPendingFocusTarget({
    runId: result.focus.run_id,
    focus: {
      forest_node_key: null,
      op_node_id: result.focus.poll?.rerun_from_op_node_id ?? result.produced_lineage.rerun_from_op_node_id,
      node_hash: null,
    },
    attempts: 0,
  });
  await deletePipelineDraft(projectRoot, draftId); // real node now lives in the forest
  dispatchDraft({ type: "remove", draftId });
  void refetch();
};
```
6. Patch + discard handlers:
```tsx
const handlePatchDraft = async (draftId: string, body: PipelineDraftPatchRequest) => {
  const res = await patchPipelineDraftParams(projectRoot, draftId, body);
  dispatchDraft({ type: "patch", draftId, draft: res.draft, draftHash: res.draft_hash });
};
const handleDiscardDraft = async (draftId: string) => {
  await deletePipelineDraft(projectRoot, draftId);
  dispatchDraft({ type: "remove", draftId });
};
```
7. Provide these handlers + the selected draft entry to the drawer so it can render `DraftEditorSection` for `isDraft` nodes, and to `NodeActionMenu` for `handleForkDraft`. Thread them through the existing `RerunProvider` / drawer prop chain (the drawer already receives the selected node; branch on `node.isDraft` to render `DraftEditorSection` instead of the standard sections).

Add imports at the top of the file:
```tsx
import { useReducer } from "react";
import { draftReducer, emptyRegistry } from "../lineage/drafts/draftRegistry";
import { mergeDraftsIntoModel } from "../lineage/drafts/mergeDraftsIntoModel";
import {
  validatePipelineDraft, executePipelineDraft, patchPipelineDraftParams,
  deletePipelineDraft, type PipelineDraftResponse, type PipelineDraftPatchRequest,
} from "../api";
```

- [ ] **Step 5: Run tests + typecheck**

Run: `frontend/node_modules/.bin/vitest run frontend/src/lineage/detail/sections/DraftEditorSection.test.tsx`
Expected: PASS (3 tests)

Run: `cd frontend && node_modules/.bin/tsc --noEmit && cd ..`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lineage/detail/sections/DraftEditorSection.tsx frontend/src/lineage/detail/sections/DraftEditorSection.test.tsx frontend/src/workbench/WorkbenchRouteContainer.tsx
git commit -m "feat(drafts): in-graph draft editor + registry/merge/pending wiring (v1.6.7 S2)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Slice 3 — Frontend: persistence (hydrate on reload)

### Task 10: hydrate drafts on mount

**Files:**
- Modify: `frontend/src/workbench/WorkbenchRouteContainer.tsx`
- Test: `frontend/src/workbench/WorkbenchRouteContainer.test.tsx` (or a focused hook test)

- [ ] **Step 1: Write the failing test**

Add a test that mounts `ForestWorkbench` with `listPipelineDrafts` mocked to return one summary whose `source_node_hash` matches a forest node, and asserts a draft node (`draft:d1`) appears on the canvas after mount. Append to `frontend/src/workbench/WorkbenchRouteContainer.test.tsx`:

```tsx
it("hydrates persisted drafts onto the forest on mount", async () => {
  vi.mocked(api.listPipelineDrafts).mockResolvedValue([
    { draft_id: "d1", status: "draft", draft_hash: "h1", source_node_hash: "hash_a", source_op_node_id: "model#0" },
  ]);
  renderForestWorkbench(); // existing helper that provides a forest with a node whose nodeHash === "hash_a"
  expect(await screen.findByTestId("graph-node-lifecycle")).toHaveAttribute("data-lifecycle", "draft");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `frontend/node_modules/.bin/vitest run frontend/src/workbench/WorkbenchRouteContainer.test.tsx -t hydrates`
Expected: FAIL — no draft node rendered

- [ ] **Step 3: Implement hydrate effect**

In `ForestWorkbench`, add an effect that runs once per `projectRoot` mount:

```tsx
useEffect(() => {
  let cancelled = false;
  listPipelineDrafts(projectRoot)
    .then((summaries) => {
      if (cancelled) return;
      const unexecuted = summaries.filter((s) => s.status !== "executed");
      if (unexecuted.length) dispatchDraft({ type: "hydrate", summaries: unexecuted });
    })
    .catch(() => {/* drafts are best-effort; never block the forest */});
  return () => { cancelled = true; };
}, [projectRoot]);
```

Add `listPipelineDrafts` to the api import in this file.

- [ ] **Step 4: Run test to verify it passes**

Run: `frontend/node_modules/.bin/vitest run frontend/src/workbench/WorkbenchRouteContainer.test.tsx -t hydrates`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/workbench/WorkbenchRouteContainer.tsx frontend/src/workbench/WorkbenchRouteContainer.test.tsx
git commit -m "feat(drafts): hydrate persisted drafts onto forest on mount (v1.6.7 S3)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 11: hydrated draft loads full draft on selection

**Files:**
- Modify: `frontend/src/workbench/WorkbenchRouteContainer.tsx`
- Test: `frontend/src/workbench/WorkbenchRouteContainer.test.tsx`

Hydrated entries have `draft: null` (summary only). When a hydrated draft node is selected, lazily `getPipelineDraft` and `put` it so `DraftEditorSection` has `editable_schema` to render.

- [ ] **Step 1: Write the failing test**

```tsx
it("loads the full draft when a hydrated draft node is selected", async () => {
  vi.mocked(api.listPipelineDrafts).mockResolvedValue([
    { draft_id: "d1", status: "draft", draft_hash: "h1", source_node_hash: "hash_a", source_op_node_id: "model#0" },
  ]);
  vi.mocked(api.getPipelineDraft).mockResolvedValue({ draft: fullDraft("d1"), draft_hash: "h1" });
  renderForestWorkbench();
  await userEvent.click(await screen.findByTestId("graph-node-lifecycle"));
  expect(api.getPipelineDraft).toHaveBeenCalledWith(expect.any(String), "d1");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `frontend/node_modules/.bin/vitest run frontend/src/workbench/WorkbenchRouteContainer.test.tsx -t "loads the full draft"`
Expected: FAIL — `getPipelineDraft` not called

- [ ] **Step 3: Implement lazy load on select**

Add an effect keyed on the selected node: when the selected node `isDraft` and its registry entry has `draft === null`, fetch and `put`:

```tsx
useEffect(() => {
  const key = selectedDraftId; // derive from selected node's draftId
  if (!key) return;
  const entry = registry.get(key);
  if (!entry || entry.draft !== null) return;
  getPipelineDraft(projectRoot, key)
    .then((res) => dispatchDraft({ type: "put", draftId: key, draft: res.draft, draftHash: res.draft_hash }))
    .catch(() => {/* ignore; editor shows empty until retried */});
}, [selectedDraftId, projectRoot, registry]);
```

Derive `selectedDraftId` from the workbench selection (the selected node's `draftId` when `isDraft`). Add `getPipelineDraft` to the api import.

- [ ] **Step 4: Run test to verify it passes**

Run: `frontend/node_modules/.bin/vitest run frontend/src/workbench/WorkbenchRouteContainer.test.tsx -t "loads the full draft"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/workbench/WorkbenchRouteContainer.tsx frontend/src/workbench/WorkbenchRouteContainer.test.tsx
git commit -m "feat(drafts): lazy-load full draft when a hydrated draft node is selected (v1.6.7 S3)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Slice 4 — Drawer header toolbar redesign + Actions fix

### Task 12: `DetailHeader` persistent toolbar row + id truncation

**Files:**
- Modify: `frontend/src/lineage/header/DetailHeader.tsx`
- Test: `frontend/src/lineage/header/DetailHeader.test.tsx` (create if absent)

Root cause (spec §4.4): the `.dp-kind` non-wrapping flex row packs long mono ids + warnings then pushes the action cluster off the right edge via `margin-left:auto`. Fix: dedicated always-visible toolbar row; id text truncates.

- [ ] **Step 1: Write the failing test**

Create/append `frontend/src/lineage/header/DetailHeader.test.tsx`:

```tsx
it("keeps the action toolbar visible with a very long run id (truncates the id)", () => {
  renderHeader({
    node: makeNode({ nodeKey: "n".repeat(120), kind: "model" }),
  });
  const meta = screen.getByTestId("detail-header-meta");
  // truncation styles applied so the id cannot push actions off-screen
  expect(meta).toHaveStyle({ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" });
  // the actions toolbar and close are in a separate, always-rendered row
  expect(screen.getByTestId("detail-header-toolbar")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /close/i })).toBeVisible();
});

it("shows Fork draft affordance only for non-draft nodes", () => {
  renderHeader({ node: makeNode({ isDraft: true, lifecycleState: "draft" }) });
  expect(screen.queryByRole("button", { name: /fork draft/i })).toBeNull();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `frontend/node_modules/.bin/vitest run frontend/src/lineage/header/DetailHeader.test.tsx`
Expected: FAIL — `detail-header-toolbar` testid / truncation not present

- [ ] **Step 3: Restructure the header**

In `frontend/src/lineage/header/DetailHeader.tsx`, split the single `.dp-kind` row into TWO rows:

1. **Toolbar row (always rendered, own flexline)** — houses the state chip (when `node.isDraft`), context buttons, `NodeActionMenu` (now `⋯`), and close `×`. This row does NOT contain the long id, so nothing can push it off-screen:

```tsx
<div
  data-testid="detail-header-toolbar"
  style={{ display: "flex", alignItems: "center", gap: 6, minHeight: 28 }}
>
  {node.isDraft && node.lifecycleState && (
    <span data-testid="detail-header-state-chip" data-state={node.lifecycleState}>
      {node.lifecycleState}
    </span>
  )}
  <span style={{ flex: 1 }} />
  {/* Fork draft: only for executed (non-draft) nodes — backend forbids draft-of-draft */}
  {!node.isDraft && onForkDraft && (
    <button type="button" onClick={onForkDraft}>Fork draft</button>
  )}
  {onShowJson && <NodeActionMenu node={node} model={model} onShowJson={onShowJson} />}
  <button type="button" onClick={onClose} aria-label="Close">×</button>
</div>
```

2. **Meta row (truncating)** — the kind + mono id + warnings, now allowed to ellipsize:

```tsx
<div
  data-testid="detail-header-meta"
  className="dp-kind"
  style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "100%" }}
>
  <span>{node.kind}</span>
  {/* ...existing displayRunId · nodeKey · ownerResolution · warnings spans... */}
</div>
```

Remove the old `margin-left:auto` action cluster from the meta row (it moved to the toolbar row). Keep `ResolverFailureState` rendering in the meta row as today. `onForkDraft` is a new optional prop wired from the drawer to `handleForkDraft` (Task 9); Validate/Execute for draft nodes live in `DraftEditorSection` (drawer body), so the toolbar only needs the state chip + Fork + `⋯` + `×`.

- [ ] **Step 4: Run test to verify it passes**

Run: `frontend/node_modules/.bin/vitest run frontend/src/lineage/header/DetailHeader.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lineage/header/DetailHeader.tsx frontend/src/lineage/header/DetailHeader.test.tsx
git commit -m "fix(drawer): persistent header toolbar row + id truncation (Actions reachable) (v1.6.7 S4)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Slice 5 — Retire Pipeline tab entry + full gate

### Task 13: retire Pipeline tab entry (view code kept)

**Files:**
- Modify: the view switcher that registers the Pipeline tab (search `view-pipeline` / `PipelineView` registration).
- Test: the switcher's test.

- [ ] **Step 1: Find the registration**

Run: `grep -rn "PipelineView\|view-pipeline\|\"pipeline\"" frontend/src --include=*.tsx --include=*.ts | grep -v ".test."`
Identify where the Pipeline tab is added to the view switcher.

- [ ] **Step 2: Write the failing test**

In the switcher's test, assert the Pipeline tab is no longer offered:

```tsx
it("does not offer the Pipeline tab (retired in v1.6.7)", () => {
  renderSwitcher();
  expect(screen.queryByRole("tab", { name: /pipeline/i })).toBeNull();
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `frontend/node_modules/.bin/vitest run <switcher test path>`
Expected: FAIL — Pipeline tab still present

- [ ] **Step 4: Remove the entry**

Remove the Pipeline tab from the switcher's tab list (leave `PipelineView.tsx` and the route/component intact — only the tab entry is retired).

- [ ] **Step 5: Run test to verify it passes**

Run: `frontend/node_modules/.bin/vitest run <switcher test path>`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add <switcher file> <switcher test>
git commit -m "chore(workbench): retire Pipeline tab entry; DraftGraphRoute kept as deep-link fallback (v1.6.7 S5)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 14: full gate + golden 0-drift verification

**Files:** none (verification only)

- [ ] **Step 1: Run the gate**

Run: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh`
Expected: all green — BE tests pass, FE tests pass, `tsc` 0 errors, golden 0-drift.

- [ ] **Step 2: Verify golden 0-drift explicitly**

Run: `git status --porcelain tests/golden backend/tests/golden 2>/dev/null; git diff --stat`
Expected: NO changes under any `golden/` dir. This version adds only list/delete endpoints (no artifact/graph production), so any golden drift means an accidental change — investigate before proceeding.

- [ ] **Step 3: Manual smoke via preview (real 8010 backend)**

Per handoff dev-env note: verify backend changes via the running 8010 backend, not a throwaway script. Start the preview, then:
- Fork a draft from an executed model node → a dashed draft node appears (no route change).
- Edit a param → Save → Validate → node turns valid → Execute → node goes pending → real child appears; draft node removed.
- Reload the page → an unexecuted draft is still on the graph.
- Discard a draft → it disappears and its json is deleted.

- [ ] **Step 4: Commit any smoke-driven fixes, then stop for review**

Do not push. Report gate results + smoke results for review before shipping/tagging.

---

## Self-review notes (for the implementer)

- **`renderControl` shape:** Task 9 assumes `renderControl(control, value, onChange)`. The authoritative call site is `pipelineDrafts/ModelNodeInspector.tsx` — match it exactly; if it maps controls to `{...control, value}` objects, mirror that.
- **Drawer branch point:** the drawer must render `DraftEditorSection` when `selectedNode.isDraft`, else the existing section registry. Find the drawer body render in `DetailDrawer.tsx` and branch there.
- **Prop threading:** `handleForkDraft` / `handleValidateDraft` / `handleExecuteDraft` / `handlePatchDraft` / `handleDiscardDraft` originate in `ForestWorkbench`. Thread via the existing provider used for rerun (`RerunProvider`) or a sibling `DraftActionsProvider` context to avoid deep prop drilling — prefer a small new context in `frontend/src/lineage/drafts/` mirroring `RerunContext`.
- **Selection validity:** confirm draft node keys (`draft:{id}`) pass `WorkbenchStateProvider`'s `validNodeKeys` — they will, because `validNodeKeys` derives from the merged `model.nodes` (Task 9 step 4.2 ordering).
