# Frozen Context Pack

Line: `v1-8-8-agent-chain-hardening`
Baseline SHA: `2963c45a2d4879efa1c4038a38aaf201fe9611ef`

## Objective
# v1.8.8 Agent-chain hardening objective

Close the three known acceptance gaps on code baseline `ad51d23`: make Report
provider output safely accepted and saved, validate Notebook artifacts against
the option-owned contract while preserving the ambient index, and make the
eighteen live reachability gaps executable through one declaration-driven
workflow seam. Make Genesis draft editing consume a server-owned two-phase
schema. Preserve proposal confirmation, numerical fail-closed behavior, typed
provenance, and the prediction-only boundary for resampling.

The current shared capability inventory is `118 / 4 / 94 / 98 / 2 / 18` and
the target is `118 / 4 / 112 / 116 / 2 / 0`. The eighteen IDs and the current
P7 operation denominator must be queried from live declarations before tests
are written. A host-side browser-visible matrix must cover every operation
returned by the live P7 registry with a durable result or an explicit typed
optional-dependency block; unit tests and direct adapter calls do not count.

Keep Report, Notebook, reachability, and Genesis changes module-isolated. Do
not add per-operation orchestrator branches, silently retry typed Agent calls,
silently drop provider content, or perform push, PR, merge, tag, or release.

