# Frozen Context Pack

Line: `v1-8-2-raw-statistics`
Baseline SHA: `418b040b766cc929447b38f7f14e00531168ec7c`

## Objective
# v1.8.2 objective: Raw-node statistical exploration

Add a first-class, pre-model statistical exploration surface on the immutable
Raw data node. Users must be able to compose multiple AND filters, preview and
persist grouped descriptive statistics, and compute a pooled correlation matrix
without writing Python or selecting a regression model first. The persisted
statistics must retain the source node, filter specification, grouping, method,
missing-value policy, selected variables, and result artifact references so the
later model decision is evidence-backed and reproducible.

The v1.8.1 release line, tag, and published worktree are protected. This line
starts from the merged v1.8.1 baseline `418b040b` and must not modify or retag
v1.8.1.

## Boundary
- Affected paths: `docs/releases/v1.8.2-release-notes.md`, `backend/workbench/agent/audit_export.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/core.py`, `backend/workbench/agent/execution.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/notebook/service.py`, `backend/workbench/agent/operations.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/agent/proposals.py`, `backend/workbench/agent/recipes/registry.py`, `backend/workbench/agent/tools.py`, `backend/workbench/agent/workflow.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/contracts/model/ols.py`, `backend/workbench/econometrics/normalize.py`, `backend/workbench/engine/capabilities.py`, `backend/workbench/engine/stages/estimation.py`, `backend/workbench/engine/stages/report.py`, `backend/workbench/exploration_log.py`, `backend/workbench/http/agent_routes.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/http/statistical_exploration_routes.py`, `backend/workbench/model_terms.py`, `backend/workbench/orchestrator/__init__.py`, `backend/workbench/orchestrator/_report_build.py`, `backend/workbench/report_view_model.py`, `backend/workbench/reporting.py`, `backend/workbench/services/draft_materialization.py`, `backend/workbench/services/draft_service.py`, `backend/workbench/services/run_service.py`, `backend/workbench/statistical_exploration.py`, `backend/workbench/visualization.py`, `docs/superpowers/plans/2026-07-24-ols-model-options-contract-design.md`, `docs/superpowers/plans/2026-07-25-v1.8.2-class3-agent-workflow.md`, `docs/superpowers/specs/2026-07-25-model-custom-contract-design.md`, `docs/superpowers/specs/2026-07-25-v1.8.2-class3-agent-workflow-design.md`, `frontend/src/api.ts`, `frontend/src/lineage/detail/sections/AskAISection.test.tsx`, `frontend/src/lineage/detail/sections/AskAISection.tsx`, `frontend/src/lineage/detail/sections/OperationSection.tsx`, `frontend/src/lineage/detail/sections/StatisticalExplorationSection.test.tsx`, `frontend/src/lineage/detail/sections/StatisticalExplorationSection.tsx`, `frontend/src/lineage/statisticalExploration.ts`, `frontend/src/pipelineDrafts/ModelNodeInspector.test.tsx`, `frontend/src/pipelineDrafts/ModelNodeInspector.tsx`, `frontend/src/workbench/views/StatisticalExplorationTable.tsx`, `frontend/src/workbench/views/TableView.test.tsx`, `frontend/src/workbench/views/TableView.tsx`, `frontend/src/workbench/views/tableRunScope.test.ts`, `frontend/src/workbench/views/tableRunScope.ts`, `tests/fixtures/statistical_exploration/expected.json`, `tests/fixtures/statistical_exploration/school_panel.csv`, `tests/golden/continuous_ols.json`, `tests/golden/count_poisson.json`, `tests/golden/imputation.json`, `tests/golden/panel.json`, `tests/test_advanced_econometrics.py`, `tests/test_agent_capabilities.py`, `tests/test_agent_context_tools.py`, `tests/test_agent_data_cast_proposal.py`, `tests/test_agent_generic_workflow.py`, `tests/test_agent_harness_foundation.py`, `tests/test_agent_operation_audit.py`, `tests/test_agent_proposal_operations.py`, `tests/test_agent_statistical_operations.py`, `tests/test_class3_workflow.py`, `tests/test_class3_workflow_ols.py`, `tests/test_class3_workflow_resume.py`, `tests/test_class3_workflow_runtime.py`, `tests/test_exploration_log.py`, `tests/test_lmm_extension_seams.py`, `tests/test_model_options_owner_binding.py`, `tests/test_model_terms.py`, `tests/test_no_exercise_specific_naming.py`, `tests/test_notebook_materialization.py`, `tests/test_ols_model_options_contract.py`, `tests/test_pipeline_drafts_genesis.py`, `tests/test_risk_policy.py`, `tests/test_statistical_exploration.py`, `tests/test_statistical_exploration_derived.py`, `tests/test_statistical_exploration_golden.py`, `tests/test_statistical_exploration_ols_context.py`, `tests/test_statistical_exploration_reporting.py`, `tests/test_statistical_exploration_stata_semantics.py`, `tests/test_visualization.py`, `tests/test_workflow_resume.py`, `tests/test_workflow_runtime.py`, `tests/workflow_fixtures.py`
- Allowed paths: `backend/workbench/agent/audit_export.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/core.py`, `backend/workbench/agent/execution.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/notebook/service.py`, `backend/workbench/agent/operations.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/agent/proposals.py`, `backend/workbench/agent/recipes/registry.py`, `backend/workbench/agent/tools.py`, `backend/workbench/agent/workflow.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/contracts/model/ols.py`, `backend/workbench/econometrics/normalize.py`, `backend/workbench/engine/capabilities.py`, `backend/workbench/engine/stages/estimation.py`, `backend/workbench/engine/stages/report.py`, `backend/workbench/http/agent_routes.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/http/statistical_exploration_routes.py`, `backend/workbench/orchestrator/__init__.py`, `backend/workbench/orchestrator/_report_build.py`, `backend/workbench/services/draft_materialization.py`, `backend/workbench/services/draft_service.py`, `backend/workbench/services/run_service.py`, `docs/superpowers/plans/2026-07-24-ols-model-options-contract-design.md`, `docs/superpowers/plans/2026-07-25-v1.8.2-class3-agent-workflow.md`, `docs/superpowers/specs/2026-07-25-model-custom-contract-design.md`, `docs/superpowers/specs/2026-07-25-v1.8.2-class3-agent-workflow-design.md`, `frontend/src/api.ts`, `frontend/src/lineage/detail/sections/AskAISection.test.tsx`, `frontend/src/lineage/detail/sections/AskAISection.tsx`, `frontend/src/lineage/detail/sections/OperationSection.tsx`, `frontend/src/lineage/detail/sections/StatisticalExplorationSection.test.tsx`, `frontend/src/lineage/detail/sections/StatisticalExplorationSection.tsx`, `frontend/src/lineage/statisticalExploration.ts`, `frontend/src/pipelineDrafts/ModelNodeInspector.test.tsx`, `frontend/src/pipelineDrafts/ModelNodeInspector.tsx`, `frontend/src/workbench/views/StatisticalExplorationTable.tsx`, `frontend/src/workbench/views/TableView.test.tsx`, `frontend/src/workbench/views/TableView.tsx`, `frontend/src/workbench/views/tableRunScope.test.ts`, `frontend/src/workbench/views/tableRunScope.ts`, `tests/fixtures/statistical_exploration/expected.json`, `tests/fixtures/statistical_exploration/school_panel.csv`, `tests/golden/continuous_ols.json`, `tests/golden/count_poisson.json`, `tests/golden/imputation.json`, `tests/golden/panel.json`, `tests/test_advanced_econometrics.py`, `tests/test_agent_capabilities.py`, `tests/test_agent_context_tools.py`, `tests/test_agent_data_cast_proposal.py`, `tests/test_agent_generic_workflow.py`, `tests/test_agent_harness_foundation.py`, `tests/test_agent_operation_audit.py`, `tests/test_agent_proposal_operations.py`, `tests/test_agent_statistical_operations.py`, `tests/test_class3_workflow.py`, `tests/test_class3_workflow_ols.py`, `tests/test_class3_workflow_resume.py`, `tests/test_class3_workflow_runtime.py`, `tests/test_exploration_log.py`, `tests/test_lmm_extension_seams.py`, `tests/test_model_options_owner_binding.py`, `tests/test_model_terms.py`, `tests/test_no_exercise_specific_naming.py`, `tests/test_notebook_materialization.py`, `tests/test_ols_model_options_contract.py`, `tests/test_pipeline_drafts_genesis.py`, `tests/test_risk_policy.py`, `tests/test_statistical_exploration.py`, `tests/test_statistical_exploration_derived.py`, `tests/test_statistical_exploration_golden.py`, `tests/test_statistical_exploration_ols_context.py`, `tests/test_statistical_exploration_reporting.py`, `tests/test_statistical_exploration_stata_semantics.py`, `tests/test_visualization.py`, `tests/test_workflow_resume.py`, `tests/test_workflow_runtime.py`, `tests/workflow_fixtures.py`
- Protected paths: `docs/releases/v1.8.1-release-notes.md`, `docs/superpowers/release-trains/v1.8.1`, `docs/superpowers/specs/2026-07-23-v1.8.1-graph-first-notebook-projection-design.md`, `docs/superpowers/specs/2026-07-24-v1.8.1-agent-surface-polish-design.md`, `.worktrees/integration-v1.8.1`
- Dependencies: none
- Tests: `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 bash ./scripts/gate.sh`, `backend targeted tests for statistical exploration contracts`, `frontend targeted tests for Raw data detail and statistics panel`, `TypeScript check`, `browser smoke for Raw data filter -> summarize -> correlation -> model handoff`
- Known gates: `GATE PASSED`, `Golden / invariant / snapshot drift remains zero`, `Raw-node statistics stay read-only and evidence-backed`, `v1.8.1 tag and release worktree remain unchanged`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass

