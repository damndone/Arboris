# Frozen Context Pack

Line: `v1-8-4-agent-model-composition`
Baseline SHA: `6884a03742603689d5032c86223a42da50d4f5b8`

## Objective
v1.8.4 Agent Model Composition

Objective

Expose the existing server-validated OLS term vocabulary through the Notebook
Agent lifecycle, so a user can request a model with declared categorical
terms and declared polynomial terms, review the typed workflow, confirm it,
and receive the completed results as bounded evidence.

Add only two server-defined post-estimation result operations required to
interpret such models generically: a joint test over a declared model-term
group and the stationary point of a declared quadratic term.  Both must be
derived from the completed model branch, carry artifact provenance, validate
their semantic preconditions, and reject unsupported requests.

Non-goals

No arbitrary formulas, code execution, raw-data browsing, automatic
execution, dataset- or exercise-specific column names, or implicit changes
to an existing model.  Every workflow remains typed, server-validated, and
subject to the existing Proposal/Risk confirmation lifecycle.

Acceptance

Focused tests prove that the Notebook planner accepts only a source-pinned
operation.multi_step proposal, the published workflow vocabulary permits
categorical and polynomial declarations, invalid selectors fail closed, and
the two post-estimation results are reproducible from a completed branch with
durable artifact references.  A Workbench UI acceptance run must show Agent
recommendation -> user confirmation -> completed workflow -> evidence-backed
answer without a backend code-upload path.

