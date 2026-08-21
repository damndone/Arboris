# Work Order — v1.8.9 P1 Classification Central Consumer

## Exact baseline

- Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`
- Worktree: `workbench-v1.8.9-hardening-integration`
- Formal line: `v1-8-9-p1-classification-central-consumer`

## Scope

This line owns the central classification consumer facade, Agent/Notebook
wrapper delegation and the Run detail authority flag. The exact
provider-projection adapter join and frontend renderer registry are a later C2
line, not a hidden success condition here.

## Allowed paths

- `backend/workbench/services/classification_consumer_service.py`
- `backend/workbench/services/results_service.py`
- `backend/workbench/agent/context_tools.py`
- `backend/workbench/agent/notebook/evidence.py`
- `backend/workbench/http/runs_routes.py`
- `tests/test_v189_classification_central_consumer.py`
- `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-central-consumer-objective.md`
- `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p1-classification-central-consumer.md`
- `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-central-consumer-handoff.md`

## Protected boundaries

- `backend/workbench/predictive_research/classification_adapters.py`
- `backend/workbench/predictive_research/classification_protocol.py`
- `backend/workbench/predictive_research/consumer_projection.py`
- `backend/workbench/predictive_research/persistence.py`
- `backend/workbench/agent/workflow_runtime.py`
- `backend/workbench/agent/plan_compiler.py`
- `backend/workbench/agent/notebook/planning_agent.py`
- frontend Report/Notebook components
- merge, push, tag, release and external-provider configuration

## Dependencies

- `v1-8-9-agent-notebook-runtime-bootstrap`
- `v1-8-9-central-evidence-consumer-mount`
- `v1-8-9-p1-classification-production`

## Required tests and known gates

- Central classification consumer tests and catalog coverage tests.
- Existing classification production and consumer tests.
- Compileall and diff check.
- Browser-visible acceptance, real provider, cross-process identity, full
  repository gate and release remain `NOT VERIFIED` until separately run.
