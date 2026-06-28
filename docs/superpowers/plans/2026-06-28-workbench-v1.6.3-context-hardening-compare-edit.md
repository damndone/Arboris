# Workbench v1.6.3 Context Hardening + Compare/Edit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the rerun child-centered loop: explicit-source compare, summary diff, single-node manual patch preview, context-validated patch rerun, focus new child, and compare again.

**Architecture:** Extend the existing v1.6.2 `NodeOperationContextV1` contract with rerun provenance and debug trace, then add a source-bound compare layer that only composes validated contexts. Manual patching stays narrow: schema-declared single-node value replacement, validated on the backend before context-driven rerun creates a new child. Frontend UI remains detail-drawer based: compare section cards plus an operation preview/confirm flow.

**Tech Stack:** FastAPI + Pydantic + pytest backend; React 18 + TypeScript + Vitest frontend; existing lineage forest contracts in `backend/workbench/lineage/*`, `frontend/src/lineage/api/*`, and `frontend/src/workbench/*`.

**Spec:** `docs/superpowers/specs/2026-06-28-workbench-v1.6.3-context-hardening-compare-edit-design.md`

---

## Global Rules

- Work in an isolated worktree, recommended path: `.worktrees/workbench-v1.6.3`.
- Do not touch existing untracked scratch paths in the main checkout.
- Do not implement parent compare, active-head compare recommendation, arbitrary node compare, AI patch, PipelineDraft, graph editor, full artifact diff, or dataset diff.
- `Compare with source` is only available from explicit `rerun_from` provenance.
- Source must never be inferred from parent, active head, timestamps, node hash similarity, run order, or `runs[0]`.
- Every write operation must pass backend validation. Frontend context is submitted for validation, not trusted.
- Each task ends with focused tests and a commit.
- Full release requires `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh`.

## File Map

Create:

- `frontend/src/lineage/api/rerunProvenance.ts` — frontend types and helpers for node/run `rerun_from`, provenance consistency, and compare gate evaluation.
- `frontend/src/lineage/api/rerunProvenance.test.ts` — provenance gate tests, including no `runs[0]` fallback.
- `frontend/src/lineage/api/compareWithSource.ts` — source-bound summary diff builder over two `NodeOperationContextV1` objects.
- `frontend/src/lineage/api/compareWithSource.test.ts` — summary diff, empty section, truncation, and fingerprint gate tests.
- `frontend/src/lineage/detail/sections/CompareWithSourceSection.tsx` — section-card compare UI.
- `frontend/src/lineage/detail/sections/CompareWithSourceSection.test.tsx` — UI gate and rendering tests.
- `frontend/src/lineage/detail/sections/manualRerunPatch.ts` — patch model, normalized comparison, frontend patch construction.
- `frontend/src/lineage/detail/sections/manualRerunPatch.test.ts` — patch normalization and no-op/duplicate tests.
- `backend/workbench/lineage/rerun_provenance.py` — run-level/node-level `rerun_from` persistence helpers and produced lineage response helpers.
- `backend/workbench/lineage/manual_patch_validation.py` — Pydantic models, normalized comparison, idempotency checks, patch validator.
- `tests/test_manual_patch_validation.py` — backend validator tests.

Modify:

- `backend/workbench/api.py` — accept manual patch payloads, persist rerun provenance, return produced node lineage, and route validation errors.
- `backend/workbench/lineage/headset.py` — expose node-level `rerun_from` and run-level fallback metadata in headset nodes/heads.
- `backend/workbench/lineage/node_index.py` — store optional node-level `rerun_from` in `node_index.json`.
- `backend/workbench/lineage/node_write_validation.py` — add resolver trace/fingerprint logging helpers and reuse validation in compare/patch gates.
- `tests/test_rerun_endpoint.py` — context rerun provenance, idempotency, produced lineage, focus-null regression tests.
- `tests/test_graph_headset.py` — headset exposes rerun provenance and no `runs[0]` regressions.
- `frontend/src/api.ts` and `frontend/src/api.test.ts` — add manual patch request/response types and produced lineage response shape.
- `frontend/src/lineage/api/graphViewTypes.ts` — add optional `rerunFrom`, `runRerunFrom`, and `editableSchemaVersion` to `HeadSetNode`.
- `frontend/src/lineage/api/nodeOperationContext.ts` and `.test.ts` — include rerun provenance, resolver trace, and compare capability gating.
- `frontend/src/workbench/forestModel.ts` — no mapping should be needed if `graphAdapter` carries headset node fields through; verify this file remains a pure forest-to-graph projection.
- `frontend/src/workbench/registry/sectionRegistry.ts` — register Compare section near Operation section.
- `frontend/src/lineage/detail/sections/OperationSection.tsx` and `.test.tsx` — replace direct rerun submit with patch preview and `Rerun source with changes`.
- `frontend/src/lineage/detail/RerunContext.tsx` and `.test.tsx` — submit `ManualRerunPatch` and route produced lineage.
- `frontend/src/workbench/WorkbenchRouteContainer.tsx` and `.test.tsx` — reflect backend-updated active head, support produced lineage pending/indexed focus, and telemetry hooks.
- `docs/dev-browser-smoke.md` or a new focused doc under `docs/` — add v1.6.3 browser regression seed instructions.

## Task 0: Worktree and Baseline

**Files:**
- Read: `docs/superpowers/specs/2026-06-28-workbench-v1.6.3-context-hardening-compare-edit-design.md`
- No source changes

- [ ] **Step 1: Create implementation worktree**

Run from `/Users/jiayuanren/项目规划`:

```bash
git worktree add .worktrees/workbench-v1.6.3 -b codex/workbench-v1.6.3
cd .worktrees/workbench-v1.6.3
```

Expected: branch `codex/workbench-v1.6.3` checked out at the current planning commit.

- [ ] **Step 2: Confirm clean baseline**

Run:

```bash
git status --short --branch
git log --oneline --max-count=3
```

Expected: clean worktree. Latest commit is `docs: add v1.6.3 compare edit spec`.

- [ ] **Step 3: Run focused baseline tests**

Run:

```bash
cd frontend && npm test -- \
  src/lineage/api/nodeOperationContext.test.ts \
  src/lineage/detail/sections/OperationSection.test.tsx \
  src/workbench/WorkbenchRouteContainer.test.tsx
cd ..
.venv/bin/python -m pytest \
  tests/test_node_write_validation.py \
  tests/test_rerun_endpoint.py \
  tests/test_graph_headset.py -q
```

Expected: all tests pass before implementation starts.

- [ ] **Step 4: Commit nothing**

Expected: no files changed in Task 0.

## Task 1: Backend Rerun Provenance and Produced Lineage

**Files:**
- Create: `backend/workbench/lineage/rerun_provenance.py`
- Modify: `backend/workbench/lineage/node_index.py`
- Modify: `backend/workbench/lineage/headset.py`
- Modify: `backend/workbench/api.py`
- Test: `tests/test_rerun_endpoint.py`
- Test: `tests/test_graph_headset.py`

- [ ] **Step 1: Write failing provenance response tests**

Add to `tests/test_rerun_endpoint.py`:

```python
def test_context_rerun_persists_run_level_rerun_from_and_returns_pending_lineage(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    owner = _create_terminal_run(project.root)
    node_id = _model_node_id(project.root, owner)
    _write_node_index(project.root, owner, node_id, "hash_owner_model")
    fingerprint = _context_fingerprint(
        project.root,
        owner_run_id=owner,
        op_node_id=node_id,
        node_hash="hash_owner_model",
        forest_node_key="hash_owner_model",
        owner_resolution="active_head_contains_node",
        active_head_run_id=owner,
    )

    resp = client.post(
        f"/runs/{owner}/rerun",
        params={"project_root": str(project.root)},
        json={
            "request_id": "req_provenance",
            "operation": "rerun",
            "context_version": "node-operation-context/v1",
            "context_fingerprint": fingerprint,
            "owner_run_id": owner,
            "op_node_id": node_id,
            "node_hash": "hash_owner_model",
            "forest_node_key": "hash_owner_model",
            "owner_resolution": "active_head_contains_node",
            "active_head_run_id": owner,
            "op_overrides": {"covariance": "unadjusted"},
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["produced_lineage"] == {
        "produced_owner_run_id": body["run_id"],
        "produced_op_node_id": None,
        "produced_node_hash": None,
        "rerun_request_id": "req_provenance",
        "status": "pending_index",
        "rerun_from": {
            "owner_run_id": owner,
            "op_node_id": node_id,
            "node_hash": "hash_owner_model",
            "context_fingerprint": fingerprint,
            "rerun_request_id": "req_provenance",
        },
    }
    stored = json.loads((project.root / "runs" / body["run_id"] / "run_inputs.json").read_text())
    assert stored["rerun_from"]["owner_run_id"] == owner
    assert stored["rerun_from"]["op_node_id"] == node_id
```

Add to `tests/test_graph_headset.py`:

```python
def test_headset_exposes_run_level_rerun_from_on_child_head(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    parent = _create_terminal_run(project.root)
    child = _create_terminal_run(project.root)
    (project.root / "runs" / child / "run_inputs.json").write_text(
        json.dumps({
            "form": {},
            "upload": {"sha256": "hash"},
            "rerun_of": parent,
            "from_node": "model:ols_1",
            "rerun_from": {
                "owner_run_id": parent,
                "op_node_id": "model:ols_1",
                "node_hash": "hash_parent_model",
                "context_fingerprint": "nocv1:parent",
                "rerun_request_id": "req_headset",
            },
        }),
        encoding="utf-8",
    )
    body = client.get(
        f"/runs/{child}/graph",
        params={"project_root": str(project.root), "view": "headset"},
    ).json()
    child_head = next(head for head in body["heads"] if head["run_id"] == child)
    assert child_head["rerun_from"]["rerun_request_id"] == "req_headset"
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_rerun_endpoint.py::test_context_rerun_persists_run_level_rerun_from_and_returns_pending_lineage \
  tests/test_graph_headset.py::test_headset_exposes_run_level_rerun_from_on_child_head -q
```

Expected: fail because `produced_lineage` and headset `rerun_from` are not implemented.

- [ ] **Step 3: Implement backend provenance helpers**

Create `backend/workbench/lineage/rerun_provenance.py`:

```python
from __future__ import annotations

from typing import Any


def run_rerun_from_from_context(*, request_id: str, owner_run_id: str, op_node_id: str, node_hash: str, context_fingerprint: str, patch_id: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "owner_run_id": owner_run_id,
        "op_node_id": op_node_id,
        "node_hash": node_hash,
        "context_fingerprint": context_fingerprint,
        "rerun_request_id": request_id,
    }
    if patch_id:
        body["patch_id"] = patch_id
    return body


def pending_produced_lineage(*, produced_owner_run_id: str, rerun_from: dict[str, Any]) -> dict[str, Any]:
    return {
        "produced_owner_run_id": produced_owner_run_id,
        "produced_op_node_id": None,
        "produced_node_hash": None,
        "rerun_request_id": str(rerun_from["rerun_request_id"]),
        "rerun_from": rerun_from,
        "status": "pending_index",
    }


def indexed_produced_lineage(*, produced_owner_run_id: str, produced_op_node_id: str, produced_node_hash: str, rerun_from: dict[str, Any]) -> dict[str, Any]:
    return {
        "produced_owner_run_id": produced_owner_run_id,
        "produced_op_node_id": produced_op_node_id,
        "produced_node_hash": produced_node_hash,
        "rerun_request_id": str(rerun_from["rerun_request_id"]),
        "rerun_from": rerun_from,
        "status": "indexed",
    }
```

- [ ] **Step 4: Persist run-level provenance from rerun endpoint**

Modify `backend/workbench/api.py`:

```python
from .lineage.rerun_provenance import pending_produced_lineage, run_rerun_from_from_context
```

Inside `rerun_endpoint`, after `accepted_context = accepted_context_from(request)`, derive:

```python
run_level_rerun_from = run_rerun_from_from_context(
    request_id=request.request_id,
    owner_run_id=request.owner_run_id,
    op_node_id=request.op_node_id,
    node_hash=request.node_hash,
    context_fingerprint=request.context_fingerprint,
)
```

Before `_submit_run(...)`, merge provenance into run inputs by passing it through the form side channel:

```python
rerun_metadata = {"rerun_from": run_level_rerun_from} if run_level_rerun_from else {}
```

After `_submit_run(...)`, write the metadata into the child `run_inputs.json`:

```python
if rerun_metadata:
    child_inputs_path = root / "runs" / child_id / "run_inputs.json"
    child_inputs = json.loads(child_inputs_path.read_text(encoding="utf-8"))
    child_inputs.update(rerun_metadata)
    child_inputs_path.write_text(json.dumps(child_inputs, indent=2, sort_keys=True), encoding="utf-8")
```

Return:

```python
"produced_lineage": (
    pending_produced_lineage(
        produced_owner_run_id=child_id,
        rerun_from=run_level_rerun_from,
    )
    if run_level_rerun_from is not None
    else None
),
```

- [ ] **Step 5: Expose run-level provenance in headset heads**

Modify `backend/workbench/lineage/headset.py` when appending `heads`:

```python
heads.append({
    "run_id": run_id,
    "head_node_hash": nodes[head_key]["node_hash"] if head_key in nodes else None,
    "from_node": inputs.get("from_node"),
    "rerun_of": inputs.get("rerun_of"),
    "rerun_from": inputs.get("rerun_from"),
    "rerun_reason": inputs.get("rerun_reason"),
    "status": manifest.get("status"),
    "created_at": manifest.get("started_at") or manifest.get("created_at"),
})
```

- [ ] **Step 6: Run focused backend tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_rerun_endpoint.py::test_context_rerun_persists_run_level_rerun_from_and_returns_pending_lineage \
  tests/test_rerun_endpoint.py::test_context_driven_rerun_uses_owner_run_not_url_run \
  tests/test_graph_headset.py::test_headset_exposes_run_level_rerun_from_on_child_head -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/workbench/lineage/rerun_provenance.py backend/workbench/api.py backend/workbench/lineage/headset.py tests/test_rerun_endpoint.py tests/test_graph_headset.py
