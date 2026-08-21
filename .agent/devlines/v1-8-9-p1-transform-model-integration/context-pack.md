# Frozen Context Pack

Line: `v1-8-9-p1-transform-model-integration`
Baseline SHA: `968328119632b9fa52e0f263724f7a7733d44ced`

## Objective
# Workbench v1.8.9 P1 Transform-to-Model Integration

Close the real persisted-child workflow failure where a typed data transform is followed by model genesis. Keep receipt-bound artifact admission and source-content binding fail-closed; do not bypass the server registry or fall back to the target dataset.

Scope: backend/workbench/agent/workflow_runtime.py, tests/test_agent_data_management_p4.py.

Acceptance: the real transform-to-model path completes with the renamed child as the model source; tampered/missing/foreign result artifacts remain rejected; focused regression and formal verification pass.

## Boundary
- Affected paths: `backend/workbench/agent/workflow_runtime.py`, `tests/test_agent_data_management_p4.py`
- Allowed paths: `backend/workbench/agent/workflow_runtime.py`, `tests/test_agent_data_management_p4.py`
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -q tests/test_agent_data_management_p4.py`
- Known gates: none

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_markdown":"# Global Development Rules\n\nGenerated from repeated devline events. Mandatory rules have appeared at least three times.\n\n- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)\n","global_rules_markdown_sha256":"b619424541a214099df16821c0642f4b2ddb9ee498f66cce7dece275b1117fe5","global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"7d2646296aff49c2c92e83e53f6ad44990aec4280746ec5cf7d9f40b3ab87598"}
```

## Mandatory global development rules
# Global Development Rules

Generated from repeated devline events. Mandatory rules have appeared at least three times.

- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)

## Selected historical lessons
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### p4-data-management (2026-08-08T23:58:00.000Z)

Completed formal devline p4-data-management; final_state=COMPLETED; failure_lesson_keys=branch-local-schema-projection, execute-provider-handler-after-projection, formal-event-vocabulary, formal-start-normalized-tags, mutation-derived-values, mutation-live-projection, mutation-no-silent-dataset-omission, p4-contract-first, preserve-existing-branch-return, review-live-registry-api, strip-composition-fields-at-adapter, typed-adapter-parameter-boundary, typed-preview-field-fidelity

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-9-p0-workflow-truth-remediation-6 (2026-08-16T16:15:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-6; final_state=COMPLETED; failure_lesson_keys=formal-output-registration-transaction, register-child-run-model-artifacts, runtime-fixture-model-preconditions, use-declared-model-minimum

### v1-8-9-p0-workflow-truth-remediation-3 (2026-08-16T15:26:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-3; final_state=COMPLETED; failure_lesson_keys=unsupported-formal-status-command, workflow-remediation-3-red-before-fix

### v1-8-9-p0-workflow-truth-remediation-5 (2026-08-16T13:35:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-5; final_state=COMPLETED; failure_lesson_keys=production-host-integration-boundary, runtime-artifact-no-follow, workflow-remediation-5-red-before-fix

### v1-8-9-p0-workflow-truth-remediation-4 (2026-08-16T12:44:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-4; final_state=COMPLETED; failure_lesson_keys=test-selector-command-error, workflow-remediation-4-red-before-fix, workflow4-host-integration-dependency

### v1-8-9-p0-workflow-truth-remediation-2 (2026-08-16T11:10:20.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-2; final_state=COMPLETED; failure_lesson_keys=workflow-persistence-and-lineage-gap, workflow-remediation-red-before-fix

### v1-8-9-p0-workflow-truth-remediation (2026-08-16T10:36:38.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation; final_state=COMPLETED; failure_lesson_keys=admission-step-contract-binding, fd-persistence-separate-lane, focused-recompile-after-authority, reviewer-report-reference, workflow-truth-authority-boundary

### v1-8-9-p0-workflow-truth-core (2026-08-16T09:53:39.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-core; final_state=COMPLETED; failure_lesson_keys=retry-admission-reservation, shared-gates-not-verified, typed-output-persistence