### local-contained-execution (2026-07-20T17:44:54.000Z)

Completed formal devline local-contained-execution; final_state=CLOSED; failure_lesson_keys=none

### v173-c2-native-acceptance (2026-07-20T16:55:33.000Z)

Completed formal devline v173-c2-native-acceptance; final_state=CLOSED; failure_lesson_keys=c2-runtime-trust-identity

### wo-a-live-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-live-agent; final_state=CLOSED; failure_lesson_keys=none

### integration-v1-7-3 (2026-07-20T17:43:14.000Z)

Completed formal devline integration-v1-7-3; final_state=CLOSED; failure_lesson_keys=c1-c2-execution-boundary, cross-boundary-fixture-parity, declared-owner-no-test-shadowing, entrypoint-contract-coverage, runtime-contract-assembly, versioned-result-visible-reader-adapter

### wo-b-model-pack (2026-07-20T17:44:54.000Z)

Completed formal devline wo-b-model-pack; final_state=CLOSED; failure_lesson_keys=versioned-public-result-contract

### wo-c-ui (2026-07-20T17:44:54.000Z)

Completed formal devline wo-c-ui; final_state=CLOSED; failure_lesson_keys=none

### wo-d-evaluation (2026-07-20T17:44:54.000Z)

Completed formal devline wo-d-evaluation; final_state=CLOSED; failure_lesson_keys=containment-c1-c2-boundary
