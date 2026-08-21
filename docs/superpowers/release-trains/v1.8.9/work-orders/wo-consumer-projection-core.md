# v1.8.9 Consumer Projection Core Work Order

## Objective and non-goals

Implement persisted EvidenceEnvelope-to-consumer projections and declaration-
derived coverage. Do not alter statistical computation, workflow execution,
central compiler/registry, Notebook planning, Report mounting or release
machinery.

## Exact baseline

- Baseline/wave lock: `91ee6a05eab2a1892844c8a3057e1e607359a29e`.
- Integration worktree: `workbench-v1.8.9-hardening-integration`.
- Formal line: `v1-8-9-consumer-projection-core`.

## Owned paths

- `backend/workbench/evidence/consumer_adapters.py`
- `backend/workbench/evidence/coverage.py`
- `backend/workbench/services/results_service.py`
- `backend/workbench/agent/context_tools.py`
- `backend/workbench/agent/notebook/evidence.py`
- `backend/workbench/report_view_model.py`
- `backend/workbench/providers/builtin/consumer_projection.json`
- `frontend/src/report/FamilyEvidence.tsx`
- `frontend/src/report/FamilyEvidence.test.tsx`
- `frontend/src/report/reportEvidence.ts`
- `frontend/src/notebook/evidenceContracts.ts`
- `tests/test_v189_consumer_projection.py`
- `tests/test_v189_consumer_coverage.py`
- `docs/superpowers/objectives/2026-08-20-v1.8.9-consumer-projection-core-objective.md`
- `docs/superpowers/release-trains/v1.8.9/work-orders/wo-consumer-projection-core.md`
- `docs/superpowers/handoff/2026-08-20-v1.8.9-consumer-projection-core-handoff.md`

## Protected paths

`backend/workbench/agent/workflow.py`,
`backend/workbench/agent/workflow_runtime.py`,
`backend/workbench/agent/workflow_contracts.py`,
`backend/workbench/agent/plan_compiler.py`,
`backend/workbench/agent/workflow_capability_registry.py`,
`backend/workbench/agent/workflow_capability_adapters.py`,
`backend/workbench/agent/notebook/planning_agent.py`,
`frontend/src/report/ReportView.tsx`,
`frontend/src/workbench/registry/sectionRegistry.ts`, statistical estimator
math, release/merge/push/tag machinery and other worktrees.

## Parallel ownership split

- Backend projection owner: evidence adapters, results facade and Agent/Notebook
  evidence context, plus `tests/test_v189_consumer_projection.py`.
- Coverage/provider owner: coverage registry and provider declaration, plus
  `tests/test_v189_consumer_coverage.py`.
- UI contract owner: Report family renderer, typed report evidence and Notebook
  evidence contracts/tests.

No worker may edit another worker's owned paths. Integration review is required
before closeout.

## Acceptance commands

- `cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_consumer_projection.py ../tests/test_v189_consumer_coverage.py -q`
- `cd frontend && npm test -- --run src/report/FamilyEvidence.test.tsx`
- `cd frontend && npm run typecheck`
- `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench`
- `git diff --check`
- formal event verification and retrospective through `scripts/devline_control.py`.

## Known gates

Production mounts, central Agent/Notebook/Report cutover, browser acceptance,
real provider benchmarks, host identity configuration, full repository gate,
release, merge, push and tag are not part of this line.
