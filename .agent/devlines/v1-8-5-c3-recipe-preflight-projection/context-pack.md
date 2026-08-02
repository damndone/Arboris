# Frozen Context Pack

Line: `v1-8-5-c3-recipe-preflight-projection`
Baseline SHA: `4013e04816f219588cde9396ac66b9ec331a4cbe`

## Objective
# v1.8.5 C3 — Recipe Preflight and Result Projection Objective

This is the bounded completion slice for C2 in
`2026-07-31-v1.8.5-typed-memory-and-model-family-design.md`. The parent
design remains the only version-scope authority.

## Objective

Complete the two RecipeContract promises that C2 left as labels rather than
enforced behaviour: validate the selected time/value series before a Dataset
Genesis Draft is persisted, and publish a deterministic, bounded public result
projection for each admitted Recipe.

## Scope

- Add a server-owned Recipe input preflight at Dataset Genesis materialization.
  It resolves only the verified upload already pinned by the Notebook, uses the
  selected Recipe's existing owner contract, and refuses a Draft when the
  current source violates a blocking time-series prerequisite.
- Reuse pack-owned validation semantics rather than reimplementing estimator
  mathematics: ETS duplicate timestamps, interior missing values, regular
  calendar gaps/irregularity, minimum sample size, multiplicative positivity,
  and constant series; ARMA/GARCH time/value parsing, index semantics,
  blocking diagnostics, and transform eligibility.
- Preserve the existing execution-time validation as defence in depth. A
  preflight never repairs, fills, reorders source data invisibly, infers a
  cadence, changes a fitted model, or discloses raw rows to the provider.
- Fail closed if the verified source cannot be read within the existing bounded
  source-inspection policy; include a stable, actionable Recipe error code.
- Replace opaque Recipe `result_projection` labels with published, recipe-owned
  bounded projections that reuse already-persisted artifact types. Extend the
  Agent public-artifact reader only where a Recipe has no current projection;
  do not create a packet, artifact id, schema version, or unbounded raw-series
  exposure.
- Exercise accepted and rejected paths through materialization and Agent public
  evidence. Existing Table/Report artifacts remain the source of truth; this
  slice may not redesign their UI or alter estimator output.

## Explicit non-scope

- No estimator, numerical method, diagnostic algorithm, artifact registry,
  packet-schema registry, model-options vocabulary, default-target expansion,
  memory mutation, time-series multi-step workflow, or automatic frequency
  inference.
- No new artifact type or unaudited artifact payload. No raw source rows,
  arbitrary files, or visual conclusion are surfaced to an Agent.
- No frontend redesign and no change to Proposal/Risk confirmation or execution
  authority.

## Acceptance

Tests must first fail, then pass, for an ETS blocking source and an
ARMA/GARCH blocking/transform-ineligible source before any Draft is written.
Valid sources must retain the existing Draft and execution path. Recipe public
results must be bounded, contain artifact-backed evidence references, and
refuse unsupported or malformed payloads without falling back to an OLS view.
Existing ETS and ARMA/GARCH known-truth tests, focused Notebook/Agent evidence
tests, naming gate, and TypeScript check remain green. Browser acceptance, if
run, must distinguish visible Draft rejection from executed-result evidence.

## Boundary
- Affected paths: `docs/superpowers/specs/2026-08-01-v1.8.5-c3-recipe-preflight-projection-objective.md`, `docs/superpowers/specs/2026-08-01-v1.8.5-c3-recipe-preflight-projection-event.json`, `backend/workbench/agent/recipe_contracts.py`, `backend/workbench/agent/notebook/materialization.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/recipes/ets.py`, `tests/test_recipe_contracts.py`, `tests/test_notebook_materialization.py`, `tests/test_agent_context_tools.py`, `tests/test_no_exercise_specific_naming.py`
- Allowed paths: `docs/superpowers/specs/2026-08-01-v1.8.5-c3-recipe-preflight-projection-objective.md`, `docs/superpowers/specs/2026-08-01-v1.8.5-c3-recipe-preflight-projection-event.json`, `backend/workbench/agent/recipe_contracts.py`, `backend/workbench/agent/notebook/materialization.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/recipes/ets.py`, `tests/test_recipe_contracts.py`, `tests/test_notebook_materialization.py`, `tests/test_agent_context_tools.py`, `tests/test_no_exercise_specific_naming.py`
- Protected paths: `backend/workbench/engine/packs/ets/input.py`, `backend/workbench/engine/packs/arma_garch/input.py`, `backend/workbench/contracts/model/ets.py`, `backend/workbench/contracts/model/arma_garch.py`, `backend/workbench/artifacts.py`, `frontend`
- Dependencies: `v1-8-5-c2-time-series-recipe`, `v1-8-5-b3-recipe-default-materialization`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_recipe_contracts.py tests/test_notebook_materialization.py tests/test_agent_context_tools.py tests/test_no_exercise_specific_naming.py -q`, `cd frontend && ./node_modules/.bin/tsc --noEmit`
- Known gates: `Read generated context pack, global rules, and required retrospectives before edits.`, `Recipe preflight uses a verified, bounded upload path and fails closed on unreadable or truncated source; it never exposes raw rows to the provider.`, `Existing execution-time pack validation is protected defence in depth; no estimator changes.`, `No new artifact type or packet schema before the planned artifact-schema work.`, `Do not stop existing 5177 Workbench/Vite processes or close the user browser tab.`

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

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work

### v1-8-3-cf4-deterministic-materialization (2026-07-27T04:10:00.000Z)

Completed formal devline v1-8-3-cf4-deterministic-materialization; final_state=COMPLETED; failure_lesson_keys=caller-id-fail-closed, optional-identity-compatibility, provenance-get-or-create-identity, stable-materialization-first
