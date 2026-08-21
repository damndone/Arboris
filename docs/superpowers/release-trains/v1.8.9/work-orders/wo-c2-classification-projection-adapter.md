# Work Order — v1.8.9 C2 Classification Projection Adapter

## Exact baseline

- Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`
- Worktree: `workbench-v1.8.9-hardening-integration`
- Formal line: `v1-8-9-c2-classification-projection-adapter`

## Scope

This line owns the provider-scoped projection registry, exact catalog join for
classification consumers, and the Report-side closed renderer binding. It may
extend the generic consumer registry only through backward-compatible scoped
bindings. It must not change statistical producer semantics.

## Allowed paths

- `backend/workbench/evidence/consumer_adapters.py`
- `backend/workbench/evidence/coverage.py`
- `backend/workbench/evidence/provider_projection_adapters.py`
- `backend/workbench/services/classification_consumer_service.py`
- `tests/test_v189_classification_projection_adapter.py`
- `tests/test_v189_consumer_coverage.py`
- `tests/test_v189_provider_projection_identity.py`
- `frontend/src/report/ClassificationEvidence.tsx`
- `frontend/src/report/ReportView.tsx`
- `frontend/src/report/ReportWorkspaceContext.tsx`
- `frontend/src/report/reportRendererRegistry.ts`
- `frontend/src/report/ReportClassificationProjection.v189.test.tsx`
- `frontend/src/report/ReportView.v189.test.tsx`
- `frontend/src/report/ReportEvidenceBoundary.v189.test.tsx`
- `docs/superpowers/objectives/2026-08-20-v1.8.9-c2-classification-projection-adapter-objective.md`
- `docs/superpowers/release-trains/v1.8.9/work-orders/wo-c2-classification-projection-adapter.md`
- `docs/superpowers/handoff/2026-08-20-v1.8.9-c2-classification-projection-adapter-handoff.md`

## Protected boundaries

- `backend/workbench/predictive_research/classification_adapters.py`
- `backend/workbench/predictive_research/classification_protocol.py`
- `backend/workbench/predictive_research/consumer_projection.py`
- `backend/workbench/predictive_research/persistence.py`
- `backend/workbench/agent/workflow_runtime.py`
- `backend/workbench/agent/plan_compiler.py`
- provider manifest files and contract definitions
- frontend estimator, Notebook planner, and generic data-operation components
- merge, push, tag, release and external-provider configuration

## Dependencies

- `v1-8-9-p1-classification-central-consumer`
- `v1-8-9-consumer-catalog-contract`
- `v1-8-9-provider-projection-identity`
- `v1-8-9-central-evidence-consumer-mount`

## Required tests and known gates

- Exact provider/path/consumer catalog binding and coverage tests.
- Existing central classification, production, consumer projection and generic
  evidence boundary suites.
- Frontend Report classification projection and renderer registry tests.
- Compileall and `git diff --check`.
- Browser-visible acceptance, real provider, cross-process identity, full
  repository gate and release remain `NOT VERIFIED` until separately run.
