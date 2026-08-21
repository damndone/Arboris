# Work Order: v1.8.9 P1 Survey central source

- Objective: `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-survey-central-source-objective.md`
- Baseline: `91ee6a05eab2a1892844c8a3057e1e607359a29e`
- Formal line: `v1-8-9-p1-survey-central-source`
- Worktree: `workbench-v1.8.9-hardening-integration` feature worktree

## Owned paths

- `backend/workbench/evidence/survey_projection_adapter.py`
- `backend/workbench/services/survey_consumer_service.py`
- `backend/workbench/providers/builtin/survey.json`
- `backend/workbench/agent/context_tools.py`
- `backend/workbench/agent/notebook/evidence.py`
- `tests/test_v189_survey_central_consumer.py`
- this objective, work order, and handoff

## Read-only contracts

- `backend/workbench/predictive_research/persistence.py`
- `backend/workbench/predictive_research/consumer_projection.py`
- `backend/workbench/evidence/provider_projection_adapters.py`
- `backend/workbench/providers/catalog.py`
- `backend/workbench/agent/notebook/service.py`

## Forbidden paths

- `backend/workbench/predictive_research/**`
- `backend/workbench/data_operations.py`
- `backend/workbench/app.py`
- `frontend/src/**`
- Survey estimator and variance-engine implementation files

## Gates

TDD RED/GREEN for source authorization, shared Agent/Notebook snapshot,
foreign/path/raw rejection, supported Survey family projection, and typed
unavailable unsupported family; focused tests; catalog/coverage; compileall;
diff check; formal verification. Report/HTTP/browser/provider/full/release
remain separate.
