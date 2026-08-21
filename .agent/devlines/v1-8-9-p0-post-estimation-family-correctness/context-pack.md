# Frozen Context Pack

Line: `v1-8-9-p0-post-estimation-family-correctness`
Baseline SHA: `3257663c4236d8184805f658852f4e5a77c73f48`

## Objective
# Workbench v1.8.9 P0 Post-estimation Family Correctness

## Objective

Prove and, if necessary, repair the post-estimation family boundary so that
OLS-only inference adapters can never refit a non-OLS branch or emit an OLS
statistic under a foreign model identity. Unsupported families must fail closed
with the registered typed reason; supported OLS paths must retain the declared
covariance, model artifact identity, and evidence provenance.

## Scope

- `backend/workbench/agent/workflow_runtime.py`
- `backend/workbench/agent/post_estimation_registry.py`
- `tests/test_v189_workflow_truth.py`
- `tests/test_workflow_runtime.py`

## Acceptance

- A non-OLS branch presented to an OLS post-estimation operation is rejected
  before refit/persistence with the stable unsupported-family contract.
- OLS post-estimation tests remain numerically correct and preserve covariance
  and source/model evidence bindings.
- No hard-coded model identity can be used to authorize foreign evidence.
- Compile, diff check, formal verify, retrospective, and scoped tests pass.

## Non-goals

Do not add new post-estimation model families in this line or weaken the
registry/exact result contracts.

## Boundary
- Affected paths: `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/agent/post_estimation_registry.py`, `tests/test_v189_workflow_truth.py`, `tests/test_workflow_runtime.py`
- Allowed paths: `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/agent/post_estimation_registry.py`, `tests/test_v189_workflow_truth.py`, `tests/test_workflow_runtime.py`
- Protected paths: none
- Dependencies: none
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:tests .venv/bin/pytest -q tests/test_v189_workflow_truth.py tests/test_workflow_runtime.py`
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
### v1-8-9-p0-workflow-truth-remediation (2026-08-16T10:36:38.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation; final_state=COMPLETED; failure_lesson_keys=admission-step-contract-binding, fd-persistence-separate-lane, focused-recompile-after-authority, reviewer-report-reference, workflow-truth-authority-boundary

### v1-8-9-p0-workflow-truth-core (2026-08-16T09:53:39.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-core; final_state=COMPLETED; failure_lesson_keys=retry-admission-reservation, shared-gates-not-verified, typed-output-persistence

### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

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

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission
