# Frozen Context Pack

Line: `v1-8-9-provider-catalog-integration`
Baseline SHA: `c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749`

## Objective
# v1.8.9 Provider Catalog Integration Objective

Restore one deterministic provider-catalog identity order after the parallel
Data Consumer, Consumer Projection, and Classification ML contributions are
combined. Provider IDs must be ordered by server-owned identity with filename
as a deterministic tie-breaker; no provider manifest, central Agent/Notebook
routing, runtime executor, or consumer mount may be changed.

## Boundary
- Affected paths: `backend/workbench/providers/catalog.py`, `tests/contracts/test_v189_contract_lock.py`, `docs/superpowers/objectives/2026-08-16-v1.8.9-provider-catalog-integration-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-provider-catalog-integration.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-provider-catalog-integration-handoff.md`
- Allowed paths: `backend/workbench/providers/catalog.py`, `tests/contracts/test_v189_contract_lock.py`, `docs/superpowers/objectives/2026-08-16-v1.8.9-provider-catalog-integration-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-provider-catalog-integration.md`, `docs/superpowers/handoff/2026-08-16-v1.8.9-provider-catalog-integration-handoff.md`
- Protected paths: `backend/workbench/providers/builtin`, `backend/workbench/agent`, `backend/workbench/evidence`, `frontend/src/workbench/registry/sectionRegistry.ts`, `frontend/src/report/ReportView.tsx`
- Dependencies: `v1-8-9-p1-data-consumer-core`, `v1-8-9-consumer-projection-core`, `v1-8-9-p1-classification-ml-core`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/contracts/test_v189_contract_lock.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_consumer_projection.py tests/test_v189_consumer_coverage.py tests/predictive_research/test_classification_contracts_v189.py tests/predictive_research/test_classification_protocol_v189.py tests/predictive_research/test_classification_leakage_v189.py tests/predictive_research/test_classification_consumers_v189.py -q`
- Known gates: `Provider runtime, browser, Agent/Notebook/Report cutover, full gate, merge, push and tag remain separate evidence`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none
