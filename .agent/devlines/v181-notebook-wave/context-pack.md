# Frozen Context Pack

Line: `v181-notebook-wave`
Baseline SHA: `d26d079e4daec6920b0f6527b919c6df1892c635`

## Objective
v1.8.1 Notebook wave (Gate 4/5/6) under ADR-PD-001: 3 feature lanes + 1 evaluation lane from a single contract lock.

## Boundary
- Affected paths: `backend/workbench/contracts/agent/notebook_option.py`, `backend/workbench/contracts/model/ets.py`, `backend/workbench/agent/notebook`, `backend/workbench/agent/context_compiler.py`, `backend/workbench/agent/trace.py`, `backend/workbench/engine/capabilities.py`, `backend/workbench/engine/packs/ets`, `backend/workbench/engine/packs/builtin_declarations.py`, `backend/workbench/analysis_loop/time_series_compare.py`, `backend/workbench/lineage/pipeline_drafts.py`, `backend/workbench/services/draft_service.py`, `backend/workbench/services/draft_materialization.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/http/drafts_routes.py`, `backend/workbench/app.py`, `backend/workbench/ingestion.py`, `frontend/src/notebook`, `frontend/src/api.ts`, `frontend/src/lineage/drafts`, `frontend/src/pipelineDrafts`, `frontend/src/workbench/WorkbenchMain.tsx`, `frontend/src/workbench/WorkbenchRouteContainer.tsx`, `frontend/src/workbench/WorkbenchTopbar.tsx`, `frontend/src/workbench/state/urlSchema.ts`, `tests/contracts/test_v181_contract_lock.py`, `tests/fixtures/contracts/v181`, `tests/evaluation/v181`, `tests/models/ets`, `tests/test_notebook_routes.py`, `tests/test_notebook_option_producer.py`, `tests/test_notebook_graph_projection.py`, `tests/test_notebook_evidence.py`, `tests/test_notebook_recommendation.py`, `tests/test_notebook_planning_agent.py`, `tests/test_notebook_materialization.py`, `tests/test_context_compiler_entry_point.py`, `tests/test_pipeline_drafts_api.py`, `tests/test_ets_wiring.py`, `tests/test_time_series_compare_adapter.py`, `frontend/src/workbench/WorkbenchMain.notebook.test.tsx`, `frontend/src/workbench/WorkbenchNotebookMount.notebook.test.tsx`, `frontend/src/workbench/state/urlSchema.notebook.test.ts`, `docs/superpowers/specs/2026-07-22-v1.8.1-agent-notebook-analysis-option.md`, `docs/superpowers/specs/2026-07-23-v1.8.1-graph-first-notebook-projection-design.md`, `docs/superpowers/plans/2026-07-23-v1.8.1-graph-first-notebook-projection-plan.md`
- Allowed paths: none
- Protected paths: none
- Dependencies: none
- Tests: none
- Known gates: `scripts/gate.sh`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### wo-b-model-pack (2026-07-20T17:44:54.000Z)

Completed formal devline wo-b-model-pack; final_state=CLOSED; failure_lesson_keys=versioned-public-result-contract
