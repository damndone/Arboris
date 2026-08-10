# Frozen Context Pack

Line: `p6-p7-capability-adoption`
Baseline SHA: `ebba33f18037d3569f3d39dae8773b21a870e6e5`

## Objective
# P6/P7 Capability Adoption Objective

At baseline `ebba33f18037d3569f3d39dae8773b21a870e6e5`, integrate every
operation declared by the frozen P7 source into Arboris's existing typed Agent
workflow seam. The current source audit is the truth: 62 unique IDs are
declared across the live `*_OPERATION_IDS` collections, and the power-analysis
contract additionally exposes three designs by four solve targets without an
operation-ID collection. Make those 12 combinations explicit in the adoption
contract and test them all.

One declaration must automatically supply the closed editable schema,
OperationRegistry definition, workflow vocabulary, planning/inspect/route
visibility, capability inventory identity, reachability path, typed input
adapter, result validation, provenance, and generic workflow execution. Keep
pack operations composable through `operation.multi_step` unless a separately
verified top-level surface is enabled. Do not add an orchestrator branch per
operation, do not hide missing adapters as exemptions, and do not silently
discard a non-frame input.

Selectively adopt only the frozen P7 contract/runtime/test material; preserve
P0/P1/P2, Agent foundations, frontend, survey mathematics, and shared-stage
boundaries. Prove correctness with TDD red tests, behavior-changing mutation
evidence, external numerical oracles, focused workflow execution, formal FMS
verification, and the host full gate. Browser and real-person natural-language
acceptance remain explicitly deferred to the final P7 phase.

## Boundary
- Affected paths: `backend/workbench/engine/replicate_combine`
- Allowed paths: `backend/workbench/engine/replicate_combine`
- Protected paths: `backend/workbench/agent/capability_contract.py`, `backend/workbench/agent/orchestrator.py`, `backend/workbench/agent/core.py`, `backend/workbench/survey`, `backend/workbench/engine/stages`, `backend/workbench/imputation.py`, `backend/workbench/orchestrator`, `backend/workbench/report_view_model.py`, `frontend`
- Dependencies: none
- Tests: `backend/.venv/bin/python -m pytest tests/test_p7_adoption_registry.py -q`, `backend/.venv/bin/python -m pytest tests/test_capability_inventory.py tests/test_workflow_seam.py -q`
- Known gates: `bash scripts/gate.sh --full`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-3-cf2-dependency-bundles (2026-07-26T14:13:57.917Z)

Completed formal devline v1-8-3-cf2-dependency-bundles; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary

### v1-8-3-cf3-validation-runtime (2026-07-27T12:25:00.000Z)

Completed formal devline v1-8-3-cf3-validation-runtime; final_state=COMPLETED; failure_lesson_keys=authoring-source-allowlist, cf3-validation-runtime-red, fms-event-draft-validation, protocol-identity-binding

### v1-8-5-a2-memory-settings-management (2026-08-01T12:19:00.000Z)

Completed formal devline v1-8-5-a2-memory-settings-management; final_state=COMPLETED; failure_lesson_keys=memory-library-management-safe-identification, memory-retrieval-storage-failure-is-503, notebook-memory-server-owned-settings, preference-store-reject-symlink-ancestor, preference-write-complete-before-replace, tdd-red-a2-local-preferences-confirmation

### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work

### v1-8-3-cf1-capability-resolution (2026-07-26T13:37:35.000Z)

Completed formal devline v1-8-3-cf1-capability-resolution; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-5-a1-local-memory-bootstrap (2026-08-01T11:27:52.000Z)

Completed formal devline v1-8-5-a1-local-memory-bootstrap; final_state=COMPLETED; failure_lesson_keys=tdd-red-local-memory-bootstrap
