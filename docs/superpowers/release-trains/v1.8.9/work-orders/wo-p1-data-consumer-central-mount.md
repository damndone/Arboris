# Work Order: P1 data-consumer central mount

- Objective: `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-data-consumer-central-mount-objective.md`
- Baseline / wave lock: `91ee6a05eab2a1892844c8a3057e1e607359a29e`
- Formal line: `v1-8-9-p1-data-consumer-central-mount`
- Worktree: `workbench-v1.8.9-hardening-integration`

## Owned paths

- `backend/workbench/http/data_operation_routes.py`
- `frontend/src/workbench/registry/sectionRegistry.ts`
- `frontend/src/lineage/detail/sections/DataOperationsSection.tsx`
- `tests/test_v189_data_consumer_central_mount.py`
- `frontend/src/workbench/registry/sectionRegistry.v189.test.ts`
- `frontend/src/lineage/detail/sections/DataOperationsSection.test.tsx`

## Read-only contracts

- `backend/workbench/data_operation_manifest.py`
- `backend/workbench/data_operations.py`
- `backend/workbench/agent/context_tools.py`
- `backend/workbench/agent/notebook/evidence.py`
- `backend/workbench/services/results_service.py`
- `docs/superpowers/plans/2026-08-15-v1.8.9-p1-data-consumer-implementation-plan.md`

## Forbidden paths

- `backend/workbench/predictive_research/**`
- `backend/workbench/evidence/**`
- `backend/workbench/agent/workflow.py`
- `backend/workbench/agent/workflow_runtime.py`
- `frontend/src/report/**`

## Tests and gates

- RED/GREEN central backend tests for route/manifest/effect/record/output-port
  identity and fail-closed cases.
- Focused frontend registry and data-operation component tests.
- Existing package data-consumer focused suite and frontend typecheck.
- `git diff --check` and backend compileall.
- Browser, external provider, cross-process authority, full repository gate,
  merge, tag, and release remain separate known gates.

## Safety constraints

No raw rows, filesystem paths, caller-authored evidence, injected registry, or
unadvertised operation may cross the central surface. Any missing or stale
server-owned identity must produce typed unavailable/rejection, never a
successful-looking editor or result.

