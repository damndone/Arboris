# Workbench v1.6.2 NodeOperationContext Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Standardize lineage forest node operations through `NodeOperationContextV1`, make rerun write-safe and active-head aware, and ship a read-only Ask AI context packet/panel without graph mutation.

**Architecture:** Add a frontend resolver as the only UI node-operation semantic entry point, then migrate existing consumers to resolved context. Backend rerun stays the write safety authority by validating submitted operation targets before execution. Ask AI consumes a packet generated from successful context only and never receives raw runs, full artifacts, or executable action bindings.

**Tech Stack:** React 18 + TypeScript + Vite + vitest for frontend; FastAPI + Pydantic + pytest for backend; existing lineage forest/head-set contracts in `frontend/src/lineage/api/*` and `backend/workbench/lineage/*`.

**Spec:** `docs/superpowers/specs/2026-06-27-workbench-v1.6.2-node-operation-context-design.md`

---

## Global Rules

- Work in a clean implementation worktree, recommended path: `.worktrees/workbench-v1.6.2`.
- Do not push from implementation agents unless the user explicitly asks.
- Keep existing untracked files in the main checkout untouched.
- Each task must end with its own tests and commit.
- Run the focused tests listed in each task before committing.
- Before release handoff, run `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh`.
- Preserve backward compatibility while migrating: existing `/runs/{run_id}/rerun` tests that post legacy `from_node` bodies must keep passing until frontend is fully switched.

## File Map

Create:

- `frontend/src/lineage/api/nodeOperationContext.ts` — types, resolver, fingerprint, debug explanation helper, seed fixture helpers for tests.
- `frontend/src/lineage/api/nodeOperationContext.test.ts` — resolver unit tests.
- `frontend/src/lineage/detail/NodeOperationContextProvider.tsx` — React provider/hook for selected drawer node context.
- `frontend/src/lineage/detail/ResolverFailureState.tsx` — first-class failure UI.
- `frontend/src/lineage/detail/sections/askAiContextPacket.ts` — packet generator, artifact visibility policy, response guardrails.
- `frontend/src/lineage/detail/sections/askAiContextPacket.test.ts` — packet/visibility/guardrail tests.
- `frontend/src/lineage/detail/sections/askAiClient.ts` — read-only Ask AI request client with advisory-text response contract.
- `frontend/src/lineage/detail/sections/AskAISection.test.tsx` — Ask AI UI tests.
- `backend/workbench/lineage/node_write_validation.py` — write request models, fingerprint recomputation, rerun target validator.
- `tests/test_node_write_validation.py` — backend validator unit tests.

Modify:

- `frontend/src/lineage/api/graphViewTypes.ts` — deprecate `resolveOwnerRun` fallback behavior; keep only if tests need legacy compatibility during migration.
- `frontend/src/lineage/api/graphViewTypes.test.ts` — replace old fallback tests with context resolver tests.
- `frontend/src/lineage/detail/DetailDrawer.tsx` — wrap header/sections in `NodeOperationContextProvider`.
- `frontend/src/lineage/header/DetailHeader.tsx` and `.test.tsx` — read resolved context/failure state.
- `frontend/src/lineage/graph/NodeActionMenu.tsx` and `.test.tsx` — read capabilities and disambiguation state.
- `frontend/src/lineage/detail/RerunContext.tsx` and `.test.tsx` — submit `NodeWriteOperationRequestV1`, handle response focus.
- `frontend/src/lineage/detail/sections/OperationSection.tsx` and `.test.tsx` — build rerun request from context.
- `frontend/src/api.ts` and `frontend/src/api.test.ts` — add request/response types for validated rerun and read-only Ask AI.
- `frontend/src/workbench/WorkbenchRouteContainer.tsx` and `.test.tsx` — after rerun success, set active head and select/focus new node when resolvable.
- `backend/workbench/api.py` — accept and validate context-driven rerun request, return expanded rerun response while keeping legacy `run_id`.
- `tests/test_rerun_endpoint.py` — add validator/error/accepted-context coverage.
- `tests/test_graph_headset.py` — add reusable seed scenario where array order differs from active head and a shared upstream node appears in multiple candidate runs.

## Task 0: Implementation Worktree and Baseline

**Files:**
- Read: `docs/superpowers/specs/2026-06-27-workbench-v1.6.2-node-operation-context-design.md`
- No source changes

- [ ] **Step 1: Create an isolated worktree**

Run from `/Users/jiayuanren/项目规划`:

```bash
git worktree add .worktrees/workbench-v1.6.2 -b codex/workbench-v1.6.2
cd .worktrees/workbench-v1.6.2
```

Expected: new branch `codex/workbench-v1.6.2` checked out at the current spec commit.

- [ ] **Step 2: Confirm baseline**

Run:

```bash
git status --short --branch
git log --oneline --max-count=3
```

Expected: clean worktree, latest commits include the v1.6.2 spec commits.

- [ ] **Step 3: Run focused current tests**

If `.venv` is missing, create it before running tests:

```bash
~/.local/bin/python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev,panel,ml,imbalanced,imputation]" jsonschema
```

Run:

```bash
cd frontend && npm test -- src/lineage/api/graphViewTypes.test.ts src/lineage/detail/RerunContext.test.tsx
cd ..
.venv/bin/python -m pytest tests/test_rerun_endpoint.py tests/test_graph_headset.py -q
```

Expected: all listed tests pass.

- [ ] **Step 4: Commit nothing**

Expected: no source changes in Task 0.

## Task 1: NodeOperationContext Types, Fixture, Resolver, and Debug Helper

**Files:**
- Create: `frontend/src/lineage/api/nodeOperationContext.ts`
- Create: `frontend/src/lineage/api/nodeOperationContext.test.ts`
- Modify: `frontend/src/lineage/api/graphViewTypes.ts`
- Modify: `frontend/src/lineage/api/graphViewTypes.test.ts`

- [ ] **Step 1: Write failing resolver tests**

Create `frontend/src/lineage/api/nodeOperationContext.test.ts` with tests for:

