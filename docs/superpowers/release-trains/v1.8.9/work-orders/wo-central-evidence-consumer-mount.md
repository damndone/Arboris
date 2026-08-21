# Work Order: v1.8.9 Central Evidence Consumer Mount

## Objective

Connect the server-owned persisted evidence projection to the production
Agent/Notebook/Report consumer surfaces without re-reading or recomputing
untrusted model-result packets.

## Baseline and dependencies

- baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`
- prior line: `v1-8-9-central-consumer-execution`
- dependencies: Contract Lock, consumer projection core, Report evidence core,
  shared Agent/Notebook runtime bootstrap, typed data/classification host ports

## Owned paths

- `backend/workbench/http/runs_routes.py`
- `backend/workbench/services/results_service.py`
- `backend/workbench/agent/context_tools.py`
- `backend/workbench/agent/notebook/evidence.py`
- `backend/workbench/report_view_model.py`
- `tests/test_v189_central_evidence_consumer_mount.py`
- `tests/test_v189_agent_notebook_runtime_bridge.py`
- `tests/test_v189_evidence_report_boundary.py`
- this work order and its objective/handoff

## Forbidden paths

- `backend/workbench/evidence/**` (the C0 store and registry are consumed,
  not rewritten here)
- `backend/workbench/engine/**`
- `frontend/src/**`
- `backend/workbench/prediction.py`

## Required tests and gates

- red-first route/service/context/report tests proving positive typed evidence
  consumption and fail-closed missing/foreign/stale behavior
- Agent and Notebook must share one projection function/registry
- Report must reject raw fallback and preserve explicit unavailable status
- focused tests, `compileall`, `git diff --check`, formal verify, generated
  retrospective
- browser/provider/cross-process/full/release remain `NOT VERIFIED`

## Safety and rollback

The central consumer must not gain authority to create evidence or execute a
provider. If the line is backed out, preserve the typed host-port and C0
changes from prior lines and revert only this line's consumer mounts.