git commit -m "feat(lineage): persist context rerun provenance"
```

## Task 2: Frontend Rerun Provenance Types and Compare Gate

**Files:**
- Create: `frontend/src/lineage/api/rerunProvenance.ts`
- Create: `frontend/src/lineage/api/rerunProvenance.test.ts`
- Modify: `frontend/src/lineage/api/graphViewTypes.ts`
- Modify: `frontend/src/lineage/api/nodeOperationContext.ts`
- Modify: `frontend/src/lineage/api/nodeOperationContext.test.ts`
- Read: `frontend/src/workbench/forestModel.ts`

- [ ] **Step 1: Write failing provenance gate tests**

Create `frontend/src/lineage/api/rerunProvenance.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { getCompareWithSourceGate } from "./rerunProvenance";
import type { NodeOperationContextV1 } from "./nodeOperationContext";

function context(overrides: Partial<NodeOperationContextV1> = {}): NodeOperationContextV1 {
  return {
    context_version: "node-operation-context/v1",
    context_kind: "executed_lineage_node",
    context_fingerprint: "nocv1:child",
    selection: { forest_node_key: "hash_child::model:ols_1", node_hash: "hash_child", display_label: "OLS", kind: "model", stage: "model" },
    ownership: { active_head_run_id: "run_child", candidate_run_refs: [], candidate_run_ids: ["run_child"], shared_by_run_ids: ["run_child"], owner_run_id: "run_child", owner_resolution: "single_candidate" },
    operation_target: { owner_run_id: "run_child", op_node_id: "model:ols_1", node_hash: "hash_child", node_state: "materialized" },
    lineage_context: { path_run_id: "run_child", upstream_path: [], active_head_path_contains_node: true },
    node_payload: { decisions: [], artifacts: [], editable_schema: null, params: {} },
    capabilities: { can_rerun: true, can_ask_ai: true, can_compare: false, can_rollback_focus: false, can_edit_params: false, disabled_reasons: [] },
    comparison_readiness: { can_compare: false, candidate_run_ids: ["run_child"], active_head_run_id: "run_child", owner_run_id: "run_child", shared_by_run_ids: ["run_child"] },
    context_diagnostics: { warnings: [], resolution_notes: [] },
    ...overrides,
  };
}

describe("getCompareWithSourceGate", () => {
  it("passes when node-level rerun_from is present", () => {
    const result = getCompareWithSourceGate(context({
      rerun_from: {
        owner_run_id: "run_source",
        op_node_id: "model:ols_1",
        node_hash: "hash_source",
        context_fingerprint: "nocv1:source",
        rerun_request_id: "req_1",
      },
    }));
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(result.source_kind).toBe("node_level_rerun_from");
  });

  it("fails closed without rerun_from instead of using runs[0]", () => {
    const result = getCompareWithSourceGate(context({
      ownership: {
        ...context().ownership,
        candidate_run_ids: ["run_source", "run_child"],
        shared_by_run_ids: ["run_source", "run_child"],
      },
    }));
    expect(result).toEqual({ ok: false, reason: "missing_rerun_from" });
  });
});
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
cd frontend && npm test -- src/lineage/api/rerunProvenance.test.ts
```

Expected: fail because `rerunProvenance.ts` does not exist and `NodeOperationContextV1` has no `rerun_from`.

- [ ] **Step 3: Extend frontend types**

Modify `frontend/src/lineage/api/nodeOperationContext.ts`:

```ts
export interface RerunFromProvenance {
  owner_run_id: string;
  op_node_id: string;
  node_hash: string;
  context_fingerprint: string;
  patch_id?: string;
  rerun_request_id: string;
}
```

Add to `NodeOperationContextV1`:

```ts
rerun_from?: RerunFromProvenance;
run_rerun_from?: RerunFromProvenance;
resolver_trace?: string[];
```

Modify `frontend/src/lineage/api/graphViewTypes.ts` `HeadSetNode`:

```ts
rerunFrom?: RerunFromProvenance;
runRerunFrom?: RerunFromProvenance;
editableSchemaVersion?: string;
```

Import the type with:

```ts
import type { RerunFromProvenance } from "./nodeOperationContext";
```

- [ ] **Step 4: Implement gate helper**

Create `frontend/src/lineage/api/rerunProvenance.ts`:

```ts
import type { NodeOperationContextV1, RerunFromProvenance } from "./nodeOperationContext";

export type CompareWithSourceGate =
  | { ok: true; source_kind: "node_level_rerun_from" | "run_level_rerun_from_fallback"; rerun_from: RerunFromProvenance }
  | { ok: false; reason: "missing_rerun_from" | "provenance_mismatch" | "run_level_fallback_ambiguous" };

export function getCompareWithSourceGate(context: NodeOperationContextV1): CompareWithSourceGate {
  if (context.rerun_from) {
    if (context.run_rerun_from && !sameRerunFrom(context.rerun_from, context.run_rerun_from)) {
      return { ok: false, reason: "provenance_mismatch" };
    }
    return { ok: true, source_kind: "node_level_rerun_from", rerun_from: context.rerun_from };
  }
  if (context.run_rerun_from && context.ownership.candidate_run_ids.length === 1) {
    return { ok: true, source_kind: "run_level_rerun_from_fallback", rerun_from: context.run_rerun_from };
  }
  return { ok: false, reason: context.run_rerun_from ? "run_level_fallback_ambiguous" : "missing_rerun_from" };
}

function sameRerunFrom(left: RerunFromProvenance, right: RerunFromProvenance): boolean {
  return left.owner_run_id === right.owner_run_id &&
    left.op_node_id === right.op_node_id &&
    left.node_hash === right.node_hash &&
    left.context_fingerprint === right.context_fingerprint &&
    left.rerun_request_id === right.rerun_request_id &&
    (left.patch_id ?? null) === (right.patch_id ?? null);
}
```

- [ ] **Step 5: Wire resolver and adapter**

In `resolveNodeOperationContext(...)`, copy provenance from selected node:

```ts
const nodeRerunFrom = node.rerunFrom;
const runRerunFrom = node.runRerunFrom;
```

Add to the returned context:

```ts
rerun_from: nodeRerunFrom,
run_rerun_from: runRerunFrom,
resolver_trace: explainResolveNodeOperationContext(input).split("\n"),
```

Verify `frontend/src/workbench/forestModel.ts` remains a pure projection:

```ts
return {
  schemaVersion: forest.schemaVersion,
  runId,
  legacy: forest.legacy,
  nodes: forest.nodes,
  edges,
  stats: {
    nodeCount: forest.nodes.length,
    edgeCount: edges.length,
    leafCount: forest.nodes.filter((n) => !sources.has(n.id)).length,
    hasDpCount: forest.nodes.filter((n) => n.decisions.length > 0).length,
  },
};
```

If provenance fields are missing in the UI, fix the headset adapter that creates `ForestViewModel.nodes`; do not add a second mapping layer to `forestModel.ts`.

- [ ] **Step 6: Run focused tests**

Run:

```bash
cd frontend && npm test -- \
  src/lineage/api/rerunProvenance.test.ts \
  src/lineage/api/nodeOperationContext.test.ts
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lineage/api/rerunProvenance.ts frontend/src/lineage/api/rerunProvenance.test.ts frontend/src/lineage/api/graphViewTypes.ts frontend/src/lineage/api/nodeOperationContext.ts frontend/src/lineage/api/nodeOperationContext.test.ts
git commit -m "feat(lineage): gate source compare on rerun provenance"
```

## Task 3: Compare With Source Result Builder and UI

**Files:**
- Create: `frontend/src/lineage/api/compareWithSource.ts`
- Create: `frontend/src/lineage/api/compareWithSource.test.ts`
- Create: `frontend/src/lineage/detail/sections/CompareWithSourceSection.tsx`
- Create: `frontend/src/lineage/detail/sections/CompareWithSourceSection.test.tsx`
- Modify: `frontend/src/workbench/registry/sectionRegistry.ts`

- [ ] **Step 1: Write compare builder tests**

Create `frontend/src/lineage/api/compareWithSource.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { buildCompareWithSourceResult } from "./compareWithSource";
import type { NodeOperationContextV1 } from "./nodeOperationContext";

function baseContext(runId: string, fingerprint: string, params: Record<string, unknown>, metrics: Record<string, unknown>): NodeOperationContextV1 {
  return {
    context_version: "node-operation-context/v1",
    context_kind: "executed_lineage_node",
    context_fingerprint: fingerprint,
    selection: { forest_node_key: `${runId}:key`, node_hash: `${runId}:hash`, display_label: "OLS", kind: "model", stage: "model" },
    ownership: { active_head_run_id: runId, candidate_run_refs: [], candidate_run_ids: [runId], shared_by_run_ids: [runId], owner_run_id: runId, owner_resolution: "single_candidate" },
    operation_target: { owner_run_id: runId, op_node_id: "model:ols_1", node_hash: `${runId}:hash`, node_state: "materialized" },
    lineage_context: { path_run_id: runId, upstream_path: [{ key: `${runId}:source`, label: "Source", kind: "dataset", stage: "source" }], active_head_path_contains_node: true },
    node_payload: { decisions: [], artifacts: [], editable_schema: null, params, metrics },
    capabilities: { can_rerun: true, can_ask_ai: true, can_compare: true, can_rollback_focus: false, can_edit_params: false, disabled_reasons: [] },
    comparison_readiness: { can_compare: true, candidate_run_ids: [runId], active_head_run_id: runId, owner_run_id: runId, shared_by_run_ids: [runId] },
    context_diagnostics: { warnings: [], resolution_notes: [] },
  };
}

describe("buildCompareWithSourceResult", () => {
  it("builds summary field diffs and empty sections", () => {
    const result = buildCompareWithSourceResult({
      source: baseContext("run_source", "nocv1:source", { covariance: "clustered" }, { r_squared: 0.42 }),
      current: baseContext("run_child", "nocv1:child", { covariance: "robust" }, { r_squared: 0.51 }),
      provenance: { source_kind: "node_level_rerun_from", rerun_request_id: "req_1" },
    });

    expect(result.sections.params.items[0]).toMatchObject({
      field_id: "covariance",
      change_type: "changed",
      old_value: "clustered",
      new_value: "robust",
    });
    expect(result.sections.metrics.items[0].delta).toBeCloseTo(0.09);
    expect(result.sections.diagnostics).toMatchObject({
      changed: false,
      total_changed: 0,
      items: [],
    });
  });
});
```

- [ ] **Step 2: Run builder test and confirm failure**

Run:

```bash
cd frontend && npm test -- src/lineage/api/compareWithSource.test.ts
```

Expected: fail because module does not exist.

- [ ] **Step 3: Implement compare builder**

Create `frontend/src/lineage/api/compareWithSource.ts`:

```ts
import type { NodeOperationContextV1 } from "./nodeOperationContext";

export interface CompareSection<T> {
  changed: boolean;
  total_changed: number;
  items: T[];
  truncated?: boolean;
  summary: string;
}

export interface FieldDiff {
  field_id: string;
  label?: string;
  change_type: "added" | "removed" | "changed";
  old_value?: unknown;
  new_value?: unknown;
  delta?: number | string | null;
}

export interface CompareWithSourceResult {
  compare_version: "compare-with-source/v1";
  compare_kind: "source";
  left: NodeOperationContextV1;
  right: NodeOperationContextV1;
  provenance: { source_kind: "node_level_rerun_from" | "run_level_rerun_from_fallback"; rerun_request_id: string; patch_id?: string };
  sections: {
    params: CompareSection<FieldDiff>;
    decisions: CompareSection<FieldDiff>;
    metrics: CompareSection<FieldDiff>;
    diagnostics: CompareSection<FieldDiff>;
    artifacts: CompareSection<FieldDiff>;
    upstream_path: CompareSection<FieldDiff>;
  };
}

export function buildCompareWithSourceResult(input: {
  source: NodeOperationContextV1;
  current: NodeOperationContextV1;
  provenance: CompareWithSourceResult["provenance"];
}): CompareWithSourceResult {
  return {
    compare_version: "compare-with-source/v1",
    compare_kind: "source",
    left: input.source,
    right: input.current,
    provenance: input.provenance,
    sections: {
      params: fieldSection("parameter", input.source.node_payload.params, input.current.node_payload.params, 10),
      decisions: emptySection("No decision changes detected."),
      metrics: fieldSection("metric", input.source.node_payload.metrics ?? {}, input.current.node_payload.metrics ?? {}, 10),
      diagnostics: emptySection("No diagnostic changes detected."),
      artifacts: emptySection("No artifact summary changes detected."),
      upstream_path: upstreamPathSection(input.source, input.current),
    },
  };
}

function emptySection<T>(summary: string): CompareSection<T> {
  return { changed: false, total_changed: 0, items: [], summary };
}

function fieldSection(label: string, left: Record<string, unknown>, right: Record<string, unknown>, limit: number): CompareSection<FieldDiff> {
  const keys = Array.from(new Set([...Object.keys(left), ...Object.keys(right)])).sort();
  const diffs = keys.flatMap((key): FieldDiff[] => {
    if (!(key in left)) return [{ field_id: key, change_type: "added", new_value: right[key] }];
    if (!(key in right)) return [{ field_id: key, change_type: "removed", old_value: left[key] }];
    if (stableValue(left[key]) === stableValue(right[key])) return [];
    const delta = typeof left[key] === "number" && typeof right[key] === "number" ? (right[key] as number) - (left[key] as number) : null;
    return [{ field_id: key, change_type: "changed", old_value: left[key], new_value: right[key], delta }];
  });
  return {
    changed: diffs.length > 0,
    total_changed: diffs.length,
    items: diffs.slice(0, limit),
    truncated: diffs.length > limit || undefined,
    summary: diffs.length === 0 ? `No ${label} changes detected.` : `${diffs.length} ${label} changes detected.`,
  };
}

function upstreamPathSection(source: NodeOperationContextV1, current: NodeOperationContextV1): CompareSection<FieldDiff> {
  const oldPath = source.lineage_context.upstream_path.map((node) => node.key);
  const newPath = current.lineage_context.upstream_path.map((node) => node.key);
  if (stableValue(oldPath) === stableValue(newPath)) return emptySection("No upstream path changes detected.");
  return {
    changed: true,
    total_changed: 1,
    items: [{ field_id: "upstream_path", change_type: "changed", old_value: oldPath, new_value: newPath }],
    summary: "Upstream path changed.",
  };
}

function stableValue(value: unknown): string {
  return JSON.stringify(value, Object.keys(value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}).sort());
}
```

- [ ] **Step 4: Write Compare UI tests**

Create `frontend/src/lineage/detail/sections/CompareWithSourceSection.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CompareWithSourceSection } from "./CompareWithSourceSection";

const mockGate = vi.hoisted(() => ({ ok: false as unknown }));

vi.mock("../../api/rerunProvenance", () => ({
  getCompareWithSourceGate: () => mockGate,
}));

describe("CompareWithSourceSection", () => {
  it("does not render an actionable compare entry without rerun_from", () => {
    mockGate.ok = false;
    render(<CompareWithSourceSection />);
    expect(screen.queryByRole("button", { name: /compare with source/i })).toBeNull();
    expect(screen.getByText(/No rerun source recorded/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 5: Implement minimal Compare UI**

Create `CompareWithSourceSection.tsx`:

```tsx
import { useResolvedNodeOperationContext } from "../NodeOperationContextProvider";
import { getCompareWithSourceGate } from "../../api/rerunProvenance";

export function CompareWithSourceSection() {
  const resolved = useResolvedNodeOperationContext();
  if (!resolved || !resolved.ok) return null;
  const gate = getCompareWithSourceGate(resolved.context);
  if (!gate.ok) {
    return (
      <section aria-label="Compare with source" data-testid="compare-with-source-section" style={{ marginTop: 18 }}>
        <div className="ln-section-label">Compare with source</div>
        <div style={{ fontSize: 12, color: "var(--label-tertiary)" }}>No rerun source recorded for this node.</div>
      </section>
    );
  }
  return (
    <section aria-label="Compare with source" data-testid="compare-with-source-section" style={{ marginTop: 18 }}>
      <div className="ln-section-label">Compare with source</div>
      <button type="button">Compare with source</button>
    </section>
  );
}
```

Register it in `sectionRegistry.ts` after lineage/context sections and before Operation, using the local registry pattern.

- [ ] **Step 6: Run focused frontend tests**

Run:

```bash
cd frontend && npm test -- \
  src/lineage/api/compareWithSource.test.ts \
  src/lineage/detail/sections/CompareWithSourceSection.test.tsx
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lineage/api/compareWithSource.ts frontend/src/lineage/api/compareWithSource.test.ts frontend/src/lineage/detail/sections/CompareWithSourceSection.tsx frontend/src/lineage/detail/sections/CompareWithSourceSection.test.tsx frontend/src/workbench/registry/sectionRegistry.ts
git commit -m "feat(lineage): add source-bound compare summary"
```

## Task 4: Backend Manual Patch Validator and Idempotency

**Files:**
- Create: `backend/workbench/lineage/manual_patch_validation.py`
- Create: `tests/test_manual_patch_validation.py`
- Modify: `backend/workbench/api.py`
- Modify: `tests/test_rerun_endpoint.py`

- [ ] **Step 1: Write validator tests**

Create `tests/test_manual_patch_validation.py`:

```python
import pytest

from workbench.lineage.manual_patch_validation import (
    ManualPatchValidationError,
    ManualRerunPatch,
    normalize_for_compare,
    validate_manual_patch,
)


def _schema():
    return [
        {"key": "covariance", "label": "Covariance", "kind": "select", "editable": True, "options": ["clustered", "robust"], "value": "clustered"},
        {"key": "internal_id", "label": "Internal", "kind": "text", "editable": False, "value": "locked"},
    ]


def _patch(**overrides):
    data = {
        "patch_id": "patch_1",
        "patch_source": "MANUAL_EDIT",
        "source_context_fingerprint": "nocv1:source",
        "editable_schema_version": "schema:v1",
        "target": {"owner_run_id": "run_source", "op_node_id": "model:ols_1", "node_hash": "hash_source"},
        "changes": [{"field_id": "covariance", "old_value": "clustered", "new_value": "robust"}],
    }
    data.update(overrides)
    return ManualRerunPatch(**data)


def test_valid_patch_returns_overrides():
    result = validate_manual_patch(
        patch=_patch(),
        current_values={"covariance": "clustered"},
        editable_schema=_schema(),
        editable_schema_version="schema:v1",
    )
    assert result == {"covariance": "robust"}


def test_empty_patch_rejected():
    with pytest.raises(ManualPatchValidationError, match="EMPTY_PATCH"):
        validate_manual_patch(
            patch=_patch(changes=[]),
            current_values={"covariance": "clustered"},
            editable_schema=_schema(),
            editable_schema_version="schema:v1",
        )


def test_duplicate_field_rejected():
    duplicate = [
        {"field_id": "covariance", "old_value": "clustered", "new_value": "robust"},
        {"field_id": "covariance", "old_value": "clustered", "new_value": "robust"},
    ]
    with pytest.raises(ManualPatchValidationError, match="DUPLICATE_FIELD"):
        validate_manual_patch(
            patch=_patch(changes=duplicate),
            current_values={"covariance": "clustered"},
            editable_schema=_schema(),
            editable_schema_version="schema:v1",
        )


def test_noop_after_normalization_rejected():
    with pytest.raises(ManualPatchValidationError, match="NOOP_PATCH"):
        validate_manual_patch(
            patch=_patch(changes=[{"field_id": "covariance", "old_value": "clustered", "new_value": "clustered"}]),
            current_values={"covariance": "clustered"},
            editable_schema=_schema(),
            editable_schema_version="schema:v1",
        )


def test_field_value_stale_rejected():
    with pytest.raises(ManualPatchValidationError, match="FIELD_VALUE_STALE"):
        validate_manual_patch(
            patch=_patch(changes=[{"field_id": "covariance", "old_value": "clustered", "new_value": "robust"}]),
            current_values={"covariance": "robust"},
            editable_schema=_schema(),
            editable_schema_version="schema:v1",
        )


def test_object_normalization_sorts_keys():
    assert normalize_for_compare({"b": 2, "a": 1}) == normalize_for_compare({"a": 1, "b": 2})
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_manual_patch_validation.py -q
```

Expected: fail because module does not exist.

- [ ] **Step 3: Implement patch validator**

Create `backend/workbench/lineage/manual_patch_validation.py`:

```python
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel


class ManualPatchValidationError(ValueError):
    pass


class ManualRerunPatchTarget(BaseModel):
    owner_run_id: str
    op_node_id: str
    node_hash: str


class ManualRerunPatchChange(BaseModel):
    field_id: str
    old_value: Any
    new_value: Any


class ManualRerunPatch(BaseModel):
    patch_id: str
    patch_source: Literal["MANUAL_EDIT"]
    source_context_fingerprint: str
    editable_schema_version: str
    target: ManualRerunPatchTarget
    changes: list[ManualRerunPatchChange]


def normalize_for_compare(value: Any, schema: dict[str, Any] | None = None) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return json.dumps(float(value), separators=(",", ":"))
    if isinstance(value, str) and schema and schema.get("trim") is True:
        return json.dumps(value.strip(), separators=(",", ":"))
    if isinstance(value, list):
        values = [normalize_for_compare(item) for item in value]
        if schema and schema.get("order_insensitive") is True:
            values = sorted(values)
        return json.dumps(values, separators=(",", ":"))
    if isinstance(value, dict):
        return json.dumps({key: json.loads(normalize_for_compare(value[key])) for key in sorted(value)}, separators=(",", ":"), sort_keys=True)
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def validate_manual_patch(*, patch: ManualRerunPatch, current_values: dict[str, Any], editable_schema: list[dict[str, Any]], editable_schema_version: str) -> dict[str, Any]:
    if patch.editable_schema_version != editable_schema_version:
        raise ManualPatchValidationError("EDITABLE_SCHEMA_STALE")
    if not patch.changes:
        raise ManualPatchValidationError("EMPTY_PATCH")

    schema_by_key = {str(item.get("key")): item for item in editable_schema if item.get("key")}
    seen: set[str] = set()
    overrides: dict[str, Any] = {}
    for change in patch.changes:
        if change.field_id in seen:
            raise ManualPatchValidationError("DUPLICATE_FIELD")
        seen.add(change.field_id)
        field_schema = schema_by_key.get(change.field_id)
        if not field_schema or field_schema.get("editable") is False:
            raise ManualPatchValidationError("FIELD_NOT_EDITABLE")
        current_value = current_values.get(change.field_id)
        if normalize_for_compare(change.old_value, field_schema) != normalize_for_compare(current_value, field_schema):
            raise ManualPatchValidationError("FIELD_VALUE_STALE")
        if normalize_for_compare(change.old_value, field_schema) == normalize_for_compare(change.new_value, field_schema):
            raise ManualPatchValidationError("NOOP_PATCH")
        if field_schema.get("options"):
            allowed = [opt.get("value") if isinstance(opt, dict) else opt for opt in field_schema["options"]]
            if change.new_value not in allowed:
                raise ManualPatchValidationError("INVALID_FIELD_VALUE")
        overrides[change.field_id] = change.new_value

    if not overrides:
        raise ManualPatchValidationError("EMPTY_PATCH")
    return overrides
```

- [ ] **Step 4: Add idempotency tests at endpoint**

Add to `tests/test_rerun_endpoint.py`:

```python
def test_manual_patch_idempotency_reuses_existing_child(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    parent = _create_terminal_run(project.root)
    node_id = _model_node_id(project.root, parent)
    _write_node_index(project.root, parent, node_id, "hash_parent_model")
    fingerprint = _context_fingerprint(
        project.root,
        owner_run_id=parent,
        op_node_id=node_id,
        node_hash="hash_parent_model",
        forest_node_key="hash_parent_model",
        owner_resolution="active_head_contains_node",
        active_head_run_id=parent,
    )
    payload = {
        "request_id": "req_patch_1",
        "operation": "rerun",
        "context_version": "node-operation-context/v1",
        "context_fingerprint": fingerprint,
        "owner_run_id": parent,
        "op_node_id": node_id,
        "node_hash": "hash_parent_model",
        "forest_node_key": "hash_parent_model",
        "owner_resolution": "active_head_contains_node",
        "active_head_run_id": parent,
        "manual_patch": {
            "patch_id": "patch_same",
            "patch_source": "MANUAL_EDIT",
            "source_context_fingerprint": fingerprint,
            "editable_schema_version": "run_inputs",
            "target": {"owner_run_id": parent, "op_node_id": node_id, "node_hash": "hash_parent_model"},
            "changes": [{"field_id": "covariance", "old_value": "nonrobust", "new_value": "unadjusted"}],
        },
    }
    first = client.post(f"/runs/{parent}/rerun", params={"project_root": str(project.root)}, json=payload)
    second = client.post(f"/runs/{parent}/rerun", params={"project_root": str(project.root)}, json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["run_id"] == first.json()["run_id"]
```

- [ ] **Step 5: Wire manual patch into API**

Modify `RerunRequest` in `backend/workbench/api.py`:

```python
manual_patch: dict[str, Any] | None = None
```

When `manual_patch` exists:

```python
patch = ManualRerunPatch(**body.manual_patch)
if patch.source_context_fingerprint != request.context_fingerprint:
    raise HTTPException(status_code=409, detail="SOURCE_CONTEXT_MISMATCH")
```

Build current values from resolved contract/backfilled run inputs:

```python
editable_schema = _backfill_schema_values(contract.editable_schema, inputs["form"])
current_values = {item["key"]: item.get("value") for item in editable_schema if item.get("key")}
body.op_overrides = validate_manual_patch(
    patch=patch,
    current_values=current_values,
    editable_schema=editable_schema,
    editable_schema_version=body.manual_patch.get("editable_schema_version", "run_inputs"),
)
```

Implement idempotency with a project-local file:

```python
idempotency_path = root / "runs" / effective_run_id / "manual_patch_idempotency.json"
```

Store keys by `patch_id` with normalized payload and child result. On same key/payload return existing result; on same key/different payload return 409 `PATCH_ID_CONFLICT`.

- [ ] **Step 6: Run backend tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_manual_patch_validation.py \
  tests/test_rerun_endpoint.py::test_manual_patch_idempotency_reuses_existing_child \
  tests/test_rerun_endpoint.py::test_context_driven_rerun_uses_owner_run_not_url_run -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/workbench/lineage/manual_patch_validation.py backend/workbench/api.py tests/test_manual_patch_validation.py tests/test_rerun_endpoint.py
git commit -m "feat(api): validate manual rerun patches"
```

## Task 5: Frontend Manual Patch Preview and Submission

**Files:**
- Create: `frontend/src/lineage/detail/sections/manualRerunPatch.ts`
- Create: `frontend/src/lineage/detail/sections/manualRerunPatch.test.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/api.test.ts`
- Modify: `frontend/src/lineage/detail/RerunContext.tsx`
- Modify: `frontend/src/lineage/detail/RerunContext.test.tsx`
- Modify: `frontend/src/lineage/detail/sections/OperationSection.tsx`
- Modify: `frontend/src/lineage/detail/sections/OperationSection.test.tsx`

- [ ] **Step 1: Write frontend patch model tests**

Create `manualRerunPatch.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { buildManualRerunPatch, normalizeForCompare } from "./manualRerunPatch";

describe("manualRerunPatch", () => {
  it("builds a single-node patch with old and new values", () => {
    const patch = buildManualRerunPatch({
      patchId: "patch_1",
      sourceContextFingerprint: "nocv1:source",
      editableSchemaVersion: "schema:v1",
      target: { owner_run_id: "run_source", op_node_id: "model:ols_1", node_hash: "hash_source" },
      initialValues: { covariance: "clustered" },
      currentValues: { covariance: "robust" },
    });
    expect(patch.changes).toEqual([{ field_id: "covariance", old_value: "clustered", new_value: "robust" }]);
  });

  it("returns null for no-op normalized changes", () => {
    expect(buildManualRerunPatch({
      patchId: "patch_1",
      sourceContextFingerprint: "nocv1:source",
      editableSchemaVersion: "schema:v1",
      target: { owner_run_id: "run_source", op_node_id: "model:ols_1", node_hash: "hash_source" },
      initialValues: { covariance: "clustered" },
      currentValues: { covariance: "clustered" },
    })).toBeNull();
  });

  it("normalizes object keys deterministically", () => {
    expect(normalizeForCompare({ b: 2, a: 1 })).toBe(normalizeForCompare({ a: 1, b: 2 }));
  });
});
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
cd frontend && npm test -- src/lineage/detail/sections/manualRerunPatch.test.ts
```

Expected: fail because module does not exist.

- [ ] **Step 3: Implement frontend patch helper**

Create `manualRerunPatch.ts`:

```ts
export interface ManualRerunPatch {
  patch_id: string;
  patch_source: "MANUAL_EDIT";
  source_context_fingerprint: string;
  editable_schema_version: string;
  target: { owner_run_id: string; op_node_id: string; node_hash: string };
  changes: Array<{ field_id: string; old_value: unknown; new_value: unknown }>;
}

export function buildManualRerunPatch(input: {
  patchId: string;
  sourceContextFingerprint: string;
  editableSchemaVersion: string;
  target: ManualRerunPatch["target"];
  initialValues: Record<string, unknown>;
  currentValues: Record<string, unknown>;
}): ManualRerunPatch | null {
  const changes = Object.keys(input.currentValues).sort().flatMap((key) => {
    const oldValue = input.initialValues[key];
    const newValue = input.currentValues[key];
    return normalizeForCompare(oldValue) === normalizeForCompare(newValue)
      ? []
      : [{ field_id: key, old_value: oldValue, new_value: newValue }];
  });
  if (changes.length === 0) return null;
  return {
    patch_id: input.patchId,
    patch_source: "MANUAL_EDIT",
    source_context_fingerprint: input.sourceContextFingerprint,
    editable_schema_version: input.editableSchemaVersion,
    target: input.target,
    changes,
  };
}

export function normalizeForCompare(value: unknown): string {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(value).sort()) out[key] = (value as Record<string, unknown>)[key];
    return JSON.stringify(out);
  }
  return JSON.stringify(value);
}
```

- [ ] **Step 4: Extend frontend API and rerun context**

Modify `frontend/src/api.ts`:

```ts
import type { ManualRerunPatch } from "./lineage/detail/sections/manualRerunPatch";
```

Add to `NodeWriteOperationRequestV1`:

```ts
manual_patch?: ManualRerunPatch;
```

Add to `RerunResponseV1`:

```ts
produced_lineage?: {
  produced_owner_run_id: string;
  produced_op_node_id?: string | null;
  produced_node_hash?: string | null;
  rerun_request_id: string;
  rerun_from: {
    owner_run_id: string;
    op_node_id: string;
    node_hash: string;
    context_fingerprint: string;
    patch_id?: string;
    rerun_request_id: string;
  };
  status: "indexed" | "pending_index";
} | null;
```

Modify `RerunArgs` in `RerunContext.tsx`:

```ts
manualPatch?: ManualRerunPatch;
```

Include in request:

```ts
manual_patch: args.manualPatch,
op_overrides: args.manualPatch ? {} : args.opOverrides,
```

- [ ] **Step 5: Update OperationSection to preview patch**

In `OperationSection.tsx`, replace direct submit with two-step preview:

```tsx
const [previewPatch, setPreviewPatch] = useState<ManualRerunPatch | null>(null);
const patch = buildManualRerunPatch({
  patchId: `patch_${context.context_fingerprint}_${Object.keys(overrides).join("_")}`,
  sourceContextFingerprint: context.context_fingerprint,
  editableSchemaVersion: node.editableSchemaVersion ?? context.operation_target.editable_schema_source ?? "run_inputs",
  target: {
    owner_run_id: context.operation_target.owner_run_id,
    op_node_id: context.operation_target.op_node_id,
    node_hash: context.operation_target.node_hash,
  },
  initialValues: initial,
  currentValues: values,
});
```

Button text:

```tsx
{previewPatch ? "Confirm rerun source with changes" : "Preview source changes"}
```

On confirm:

```ts
await rerun.submitRerun({ context, opOverrides: {}, manualPatch: previewPatch });
```

Render preview:

```tsx
{previewPatch && (
  <div data-testid="manual-patch-preview">
    {previewPatch.changes.map((change) => (
      <div key={change.field_id}>
        <strong>{change.field_id}</strong>: {String(change.old_value)} -> {String(change.new_value)}
      </div>
    ))}
  </div>
)}
```

- [ ] **Step 6: Update OperationSection tests**

Add to `OperationSection.test.tsx`:

```tsx
it("previews a manual patch before submitting rerun", async () => {
  const { submitRerun } = renderWithRerun(modelNode());
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "robust" } });
  fireEvent.click(screen.getByTestId("operation-rerun-submit"));
  expect(screen.getByTestId("manual-patch-preview")).toHaveTextContent("covariance");
  expect(submitRerun).not.toHaveBeenCalled();
  fireEvent.click(screen.getByTestId("operation-rerun-submit"));
  await waitFor(() => expect(submitRerun).toHaveBeenCalledTimes(1));
  expect(submitRerun.mock.calls[0][0].manualPatch.patch_source).toBe("MANUAL_EDIT");
});
```

- [ ] **Step 7: Run frontend tests**

Run:

```bash
cd frontend && npm test -- \
  src/lineage/detail/sections/manualRerunPatch.test.ts \
  src/lineage/detail/sections/OperationSection.test.tsx \
  src/lineage/detail/RerunContext.test.tsx \
  src/api.test.ts
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lineage/detail/sections/manualRerunPatch.ts frontend/src/lineage/detail/sections/manualRerunPatch.test.ts frontend/src/api.ts frontend/src/api.test.ts frontend/src/lineage/detail/RerunContext.tsx frontend/src/lineage/detail/RerunContext.test.tsx frontend/src/lineage/detail/sections/OperationSection.tsx frontend/src/lineage/detail/sections/OperationSection.test.tsx
git commit -m "feat(lineage): preview and submit manual rerun patches"
```

## Task 6: Focus, Telemetry, and Context Mismatch UX

**Files:**
- Modify: `frontend/src/workbench/WorkbenchRouteContainer.tsx`
- Modify: `frontend/src/workbench/WorkbenchRouteContainer.test.tsx`
- Modify: `frontend/src/lineage/api/nodeOperationContext.ts`
- Modify: `frontend/src/lineage/api/nodeOperationContext.test.ts`
- Modify: `backend/workbench/lineage/node_write_validation.py`
- Modify: `tests/test_node_write_validation.py`

- [ ] **Step 1: Write frontend focus tests**

Add to `WorkbenchRouteContainer.test.tsx`:

```tsx
it("uses produced lineage pending_index to poll by rerun request id without guessing runs[0]", async () => {
  vi.spyOn(api, "getRunGraphHeadSet")
    .mockResolvedValueOnce(forestResponse("hash_model"))
    .mockResolvedValueOnce(forestResponse("hash_model"))
    .mockResolvedValueOnce(forkedForestResponse());
  vi.spyOn(api, "rerunFromNode").mockResolvedValue({
    run_id: "run_child",
    new_run_id: "run_child",
    new_active_head_id: "run_child",
    focus: null,
    rerun_from: {
      owner_run_id: "run_source",
      op_node_id: "model:ols_1",
      node_hash: "hash_source",
      forest_node_key: "hash_source::model:ols_1",
    },
    produced_lineage: {
      produced_owner_run_id: "run_child",
      rerun_request_id: "req_focus",
      status: "pending_index",
      rerun_from: {
        owner_run_id: "run_source",
        op_node_id: "model:ols_1",
        node_hash: "hash_source",
        context_fingerprint: "nocv1:source",
        rerun_request_id: "req_focus",
      },
    },
  });
  render(
    <MemoryRouter initialEntries={["/?tab=lineage&tabs=hash_model&active=hash_model"]}>
      <Routes>
        <Route
          path="*"
          element={<WorkbenchRouteContainer projectRoot="/proj" runId="run_a" />}
        />
      </Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByTestId("detail-drawer")).toBeInTheDocument();

  fireEvent.change(screen.getByRole("combobox"), { target: { value: "robust" } });
  fireEvent.click(screen.getByTestId("operation-rerun-submit"));

  await waitFor(() => expect(api.getRunGraphHeadSet).toHaveBeenCalledTimes(3));
  await waitFor(() =>
    expect(screen.getByTestId("forest-head-run_child")).toHaveAttribute(
      "aria-pressed",
      "true",
    ),
  );
  await waitFor(() =>
    expect(document.getElementById("detail-drawer-title")?.textContent).toBe(
      "Child OLS",
    ),
  );
});
```

- [ ] **Step 2: Add backend trace/logging tests**

Add to `tests/test_node_write_validation.py`:

```python
def test_fingerprint_mismatch_error_includes_expected_code(tmp_path: Path):
    _write_graph(tmp_path, "run_a")
    _write_node_index(tmp_path)
    with pytest.raises(ValueError, match="context_stale: context_fingerprint"):
        validate_rerun_operation_target(tmp_path, _request(context_fingerprint="wrong"))
```

This duplicates the release gate in a permanent named test if the current test name changes later.

- [ ] **Step 3: Implement focus produced lineage support**

Modify `RerunResponseV1` handling in `WorkbenchRouteContainer.tsx`:

```ts
const lineage = response.produced_lineage;
const focus = response.focus;
setPendingFocusTarget({
  runId: response.new_active_head_id ?? response.run_id,
  focus: focus
    ? { forest_node_key: focus.forest_node_key, op_node_id: focus.op_node_id, node_hash: focus.node_hash }
    : {
        forest_node_key: null,
        op_node_id: lineage?.produced_op_node_id ?? response.rerun_from.op_node_id,
        node_hash: lineage?.produced_node_hash ?? null,
      },
  attempts: 0,
});
```

Keep existing retry limit and never inspect `runs[0]`.

- [ ] **Step 4: Add resolver trace fields**

Modify `explainResolveNodeOperationContext(...)` to include:

```ts
context_fingerprint_inputs
rerun_from
run_rerun_from
```

Ensure trace remains deterministic and tests assert that no candidate array order fallback appears.

- [ ] **Step 5: Run focused tests**

Run:

```bash
cd frontend && npm test -- \
  src/workbench/WorkbenchRouteContainer.test.tsx \
  src/lineage/api/nodeOperationContext.test.ts
cd ..
.venv/bin/python -m pytest tests/test_node_write_validation.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/workbench/WorkbenchRouteContainer.tsx frontend/src/workbench/WorkbenchRouteContainer.test.tsx frontend/src/lineage/api/nodeOperationContext.ts frontend/src/lineage/api/nodeOperationContext.test.ts backend/workbench/lineage/node_write_validation.py tests/test_node_write_validation.py
git commit -m "test(lineage): harden context focus and trace gates"
```

## Task 7: Browser Regression Seed and Release Gates

**Files:**
- Modify: `docs/dev-browser-smoke.md`
- Modify: `frontend/src/lineage/api/rerunProvenance.test.ts`
- Modify: `frontend/src/lineage/api/compareWithSource.test.ts`
- Modify: `frontend/src/lineage/detail/sections/OperationSection.test.tsx`
- Modify: `tests/test_rerun_endpoint.py`
- Modify: `tests/test_graph_headset.py`

- [ ] **Step 1: Add v1.6.3 browser smoke instructions**

Append to `docs/dev-browser-smoke.md`:

```markdown
## V1.6.3 Context Hardening + Compare/Edit Smoke

Create a source run, rerun it through a context-driven node operation, open the rerun child node, and verify:

- `Compare with source` appears only on the rerun child node.
- The compare view shows summary sections for params, metrics, diagnostics, artifacts, and upstream path.
- The operation panel says `Rerun source with changes`.
- Preview shows old/new values before submit.
- Confirming rerun creates a new child.
- The UI reflects the backend-updated active head.
- If focus is pending, polling selects the child after indexing.
- No source, focus, owner, or patch target is inferred from `runs[0]`.
```

- [ ] **Step 2: Add permanent no-runs[0] tests**

In `rerunProvenance.test.ts`, add:

```ts
it("does not use candidate_run_ids[0] as compare source when rerun_from is absent", () => {
  const result = getCompareWithSourceGate(context({
    ownership: {
      ...context().ownership,
      candidate_run_ids: ["run_source_like", "run_child"],
      shared_by_run_ids: ["run_source_like", "run_child"],
    },
  }));
  expect(result).toEqual({ ok: false, reason: "missing_rerun_from" });
});
```

In `tests/test_rerun_endpoint.py`, assert repeated context reruns use explicit owner and patch idempotency instead of URL run or first run.

- [ ] **Step 3: Run focused regression matrix**

Run:

```bash
cd frontend && npm test -- \
  src/lineage/api/rerunProvenance.test.ts \
  src/lineage/api/compareWithSource.test.ts \
  src/lineage/detail/sections/CompareWithSourceSection.test.tsx \
  src/lineage/detail/sections/manualRerunPatch.test.ts \
  src/lineage/detail/sections/OperationSection.test.tsx \
  src/workbench/WorkbenchRouteContainer.test.tsx
cd ..
.venv/bin/python -m pytest \
  tests/test_manual_patch_validation.py \
  tests/test_node_write_validation.py \
  tests/test_rerun_endpoint.py \
  tests/test_graph_headset.py -q
```

Expected: all pass.

- [ ] **Step 4: Run typecheck and full gate**

Run:

```bash
cd frontend && npm run typecheck
cd ..
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh
```

Expected: typecheck passes and gate reports success.

- [ ] **Step 5: Commit**

```bash
git add docs/dev-browser-smoke.md frontend/src/lineage/api/rerunProvenance.test.ts frontend/src/lineage/api/compareWithSource.test.ts frontend/src/lineage/detail/sections/OperationSection.test.tsx tests/test_rerun_endpoint.py tests/test_graph_headset.py
git commit -m "test(lineage): add v1.6.3 compare edit regression gates"
```

## Self-review Checklist

- Spec coverage: Tasks 1-2 cover rerun provenance and compare gate; Task 3 covers Compare v1 summary diff/UI; Tasks 4-5 cover manual patch validation/preview/submission; Task 6 covers focus/null telemetry and context UX; Task 7 covers browser seed and release gates.
- Scope check: no task implements parent compare, active-head recommendation, arbitrary compare, PipelineDraft, AI patch, full artifact diff, dataset diff, run-level patch, multi-node patch, or nested JSON patch.
- Type consistency: use `rerun_from`, `run_rerun_from`, `produced_lineage`, `ManualRerunPatch`, `patch_id`, `source_context_fingerprint`, and `editable_schema_version` consistently across backend and frontend.
- Gate consistency: fingerprint mismatch is a failed gate result; `Compare with source` is not shown/executed.
- Idempotency consistency: repeated same `patch_id` and same normalized payload returns existing rerun request/result; same `patch_id` with different payload returns `PATCH_ID_CONFLICT`.
- Focus consistency: frontend reflects `new_active_head_id` from backend response and never locally invents active head or focus from `runs[0]`.
