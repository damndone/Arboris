# Frozen Context Pack

Line: `v1-8-5-notebook-capability-admission`
Baseline SHA: `11adfb7e27701af461a59a3cae44fb6967a02523`

## Objective
# v1.8.5 slice objective — Notebook workflow capability admission

## Objective

Make the Notebook planner's native capability catalog derive its
workflow-executable set from server-owned `ModelFamilyContract` and
`RecipeContract` registrations. Legacy UI aliases such as `glm:*` remain
available to the manual capability surface, but must not be advertised to the
Notebook Agent until they publish an independent contract for inputs, result
shape, diagnostics, and artifact projection.

This is a general admission rule, not a model-specific prompt restriction:
new model families become Notebook-plannable by registering their contract;
the planner must never infer workflow eligibility from the presence of a
handler or a legacy UI alias alone.

## Scope

- Add one server-owned helper for the native Notebook workflow capability set.
- Use it when the Notebook route builds its native planning manifest and when
  it creates a persisted source projection's available-capability list.
- Preserve deployment-provided capability projections; this slice does not
  change custom capability authority or manual `/capabilities` output.
- Add focused regression tests proving the contract-derived allowlist excludes
  uncontracted aliases and includes the registered regression/Recipe families.

## Explicit non-goals

- Do not remove or rename legacy manual capabilities.
- Do not add a new model family, estimator, alias, prompt exception, or
  frontend-only filter.
- Do not change estimation, artifact payloads, proposal authorization, or
  browser behavior.

## Acceptance evidence

- A red test demonstrates that the native Notebook set is not currently
  contract-derived.
- Focused Notebook route/planning tests pass after the change.
- Existing model-family, Recipe, and frontend type checks remain green.
- No browser-acceptance or full-gate claim is made by this slice.

## Boundary
- Affected paths: `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/http/notebook_routes.py`, `tests/test_notebook_routes.py`, `docs/superpowers/specs/2026-08-01-v1.8.5-notebook-capability-admission-objective.md`
- Allowed paths: `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/http/notebook_routes.py`, `tests/test_notebook_routes.py`, `docs/superpowers/specs/2026-08-01-v1.8.5-notebook-capability-admission-objective.md`
- Protected paths: `backend/workbench/engine/capabilities.py`, `backend/workbench/agent/recipe_contracts.py`, `frontend/src`, `docs/superpowers/specs/2026-07-31-v1.8.5-typed-memory-and-model-family-design.md`
- Dependencies: `v1.8.5 C1 model family and C2 Recipe contracts remain server-owned`, `manual /capabilities output remains unchanged`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_notebook_routes.py -k notebook_capability_admission`, `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/pytest -q tests/test_workflow_runtime.py -k model_family`
- Known gates: `frontend tsc remains green`, `browser acceptance and full gate are separate evidence`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-5-a2-memory-settings-management (2026-08-01T12:19:00.000Z)

Completed formal devline v1-8-5-a2-memory-settings-management; final_state=COMPLETED; failure_lesson_keys=memory-library-management-safe-identification, memory-retrieval-storage-failure-is-503, notebook-memory-server-owned-settings, preference-store-reject-symlink-ancestor, preference-write-complete-before-replace, tdd-red-a2-local-preferences-confirmation

### v1-8-5-a1-local-memory-bootstrap (2026-08-01T11:27:52.000Z)

Completed formal devline v1-8-5-a1-local-memory-bootstrap; final_state=COMPLETED; failure_lesson_keys=tdd-red-local-memory-bootstrap

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-cf4-server-recommendation-stage (2026-07-27T06:24:00.000Z)

Completed formal devline v1-8-3-cf4-server-recommendation-stage; final_state=COMPLETED; failure_lesson_keys=server-recommendation-red

### v1-8-3-cf4-notebook-planner-projection-r1 (2026-07-26T23:16:01.000Z)

Completed formal devline v1-8-3-cf4-notebook-planner-projection-r1; final_state=COMPLETED; failure_lesson_keys=bounded-planner-projection-inputs, consumer-admission-facts-align-across-contracts, scope-aware-bound-option-revalidation, tdd-red-before-planner-projection

### v1-8-3-cf4-notebook-provider-injection (2026-07-26T22:45:00.000Z)

Completed formal devline v1-8-3-cf4-notebook-provider-injection; final_state=COMPLETED; failure_lesson_keys=formal-rescope-boundary, tdd-red-before-provider-injection

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission
