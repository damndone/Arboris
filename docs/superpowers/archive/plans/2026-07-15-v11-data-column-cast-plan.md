# V11 Data Column Cast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the first immutable, preview-first `data.column.cast` typed operation on the existing GraphStore, artifact registry, and single-worker operation lifecycle.

**Architecture:** A small backend data-operation module owns the frozen cast spec, deterministic preview, source/artifact resolution, and lifecycle handler. HTTP routes expose only typed fields and revalidate the preview fingerprint before confirmation. A focused frontend section consumes the same preview/confirm contract; no natural-language Agent proposal is enabled until this manual path is reliable.

**Tech Stack:** Python dataclasses, pandas, FastAPI/Pydantic, existing GraphStore and artifact registry, pytest, React/TypeScript, Vitest.

---

### Task 1: Make single-worker control-plane mode explicit

**Files:**
- Create: `backend/workbench/control_plane.py`
- Modify: `backend/workbench/app.py`
- Modify: `backend/workbench/http/agent_routes.py`
- Modify: `backend/workbench/http/projects_routes.py`
- Test: `tests/test_control_plane.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing tests** for the default capability field and rejection of `WORKBENCH_WORKERS > 1` or `WEB_CONCURRENCY > 1`.
- [ ] **Step 2: Run `pytest tests/test_control_plane.py -q` and observe the missing contract failure.**
- [ ] **Step 3: Implement `control_plane_mode()` and an app startup guard with a clear `SINGLE_WORKER_REQUIRED` error.**
- [ ] **Step 4: Add `control_plane_mode: single_worker` to `/agent/capabilities`, `/capabilities`, and a lightweight `/health` response.**
- [ ] **Step 5: Run the focused tests and update README deployment notes.**

### Task 2: Seed a deterministic pending Agent rerun proposal

**Files:**
- Modify: `backend/workbench/dev_fixtures/agent_navigation.py`
- Modify: `scripts/seed_agent_navigation_smoke.py`
- Test: `tests/test_agent_navigation_fixture.py`
- Modify: `docs/dev-browser-smoke.md`

- [ ] **Step 1: Add a failing fixture test requiring a pending `model.rerun` proposal and manifest fields for its target/fingerprint.**
- [ ] **Step 2: Run the focused fixture test and observe the missing pending proposal.**
- [ ] **Step 3: Extend the existing domain seeder to create, but not confirm, a deterministic rerun proposal using `WorkbenchOrchestrator.create_proposal`.**
- [ ] **Step 4: Add the browser steps for confirm → child run → diff/verification → deep-link → reload, with no provider call.**
- [ ] **Step 5: Run fixture tests and execute the fresh browser smoke, recording actual URLs and visible states.**

### Task 3: Define the typed cast spec and deterministic preview

**Files:**
- Create: `backend/workbench/data_operations.py`
- Test: `tests/test_data_column_cast.py`

- [ ] **Step 1: Write failing tests for allowed dtypes, missing columns, strict conversion failures, counts, and deterministic preview fingerprints.**
- [ ] **Step 2: Run the focused tests and observe the missing module/contract failure.**
- [ ] **Step 3: Implement frozen `DataColumnCastSpecV1`, `DataColumnCastPreview`, source artifact resolution, strict conversion, schema fingerprints, and blocking preview status.**
- [ ] **Step 4: Run the focused tests and verify no files are written by preview.**

### Task 4: Implement the immutable artifact effect and graph child

**Files:**
- Modify: `backend/workbench/data_operations.py`
- Modify: `backend/workbench/graph_model.py` only if a typed annotation field is required; otherwise preserve the existing model
- Test: `tests/test_data_column_cast.py`

- [ ] **Step 1: Add failing tests for source immutability, artifact index input provenance, child node/edge payload, downstream invalidation, and deterministic duplicate effect identity.**
- [ ] **Step 2: Run the focused tests and observe the missing effect behavior.**
- [ ] **Step 3: Implement deterministic artifact/recipe paths, `register_artifact`, and `GraphStore.mutate` child creation with a source SHA precondition.**
- [ ] **Step 4: Run focused tests and confirm the second execution returns the same artifact/node binding.**

### Task 5: Plug cast into the shared operation lifecycle

**Files:**
- Modify: `backend/workbench/agent/operations.py`
- Modify: `backend/workbench/agent/orchestrator.py`
- Modify: `backend/workbench/data_operations.py`
- Test: `tests/test_agent_operation_lifecycle.py`
- Test: `tests/test_data_column_cast.py`

- [ ] **Step 1: Add failing lifecycle tests for `data.column.cast` claim, effect commit, projection, and failpoints after effect and after graph binding.**
- [ ] **Step 2: Run focused lifecycle tests and observe the unregistered executor failure.**
- [ ] **Step 3: Register the capability with `natural_language_enabled=False` and add a typed handler adapter to the existing lifecycle hooks.**
- [ ] **Step 4: Ensure reconcile finds the deterministic effect and never creates a second child.**
- [ ] **Step 5: Run the lifecycle tests and existing Agent focused suite.**

### Task 6: Add preview/confirm/readback HTTP routes

**Files:**
- Create: `backend/workbench/http/data_operation_routes.py`
- Modify: `backend/workbench/app.py`
- Test: `tests/test_data_operation_routes.py`

- [ ] **Step 1: Write failing API tests for preview, blocking preview, stale confirm, successful confirm, operation readback, and unsupported extra fields.**
- [ ] **Step 2: Run the focused API tests and observe 404/missing route failures.**
- [ ] **Step 3: Implement strict Pydantic request models and route-level project/run/node/artifact resolution.**
- [ ] **Step 4: Confirm through the shared lifecycle with `actor_type=human_ui` and `confirmation_source=data_column_cast_ui`.**
- [ ] **Step 5: Run focused API tests and verify reload/readback from fresh stores.**

### Task 7: Add the manual graph-node UI

**Files:**
- Create: `frontend/src/lineage/detail/sections/DataColumnCastSection.tsx`
- Create: `frontend/src/lineage/detail/sections/DataColumnCastSection.test.tsx`
- Modify: `frontend/src/lineage/detail/sections/DetailDrawer.tsx` or the existing section registry seam
- Modify: `frontend/src/api.ts`

- [ ] **Step 1: Write failing component tests for selecting an existing column, choosing an enum dtype, rendering preview counts/blocking failures, and requiring an explicit confirm click.**
- [ ] **Step 2: Run the focused Vitest test and observe the missing section failure.**
- [ ] **Step 3: Implement the typed API client and section for `dataset_stage` nodes with no arbitrary expression input.**
- [ ] **Step 4: Run the focused frontend tests and TypeScript.**

### Task 8: Browser acceptance and closeout evidence

**Files:**
- Modify: `docs/dev-browser-smoke.md`
- Modify: `progress.md`
- Modify: `findings.md`

- [ ] **Step 1: Seed a fresh scratch project and record the exact graph/node URL.**
- [ ] **Step 2: Preview a valid cast and record visible before/after dtype and counts.**
- [ ] **Step 3: Confirm once, verify the new child graph node, artifact, operation record, and downstream invalidation.**
- [ ] **Step 4: Reload and verify the operation/readback state and source immutability.**
- [ ] **Step 5: Run `bash scripts/gate.sh`, `git diff --check`, protected-file status, and report any remaining unsupported boundary honestly.**
