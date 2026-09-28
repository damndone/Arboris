# Work Order — v1.8.9 Consumer Projection Core

## Baseline and authority

- Exact parent: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`
- Branch/worktree: `workbench-v1.8.9-wave-a` / `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-wave-a`
- Formal line: `v1-8-9-consumer-projection-core`
- Plan: `docs/superpowers/plans/2026-08-15-v1.8.9-consumer-projection-implementation-plan.md`
- C0 handoff: `docs/superpowers/handoff/2026-08-15-v1.8.9-contract-lock-handoff.md`
- C0 catalog digest: `cac54a40f62620b84d288416ee09d5b04814f4dbcb2c8ee3a4595522e3e0da40`
- C0 evidence envelope contract: `a3aa7ac15779077042ef3f0e15ada0df6e1aefc555723c1617f5876d98a22835`
- C0 evidence persistence contract: `44105bfc2fdada97a92c136bf29e4e2762e4098bbc5207fa47eb27509d0023f2`
- C0 context-egress contract: `892d6f672a9de9fae50dfe2c029a97e00dc24fede045df6ca9cf35e3c6b10817`

## Dependencies

The formal dependency IDs required by the implementation plan are:

- `v1-8-9-contract-lock` — completed C0; verified handoff and retrospective
  are present and its exact tip is the baseline above.
- `v1-8-9-p0-workflow-truth-core` — declared dependency; no implementation
  handoff is present in this worktree at startup.
- `v1-8-9-p0-evidence-core` — declared dependency; no implementation handoff
  is present in this worktree at startup. This line consumes the C0
  `EvidencePersistencePortV1` through injection and does not implement a
  private persistence provider.
- `v1-8-9-p0-agent-compiler-core` — declared dependency; no implementation
  handoff is present in this worktree at startup. This line consumes only the
  C0 egress contract and does not alter compiler/runtime control flow.

The absence of the three P0 handoffs is a known integration boundary, not a
permission to duplicate their code. Any claim requiring those implementations
or a C1 merge remains `NOT VERIFIED`.

## Owned paths

The line owns only the following implementation, test, provider contribution
and handoff paths:

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
- `docs/superpowers/objectives/2026-08-15-v1.8.9-consumer-projection-objective.md`
- `docs/superpowers/release-trains/v1.8.9/work-orders/wo-consumer-projection-core.md`
- `docs/superpowers/handoff/2026-08-15-v1.8.9-consumer-projection-core-handoff.md`

## Protected paths and parallel dirty work

Protect the central runtime/compiler/registry and mount boundaries supplied by
the plan:

- `backend/workbench/agent/workflow_runtime.py`
- `backend/workbench/agent/plan_compiler.py`
- `backend/workbench/agent/workflow_capability_registry.py`
- `backend/workbench/agent/workflow_capability_adapters.py`
- `backend/workbench/agent/notebook/planning_agent.py`
- `frontend/src/report/ReportView.tsx`
- `frontend/src/workbench/registry/sectionRegistry.ts`

The active worktree also contains the completed-but-uncommitted P1 data
consumer line. Its dirty files are explicitly outside this work order and
must remain byte-for-byte untouched:

- `backend/workbench/data_operations.py`
- `backend/workbench/http/data_operation_routes.py`
- `backend/workbench/metadata.py`
- `backend/workbench/data_context_egress.py`
- `backend/workbench/data_operation_manifest.py`
- `backend/workbench/data_profile.py`
- `backend/workbench/filter_ast.py`
- `backend/workbench/providers/builtin/data_consumer.json`
- `frontend/src/lineage/dataOperationManifest.ts`
- `frontend/src/lineage/detail/sections/DataOperationsSection.tsx`
- `frontend/src/lineage/detail/sections/DataOperationsSection.test.tsx`
- `tests/test_v189_context_egress.py`
- `tests/test_v189_data_operation_manifest.py`
- `tests/test_v189_data_profile.py`
- `tests/test_v189_filter_ast.py`
- `tests/test_data_operation_routes.py`
- `tests/contracts/test_v189_contract_lock.py`
- the existing P1 objective, work order, handoff and formal records

## Acceptance commands

```text
cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_consumer_projection.py ../tests/test_v189_consumer_coverage.py -q
cd frontend && npm test -- --run src/report/FamilyEvidence.test.tsx && npm run typecheck
PYTHONPATH=$PWD/backend .venv/bin/python -m compileall -q backend/workbench/evidence backend/workbench/services/results_service.py backend/workbench/agent/context_tools.py backend/workbench/agent/notebook/evidence.py backend/workbench/report_view_model.py
git diff --check
PYTHONPATH=$PWD/backend .venv/bin/python scripts/devline_control.py verify --line v1-8-9-consumer-projection-core
PYTHONPATH=$PWD/backend .venv/bin/python scripts/devline_control.py retrospective --line v1-8-9-consumer-projection-core
```

## Known gates and non-goals

- This line does not prove P0 C1 implementation or merge compatibility.
- Production Evidence Core persistence integration remains `NOT VERIFIED` when
  only an injected C0 port is available.
- Agent/Notebook/Report/UI production mounts, real-browser acceptance, external
  provider behavior, provider-backed LLM benchmark, performance, full gate,
  push, merge, tag and release are `NOT VERIFIED` and out of scope.
- No commit, merge, push or tag is authorized.