```ts
import { describe, expect, it } from "vitest";
import {
  explainResolveNodeOperationContext,
  makeOwnerResolutionSeedFixture,
  resolveNodeOperationContext,
} from "./nodeOperationContext";

describe("resolveNodeOperationContext", () => {
  it("prefers active head when it owns the shared node and is not runs[0]", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const result = resolveNodeOperationContext({
      forest: seed.forest,
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: seed.activeHeadRunId,
    });
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(result.context.ownership.owner_run_id).toBe(seed.activeHeadRunId);
    expect(result.context.ownership.owner_resolution).toBe("active_head_contains_node");
    expect(result.context.operation_target.op_node_id).toBe(seed.sharedOpNodeId);
  });

  it("returns ambiguous_owner_run instead of falling back to first candidate", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const result = resolveNodeOperationContext({
      forest: seed.forest,
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: "run_not_owner",
    });
    expect(result.ok).toBe(false);
    if (result.ok) throw new Error("expected failure");
    expect(result.reason).toBe("ambiguous_owner_run");
    expect(result.candidate_run_refs?.map((r) => r.run_id)).toEqual([
      "run_a",
      "run_c",
    ]);
  });

  it("allows run-scoped selected hint to override active head", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const result = resolveNodeOperationContext({
      forest: seed.forest,
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: seed.activeHeadRunId,
      selected_run_hint: "run_a",
      selected_run_hint_source: "run_scoped_surface",
    });
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(result.context.ownership.owner_run_id).toBe("run_a");
    expect(result.context.ownership.owner_resolution).toBe("selected_run_hint");
  });

  it("does not let an unscoped selected hint override active head", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const result = resolveNodeOperationContext({
      forest: seed.forest,
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: seed.activeHeadRunId,
      selected_run_hint: "run_a",
      selected_run_hint_source: "none",
    });
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(result.context.ownership.owner_run_id).toBe(seed.activeHeadRunId);
  });

  it("manual candidate selection resolves context without changing active head", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const result = resolveNodeOperationContext({
      forest: seed.forest,
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: "run_not_owner",
      selected_run_hint: "run_a",
      selected_run_hint_source: "manual_candidate_selection",
    });
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    expect(result.context.ownership.owner_resolution).toBe("manual_candidate_selection");
    expect(result.context.ownership.active_head_run_id).toBe("run_not_owner");
  });

  it("explain helper includes owner-resolution trace", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const trace = explainResolveNodeOperationContext({
      forest: seed.forest,
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: seed.activeHeadRunId,
    });
    expect(trace).toContain("selected forest node");
    expect(trace).toContain("candidate_run_refs");
    expect(trace).toContain("active_head_contains_node");
  });
});
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
cd frontend && npm test -- src/lineage/api/nodeOperationContext.test.ts
```

Expected: fail because `nodeOperationContext.ts` does not exist.

- [ ] **Step 3: Implement resolver types and fixture**

Create `frontend/src/lineage/api/nodeOperationContext.ts` with:

```ts
import type {
  ArtifactRef,
  EditableControl,
  ForestViewModel,
  HeadSetNode,
} from "./graphViewTypes";

export type OwnerResolution =
  | "active_head_contains_node"
  | "selected_run_hint"
  | "single_candidate"
  | "manual_candidate_selection";

export type SelectedRunHintSource =
  | "none"
  | "run_scoped_surface"
  | "manual_candidate_selection";

export type NodeState = "materialized" | "failed" | "stale";

export interface CandidateRunRef {
  run_id: string;
  op_node_id: string;
  node_hash: string;
  is_active_head: boolean;
  path_contains_node: boolean;
}

export interface ResolveNodeOperationContextInput {
  forest: ForestViewModel;
  selected_forest_node_key: string;
  active_head_run_id: string | null;
  selected_run_hint?: string | null;
  selected_run_hint_source?: SelectedRunHintSource;
}

export type ResolveNodeOperationContextResult =
  | { ok: true; context: NodeOperationContextV1 }
  | {
      ok: false;
      reason:
        | "unsupported_planned_node"
        | "missing_owner_run"
        | "ambiguous_owner_run"
        | "missing_op_node"
        | "missing_node_hash"
        | "context_stale";
      selected_node_key: string;
      active_head_run_id?: string | null;
      candidate_run_ids?: string[];
      candidate_run_refs?: CandidateRunRef[];
      node_hash?: string;
      detail?: string;
    };

export interface NodeOperationContextV1 {
  context_version: "node-operation-context/v1";
  context_kind: "executed_lineage_node";
  context_fingerprint: string;
  selection: {
    forest_node_key: string;
    node_hash: string;
    display_label: string;
    kind: string;
    stage: string;
  };
  ownership: {
    active_head_run_id: string | null;
    candidate_run_refs: CandidateRunRef[];
    candidate_run_ids: string[];
    shared_by_run_ids: string[];
    owner_run_id: string;
    owner_resolution: OwnerResolution;
    rerun_of?: string | null;
    parent_run_id?: string | null;
  };
  operation_target: {
    owner_run_id: string;
    op_node_id: string;
    node_hash: string;
    node_state: NodeState;
    editable_schema_source?: "run_inputs" | "capabilities";
  };
  lineage_context: {
    path_run_id: string;
    upstream_path: Array<{ key: string; label: string; kind: string; stage: string }>;
    downstream_hint?: { has_downstream: boolean; downstream_count?: number };
    active_head_path_contains_node: boolean;
  };
  node_payload: {
    decisions: HeadSetNode["decisions"];
    artifacts: Array<ArtifactRef & { ai_visibility: "metadata_only" }>;
    editable_schema: EditableControl[] | null;
    params: Record<string, unknown>;
    metrics?: Record<string, unknown>;
    execution_diagnostics?: Array<{ level: string; message: string }>;
  };
  capabilities: {
    can_rerun: boolean;
    can_ask_ai: boolean;
    can_compare: boolean;
    can_rollback_focus: boolean;
    can_edit_params: boolean;
    disabled_reasons: string[];
  };
  comparison_readiness: {
    can_compare: boolean;
    candidate_run_ids: string[];
    active_head_run_id: string | null;
    owner_run_id: string;
    parent_run_id?: string | null;
    shared_by_run_ids: string[];
  };
  context_diagnostics: { warnings: string[]; resolution_notes: string[] };
}
```