## Boundary
- Affected paths: `backend/workbench/agent/context_compiler.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/core.py`, `backend/workbench/agent/model.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/notebook/recommendation.py`, `backend/workbench/agent/notebook/service.py`, `backend/workbench/agent/notebook/store.py`, `backend/workbench/agent/tools.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/econometrics/runner.py`, `backend/workbench/figure_context.py`, `backend/workbench/http/agent_routes.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/http/runs_routes.py`, `backend/workbench/llm/client.py`, `backend/workbench/llm/provider_store.py`, `backend/workbench/model_terms.py`, `backend/workbench/services/run_deletion.py`, `frontend/src/api.ts`, `frontend/src/lineage/api/graphAdapter.headset.test.ts`, `frontend/src/lineage/api/graphAdapter.ts`, `frontend/src/lineage/detail/DetailDrawerTabs.test.tsx`, `frontend/src/lineage/detail/DetailDrawerTabs.tsx`, `frontend/src/lineage/detail/sections/AskAISection.test.tsx`, `frontend/src/lineage/detail/sections/AskAISection.tsx`, `frontend/src/lineage/detail/sections/BasicInfoSection.test.tsx`, `frontend/src/lineage/detail/sections/BasicInfoSection.tsx`, `frontend/src/lineage/detail/sections/StatisticalPlotSection.test.tsx`, `frontend/src/lineage/detail/sections/StatisticalPlotSection.tsx`, `frontend/src/lineage/drafts/mergeDraftsIntoModel.test.ts`, `frontend/src/lineage/drafts/mergeDraftsIntoModel.ts`, `frontend/src/lineage/graph/GraphCanvas.test.tsx`, `frontend/src/lineage/graph/GraphCanvas.tsx`, `frontend/src/lineage/runRail/RunHistoryRail.test.tsx`, `frontend/src/lineage/runRail/RunHistoryRail.tsx`, `frontend/src/lineage/tokens/lineage.css`, `frontend/src/notebook/NotebookRouteView.notebook.test.tsx`, `frontend/src/notebook/NotebookRouteView.tsx`, `frontend/src/notebook/NotebookSurface.notebook.test.tsx`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/notebook/PlanDiffConfirmation.tsx`, `frontend/src/notebook/contracts.notebook.test.tsx`, `frontend/src/notebook/contracts.ts`, `frontend/src/notebook/notebook.css`, `frontend/src/notebook/notebookApi.notebook.test.ts`, `frontend/src/notebook/notebookApi.ts`, `frontend/src/report/ReportView.test.tsx`, `frontend/src/report/ReportView.tsx`, `frontend/src/runForm/ImputationControls.test.tsx`, `frontend/src/runForm/ImputationControls.tsx`, `frontend/src/styles.css`, `frontend/src/workbench/BottomPanel.tsx`, `frontend/src/workbench/ContextMenu.test.tsx`, `frontend/src/workbench/ContextMenu.tsx`, `frontend/src/workbench/ForestContext.tsx`, `frontend/src/workbench/RunDeletionDialog.test.tsx`, `frontend/src/workbench/RunDeletionDialog.tsx`, `frontend/src/workbench/WorkbenchRouteContainer.test.tsx`, `frontend/src/workbench/WorkbenchRouteContainer.tsx`, `frontend/src/workbench/WorkbenchStateProvider.tsx`, `frontend/src/workbench/WorkbenchTopbar.tsx`, `frontend/src/workbench/agent/AgentComposer.test.tsx`, `frontend/src/workbench/agent/AgentComposer.tsx`, `frontend/src/workbench/agent/AgentPanel.test.tsx`, `frontend/src/workbench/agent/AgentPanel.tsx`, `frontend/src/workbench/agent/AgentSurfaceContext.test.tsx`, `frontend/src/workbench/agent/AgentSurfaceContext.tsx`, `frontend/src/workbench/agent/agent.css`, `frontend/src/workbench/agent/agentApi.ts`, `frontend/src/workbench/useDraftHandlers.test.ts`, `frontend/src/workbench/useDraftHandlers.ts`, `frontend/src/workbench/views/GraphView.tsx`, `frontend/src/workbench/views/StatisticalExplorationTable.tsx`, `frontend/src/workbench/views/TableView.test.tsx`, `frontend/src/workbench/views/TableView.tsx`, `tests/test_agent_context_tools.py`, `tests/test_agent_generic_workflow.py`, `tests/test_agent_harness_foundation.py`, `tests/test_agent_routes.py`, `tests/test_agent_tools.py`, `tests/test_llm_provider_store.py`, `tests/test_llm_providers.py`, `tests/test_model_terms.py`, `tests/test_notebook_graph_projection.py`, `tests/test_notebook_materialization.py`, `tests/test_notebook_planning_agent.py`, `tests/test_notebook_recommendation.py`, `tests/test_notebook_routes.py`, `tests/test_panel_covariance.py`, `tests/test_run_deletion.py`, `tests/test_workflow_runtime.py`
- Allowed paths: `backend/workbench/agent/context_compiler.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/core.py`, `backend/workbench/agent/model.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/notebook/recommendation.py`, `backend/workbench/agent/notebook/service.py`, `backend/workbench/agent/notebook/store.py`, `backend/workbench/agent/tools.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/econometrics/runner.py`, `backend/workbench/http/agent_routes.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/http/runs_routes.py`, `backend/workbench/llm/client.py`, `backend/workbench/llm/provider_store.py`, `backend/workbench/services/run_deletion.py`, `frontend/src/api.ts`, `frontend/src/lineage/api/graphAdapter.headset.test.ts`, `frontend/src/lineage/api/graphAdapter.ts`, `frontend/src/lineage/detail/DetailDrawerTabs.test.tsx`, `frontend/src/lineage/detail/DetailDrawerTabs.tsx`, `frontend/src/lineage/detail/sections/AskAISection.test.tsx`, `frontend/src/lineage/detail/sections/AskAISection.tsx`, `frontend/src/lineage/detail/sections/BasicInfoSection.test.tsx`, `frontend/src/lineage/detail/sections/BasicInfoSection.tsx`, `frontend/src/lineage/detail/sections/StatisticalPlotSection.test.tsx`, `frontend/src/lineage/detail/sections/StatisticalPlotSection.tsx`, `frontend/src/lineage/drafts/mergeDraftsIntoModel.test.ts`, `frontend/src/lineage/drafts/mergeDraftsIntoModel.ts`, `frontend/src/lineage/graph/GraphCanvas.test.tsx`, `frontend/src/lineage/graph/GraphCanvas.tsx`, `frontend/src/lineage/runRail/RunHistoryRail.test.tsx`, `frontend/src/lineage/runRail/RunHistoryRail.tsx`, `frontend/src/lineage/tokens/lineage.css`, `frontend/src/notebook/NotebookRouteView.notebook.test.tsx`, `frontend/src/notebook/NotebookRouteView.tsx`, `frontend/src/notebook/NotebookSurface.notebook.test.tsx`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/notebook/PlanDiffConfirmation.tsx`, `frontend/src/notebook/contracts.notebook.test.tsx`, `frontend/src/notebook/contracts.ts`, `frontend/src/notebook/notebook.css`, `frontend/src/notebook/notebookApi.notebook.test.ts`, `frontend/src/notebook/notebookApi.ts`, `frontend/src/report/ReportView.test.tsx`, `frontend/src/report/ReportView.tsx`, `frontend/src/runForm/ImputationControls.test.tsx`, `frontend/src/runForm/ImputationControls.tsx`, `frontend/src/styles.css`, `frontend/src/workbench/BottomPanel.tsx`, `frontend/src/workbench/ContextMenu.test.tsx`, `frontend/src/workbench/ContextMenu.tsx`, `frontend/src/workbench/ForestContext.tsx`, `frontend/src/workbench/RunDeletionDialog.test.tsx`, `frontend/src/workbench/RunDeletionDialog.tsx`, `frontend/src/workbench/WorkbenchRouteContainer.test.tsx`, `frontend/src/workbench/WorkbenchRouteContainer.tsx`, `frontend/src/workbench/WorkbenchStateProvider.tsx`, `frontend/src/workbench/WorkbenchTopbar.tsx`, `frontend/src/workbench/agent/AgentComposer.test.tsx`, `frontend/src/workbench/agent/AgentComposer.tsx`, `frontend/src/workbench/agent/AgentPanel.test.tsx`, `frontend/src/workbench/agent/AgentPanel.tsx`, `frontend/src/workbench/agent/AgentSurfaceContext.test.tsx`, `frontend/src/workbench/agent/AgentSurfaceContext.tsx`, `frontend/src/workbench/agent/agent.css`, `frontend/src/workbench/agent/agentApi.ts`, `frontend/src/workbench/useDraftHandlers.test.ts`, `frontend/src/workbench/useDraftHandlers.ts`, `frontend/src/workbench/views/GraphView.tsx`, `frontend/src/workbench/views/StatisticalExplorationTable.tsx`, `frontend/src/workbench/views/TableView.test.tsx`, `frontend/src/workbench/views/TableView.tsx`, `tests/test_agent_context_tools.py`, `tests/test_agent_generic_workflow.py`, `tests/test_agent_harness_foundation.py`, `tests/test_agent_routes.py`, `tests/test_agent_tools.py`, `tests/test_llm_provider_store.py`, `tests/test_llm_providers.py`, `tests/test_model_terms.py`, `tests/test_notebook_graph_projection.py`, `tests/test_notebook_materialization.py`, `tests/test_notebook_planning_agent.py`, `tests/test_notebook_recommendation.py`, `tests/test_notebook_routes.py`, `tests/test_panel_covariance.py`, `tests/test_run_deletion.py`, `tests/test_workflow_runtime.py`
- Protected paths: `.agent/devlines`, `docs/superpowers/specs`, `docs/superpowers/plans`, `scripts/devline_control.py`, `backend/workbench/native_containment`, `backend/workbench/engine/registry.py`
- Dependencies: `v1-8-4-agent-evidence-loop`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_notebook_planning_agent.py tests/test_agent_workflow_integration.py tests/test_agent_proposal_operations.py tests/test_notebook_routes.py`, `cd frontend && npm run typecheck && npm test -- --run`, `browser: Agent recommendation -> confirmation -> completed typed workflow -> evidence-backed answer`
- Known gates: `No arbitrary formula evaluator or raw-data browsing: term declarations and post-estimation selectors stay server-validated and bounded.`, `New worktrees require bash scripts/link-shared-deps.sh <absolute-path> before valid gates.`, `Do not pipe tsc output to tail when reading the exit code.`, `Managed macOS sandbox-exec may reject containment; preserve fail-closed behavior and do not introduce weaker fallback.`

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
