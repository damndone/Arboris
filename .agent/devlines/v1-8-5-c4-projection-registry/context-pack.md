# Frozen Context Pack

Line: `v1-8-5-c4-projection-registry`
Baseline SHA: `c68c4f94d1db34d7fd222ce7c84d0da0b4c4dfdf`

## Objective
# v1.8.5 C4 — Recipe-owned Public Projection Registry

This is a narrow follow-up to the v1.8.5 C3 Recipe projection boundary. The
parent design remains the only version-scope authority.

## Objective

Replace the Agent context reader's model-type-specific public-result dispatch
with a server-owned registry that resolves each published Recipe to exactly
one bounded projection builder. Existing ETS and ARMA/GARCH result shapes,
artifact references, and fail-closed behaviour must remain unchanged.

## Scope

- Add a lazy, immutable-in-use projection registry under
  `backend/workbench/agent/recipes/registry.py`.
- Let `RecipeContract` resolve its published projection through that registry;
  keep the serialized projection identifier backward compatible.
- Route ETS and ARMA/GARCH public evidence through the registry from
  `context_tools.py`.
- Add focused tests for registry ownership, unknown Recipe refusal, and the
  existing ETS/ARMA evidence envelopes.

## Explicit non-scope

- No frontend work, estimator changes, artifact changes, packet schema work,
  raw-series exposure, or new Recipe.
- No change to Proposal/Risk authority, memory defaults, or execution.

## Acceptance

The new registry test must fail before implementation and pass afterward. The
focused Recipe/Agent context suites, naming gate, TypeScript check, and diff
check must pass. The result remains bounded and artifact-backed; unsupported
Recipes return a stable reason code rather than falling back to OLS.

## Boundary
- Affected paths: `backend/workbench/agent/recipes/registry.py`, `backend/workbench/agent/recipe_contracts.py`, `backend/workbench/agent/context_tools.py`
- Allowed paths: `docs/superpowers/specs/2026-08-01-v1.8.5-c4-projection-registry-objective.md`, `backend/workbench/agent/recipes/registry.py`, `backend/workbench/agent/recipe_contracts.py`, `backend/workbench/agent/context_tools.py`, `tests/test_recipe_contracts.py`, `tests/test_agent_context_tools.py`, `tests/test_no_exercise_specific_naming.py`
- Protected paths: `frontend`, `backend/workbench/engine`, `backend/workbench/contracts`, `backend/workbench/domain_memory`, `backend/workbench/model_options.py`
- Dependencies: `v1-8-5-c3-recipe-preflight-projection`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_recipe_contracts.py tests/test_agent_context_tools.py tests/test_no_exercise_specific_naming.py -q`, `cd frontend && ./node_modules/.bin/tsc --noEmit`
- Known gates: `Do not stop the existing Workbench services or browser tab.`, `Use the direct tsc binary; do not pipe through tail.`, `The nested browser environment may block sandbox or localhost acceptance; do not bypass the UI boundary.`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-5-c3-recipe-preflight-projection (2026-08-01T21:47:00.000Z)

Completed formal devline v1-8-5-c3-recipe-preflight-projection; final_state=COMPLETED; failure_lesson_keys=c3-gate-dedicated-basetemp, recipe-preflight-before-draft

### v1-8-5-b3-recipe-default-materialization (2026-08-01T20:48:00.000Z)

Completed formal devline v1-8-5-b3-recipe-default-materialization; final_state=COMPLETED; failure_lesson_keys=external-memory-projection-utf8-budget, generic-memory-omissions-must-fit-context-contract, memory-payload-budget-is-utf8-bytes, memory-projection-budget-must-cover-envelope, recipe-default-bridge-currentness-and-omission-budget, recipe-default-groups-must-be-budget-atomic, recipe-default-materialization-before-provider-choice, recipe-default-truncation-must-fail-closed, recipe-defaults-not-generic-provider-hints

### v1-8-5-c2-time-series-recipe (2026-08-01T18:28:51.000Z)

Completed formal devline v1-8-5-c2-time-series-recipe; final_state=COMPLETED; failure_lesson_keys=agent-activity-requires-terminal-outcome, browser-recipe-acceptance-requires-provider-completion, c2-vocabulary-test-before-gate, dataset-recipe-genesis-must-not-become-rerun, fms-event-file-repository-relative, fms-lesson-key-normalization, fms-preventability-must-use-supported-enum, forest-presentation-must-not-mask-corrected-result-type, live-provider-failure-requires-local-trace-diagnosis-before-retry, live-recipe-planning-must-prove-model-options-before-draft, none-planning-deadline-must-not-derive-a-short-budget, provider-call-timeout-is-independent-from-total-planning-deadline, recipe-contract-before-admission, recipe-correction-must-republish-required-inputs, recipe-graph-type-must-read-result-envelope, recipe-server-owned-options-require-public-filter-and-binding, recipe-source-binding-must-remain-server-owned, recipe-vocabulary-must-reference-owner-enums, server-recommendation-validation-needs-bounded-correction, timeout-policy-change-requires-route-contract-update

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### wo-a-live-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-live-agent; final_state=CLOSED; failure_lesson_keys=none