Then implement:

```ts
export function resolveNodeOperationContext(input: ResolveNodeOperationContextInput): ResolveNodeOperationContextResult {
  const source = input.selected_run_hint_source ?? "none";
  const node = input.forest.nodes.find((n) => n.nodeKey === input.selected_forest_node_key);
  if (!node) return { ok: false, reason: "missing_op_node", selected_node_key: input.selected_forest_node_key };
  if (!node.nodeHash) {
    return { ok: false, reason: "missing_node_hash", selected_node_key: node.nodeKey };
  }
  const candidate_run_refs = (node.runs ?? []).map((run_id) => ({
    run_id,
    op_node_id: node.opNodeId,
    node_hash: node.nodeHash!,
    is_active_head: run_id === input.active_head_run_id,
    path_contains_node: true,
  }));
  if (candidate_run_refs.length === 0) {
    return { ok: false, reason: "missing_owner_run", selected_node_key: node.nodeKey, node_hash: node.nodeHash };
  }

  const activeRef = candidate_run_refs.find((r) => r.run_id === input.active_head_run_id);
  const hintRef = input.selected_run_hint
    ? candidate_run_refs.find((r) => r.run_id === input.selected_run_hint && r.node_hash === node.nodeHash && r.op_node_id)
    : undefined;

  let owner = activeRef;
  let owner_resolution: OwnerResolution = "active_head_contains_node";
  if (hintRef && (source === "run_scoped_surface" || source === "manual_candidate_selection")) {
    owner = hintRef;
    owner_resolution = source === "manual_candidate_selection" ? "manual_candidate_selection" : "selected_run_hint";
  } else if (!owner && hintRef) {
    owner = hintRef;
    owner_resolution = "selected_run_hint";
  } else if (!owner && candidate_run_refs.length === 1) {
    owner = candidate_run_refs[0];
    owner_resolution = "single_candidate";
  }

  if (!owner) {
    return {
      ok: false,
      reason: "ambiguous_owner_run",
      selected_node_key: node.nodeKey,
      active_head_run_id: input.active_head_run_id,
      candidate_run_ids: candidate_run_refs.map((r) => r.run_id),
      candidate_run_refs,
      node_hash: node.nodeHash,
      detail: "Multiple candidate runs own this node; explicit owner selection is required.",
    };
  }

  const context_fingerprint = fingerprintParts([
    node.nodeKey,
    node.nodeHash,
    owner.run_id,
    owner.op_node_id,
    input.active_head_run_id ?? "",
    String(input.forest.schemaVersion),
  ]);

  return {
    ok: true,
    context: {
      context_version: "node-operation-context/v1",
      context_kind: "executed_lineage_node",
      context_fingerprint,
      selection: { forest_node_key: node.nodeKey, node_hash: node.nodeHash, display_label: node.title, kind: node.kind, stage: node.stage },
      ownership: {
        active_head_run_id: input.active_head_run_id,
        candidate_run_refs,
        candidate_run_ids: candidate_run_refs.map((r) => r.run_id),
        shared_by_run_ids: [...node.runs],
        owner_run_id: owner.run_id,
        owner_resolution,
      },
      operation_target: {
        owner_run_id: owner.run_id,
        op_node_id: owner.op_node_id,
        node_hash: owner.node_hash,
        node_state: node.status === "failed" ? "failed" : "materialized",
        editable_schema_source: node.editableSchemaSource,
      },
      lineage_context: {
        path_run_id: owner.run_id,
        upstream_path: buildUpstreamPath(input.forest, node.nodeKey),
        active_head_path_contains_node: Boolean(activeRef),
      },
      node_payload: {
        decisions: node.decisions,
        artifacts: (node.artifacts ?? []).map((a) => ({ ...a, ai_visibility: "metadata_only" as const })),
        editable_schema: node.editableSchema ?? null,
        params: {},
        metrics: node.stats,
      },
      capabilities: resolveCapabilities(node),
      comparison_readiness: {
        can_compare: candidate_run_refs.length > 1,
        candidate_run_ids: candidate_run_refs.map((r) => r.run_id),
        active_head_run_id: input.active_head_run_id,
        owner_run_id: owner.run_id,
        shared_by_run_ids: [...node.runs],
      },
      context_diagnostics: { warnings: [], resolution_notes: [`owner_resolution=${owner_resolution}`] },
    },
  };
}
```

Also add helper functions `fingerprintParts`, `buildUpstreamPath`, `resolveCapabilities`, `explainResolveNodeOperationContext`, and `makeOwnerResolutionSeedFixture` in the same file. The seed fixture must construct `run_a`, `run_c` where `run_c` is active but not first in the candidate array, and the shared node has the same `node_hash` in both runs.

- [ ] **Step 4: Keep legacy helper temporarily but mark unsafe for new code**

Modify `frontend/src/lineage/api/graphViewTypes.ts`: update the comment for `resolveOwnerRun` to say it is legacy and must not be used for new node operations. Do not remove it until migration tasks have replaced callers.

- [ ] **Step 5: Run resolver tests**

Run:

```bash
cd frontend && npm test -- src/lineage/api/nodeOperationContext.test.ts src/lineage/api/graphViewTypes.test.ts
```

Expected: new tests pass; old `resolveOwnerRun` fallback tests may be deleted or rewritten to assert it is legacy-only.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lineage/api/nodeOperationContext.ts frontend/src/lineage/api/nodeOperationContext.test.ts frontend/src/lineage/api/graphViewTypes.ts frontend/src/lineage/api/graphViewTypes.test.ts
git commit -m "feat(lineage): add node operation context resolver"
```

## Task 2: Context Provider, Failure UI, Header, Path, and Action Consumers

**Files:**
- Create: `frontend/src/lineage/detail/NodeOperationContextProvider.tsx`
- Create: `frontend/src/lineage/detail/ResolverFailureState.tsx`
- Modify: `frontend/src/lineage/detail/DetailDrawer.tsx`
- Modify: `frontend/src/lineage/header/DetailHeader.tsx`
- Modify: `frontend/src/lineage/header/DetailHeader.test.tsx`
- Modify: `frontend/src/lineage/graph/NodeActionMenu.tsx`
- Modify: `frontend/src/lineage/graph/NodeActionMenu.test.tsx`
- Modify: `frontend/src/lineage/detail/sections/LineageChainSection.tsx`
- Modify: `frontend/src/lineage/detail/sections/LineageChainSection.test.tsx`

- [ ] **Step 1: Write provider and failure UI tests**

Add test cases to `DetailHeader.test.tsx`:

```ts
import { ForestContext } from "../../workbench/ForestContext";
import { makeOwnerResolutionSeedFixture } from "../api/nodeOperationContext";
import { DetailDrawer } from "../detail/DetailDrawer";
import { LineageContext } from "../LineageContext";

it("renders owner run from NodeOperationContext when available", () => {
  const seed = makeOwnerResolutionSeedFixture();
  const selected = seed.forest.nodes.find((n) => n.nodeKey === seed.sharedNodeKey)!;
  render(
    <ForestContext.Provider value={{ forest: seed.forest, activeRunId: seed.activeHeadRunId, setActiveRunId: vi.fn() }}>
      <LineageContext.Provider value={{ model: seed.graphModel, selectedKey: selected.nodeKey, select: vi.fn() }}>
        <DetailDrawer node={selected} onClose={vi.fn()} onShowJson={vi.fn()} />
      </LineageContext.Provider>
    </ForestContext.Provider>,
  );
  expect(screen.getByText(/run_c/)).toBeInTheDocument();
  expect(screen.queryByText(/owner.*run_a/i)).not.toBeInTheDocument();
});

it("shows resolver failure instead of fabricated owner for ambiguous context", () => {
  const seed = makeOwnerResolutionSeedFixture();
  const selected = seed.forest.nodes.find((n) => n.nodeKey === seed.sharedNodeKey)!;
  render(
    <ForestContext.Provider value={{ forest: seed.forest, activeRunId: "run_x", setActiveRunId: vi.fn() }}>
      <LineageContext.Provider value={{ model: seed.graphModel, selectedKey: selected.nodeKey, select: vi.fn() }}>
        <DetailDrawer node={selected} onClose={vi.fn()} onShowJson={vi.fn()} />
      </LineageContext.Provider>
    </ForestContext.Provider>,
  );
  expect(screen.getByTestId("resolver-failure-state")).toHaveTextContent("ambiguous_owner_run");
  expect(screen.queryByRole("button", { name: /rerun/i })).toBeDisabled();
});
```

If the existing `LineageContext` type requires additional functions, add no-op `vi.fn()` values for those required fields in this test helper; do not skip the owner/failure assertions.

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
cd frontend && npm test -- src/lineage/header/DetailHeader.test.tsx src/lineage/graph/NodeActionMenu.test.tsx
```

Expected: fail because provider/failure UI is not implemented.

- [ ] **Step 3: Add context provider**

Create `NodeOperationContextProvider.tsx`:

```tsx
import { createContext, useContext, useMemo } from "react";
import type { ReactNode } from "react";
import { useForest } from "../../workbench/ForestContext";
import type { GraphViewNode, HeadSetNode } from "../api/graphViewTypes";
import {
  resolveNodeOperationContext,
  type ResolveNodeOperationContextResult,
} from "../api/nodeOperationContext";

const Context = createContext<ResolveNodeOperationContextResult | null>(null);

export function NodeOperationContextProvider({ node, children }: { node: GraphViewNode; children: ReactNode }) {
  const forest = useForest();
  const value = useMemo<ResolveNodeOperationContextResult | null>(() => {
    if (!forest || !("runs" in node)) return null;
    return resolveNodeOperationContext({
      forest: forest.forest,
      selected_forest_node_key: (node as HeadSetNode).nodeKey,
      active_head_run_id: forest.activeRunId,
    });
  }, [forest, node]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useResolvedNodeOperationContext(): ResolveNodeOperationContextResult | null {
  return useContext(Context);
}
```

Create `ResolverFailureState.tsx`:

```tsx
import type { ResolveNodeOperationContextResult } from "../api/nodeOperationContext";

export function ResolverFailureState({ result }: { result: Exclude<ResolveNodeOperationContextResult, { ok: true }> }) {
  return (
    <div data-testid="resolver-failure-state" role="status" style={{ fontSize: 12, color: "var(--label-secondary)" }}>
      <strong>Node context needs clarification</strong>
      <div>{result.reason}</div>
      {result.candidate_run_refs && result.candidate_run_refs.length > 0 && (
        <div>Candidate runs: {result.candidate_run_refs.map((r) => r.run_id).join(", ")}</div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Wrap drawer content**

Modify `DetailDrawer.tsx` to wrap header and sections:

```tsx
<NodeOperationContextProvider node={resolved}>
  <DetailHeader node={resolved} onClose={onClose} onShowJson={onShowJson} />
  {visibleSections.map((s) => (
    <s.Component key={s.id} node={resolved} />
  ))}
</NodeOperationContextProvider>
```

- [ ] **Step 5: Migrate consumers**

In `DetailHeader.tsx`, call `useResolvedNodeOperationContext()`. If `result?.ok`, display `context.ownership.owner_run_id`, `context.ownership.owner_resolution`, and warnings from `context.context_diagnostics`. If `result && !result.ok`, render `ResolverFailureState`.

In `NodeActionMenu.tsx`, read `context.capabilities` when available. For failure state, disable Ask AI, rerun, edit, and compare. If `reason === "ambiguous_owner_run"`, render a disabled entry labelled `Choose operation owner`.

In `LineageChainSection.tsx`, when context exists, display the owner-run path from `context.lineage_context.upstream_path`. When context fails, do not render an owner-run-specific path.

- [ ] **Step 6: Run focused frontend tests**

Run:

```bash
cd frontend && npm test -- \
  src/lineage/header/DetailHeader.test.tsx \
  src/lineage/graph/NodeActionMenu.test.tsx \
  src/lineage/detail/sections/LineageChainSection.test.tsx
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lineage/detail/NodeOperationContextProvider.tsx frontend/src/lineage/detail/ResolverFailureState.tsx frontend/src/lineage/detail/DetailDrawer.tsx frontend/src/lineage/header/DetailHeader.tsx frontend/src/lineage/header/DetailHeader.test.tsx frontend/src/lineage/graph/NodeActionMenu.tsx frontend/src/lineage/graph/NodeActionMenu.test.tsx frontend/src/lineage/detail/sections/LineageChainSection.tsx frontend/src/lineage/detail/sections/LineageChainSection.test.tsx
git commit -m "feat(lineage): migrate detail consumers to node context"
```

## Task 3: Backend Node Write Validator and Rerun Request Contract

**Files:**
- Create: `backend/workbench/lineage/node_write_validation.py`
- Create: `tests/test_node_write_validation.py`
- Modify: `backend/workbench/api.py`
- Modify: `tests/test_rerun_endpoint.py`

- [ ] **Step 1: Write backend validator tests**

Create `tests/test_node_write_validation.py`:

```python
from pathlib import Path

import pytest

from workbench.lineage.node_write_validation import (
    NodeWriteOperationRequestV1,
    validate_rerun_operation_target,
)

def test_rejects_unsupported_context_version(tmp_path: Path):
    req = NodeWriteOperationRequestV1(
        request_id="req_1",
        operation="rerun",
        context_version="node-operation-context/v9",
        context_fingerprint="bad",
        owner_run_id="run_a",
        op_node_id="model:ols_1",
        node_hash="hash_a",
        forest_node_key="hash_a",
        owner_resolution="active_head_contains_node",
        active_head_run_id="run_a",
    )
    with pytest.raises(ValueError, match="unsupported_context_version"):
        validate_rerun_operation_target(tmp_path, req)
```

Add additional tests in the same file for:

- missing owner run raises `invalid_operation_target`
- op node not in owner run raises `invalid_operation_target`
- matching legacy graph node passes when `node_hash` is unavailable only for legacy request path
- `active_head_run_id` never overrides `owner_run_id`

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_node_write_validation.py -q
```

Expected: fail because module does not exist.

- [ ] **Step 3: Implement validator module**

Create `backend/workbench/lineage/node_write_validation.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from workbench.graph_store import GraphStore

SUPPORTED_CONTEXT_VERSION = "node-operation-context/v1"

class NodeWriteOperationRequestV1(BaseModel):
    request_id: str
    operation: Literal["rerun"]
    context_version: str
    context_fingerprint: str
    owner_run_id: str
    op_node_id: str
    node_hash: str
    forest_node_key: str
    owner_resolution: str
    active_head_run_id: str | None = None

class AcceptedContext(BaseModel):
    context_version: Literal["node-operation-context/v1"]
    context_fingerprint: str
    owner_run_id: str
    op_node_id: str
    node_hash: str
    validated_at: str

def validate_rerun_operation_target(runs_root: Path, request: NodeWriteOperationRequestV1) -> None:
    if request.context_version != SUPPORTED_CONTEXT_VERSION:
        raise ValueError("unsupported_context_version")
    run_root = runs_root / request.owner_run_id
    if not run_root.exists():
        raise ValueError("invalid_operation_target: owner_run_id")
    graph = GraphStore(runs_root=runs_root).read(request.owner_run_id)
    node = graph.nodes.get(request.op_node_id)
    if node is None:
        raise ValueError("invalid_operation_target: op_node_id")
    raw_hash = getattr(node, "node_hash", None)
    if raw_hash is not None and raw_hash != request.node_hash:
        raise ValueError("context_mismatch: node_hash")
```

Read the persisted node hash from `run_root / "node_index.json"` using `body.op_node_id` as the key. If the file exists and contains an entry for `op_node_id`, compare `entry["node_hash"]` to the submitted `node_hash`; if it differs, raise `context_mismatch: node_hash`. Legacy requests with no `context_version` keep the current graph-only validation path.

- [ ] **Step 4: Extend `api.py` request and response**

Modify `RerunRequest` in `backend/workbench/api.py`:

```python
class RerunRequest(BaseModel):
    from_node: str | None = None
    op_overrides: dict = {}
    rerun_reason: str = "manual_override"

    request_id: str | None = None
    operation: str | None = None
    context_version: str | None = None
    context_fingerprint: str | None = None
    owner_run_id: str | None = None
    op_node_id: str | None = None
    node_hash: str | None = None
    forest_node_key: str | None = None
    owner_resolution: str | None = None
    active_head_run_id: str | None = None
```

At the top of `rerun_endpoint`, derive:

```python
effective_run_id = body.owner_run_id or run_id
effective_from_node = body.op_node_id or body.from_node
```

If `body.context_version` is present, build `NodeWriteOperationRequestV1` and call `validate_rerun_operation_target(runs_root, request)`. On validation error, return:

- `400` for `unsupported_context_version` and `invalid_operation_target`
- `409` for `context_mismatch` and `context_stale`
- `403` for `operation_not_allowed`

Use `effective_run_id` everywhere rerun currently uses `run_id`, and use `effective_from_node` everywhere rerun currently uses `body.from_node`.

- [ ] **Step 5: Return expanded response while preserving `run_id`**

After `_submit_run`, return:

```python
return {
    "run_id": child_id,
    "new_run_id": child_id,
    "new_active_head_id": child_id,
    "focus": None,
    "rerun_from": {
        "owner_run_id": effective_run_id,
        "op_node_id": effective_from_node,
        "node_hash": body.node_hash,
        "forest_node_key": body.forest_node_key,
    },
    "accepted_context": accepted_context_or_none,
}
```

Keep `run_id` because existing frontend/backend tests consume it.

- [ ] **Step 6: Run backend tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_node_write_validation.py tests/test_rerun_endpoint.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add backend/workbench/lineage/node_write_validation.py backend/workbench/api.py tests/test_node_write_validation.py tests/test_rerun_endpoint.py
git commit -m "feat(api): validate context-driven rerun targets"
```

## Task 4: Frontend Rerun Request, Active Head, Focus, and Source Navigation

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/api.test.ts`
- Modify: `frontend/src/lineage/detail/RerunContext.tsx`
- Modify: `frontend/src/lineage/detail/RerunContext.test.tsx`
- Modify: `frontend/src/lineage/detail/sections/OperationSection.tsx`
- Modify: `frontend/src/lineage/detail/sections/OperationSection.test.tsx`
- Modify: `frontend/src/workbench/WorkbenchRouteContainer.tsx`
- Modify: `frontend/src/workbench/WorkbenchRouteContainer.test.tsx`

- [ ] **Step 1: Write failing frontend rerun tests**

Update `RerunContext.test.tsx` to assert `rerunFromNode` receives `owner_run_id`, `op_node_id`, `node_hash`, `context_fingerprint`, and `request_id` from `NodeOperationContextV1`, not `candidateRuns`.

Add a test to `WorkbenchRouteContainer.test.tsx`:

```ts
it("switches active head and selects focus after context-driven rerun success", async () => {
  // Mock rerun response with new_active_head_id="run_child" and focus.forest_node_key="hash_child".
  // Click operation submit.
  // Assert forest head button for run_child has aria-pressed=true.
  // Assert selected drawer/header is for hash_child.
});
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
cd frontend && npm test -- \
  src/lineage/detail/RerunContext.test.tsx \
  src/lineage/detail/sections/OperationSection.test.tsx \
  src/workbench/WorkbenchRouteContainer.test.tsx
```

Expected: fail because current rerun path posts legacy args.

- [ ] **Step 3: Add frontend API types**

Modify `frontend/src/api.ts`:

```ts
export interface NodeWriteOperationRequestV1 {
  request_id: string;
  operation: "rerun";
  context_version: "node-operation-context/v1";
  context_fingerprint: string;
  owner_run_id: string;
  op_node_id: string;
  node_hash: string;
  forest_node_key: string;
  owner_resolution: string;
  active_head_run_id: string | null;
  op_overrides: Record<string, unknown>;
  rerun_reason?: string;
}

export interface RerunResponseV1 {
  run_id: string;
  new_run_id: string;
  new_active_head_id: string;
  focus: { forest_node_key: string; op_node_id: string; node_hash: string } | null;
  rerun_from: { owner_run_id: string; op_node_id: string; node_hash: string | null; forest_node_key: string | null };
  accepted_context?: {
    context_version: "node-operation-context/v1";
    context_fingerprint: string;
    owner_run_id: string;
    op_node_id: string;
    node_hash: string;
    validated_at: string;
  };
}
```

Change `rerunFromNode` to accept either legacy args or `NodeWriteOperationRequestV1`, but make context-driven callers use:

```ts
body: JSON.stringify({
  ...args,
  from_node: args.op_node_id,
  rerun_reason: args.rerun_reason ?? "manual_override",
})
```

- [ ] **Step 4: Update `RerunContext`**

Replace `candidateRuns` resolution with a context-driven shape:

```ts
export interface RerunArgs {
  context: NodeOperationContextV1;
  opOverrides: Record<string, unknown>;
  rerunReason?: string;
}
```

Generate `request_id` with:

```ts
const requestId = `rerun_${Date.now()}_${Math.random().toString(36).slice(2)}`;
```

Submit to `rerunFromNode(projectRoot, args.context.operation_target.owner_run_id, request)`.

- [ ] **Step 5: Update `OperationSection`**

Read `useResolvedNodeOperationContext()`. If no successful context, render read-only controls plus `ResolverFailureState` for failed context. On submit:

```ts
await rerun.submitRerun({ context: resolved.context, opOverrides: overrides });
```

- [ ] **Step 6: Update rerun success handling**

In `WorkbenchRouteContainer.tsx`, change `RerunProvider onRerun` from refetch-only to:

```tsx
const [pendingFocusKey, setPendingFocusKey] = useState<string | null>(null);

onRerun={(response) => {
  setActiveRunId(response.new_active_head_id ?? response.run_id);
  setPendingFocusKey(response.focus?.forest_node_key ?? null);
  void refetch();
}}
```

Pass `pendingFocusKey` and `onPendingFocusConsumed` into `WorkbenchShell`. In `WorkbenchShell`, add:

```tsx
useEffect(() => {
  if (!pendingFocusKey) return;
  if (!model.nodes.some((n) => n.nodeKey === pendingFocusKey)) return;
  select(pendingFocusKey);
  onPendingFocusConsumed();
}, [model.nodes, onPendingFocusConsumed, pendingFocusKey, select]);
```

For `focus: null`, set active head and refetch, but leave `pendingFocusKey` null and render a degraded toast/status message in the operation section.

- [ ] **Step 7: Run focused tests**

Run:

```bash
cd frontend && npm test -- \
  src/api.test.ts \
  src/lineage/detail/RerunContext.test.tsx \
  src/lineage/detail/sections/OperationSection.test.tsx \
  src/workbench/WorkbenchRouteContainer.test.tsx
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api.ts frontend/src/api.test.ts frontend/src/lineage/detail/RerunContext.tsx frontend/src/lineage/detail/RerunContext.test.tsx frontend/src/lineage/detail/sections/OperationSection.tsx frontend/src/lineage/detail/sections/OperationSection.test.tsx frontend/src/workbench/WorkbenchRouteContainer.tsx frontend/src/workbench/WorkbenchRouteContainer.test.tsx
git commit -m "feat(lineage): submit rerun through node operation context"
```

## Task 5: AskAIContextPacket Generator and Debug Preview

