# Work Order — v1.8.9 Agent / Notebook Cutover

## Scope and ownership

- Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`
- Worktree: `.worktrees/workbench-v1.8.9-wave-a`
- Formal line: `v1-8-9-agent-notebook-cutover`
- Plan: `docs/superpowers/plans/2026-08-15-v1.8.9-agent-notebook-cutover-implementation-plan.md`
- Central cutover files have one writer: this line's main worker. Reviewers and
  evaluators may inspect and test but may not edit them.

Owned implementation paths:

- `backend/workbench/agent/workflow_contracts.py`
- `backend/workbench/agent/workflow_capability_registry.py`
- `backend/workbench/agent/workflow_capability_adapters.py`
- `backend/workbench/agent/trusted_executor_registry.py`
- `backend/workbench/agent/operations.py`
- `backend/workbench/agent/orchestrator.py`
- `backend/workbench/agent/notebook/planning_agent.py`
- `backend/workbench/http/agent_routes.py`
- `frontend/src/workbench/registry/sectionRegistry.ts`
- `frontend/src/report/ReportView.tsx`
- `tests/test_v189_agent_notebook_cutover.py`
- `tests/test_notebook_planning_agent.py`
- `tests/test_agent_operation_lifecycle.py`
- `frontend/src/report/ReportView.v189.test.tsx`
- `frontend/src/workbench/registry/sectionRegistry.v189.test.ts`
- this work order, objective and completion handoff

Protected paths include the frozen workflow/runtime/compiler/context compiler,
Data Consumer and Evidence producer implementations, predictive-research
implementations, provider manifests unless explicitly needed for a fixture,
application startup, release artifacts and all unrelated dirty work.

## Dependencies and known boundary

The line consumes the verified C0 Contract Lock and the package-local Data
Consumer, Classification ML, Consumer Projection and provider-catalog
contributions. The formal dependency IDs are:

- `v1-8-9-contract-lock`
- `v1-8-9-p0-workflow-truth-core`
- `v1-8-9-p0-evidence-core`
- `v1-8-9-p0-agent-compiler-core`
- `v1-8-9-p1-data-consumer-core`
- `v1-8-9-p1-classification-ml-core`
- `v1-8-9-consumer-projection-core`

The three P0 C1 implementation handoffs are absent from this worktree. Their
absence is recorded as an integration boundary; this work order must not copy
private P0 implementations or claim a C1 merge. Any existing runtime caller
that cannot be proven to reach the unique `ExecutionAdmissionV1` choke point
must be blocked or recorded as a typed gap, never silently retained as a
second authority.

## Required implementation

1. Build deterministic catalog/admission facades and a server-composed
   `TrustedExecutorRegistry`. Reject duplicate IDs, digest or contract mismatch,
   unsupported versions, path-like/dynamic-import IDs, missing/extra code
   contributions, undeclared effects and orphan operations before dispatch.
2. Add one compiler/authority loop for Agent and Notebook. Persist semantic
   plan hash separately from execution-instance hash and bind the compilation
   record to actor, session, project, data snapshot, catalog/contract digests,
   effect/resource summary, egress policy and expiry.
3. Make preview/diff reference the persisted record. Execute takes only the
   server record ID and confirmation receipt. Recompile/reconfirm after edits,
   snapshot/permission/provider/contract/effect changes; test stale, tampered,
   cross-session, race, cancel and recovery states.
4. Route free-form language through typed intent normalization and clarification
   while preserving explicit uncertainty and availability. Agent answers cite
   persisted evidence only.
5. Make Notebook recipes use the same capability/clarification/compile path,
   without a second capability table or model-family switch. Persist rerun
   prerequisites and deterministic migrations for existing durable recipes.
6. Mount declaration-derived Data Consumer and family/classification evidence
   sections in the existing registry and ReportView. Unknown/unavailable/
   degraded/blocked/stale states render safely without raw JSON fallback or
   recalculation.

## Test and gate commands

```text
cd backend && PYTHONPATH=$PWD ../.venv/bin/python -m pytest ../tests/test_v189_agent_notebook_cutover.py ../tests/test_notebook_planning_agent.py ../tests/test_agent_operation_lifecycle.py -q
cd frontend && npm test -- --run src/report/ReportView.v189.test.tsx src/workbench/registry/sectionRegistry.v189.test.ts && npm run typecheck
PYTHONPATH=$PWD/backend .venv/bin/python -m compileall -q backend/workbench/agent backend/workbench/http/agent_routes.py
git diff --check
PYTHONPATH=$PWD/backend .venv/bin/python scripts/devline_control.py verify --line v1-8-9-agent-notebook-cutover
PYTHONPATH=$PWD/backend .venv/bin/python scripts/devline_control.py retrospective --line v1-8-9-agent-notebook-cutover
```

The full host gate, browser, real external provider and release evidence are
separate. The prior full gate had 20 host `sandbox_apply` failures in unrelated
code-execution/sandbox tests; this line must not call that a product pass.

## Exit criteria

- Agent and Notebook produce the same semantic plan hash for equivalent intent
  while retaining distinct execution instance IDs and presentation projections.
- A fixture provider is usable from both paths without central family code.
- Client-shaped authority, stale confirmation, cross-session replay, changed
  data/provider/contract and unsafe egress are denied before side effects.
- Completion has an immutable Evidence Core binding, and consumers/renderers
  use typed persisted projections only.
- Formal event stream verifies and retrospective is generated. Browser,
  external provider, full gate, merge, push and tag are explicitly marked
  `NOT VERIFIED` unless separately evidenced.
