# Frozen Context Pack

Line: `v1-8-5-b3-recipe-default-materialization`
Baseline SHA: `81b704ad008397e7618e58f67730245831181d0b`

## Objective
# v1.8.5 B3 — Recipe Default Materialization Objective

This is a deliberately narrow correction slice of
`2026-07-31-v1.8.5-typed-memory-and-model-family-design.md`. The parent
design remains the only version-scope authority.

## Objective

Make an already approved, current `suggest_default` for a published
time-series Recipe usable in the real Notebook planning path. A provider may
omit `model_options.time_index_semantics` only when the server has supplied an
exact eligible default for that Recipe; before Draft validation the server must
resolve the field through that default or reject the option. A missing,
expired, mismatched, conflicting, or cross-Recipe memory must never fill the
field.

## Scope

- Preserve the final Recipe planning disclosure gate: every ETS or ARMA/GARCH
  Draft has a resolved `time_index_semantics` before validation/materialization.
- Replace the planner-facing instruction that unconditionally requires the
  provider to state the field explicitly with the exact conditional rule above.
- Extend the server-owned Notebook memory projection with a bounded,
  deterministic per-Recipe retrieval bridge for only published
  `DefaultTargetContract` Recipe targets. The bridge must use existing runtime
  validity, scope, vocabulary, byte, and entry controls, deduplicate results,
  and retain the existing generic projection behaviour.
- Bind no target outside the proposal's selected Recipe. Existing
  `apply_memory_defaults` remains the only proposal mutation boundary and
  continues to preserve explicit-value precedence and provenance.
- Add red-first tests for real local-runtime retrieval, conditional planner
  instructions, correct ETS application, wrong-Recipe refusal, and absent or
  invalid-default rejection. Perform a visible local Workbench planning/Draft
  acceptance with an approved memory if the current host/provider is available.

## Explicit non-scope

- No change to generic domain-memory predicate semantics, vector/semantic
  retrieval, frequency inference, estimator selection, ARMA/GARCH orders,
  execution authorization, or automatic execution.
- No new Recipe, model family, estimator, artifact, packet schema, UI redesign,
  or arbitrary model-option patching.
- No weakening of current evidence, source-column, Proposal/Risk, vocabulary,
  verifier, conflict, or provenance gates.

## Acceptance

The new tests must fail before production changes and pass after them. Focused
memory, Notebook route/planning, Recipe, naming, and TypeScript checks must
remain green. Browser evidence must state whether it proves planning/Draft
default visibility only or an executed analysis separately.

## Boundary
- Affected paths: `backend/workbench/agent/context_compiler.py`
- Allowed paths: `backend/workbench/http/notebook_routes.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/recipe_contracts.py`, `backend/workbench/agent/context_compiler.py`, `tests/test_memory_integration_context.py`, `tests/test_notebook_planning_agent.py`, `tests/test_notebook_routes.py`, `tests/test_recipe_contracts.py`, `docs/superpowers/specs/2026-08-01-v1.8.5-b3-recipe-default-materialization-objective.md`
- Protected paths: `docs/superpowers/specs/2026-07-31-v1.8.5-typed-memory-and-model-family-design.md`, `docs/superpowers/plans/2026-08-01-v1.8.5-implementation-plan.md`, `backend/workbench/domain_memory/retrieval.py`, `backend/workbench/domain_memory/local_runtime.py`, `backend/workbench/agent/notebook/memory_defaults.py`
- Dependencies: `v1-8-5-a3-memory-candidate-review`, `v1-8-5-b2-time-series-default-targets`, `v1-8-5-c2-time-series-recipe`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_memory_integration_context.py tests/test_notebook_planning_agent.py tests/test_notebook_routes.py tests/test_recipe_contracts.py tests/test_no_exercise_specific_naming.py -q`, `npx tsc --noEmit`
- Known gates: `Do not stop Vite port 5177 or close the in-app Browser tab during local acceptance.`, `Memory retrieval must remain bounded and fail-closed; no generic predicate semantic widening.`, `Do not pipe npx tsc output to tail; use its direct exit status.`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-5-a2-memory-settings-management (2026-08-01T12:19:00.000Z)

Completed formal devline v1-8-5-a2-memory-settings-management; final_state=COMPLETED; failure_lesson_keys=memory-library-management-safe-identification, memory-retrieval-storage-failure-is-503, notebook-memory-server-owned-settings, preference-store-reject-symlink-ancestor, preference-write-complete-before-replace, tdd-red-a2-local-preferences-confirmation

### v1-8-5-a1-local-memory-bootstrap (2026-08-01T11:27:52.000Z)

Completed formal devline v1-8-5-a1-local-memory-bootstrap; final_state=COMPLETED; failure_lesson_keys=tdd-red-local-memory-bootstrap

### v1-8-3-cf4-notebook-planner-projection-r1 (2026-07-26T23:16:01.000Z)

Completed formal devline v1-8-3-cf4-notebook-planner-projection-r1; final_state=COMPLETED; failure_lesson_keys=bounded-planner-projection-inputs, consumer-admission-facts-align-across-contracts, scope-aware-bound-option-revalidation, tdd-red-before-planner-projection