## Boundary
- Affected paths: `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/notebook/store.py`, `backend/workbench/agent/notebook/service.py`, `backend/workbench/agent/notebook/workflow_artifacts.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/services/notebook_source_materialization.py`, `backend/workbench/agent/p7_pack_registry.py`, `backend/workbench/qa/p7_acceptance.py`, `backend/workbench/qa/notebook_acceptance_evidence.py`, `scripts/p7_acceptance_runner.py`, `frontend/src/workbench/WorkbenchRouteContainer.tsx`, `frontend/src/workbench/CommandPalette.tsx`, `backend/workbench/agent/model.py`, `tests/test_llm_providers.py`, `tests/test_agent_tools.py`, `tests/test_notebook_routes.py`, `frontend/src/notebook/contracts.ts`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/notebook/contracts.notebook.test.tsx`, `frontend/src/notebook/NotebookSurface.notebook.test.tsx`, `backend/workbench/http/llm_routes.py`, `frontend/src/report/reportClient.ts`, `frontend/src/report/reportClient.test.ts`, `tests/test_memory_integration_context.py`, `tests/test_notebook_graph_projection.py`, `backend/workbench/agent/capability_contract.py`, `backend/workbench/agent/notebook/errors.py`, `backend/workbench/agent/notebook/materialization.py`, `backend/workbench/agent/p7_pack_adapters.py`, `backend/workbench/agent/workflow_capability_adapters.py`, `backend/workbench/agent/workflow_capability_registry.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/engine/capabilities.py`, `backend/workbench/engine/cs_attgt.py`, `backend/workbench/http/runs_routes.py`, `backend/workbench/lineage/pipeline_drafts.py`, `backend/workbench/llm/client.py`, `backend/workbench/report_contract.py`, `backend/workbench/report_quality.py`, `backend/workbench/services/draft_materialization.py`, `backend/workbench/services/draft_service.py`, `backend/workbench/services/server_run_artifacts.py`, `frontend/src/api.ts`, `frontend/src/lineage/drafts/GenesisWizard.test.tsx`, `frontend/src/lineage/drafts/GenesisWizard.tsx`, `frontend/src/lineage/drafts/ServerOwnedModelOptions.test.tsx`, `frontend/src/lineage/drafts/ServerOwnedModelOptions.tsx`, `frontend/src/notebook/NotebookRouteView.notebook.test.tsx`, `frontend/src/notebook/NotebookRouteView.tsx`, `frontend/src/notebook/notebookApi.notebook.test.ts`, `frontend/src/notebook/notebookApi.ts`, `frontend/src/pipelineDrafts/DraftGraphRoute.test.tsx`, `frontend/src/pipelineDrafts/DraftGraphRoute.tsx`, `frontend/src/report/ReportComposer.tsx`, `frontend/src/report/ReportView.test.tsx`, `frontend/src/report/ReportView.tsx`, `frontend/src/report/ReportWorkspaceContext.tsx`, `frontend/src/report/factTable.test.ts`, `frontend/src/report/factTable.ts`, `frontend/src/report/reportEvidence.test.ts`, `frontend/src/report/reportEvidence.ts`, `frontend/src/runForm/ArmaGarchControls.tsx`, `frontend/src/workbench/WorkbenchRouteContainer.test.tsx`, `tests/test_capability_inventory.py`, `tests/test_llm_chat.py`, `tests/test_notebook_artifact_contract.py`, `tests/test_notebook_planning_agent.py`, `tests/test_notebook_source_materialization.py`, `tests/test_p7_acceptance_matrix.py`, `tests/test_p7_adoption_registry.py`, `tests/test_p7_workflow_integration.py`, `tests/test_pipeline_drafts_genesis.py`, `tests/test_report_contract.py`, `tests/test_report_quality.py`, `tests/test_workflow_capability_adapters.py`, `tests/test_workflow_capability_registry.py`, `tests/test_workflow_capability_runtime.py`, `tests/test_workflow_seam.py`
- Allowed paths: `backend/workbench/agent/capability_contract.py`, `backend/workbench/agent/notebook/errors.py`, `backend/workbench/agent/notebook/materialization.py`, `backend/workbench/agent/notebook/service.py`, `backend/workbench/agent/p7_pack_registry.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/engine/cs_attgt.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/lineage/pipeline_drafts.py`, `backend/workbench/report_contract.py`, `backend/workbench/report_quality.py`, `backend/workbench/services/draft_materialization.py`, `backend/workbench/services/draft_service.py`, `frontend/src/api.ts`, `frontend/src/lineage/drafts/GenesisWizard.test.tsx`, `frontend/src/lineage/drafts/GenesisWizard.tsx`, `frontend/src/notebook/notebookApi.notebook.test.ts`, `frontend/src/notebook/notebookApi.ts`, `frontend/src/pipelineDrafts/DraftGraphRoute.test.tsx`, `frontend/src/pipelineDrafts/DraftGraphRoute.tsx`, `frontend/src/report/ReportComposer.tsx`, `frontend/src/report/ReportView.test.tsx`, `frontend/src/report/ReportView.tsx`, `frontend/src/report/ReportWorkspaceContext.tsx`, `frontend/src/report/factTable.test.ts`, `frontend/src/report/factTable.ts`, `frontend/src/report/reportEvidence.test.ts`, `frontend/src/report/reportEvidence.ts`, `frontend/src/runForm/ArmaGarchControls.tsx`, `frontend/src/workbench/WorkbenchRouteContainer.test.tsx`, `frontend/src/workbench/WorkbenchRouteContainer.tsx`, `tests/test_capability_inventory.py`, `tests/test_llm_chat.py`, `tests/test_notebook_artifact_contract.py`, `tests/test_notebook_routes.py`, `tests/test_pipeline_drafts_genesis.py`, `tests/test_report_contract.py`, `tests/test_report_quality.py`, `tests/test_workflow_seam.py`, `backend/workbench/agent/workflow_capability_adapters.py`, `backend/workbench/agent/workflow_capability_registry.py`, `backend/workbench/services/server_run_artifacts.py`, `frontend/src/lineage/drafts/ServerOwnedModelOptions.test.tsx`, `frontend/src/lineage/drafts/ServerOwnedModelOptions.tsx`, `tests/test_workflow_capability_adapters.py`, `tests/test_workflow_capability_registry.py`, `tests/test_workflow_capability_runtime.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/notebook/store.py`, `backend/workbench/agent/notebook/workflow_artifacts.py`, `backend/workbench/services/notebook_source_materialization.py`, `backend/workbench/qa/p7_acceptance.py`, `scripts/p7_acceptance_runner.py`, `tests/test_notebook_planning_agent.py`, `tests/test_notebook_store_append_only.py`, `tests/test_notebook_source_materialization.py`, `tests/test_p7_acceptance_matrix.py`, `frontend/src/workbench/CommandPalette.tsx`, `frontend/src/workbench/CommandPalette.test.tsx`, `backend/workbench/agent/model.py`, `tests/test_llm_providers.py`, `tests/test_agent_tools.py`, `tests/test_memory_integration_context.py`, `tests/test_notebook_graph_projection.py`, `backend/workbench/agent/p7_pack_adapters.py`, `backend/workbench/engine/capabilities.py`, `backend/workbench/http/llm_routes.py`, `backend/workbench/http/runs_routes.py`, `backend/workbench/llm/client.py`, `backend/workbench/qa/notebook_acceptance_evidence.py`, `frontend/src/notebook/NotebookRouteView.notebook.test.tsx`, `frontend/src/notebook/NotebookRouteView.tsx`, `frontend/src/notebook/NotebookSurface.notebook.test.tsx`, `frontend/src/notebook/NotebookSurface.tsx`, `frontend/src/notebook/contracts.notebook.test.tsx`, `frontend/src/notebook/contracts.ts`, `frontend/src/report/reportClient.test.ts`, `frontend/src/report/reportClient.ts`, `tests/test_p7_adoption_registry.py`, `tests/test_p7_workflow_integration.py`
- Protected paths: none
- Dependencies: `P7 adoption baseline: 64 live operations`, `DeepSeek provider remains explicit and no fallback`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_report_contract.py tests/test_llm_routes.py tests/test_llm_chat.py`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_notebook_artifact_contract.py tests/test_notebook_materialization.py tests/test_notebook_trace_chain.py`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_capability_inventory.py tests/test_workflow_runtime.py tests/test_workflow_seam.py tests/test_pipeline_drafts_genesis.py`, `frontend npm test -- --run src/report/reportClient.test.ts src/lineage/drafts/GenesisWizard.test.tsx`
- Known gates: `full gate must run from repository root on host terminal`, `browser acceptance is separate from pytest and full gate`, `no push PR merge tag or release`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-3-cf4-deterministic-materialization (2026-07-27T04:10:00.000Z)

Completed formal devline v1-8-3-cf4-deterministic-materialization; final_state=COMPLETED; failure_lesson_keys=caller-id-fail-closed, optional-identity-compatibility, provenance-get-or-create-identity, stable-materialization-first

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-5-c3-recipe-preflight-projection (2026-08-01T21:47:00.000Z)

Completed formal devline v1-8-5-c3-recipe-preflight-projection; final_state=COMPLETED; failure_lesson_keys=c3-gate-dedicated-basetemp, recipe-preflight-before-draft

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox
