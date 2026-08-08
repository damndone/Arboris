# Frozen Context Pack

Line: `p3-capability-registration`
Baseline SHA: `a5efa90c6fc3a5208602b89873e9c366745a19f3`

## Objective
# P3 Capability Registration Objective

At baseline a5efa90, make one workflow capability declaration sufficient to register the capability across the operation registry, proposal/editable schema, workflow vocabulary, notebook planning contracts, node context inspection, route rendering, and unified capability inventory.

Use the live WORKFLOW_STEP_SPEC_CONTRACTS declaration as the only source. Derive the operation tuple and produces/consumes/replayable projections from it, support closed field enums, and project capability_kind plus top_level_exposure_note into CapabilityContract. Keep reachability exemptions separate: the P7 pack seam must have proposed_by=(), composable_as=(operation_id,), reachability_exempt_reason=None.

Use the verified P7 operation ID repeated_measures_anova.repeated_only and fields response_column, subject_column, within_factor_columns, between_factor_column, correction; correction values are greenhouse_geisser, huynh_feldt, and none. Prove injection through tests without a second inventory list.

Do not change P0/P1/P2 behavior, workflow_runtime.py, or orchestrator dispatch. P7 numerical execution remains later work. Required evidence is a real red test followed by green implementation tests, behavior-changing mutation failures with anchored/hash-checked harnesses, focused regression tests, and the backend full suite from the repository root using only the valid R-fixture ignores.

## Boundary
- Affected paths: `docs/superpowers/plans/2026-08-08-v1.8.8-p3-capability-registration-objective.md`, `docs/superpowers/plans/2026-08-08-v1.8.8-p3-capability-registration.md`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/capability_contract.py`, `tests/test_capability_registration.py`
- Allowed paths: `docs/superpowers/plans/2026-08-08-v1.8.8-p3-capability-registration-objective.md`, `docs/superpowers/plans/2026-08-08-v1.8.8-p3-capability-registration.md`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/capability_contract.py`, `tests/test_capability_registration.py`
- Protected paths: `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/orchestrator`
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_capability_registration.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_workflow_seam.py tests/test_agent_generic_workflow.py tests/test_capability_inventory.py tests/test_capability_workflow_contract.py -q`
- Known gates: `PYTHONPATH=backend .venv/bin/python -m pytest tests -q --ignore=tests/test_cs_did_oracle.py --ignore=tests/test_cs_did_clustering.py`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-5-notebook-capability-admission (2026-08-01T22:35:30.000Z)

Completed formal devline v1-8-5-notebook-capability-admission; final_state=COMPLETED; failure_lesson_keys=notebook-admission-must-require-published-contract

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none
