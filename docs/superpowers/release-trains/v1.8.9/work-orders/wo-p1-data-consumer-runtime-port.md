# Work Order: v1.8.9 P1 data-consumer runtime port

- Objective: `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-data-consumer-runtime-port-objective.md`
- Baseline: `91ee6a05eab2a1892844c8a3057e1e607359a29e`
- Formal line: `v1-8-9-p1-data-consumer-runtime-port`
- Worktree: `workbench-v1.8.9-hardening-integration` feature worktree

## Owned paths

- `backend/workbench/app.py`
- `backend/workbench/agent/runtime_bootstrap.py`
- `backend/workbench/agent/provider_runtime_contributions.py`
- `backend/workbench/services/data_consumer_execution_resolver.py`
- `tests/test_v189_data_host_port.py`
- `tests/test_v189_agent_notebook_runtime_bootstrap.py`
- this objective, work order, and handoff

## Read-only contracts

- `backend/workbench/data_operations.py`
- `backend/workbench/data_operation_manifest.py`
- `backend/workbench/agent/cutover_runtime.py`
- `backend/workbench/agent/context_tools.py`
- `backend/workbench/http/data_operation_routes.py`

## Forbidden paths

- `backend/workbench/predictive_research/**`
- `backend/workbench/evidence/**`
- `frontend/src/**`
- `backend/workbench/data_operations.py`

## Gates

TDD RED/GREEN for default resolver, foreign source rejection, injected-port
compatibility, and no path egress; focused backend tests; compileall; diff
check; formal verification. Browser/provider/full/release remain separate.
