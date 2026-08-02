# Frozen Context Pack

Line: `v1-8-5-c2-time-series-recipe`
Baseline SHA: `ce094cfd10a4e27e17806d5c70e3855883c6db3e`

## Objective
# v1.8.5 C2 — Time-Series Recipe Objective

This is the bounded FMS objective for C2 of
`2026-07-31-v1.8.5-typed-memory-and-model-family-design.md`. The parent
design remains the only version-scope authority.

## Objective

Admit the existing ETS and ARMA/GARCH capabilities to Notebook and Agent
genesis through a server-owned `RecipeContract`. A Recipe has time/value input
semantics and its own published model-options vocabulary; it is not a
regression branch with empty predictors.

## Scope

- Define `time_series.ets` and `time_series.arma_garch` RecipeContracts with
  input-column validation, published option fields, expected artifacts and
  bounded Agent/Table/Report result projections.
- Compile a selected Recipe only into an independent dataset `model.genesis`
  Draft. The server validates `time_column` and `value_column` against the
  current dataset, validates `model_options` through the existing owner
  contract, and preserves server-owned binding facts.
- Genesis Draft validation derives the absence of regression predictors from
  the RecipeContract. It does not retain an ARMA/GARCH model-name exception,
  and it never treats a Recipe as an `operation.multi_step` regression branch.
- Add TDD coverage for accepted ETS/ARMA-GARCH paths and refusal paths:
  missing time/value columns, invalid or unconfirmed ARMA/GARCH transforms,
  missing predictors being accepted only for recipes, and legacy regression
  genesis still requiring the fields its ModelFamilyContract declares.

## Explicit non-scope

- No estimator, diagnostics, numerical-method, model-options-contract, pack,
  capability-registration, custom-capability, memory-default, or frontend
  redesign.
- No time-series multi-step workflow, model-family alias, automatic frequency
  inference, visual conclusion without an evidence packet, or change to
  historical manual Runs.

## Acceptance

Tests must first fail, then pass for both RecipeContracts and their Notebook
materialization. Existing ETS and ARMA/GARCH known-truth tests must remain
green. A later browser acceptance run must demonstrate Dataset → Notebook
option → Draft → confirmation → execution → Result/Table/Report for both
recipes, while unsupported or incomplete inputs fail closed before a Draft is
persisted.

## Boundary
- Affected paths: `backend/workbench/lineage/project_forest.py`
- Allowed paths: `docs/superpowers/specs/2026-08-01-v1.8.5-c2-time-series-recipe-objective.md`, `backend/workbench/agent/recipe_contracts.py`, `backend/workbench/agent/notebook/materialization.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/notebook/service.py`, `backend/workbench/agent/notebook/vocabulary.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/lineage/pipeline_drafts.py`, `backend/workbench/services/draft_materialization.py`, `backend/workbench/services/draft_service.py`, `backend/workbench/engine/packs/arma_garch/split.py`, `backend/workbench/engine/stages/recording.py`, `backend/workbench/lineage/headset.py`, `backend/workbench/lineage/project_forest.py`, `tests/test_recipe_contracts.py`, `tests/test_notebook_materialization.py`, `tests/test_notebook_planning_agent.py`, `tests/test_notebook_routes.py`, `tests/test_notebook_vocabulary.py`, `tests/test_ets_wiring.py`, `tests/test_agent_arma_garch_proposal.py`, `tests/test_pipeline_drafts_genesis.py`, `tests/models/ets/test_ets_known_truth.py`, `tests/models/arma_garch/test_known_truth.py`, `tests/test_graph_headset.py`, `tests/test_project_forest_api.py`, `frontend/src/aiActivity/aiActivityLog.ts`, `frontend/src/aiActivity/aiActivityLog.test.ts`, `frontend/src/workbench/panels/AiActivityPanel.tsx`, `frontend/src/workbench/panels/AiActivityPanel.test.tsx`, `frontend/src/notebook/NotebookRouteView.tsx`, `frontend/src/notebook/NotebookRouteView.notebook.test.tsx`, `frontend/src/report/ReportView.tsx`, `frontend/src/report/ReportView.test.tsx`
- Protected paths: `backend/workbench/engine`, `backend/workbench/contracts`, `backend/workbench/model_options.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/domain_memory`, `frontend`, `docs/superpowers/plans`
- Dependencies: `v1-8-5-b1-default-target-registry`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_recipe_contracts.py tests/test_notebook_materialization.py tests/test_notebook_planning_agent.py tests/test_notebook_vocabulary.py tests/test_ets_wiring.py tests/test_agent_arma_garch_proposal.py tests/test_pipeline_drafts_genesis.py tests/models/ets/test_ets_known_truth.py tests/models/arma_garch/test_known_truth.py -q`, `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_no_exercise_specific_naming.py -q`, `npx tsc --noEmit`
- Known gates: `Do not start or retain Vite during backend gates.`, `Current Codex nested Seatbelt may make sandbox-exec fail with sandbox_apply: Operation not permitted; record it and do not skip or xfail.`, `Run TypeScript directly; do not pipe npx tsc through tail.`

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

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-3-cf4-deterministic-materialization (2026-07-27T04:10:00.000Z)

Completed formal devline v1-8-3-cf4-deterministic-materialization; final_state=COMPLETED; failure_lesson_keys=caller-id-fail-closed, optional-identity-compatibility, provenance-get-or-create-identity, stable-materialization-first

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work