**Files:**
- Create: `frontend/src/lineage/detail/sections/askAiContextPacket.ts`
- Create: `frontend/src/lineage/detail/sections/askAiContextPacket.test.ts`
- Modify: `frontend/src/lineage/detail/sections/AskAISection.tsx`
- Modify: `frontend/src/lineage/detail/sections/AskAISection.test.tsx`

- [ ] **Step 1: Write packet tests**

Create `askAiContextPacket.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { makeOwnerResolutionSeedFixture, resolveNodeOperationContext } from "../../api/nodeOperationContext";
import { buildAskAIContextPacket } from "./askAiContextPacket";

describe("buildAskAIContextPacket", () => {
  it("builds packet only from successful context", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const result = resolveNodeOperationContext({
      forest: seed.forest,
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: seed.activeHeadRunId,
    });
    expect(result.ok).toBe(true);
    if (!result.ok) throw new Error(result.reason);
    const packet = buildAskAIContextPacket(result.context);
    expect(packet.packet_scope.scope_type).toBe("selected_node");
    expect(packet.context_visibility_notice.full_datasets_included).toBe(false);
    expect(packet.response_guardrails.executable_actions_allowed).toBe(false);
  });

  it("marks all generated artifact entries with ai_visibility", () => {
    const seed = makeOwnerResolutionSeedFixture();
    const result = resolveNodeOperationContext({
      forest: seed.forest,
      selected_forest_node_key: seed.sharedNodeKey,
      active_head_run_id: seed.activeHeadRunId,
    });
    if (!result.ok) throw new Error(result.reason);
    const packet = buildAskAIContextPacket(result.context);
    expect(packet.artifacts.every((a) => a.ai_visibility)).toBe(true);
  });
});
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
cd frontend && npm test -- src/lineage/detail/sections/askAiContextPacket.test.ts
```

Expected: fail because packet module does not exist.

- [ ] **Step 3: Implement packet generator**

Create `askAiContextPacket.ts`:

```ts
import type { NodeOperationContextV1 } from "../../api/nodeOperationContext";

export function buildAskAIContextPacket(context: NodeOperationContextV1) {
  return {
    packet_version: "ask-ai-context/v1" as const,
    source_context_version: context.context_version,
    context_fingerprint: context.context_fingerprint,
    packet_scope: {
      scope_type: "selected_node" as const,
      includes_upstream_path: true,
      includes_downstream_nodes: false,
      includes_full_run: false,
    },
    selection: context.selection,
    ownership: {
      active_head_run_id: context.ownership.active_head_run_id,
      owner_run_id: context.ownership.owner_run_id,
      owner_resolution: context.ownership.owner_resolution,
      shared_by_run_ids: context.ownership.shared_by_run_ids,
      candidate_run_ids: context.ownership.candidate_run_ids,
    },
    operation_target: context.operation_target,
    lineage_summary: context.lineage_context,
    node_summary: {
      params: context.node_payload.params,
      decisions: context.node_payload.decisions,
      editable_schema_summary: context.node_payload.editable_schema,
      metrics: context.node_payload.metrics,
      execution_diagnostics: context.node_payload.execution_diagnostics,
    },
    artifacts: context.node_payload.artifacts,
    context_diagnostics: context.context_diagnostics,
    context_visibility_notice: {
      artifact_policy: "metadata_and_safe_preview_only" as const,
      full_datasets_included: false as const,
      full_reports_included: false as const,
      binary_artifacts_included: false as const,
    },
    allowed_response_modes: ["explain", "summarize", "identify_risks", "suggest_questions"] as const,
    response_guardrails: {
      advisory_text_only: true as const,
      executable_actions_allowed: false as const,
      graph_mutations_allowed: false as const,
      backend_payloads_allowed: false as const,
      file_reads_allowed: false as const,
      must_disclose_visibility_limits: true as const,
    },
  };
}
```

- [ ] **Step 4: Add debug preview in `AskAISection`**

Use `useResolvedNodeOperationContext()`. If context fails, show `ResolverFailureState` and do not build packet. If context succeeds, render a `<details>` with:

```tsx
<summary>Context preview</summary>
<pre data-testid="ask-ai-context-preview">{JSON.stringify(packet, null, 2)}</pre>
```

Keep the Ask AI action disabled until Task 6, but label it `Ask AI about this node`.

- [ ] **Step 5: Run tests**

Run:

```bash
cd frontend && npm test -- src/lineage/detail/sections/askAiContextPacket.test.ts src/lineage/detail/sections/AskAISection.test.tsx
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lineage/detail/sections/askAiContextPacket.ts frontend/src/lineage/detail/sections/askAiContextPacket.test.ts frontend/src/lineage/detail/sections/AskAISection.tsx frontend/src/lineage/detail/sections/AskAISection.test.tsx
git commit -m "feat(ai): generate audited ask-ai context packet"
```

## Task 6: Read-only Ask AI Service Boundary and Advisory UI

**Files:**
- Create: `frontend/src/lineage/detail/sections/askAiClient.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/api.test.ts`
- Modify: `frontend/src/lineage/detail/sections/AskAISection.tsx`
- Modify: `frontend/src/lineage/detail/sections/AskAISection.test.tsx`

This task creates the frontend read-only service boundary to `/llm/chat`; it does not add AI graph actions or backend operation endpoints. If `/llm/chat` returns 404/501 in local development, the Ask AI panel must show the error as text and keep the context preview visible.

- [ ] **Step 1: Write Ask AI UI guardrail tests**

In `AskAISection.test.tsx`, add:

```ts
it("renders model JSON-looking response as text, not as an action", async () => {
  // Mock askAiForNode to resolve { text: '{"operation":"rerun","owner_run_id":"run_a"}' }.
  // Click Ask AI.
  // Assert the JSON appears in text content.
  // Assert no button or element with data-testid="ask-ai-executable-action" exists.
});

it("does not call Ask AI when resolver fails", async () => {
  // Mount with ambiguous owner context.
  // Click or inspect section.
  // Assert askAiForNode mock is not called and ResolverFailureState is visible.
});
```

