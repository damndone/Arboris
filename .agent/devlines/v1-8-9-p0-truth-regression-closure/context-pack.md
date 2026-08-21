# Frozen Context Pack

Line: `v1-8-9-p0-truth-regression-closure`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# Objective: v1.8.9 P0 truth-regression closure

## Objective

Bring the P0 workflow-truth regression suite onto the current v1.8.9 typed,
server-owned artifact and report-writer contracts without weakening any
fail-closed boundary.

## In scope

- Update `tests/test_v189_workflow_truth.py` model-run fixtures to publish
  canonical artifact-index records before testing source-digest mismatch.
- Update formal report race/rollback probes to obtain the current
  receipt-bound `WorkflowReportWriterV1` through the test-owned runtime path.
- Re-run the complete P0 truth suite and preserve explicit known external
  gates.

## Out of scope

- No production security relaxation.
- No raw mapping fallback for report rendering.
- No changes to statistical formulas, provider behavior, or HTTP bootstrap.

## Success criteria

- `tests/test_v189_workflow_truth.py` is green.
- The tests still prove canonical artifact digest validation and report output
  race/rollback containment through the current server-owned writer.
- Formal line verification succeeds.

## Boundary
- Affected paths: `tests/test_v189_workflow_truth.py`, `docs/superpowers/objectives/2026-08-21-v1.8.9-p0-truth-regression-closure-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-truth-regression-closure.md`
- Allowed paths: `tests/test_v189_workflow_truth.py`, `docs/superpowers/objectives/2026-08-21-v1.8.9-p0-truth-regression-closure-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-truth-regression-closure.md`
- Protected paths: `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/reporting.py`
- Dependencies: none
- Tests: `PYTHONPATH=backend:tests .venv/bin/pytest tests/test_v189_workflow_truth.py -q --disable-warnings`
- Known gates: `production host injection is not verified`, `browser acceptance is not verified`, `real external provider is not verified`, `cross-process deployment is not verified`, `full repository and release gates are not verified`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_markdown":"# Global Development Rules\n\nGenerated from repeated devline events. Mandatory rules have appeared at least three times.\n\n- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)\n","global_rules_markdown_sha256":"b619424541a214099df16821c0642f4b2ddb9ee498f66cce7dece275b1117fe5","global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"7d2646296aff49c2c92e83e53f6ad44990aec4280746ec5cf7d9f40b3ab87598"}
```

## Mandatory global development rules
# Global Development Rules

Generated from repeated devline events. Mandatory rules have appeared at least three times.

- `REVIEW|persistence_capability_bypass|filesystem persistence capability bypass` — A sealed input is insufficient when packet and index writes retain a raw-path escape. (resolution: define admission-gated FD-only writer)

## Selected historical lessons
### v1-8-9-p0-workflow-truth-remediation-6 (2026-08-16T16:15:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-6; final_state=COMPLETED; failure_lesson_keys=formal-output-registration-transaction, register-child-run-model-artifacts, runtime-fixture-model-preconditions, use-declared-model-minimum

### v1-8-9-p0-workflow-truth-remediation-5 (2026-08-16T13:35:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-5; final_state=COMPLETED; failure_lesson_keys=production-host-integration-boundary, runtime-artifact-no-follow, workflow-remediation-5-red-before-fix

### v1-8-9-p0-agent-compiler-remediation-5 (2026-08-19T02:35:17.000Z)

Completed formal devline v1-8-9-p0-agent-compiler-remediation-5; final_state=COMPLETED; failure_lesson_keys=os-boundary-probes-need-controlled-sandbox-access

### v1-8-9-p0-workflow-truth-remediation-3 (2026-08-16T15:26:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-3; final_state=COMPLETED; failure_lesson_keys=unsupported-formal-status-command, workflow-remediation-3-red-before-fix

### v1-8-9-p0-legacy-compilation-authority-cutover (2026-08-16T14:30:00.000Z)

Completed formal devline v1-8-9-p0-legacy-compilation-authority-cutover; final_state=COMPLETED; failure_lesson_keys=legacy-authority-red-before-implementation, legacy-cutover-keeps-host-dependency-explicit

### v1-8-9-p0-evidence-core-remediation-7 (2026-08-16T12:56:51.000Z)

Completed formal devline v1-8-9-p0-evidence-core-remediation-7; final_state=COMPLETED; failure_lesson_keys=evidence-host-trust-root, typed-timeout-boundary

### v1-8-9-p0-workflow-truth-remediation-4 (2026-08-16T12:44:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-4; final_state=COMPLETED; failure_lesson_keys=test-selector-command-error, workflow-remediation-4-red-before-fix, workflow4-host-integration-dependency

### v1-8-9-p0-workflow-truth-remediation-2 (2026-08-16T11:10:20.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-2; final_state=COMPLETED; failure_lesson_keys=workflow-persistence-and-lineage-gap, workflow-remediation-red-before-fix

### v1-8-9-p0-workflow-truth-remediation (2026-08-16T10:36:38.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation; final_state=COMPLETED; failure_lesson_keys=admission-step-contract-binding, fd-persistence-separate-lane, focused-recompile-after-authority, reviewer-report-reference, workflow-truth-authority-boundary

### v1-8-9-p0-workflow-truth-core (2026-08-16T09:53:39.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-core; final_state=COMPLETED; failure_lesson_keys=retry-admission-reservation, shared-gates-not-verified, typed-output-persistence
