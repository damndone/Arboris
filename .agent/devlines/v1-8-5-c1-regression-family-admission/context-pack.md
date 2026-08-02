# Frozen Context Pack

Line: `v1-8-5-c1-regression-family-admission`
Baseline SHA: `8d7c74415d5d4f6c9c3625953e0c42b3d3c22f73`

## Objective
# v1.8.5 C1 — Regression Family Admission Objective

This is the bounded FMS objective for C1 of
`2026-07-31-v1.8.5-typed-memory-and-model-family-design.md`.  The parent
design is the only version-scope authority.

## Objective

Complete the remaining workflow admission of existing native regression
families through the server-owned `ModelFamilyContract` registry: Logit,
Probit, Poisson, Negative Binomial, IV/2SLS, and TWFE DID.  Preserve the
already admitted OLS, Panel OLS, CS-DID, SA-DID, and DCDH contracts as
regression evidence, not as new delivery.

## Scope

- Each newly admitted family declares its input preflight, Genesis parameter
  construction, expected artifacts, result shape, diagnostics boundary, and
  published Notebook vocabulary in the same contract.
- IV requires non-overlapping endogenous and instrument column lists; TWFE DID
  requires panel identity, time, and one explicit treatment definition.
- A workflow and Notebook proposal either execute the selected family as
  declared or fail closed with an actionable message. They never fallback to
  OLS, assume OLS confidence-interval artifacts for a non-OLS result, or
  accept an inference option that the selected existing estimator does not
  consume.
- Existing numerical estimators and golden fixtures remain unchanged.

## Explicit non-scope

- No new estimator, `glm:*` alias, manual-form redesign, RecipeContract,
  time-series default, memory-default expansion, custom capability change, or
  exercise-specific behavior.

## Acceptance

Tests first fail and then pass for every new family’s valid path and refusal
path, including non-binary Logit/Probit, non-count Poisson/Negative Binomial,
incomplete/underidentified IV, and incomplete DID definitions.  Existing
goldens, Panel FE/dummy-FE oracle, and prior DID workflow admission remain
unchanged.

## Boundary
- Affected paths: `docs/superpowers/specs/2026-08-01-v1.8.5-c1-regression-family-admission-objective.md`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/agent/notebook/materialization.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/notebook/vocabulary.py`, `tests/test_workflow_runtime.py`, `tests/test_notebook_materialization.py`, `tests/test_notebook_planning_agent.py`, `tests/test_engine_golden.py`, `tests/test_engine_iv.py`, `tests/test_did_wiring.py`, `tests/test_cs_did_wiring.py`, `tests/test_sa_did_wiring.py`
- Allowed paths: `docs/superpowers/specs/2026-08-01-v1.8.5-c1-regression-family-admission-objective.md`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/agent/notebook/materialization.py`, `backend/workbench/agent/notebook/planning_agent.py`, `backend/workbench/agent/notebook/vocabulary.py`, `tests/test_workflow_runtime.py`, `tests/test_notebook_materialization.py`, `tests/test_notebook_planning_agent.py`, `tests/test_engine_golden.py`, `tests/test_engine_iv.py`, `tests/test_did_wiring.py`, `tests/test_cs_did_wiring.py`, `tests/test_sa_did_wiring.py`
- Protected paths: `backend/workbench/econometrics/runner.py`, `backend/workbench/engine/capabilities.py`, `backend/workbench/engine/stages/estimation.py`, `backend/workbench/engine/did_spec.py`, `backend/workbench/engine/iv_spec.py`, `backend/workbench/services/draft_materialization.py`, `backend/workbench/domain_memory`, `backend/workbench/capability_factory`, `frontend`, `tests/golden`, `.agent/devlines`
- Dependencies: `v1-8-5-b1-default-target-registry`, `v1-8-5-typed-memory-model-family`
- Tests: `tests/test_workflow_runtime.py - model family contract and workflow execution`, `tests/test_notebook_materialization.py - fail-closed Genesis Draft materialization`, `tests/test_notebook_planning_agent.py - published capability and evidence-bound planning`, `tests/test_engine_golden.py - unchanged native numerical goldens`, `tests/test_engine_iv.py and tests/test_did_wiring.py - existing IV and DID regression guards`
- Known gates: `Run link-shared-deps.sh with the absolute worktree path before dependency-based checks if links are absent.`, `Do not pipe npx tsc to tail and inspect tail status; run typecheck directly when frontend scope exists.`, `gate.sh refuses a running Vite process; do not start Vite for this backend-only line.`, `Codex nested Seatbelt can make sandbox-exec return sandbox_apply Operation not permitted; classify as host-gate evidence, never skip or xfail it.`

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

### v1-8-4-model-term-reuse (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-model-term-reuse; final_state=COMPLETED; failure_lesson_keys=none