- [ ] **Step 2: Implement frontend client**

Create `askAiClient.ts`:

```ts
import type { buildAskAIContextPacket } from "./askAiContextPacket";

export interface AskAIResponse {
  text: string;
}

export async function askAiForNode(packet: ReturnType<typeof buildAskAIContextPacket>, question: string): Promise<AskAIResponse> {
  const response = await fetch("/llm/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mode: "workbench_node_context_v1",
      question,
      packet,
      response_guardrails: packet.response_guardrails,
    }),
  });
  if (!response.ok) throw new Error(`Ask AI failed (${response.status})`);
  return response.json() as Promise<AskAIResponse>;
}
```

If `/llm/chat` is not available in local development, the UI must show an error message and keep the context preview available. It must not turn model output into actions.

- [ ] **Step 3: Implement advisory UI**

In `AskAISection.tsx`, add a text input with default question `Explain this node and its risks.`. On submit, call `askAiForNode(packet, question)` and render returned `text` in:

```tsx
<div data-testid="ask-ai-answer" role="status">{answer}</div>
```

Do not parse returned JSON. Do not render executable buttons from returned content.

- [ ] **Step 4: Run tests**

Run:

```bash
cd frontend && npm test -- src/lineage/detail/sections/AskAISection.test.tsx
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lineage/detail/sections/askAiClient.ts frontend/src/lineage/detail/sections/AskAISection.tsx frontend/src/lineage/detail/sections/AskAISection.test.tsx frontend/src/api.ts frontend/src/api.test.ts
git commit -m "feat(ai): add read-only ask ai advisory panel"
```

## Task 7: Cross-feature Regression Matrix and Release Gates

**Files:**
- Modify: `frontend/src/lineage/api/nodeOperationContext.test.ts`
- Modify: `frontend/src/lineage/detail/RerunContext.test.tsx`
- Modify: `frontend/src/workbench/WorkbenchRouteContainer.test.tsx`
- Modify: `tests/test_rerun_endpoint.py`
- Modify: `tests/test_graph_headset.py`

- [ ] **Step 1: Add reusable seed fixture coverage**

In frontend resolver tests, keep `makeOwnerResolutionSeedFixture()` as the canonical fixture for:

```text
run array order != active head
shared upstream node
active head contains selected node
another candidate run also contains the same node_hash
```

In backend `tests/test_graph_headset.py`, add a helper that creates parent + child, fetches `view=headset`, and asserts the shared upstream node has both parent and child in `runs`.

- [ ] **Step 2: Add backend no-runs[0] regression**

In `tests/test_rerun_endpoint.py`, add a context-driven rerun test where URL path run is not the owner run and assert child `run_inputs.json["rerun_of"]` equals `owner_run_id` from the body.

- [ ] **Step 3: Add stale/mismatch tests**

In `tests/test_node_write_validation.py`, add:

```python
def test_context_mismatch_rejects_wrong_node_hash(tmp_path: Path):
    runs_root = tmp_path / "runs"
    run_root = runs_root / "run_a"
    run_root.mkdir(parents=True)
    (run_root / "node_index.json").write_text(
        '{"model:ols_1": {"node_hash": "real_hash", "producing_stage": "estimation"}}'
    )
    request = NodeWriteOperationRequestV1(
        request_id="req_bad_hash",
        operation="rerun",
        context_version="node-operation-context/v1",
        context_fingerprint="fp",
        owner_run_id="run_a",
        op_node_id="model:ols_1",
        node_hash="wrong_hash",
        forest_node_key="wrong_hash",
        owner_resolution="active_head_contains_node",
        active_head_run_id="run_a",
    )
    with pytest.raises(ValueError, match="context_mismatch"):
        validate_rerun_operation_target(runs_root, request)
```

- [ ] **Step 4: Add Ask AI visibility tests**

In `askAiContextPacket.test.ts`, add assertions that dataset/report/binary artifacts are not included as full content and that redacted/truncated previews carry explicit flags.

- [ ] **Step 5: Run focused matrix**

Run:

```bash
cd frontend && npm test -- \
  src/lineage/api/nodeOperationContext.test.ts \
  src/lineage/detail/RerunContext.test.tsx \
  src/workbench/WorkbenchRouteContainer.test.tsx \
  src/lineage/detail/sections/askAiContextPacket.test.ts \
  src/lineage/detail/sections/AskAISection.test.tsx
cd ..
.venv/bin/python -m pytest tests/test_node_write_validation.py tests/test_rerun_endpoint.py tests/test_graph_headset.py -q
```

Expected: all pass.

- [ ] **Step 6: Run typecheck and full gate**

Run:

```bash
cd frontend && npm run typecheck
cd ..
LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh
```

Expected: typecheck passes and gate reports success. Existing lineage forest golden outputs have no drift unless intentionally updated and reviewed.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lineage/api/nodeOperationContext.test.ts frontend/src/lineage/detail/RerunContext.test.tsx frontend/src/workbench/WorkbenchRouteContainer.test.tsx frontend/src/lineage/detail/sections/askAiContextPacket.test.ts frontend/src/lineage/detail/sections/AskAISection.test.tsx tests/test_node_write_validation.py tests/test_rerun_endpoint.py tests/test_graph_headset.py
git commit -m "test(lineage): lock node context rerun and ask ai regressions"
```

## Self-review Checklist

- Every node operation consumer uses `NodeOperationContextV1` or explicitly degrades when no context exists.
- No new code calls `resolveOwnerRun` for rerun or owner attribution.
- Ambiguous owner returns failure and never falls back to first candidate.
- `selected_run_hint_source` is required for non-active-head override.
- Backend rerun source is `owner_run_id + op_node_id`, not `active_head_run_id`.
- Rerun success moves active head to the child run; request failure before child creation does not.
- Ask AI packet is generated only from `ok: true` context.
- Ask AI UI renders all responses as advisory text only.
- Full datasets, full reports, binary artifacts, and AI-initiated file reads are absent from packet generation.
- `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh` passes before handoff.
