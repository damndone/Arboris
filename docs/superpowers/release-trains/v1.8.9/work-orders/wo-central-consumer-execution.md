# Work Order: v1.8.9 Central Consumer Execution

## Objective

Implement the server-issued data and classification execution ports required
to turn the shared Agent/Notebook runtime from identity-only/unavailable into
real typed host execution without crossing the raw-data or evidence boundary.

## Baseline and dependencies

- baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`
- prior line: `v1-8-9-agent-notebook-runtime-bootstrap` (focused gate completed)
- dependencies: Contract Lock, P0 workflow/evidence/compiler cores, P1 data
  consumer/classification cores, consumer projection core, runtime bootstrap

## Owned paths

- `backend/workbench/data_operation_manifest.py`
- `backend/workbench/predictive_research/classification_adapters.py`
- `backend/workbench/agent/provider_runtime_contributions.py`
- `backend/workbench/agent/runtime_bootstrap.py`
- `backend/workbench/app.py`
- `tests/test_v189_central_consumer_execution.py`
- `tests/test_v189_data_operation_manifest.py`
- `tests/test_v189_classification_production.py`
- this work order and its objective/handoff

## Forbidden paths

- `backend/workbench/evidence/**`
- `backend/workbench/report_view_model.py`
- `frontend/src/**`
- `backend/workbench/engine/**`

## Required tests and gates

- red-first tests for both host ports and the shared Agent/Notebook path
- focused central-consumer and existing runtime suites
- `compileall`, `git diff --check`, formal verify, and generated retrospective
- browser/provider/cross-process/full/release remain NOT VERIFIED

## Safety and rollback

The only accepted input authority is a server-issued typed port bound to the
exact catalog/snapshot scope. If the line must be backed out, revert only the
line-owned changes after preserving the formal handoff; do not reset or delete
other dirty worktree state.
