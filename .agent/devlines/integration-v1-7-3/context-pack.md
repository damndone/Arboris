# Frozen Context Pack

Line: `integration-v1-7-3`
Baseline SHA: `0251f0a30d984bdbb2cfab404e6c646deab60cae`

## Objective
Assemble one evidence-bound v1.7.3 Integration candidate without treating control-plane, lane-local, browser, performance, or containment evidence as interchangeable.

## Boundary
- Affected paths: `backend/workbench/engine/packs/linear_mixed_effects`, `tests/models/linear_mixed_effects`, `docs/superpowers/specs/2026-07-19-failure-memory-development-efficiency-design.md`
- Allowed paths: `AGENTS.md`, `backend/workbench/orchestrator/__init__.py`, `backend/workbench/services/run_service.py`, `backend/workbench/engine/packs/builtin_declarations.py`, `backend/workbench/engine/packs/linear_mixed_effects`, `backend/workbench/engine/stages/estimation.py`, `backend/workbench/engine/stages/recording.py`, `backend/workbench/engine/stages/report.py`, `frontend/src/lineage/drafts`, `frontend/src/lineage/detail/sections/AnalysisLoopSection.tsx`, `frontend/src/lineage/detail/sections/AnalysisLoopSection.test.tsx`, `frontend/src/runForm`, `frontend/src/runResult.tsx`, `tests/test_lmm_extension_seams.py`, `tests/test_pipeline_drafts_genesis.py`, `tests/test_model_options_owner_binding.py`, `tests/test_devline_memory.py`, `tests/agent/test_lmm_public_result_view.py`, `tests/agent/test_repeated_measures_recipe.py`, `tests/agent/test_repeated_measures_recovery.py`, `tests/engine/test_lmm_execution_admission.py`, `tests/test_reporting_exports.py`, `docs/superpowers/release-trains/v1.7.3`, `docs/superpowers/roadmap/2026-07-15-graph-scale-artifact-ai-terminal-directions.md`, `docs/superpowers/followups/BACKLOG.md`, `tests/models/linear_mixed_effects`, `docs/superpowers/specs/2026-07-19-failure-memory-development-efficiency-design.md`
- Protected paths: `scripts/gate.sh`
- Dependencies: none
- Tests: none
- Known gates: `full-release-gate`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
