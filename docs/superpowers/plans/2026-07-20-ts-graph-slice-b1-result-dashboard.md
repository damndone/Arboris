# Time-Series Graph-Native — Slice B1: Result Dashboard in the Graph Drawer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the ARMA-GARCH result inside the graph node drawer as a single scannable dashboard (no 9-tab pill strip), so the result lives in the graph instead of the deprecated Overview page.

**Architecture:** Extract the existing `ts.*` artifact loader out of `runResult.tsx` into a reusable `useArmaGarchArtifacts(projectRoot, runId)` hook. Add an `ArmaGarchDashboard` component that renders the same data as stacked sections (verdict header + acceptance chips + stat tiles + candidate tables + summary blocks) instead of tab-switched panels. Mount it in the drawer via a new `sectionRegistry` entry that resolves `projectRoot` from `ProjectRootContext` and `runId` from the node's owner run.

**Tech Stack:** React + TypeScript (Vitest/RTL), existing `fetchRunArtifacts` / `fetchArtifactJson`, `ProjectRootContext`, lineage `sectionRegistry`.

**Scope guard:** Inline SVG chart rendering is Slice B2. Removing the card from `runResult.tsx` and suppressing the generic Table is Slice B3. Do not change backend or artifact schemas.

---

### Task 1: Extract `useArmaGarchArtifacts` hook

**Files:**
- Create: `frontend/src/runResult/useArmaGarchArtifacts.ts`
- Test: `frontend/src/runResult/useArmaGarchArtifacts.test.tsx`

- [ ] **Step 1: Write the failing test** — render the hook with mocked `fetchRunArtifacts`/`fetchArtifactJson`; assert it returns `undefined` when `ts.report` is absent, and a populated `ArmaGarchArtifacts` (report/contract/meanCandidates/…) when present, mapping each `ts.*` id to its field and unwrapping `envelope.payload`.
- [ ] **Step 2: Run** `cd frontend && npx vitest run src/runResult/useArmaGarchArtifacts.test.tsx` → FAIL (module missing).
- [ ] **Step 3: Implement** the hook by moving the `useEffect` block currently at `runResult.tsx:266-300` verbatim (artifact-id map, `Promise.all`, `cancelled` guard, `envelope?.payload` unwrap) behind `useArmaGarchArtifacts(projectRoot, runId)`, fetching the artifact list itself via `fetchRunArtifacts`.
- [ ] **Step 4: Run** the test → PASS.
- [ ] **Step 5: Commit** `feat(ts-graph): extract useArmaGarchArtifacts hook`.

### Task 2: `ArmaGarchDashboard` one-view component

**Files:**
- Create: `frontend/src/runResult/ArmaGarchDashboard.tsx`
- Test: `frontend/src/runResult/ArmaGarchDashboard.test.tsx`

- [ ] **Step 1: Write the failing test** — given a fixture `ArmaGarchArtifacts`, assert that **all** sections are present simultaneously (no `role="tab"` elements): verdict headline, the six acceptance chips, stat tiles (persistence / half-life / coverage / validation n), both candidate tables, forecast-validation and reproducibility blocks. Assert the honest-labelling invariants: no string `"VaR"`, no `"composite"` IC, and the plug-in interval disclaimer text is rendered.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** by restructuring `ArmaGarchResultCard`'s existing per-tab JSX into stacked `<section>`s, reusing its `CandidateTable`, `object`/`rows`/`numberText`/`text` helpers (export them from the card or move them to a shared `armaGarchView.ts`). Keep `ArmaGarchArtifacts` as the prop type.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(ts-graph): one-view ARMA-GARCH dashboard`.

### Task 3: Mount the dashboard in the node drawer

**Files:**
- Create: `frontend/src/lineage/detail/sections/ArmaGarchResultSection.tsx`
- Test: `frontend/src/lineage/detail/sections/ArmaGarchResultSection.test.tsx`
- Modify: `frontend/src/workbench/registry/sectionRegistry.ts`
- Modify: `frontend/src/lineage/detail/sections/sectionRegistry.test.ts` (id + order snapshots)

- [ ] **Step 1: Write the failing test** — the section resolves `projectRoot` via `useProjectRootOptional()` (mocked) and `runId` from the node's owner run, calls `useArmaGarchArtifacts` (mocked), and renders `ArmaGarchDashboard`; renders nothing when `projectRoot` or artifacts are absent. Add registry tests: `armaGarchResult` renders for `opType === "time_series.arma_garch"` model nodes and not for OLS.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the section and register it at **order 32** (immediately after `armaGarchOperation` at 31), keyed by the same `isArmaGarch` helper; update the two registry snapshot assertions (id list gains `"armaGarchResult"`, order list gains `32`).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(ts-graph): render ARMA-GARCH result dashboard in the node drawer`.

### Task 4: Gate

- [ ] **Step 1:** `cd frontend && npm run typecheck` → clean.
- [ ] **Step 2:** `cd frontend && npm test -- --run` → all pass.
- [ ] **Step 3:** Live check: open the graph, click the ARMA-GARCH model node, confirm the dashboard renders all sections at once with no pill strip.
- [ ] **Step 4:** Commit any incidental fixes (scoped paths only, never `git add -A`).

---

## Self-review

- **Spec coverage:** Implements spec §6 (one-view dashboard replacing the 9 pills, rendered in the drawer). §9 charts → B2; §10–11 Table/Overview → B3.
- **Placeholder scan:** Task steps reference concrete existing symbols (`fetchRunArtifacts`, `fetchArtifactJson`, `ArmaGarchArtifacts`, `CandidateTable`, `useProjectRootOptional`, `isArmaGarch`) and the exact source range being moved (`runResult.tsx:266-300`).
- **Type consistency:** `ArmaGarchArtifacts` is the shared prop/return type across Tasks 1–3; `isArmaGarch` and the registry entry shape match Slice A.
- **Risk:** `runId` resolution in the drawer (owner run vs node runs[0]) is the main integration unknown — Task 3's test pins it explicitly.
