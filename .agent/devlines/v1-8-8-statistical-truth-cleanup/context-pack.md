# Frozen Context Pack

Line: `v1-8-8-statistical-truth-cleanup`
Baseline SHA: `bb735ea2ea8246907f60900ced7dbfd97e13fe2c`

## Objective
# v1.8.8 statistical truth and integration cleanup

## Objective

Make the final v1.8.8 tree describe and expose exactly what it executes. Correct
the Matching and Hurdle inference semantics, remove unused QA compatibility and
duplicate workflow validation, and replace stale status claims with one current
handoff. Preserve fail-closed execution, declaration-derived capability wiring,
and the separation between automated execution and browser acceptance.

## Design

### Matching

- Replace the misleading `distance_policy="logit"` request field with
  `matching_geometry_policy="standardized_covariate_euclidean_v1"`.
- Add `support_distance_policy="absolute_logit_difference"` for propensity
  overlap evidence and the secondary deterministic tie-breaker.
- Replace `common_support_policy="trim"` with
  `common_support_policy="reject_disjoint_no_trim_v1"`.
- Publish the same policies in the typed proposal and result, including
  `trim_applied=false`. Do not retain aliases for the incorrect development-only
  contract.
- Freeze an independently generated R oracle for the declared geometry and
  propensity-support evidence.

### Hurdle inference

- Label the positive-count coefficient inference with
  `standard_error_method="bfgs_inverse_hessian_approximation"` and
  `p_value_status="approximate"`.
- Preserve the label in the bounded result, Agent-visible workflow evidence, and
  Report evidence. The label is data, not prose inferred by an LLM.
- Add a frozen independent R direct-formula oracle for Hurdle estimates and
  inverse-Hessian inference. Tests must compare the committed implementation to
  that oracle and continue to reject non-convergence.

### Workflow capability seam

- One operation-owned path validates the request once, executes once, and
  validates the result once. It returns both the normalized request and the
  execution so runtime persistence does not repeat validation.
- Remove the `validate_request`, `execute`, and `validate_result` constructor
  parameters that are currently ignored and overwritten by `adapter_key`.
- Keep the live declaration derivation and generic orchestrator dispatch intact.

### QA ledger and reachability records

- Delete `LegacyLedgerMigration`, the `migrate` CLI, and migration-only tests.
  A ledger without current write-once control remains rejected; Git history is
  the only reference for the deleted development compatibility path.
- Keep the complete P2 snapshot `(129, 9, 123, 127, 2, 0)` in the P2 inventory
  guard only. P5 retains the historical 18 IDs and verifies their live wiring
  plus zero current gaps without pinning the six global counts again.

### Status truth

- Add a prominent historical/superseded banner to the roadmap and P7 adoption
  design without rewriting their historical body.
- Add one final handoff naming current reachability, P7 automated execution,
  browser acceptance, local-only witness scope, known statistical limitations,
  and the exact remaining gate state.
- Resolve or supersede obsolete open formal events only by appending through
  `scripts/devline_control.py`; regenerate retrospectives through the CLI.

## Explicit non-scope

- No World ID or concrete remote witness provider.
- No claim of human identity or Anti-Agent proof.
- No 64-operation manual browser repetition.
- No broad conversion of every family branch in `p7_pack_adapters.py` to handler
  maps. Those branches are pack-internal maintenance debt, not orchestrator
  dispatch leakage, and a release-wide refactor would add risk without fixing a
  current truth or safety defect.
- No push, PR, merge, tag, or release.

## Acceptance

- New assertions are proven live with behavior-changing mutations.
- Matching proposal, contract, runtime, result, and independent oracle agree.
- Hurdle approximate inference labels survive into Agent and Report evidence and
  match the frozen independent oracle within declared tolerances.
- Workflow validators are each called exactly once per execution.
- No legacy migration command or implementation remains; uncontrolled ledgers
  still fail closed.
- One authoritative P2 snapshot reports `129 / 9 / 123 / 127 / 2 / 0`.
- Focused backend/frontend tests, formal verification, `git diff --check`, and
  the host full gate pass on the final source commit.

## Boundary
- Affected paths: `backend/workbench/contracts/model`, `backend/workbench/engine/packs`, `backend/workbench/agent`, `backend/workbench/qa`, `backend/workbench/services`, `backend/workbench/report_contract.py`, `backend/workbench/report_quality.py`, `frontend/src/report`, `scripts/p7_acceptance_runner.py`, `tests`, `docs/superpowers/roadmap`, `docs/superpowers/specs`, `docs/superpowers/handoff`
- Allowed paths: `backend/workbench/contracts/model/matching.py`, `backend/workbench/contracts/model/glm_extensions.py`, `backend/workbench/engine/packs/matching/runtime.py`, `backend/workbench/engine/packs/glm_extensions/runtime.py`, `backend/workbench/agent/p7_pack_adapters.py`, `backend/workbench/agent/p7_pack_registry.py`, `backend/workbench/agent/workflow_capability_registry.py`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/qa/p7_acceptance.py`, `backend/workbench/services/server_run_artifacts.py`, `backend/workbench/report_contract.py`, `backend/workbench/report_quality.py`, `frontend/src/report/factTable.ts`, `frontend/src/report/factTable.test.ts`, `frontend/src/report/reportEvidence.ts`, `frontend/src/report/reportEvidence.test.ts`, `scripts/p7_acceptance_runner.py`, `tests/test_matching_pack.py`, `tests/test_glm_extensions_pack.py`, `tests/test_p7_adoption_calls.py`, `tests/test_p7_adoption_registry.py`, `tests/test_p7_workflow_integration.py`, `tests/test_workflow_capability_registry.py`, `tests/test_workflow_capability_runtime.py`, `tests/test_p7_acceptance_matrix.py`, `tests/test_capability_inventory.py`, `tests/test_p5_reachability_gaps.py`, `tests/fixtures/matching/generate_oracle.R`, `tests/fixtures/matching/oracle_cases.json`, `tests/fixtures/glm_extensions/generate_oracle.R`, `tests/fixtures/glm_extensions/reference_inputs.json`, `tests/fixtures/glm_extensions/oracle_results.json`, `docs/superpowers/roadmap/2026-08-08-remaining-phase-goals.md`, `docs/superpowers/specs/2026-08-08-p7-capability-adoption.md`, `docs/superpowers/specs/2026-08-13-v1.8.8-statistical-truth-cleanup-design.md`, `docs/superpowers/handoff/2026-08-13-v1.8.8-final-status-handoff.md`, `backend/workbench/agent/context_tools.py`, `tests/test_agent_context_tools.py`, `tests/fixtures/glm_extensions/generate_hurdle_oracle.R`
- Protected paths: `backend/workbench/orchestrator`, `backend/workbench/agent/capability_contract.py`, `backend/workbench/agent/workflow_contracts.py`
- Dependencies: none
- Tests: `tests/test_matching_pack.py`, `tests/test_glm_extensions_pack.py`, `tests/test_p7_workflow_integration.py`, `tests/test_workflow_capability_registry.py`, `tests/test_workflow_capability_runtime.py`, `tests/test_p7_acceptance_matrix.py`, `tests/test_capability_inventory.py`, `tests/test_p5_reachability_gaps.py`
- Known gates: `host bash scripts/gate.sh --full`, `frontend TypeScript and Vitest`, `formal devline verification`, `no external witness claim`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-3-cf2-dependency-bundles (2026-07-26T14:13:57.917Z)

Completed formal devline v1-8-3-cf2-dependency-bundles; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-3-cf3-validation-runtime (2026-07-27T12:25:00.000Z)

Completed formal devline v1-8-3-cf3-validation-runtime; final_state=COMPLETED; failure_lesson_keys=authoring-source-allowlist, cf3-validation-runtime-red, fms-event-draft-validation, protocol-identity-binding

### v1-8-5-c3-recipe-preflight-projection (2026-08-01T21:47:00.000Z)

Completed formal devline v1-8-5-c3-recipe-preflight-projection; final_state=COMPLETED; failure_lesson_keys=c3-gate-dedicated-basetemp, recipe-preflight-before-draft

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work

### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass

### v1-8-5-a2-memory-settings-management (2026-08-01T12:19:00.000Z)

Completed formal devline v1-8-5-a2-memory-settings-management; final_state=COMPLETED; failure_lesson_keys=memory-library-management-safe-identification, memory-retrieval-storage-failure-is-503, notebook-memory-server-owned-settings, preference-store-reject-symlink-ancestor, preference-write-complete-before-replace, tdd-red-a2-local-preferences-confirmation

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox
