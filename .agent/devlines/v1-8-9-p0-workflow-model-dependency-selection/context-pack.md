# Frozen Context Pack

Line: `v1-8-9-p0-workflow-model-dependency-selection`
Baseline SHA: `afc7649c81eb54ee8adcb89edc6be14fc8378d6f`

## Objective
# v1.8.9 P0 workflow model-dependency selection

## Objective

Make post-estimation dependency resolution select the completed model branch
from a workflow step that also has a separately declared dataset source. A
non-model source dependency must not be interpreted as a malformed model
producer, while malformed or ambiguous model bindings must still fail closed.

## Scope

- Update the workflow runtime dependency selector only where needed to skip
  unrelated data dependencies and validate the selected model dependency.
- Add focused regression coverage for a model post-estimation step whose
  dependency list contains both a model producer and a source dataset step.
- Preserve server-owned admission, typed model-branch evidence, lineage and
  fail-closed behavior.

## Non-goals

- Do not remove source dependencies from compiled workflows.
- Do not revive raw payload or caller-provided model branch authority.
- Do not change estimator formulas, covariance semantics, model families, or
  provider configuration.
- Do not modify browser, provider, release or unrelated workflow seam tests.

## Acceptance

- The focused regression passes with the canonical model branch binding.
- A malformed selected model binding still fails closed.
- A workflow with a model dependency plus a non-model source dependency reaches
  the intended post-estimation operation.
- `git diff --check` and formal Context Pack verification pass.

## Boundary
- Affected paths: `backend/workbench/agent/workflow_runtime.py`, `tests/test_v189_workflow_model_dependency_selection.py`
- Allowed paths: `backend/workbench/agent/workflow_runtime.py`, `tests/test_v189_workflow_model_dependency_selection.py`
- Protected paths: `tests/test_workflow_seam.py`, `backend/workbench/agent/workflow.py`
- Dependencies: none
- Tests: `tests/test_v189_workflow_model_dependency_selection.py`, `tests/test_workflow_seam.py::test_every_consuming_operation_records_the_dataset_it_actually_read`
- Known gates: `browser-provider-full-candidate-release-separate`

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

### v1-8-8-agent-chain-hardening (2026-08-10T01:59:47.000Z)

Completed formal devline v1-8-8-agent-chain-hardening; final_state=COMPLETED; failure_lesson_keys=host-gate-calendar-and-projection, host-gate-integration-before-claim, manual-browser-coverage-gap, qa-runner-is-not-cryptographic-witness, report-upstream-retry-visible, typed-failure-fail-closed
