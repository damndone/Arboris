# Frozen Context Pack

Line: `v1-8-9-p0-report-compose-closure`
Baseline SHA: `f1905b23527f239f6161b939d93822e9de9303f0`

## Objective
# Workbench v1.8.9 P0 Report Compose Closure Objective

## Objective

Close the remaining workflow-runtime report composition boundary on the exact
v1.8.9 hardening candidate `f1905b23527f239f6161b939d93822e9de9303f0`.
`report.compose` must produce HTML, PDF, and XLSX only through a typed,
receipt-bound workflow report writer. The writer must use the existing
server-owned workflow evidence port, formal output targets, artifact hashes,
and completion registry; a caller-owned mapping must never be accepted as a
report authority or write path.

## Required outcomes

1. A valid admitted `report.compose` step emits its declared HTML, PDF, and
   XLSX artifacts and completes through the same server artifact registry as
   other workflow outputs.
2. Report output bytes are written through held formal output targets and are
   recorded with the active workflow receipt, exact run identity, producer
   step, input collection, and content digest.
3. Replaying an identical existing output is deterministic; replacing,
   rebinding, changing the run root, using another receipt, or supplying a
   raw mapping fails closed before an unbound write.
4. Existing C0 Report evidence writers remain strict and unchanged: this
   workflow report writer is a separate typed capability over the workflow
   evidence port, not a second Report evidence authority.
5. Focused workflow/runtime regressions and the relevant v1.8.9 security
   tests pass; stale fixtures are migrated to the current canonical artifact
   record contract rather than weakening the production reader.

## Exact baseline

- baseline SHA: `f1905b23527f239f6161b939d93822e9de9303f0`
- branch: `workbench-v1.8.9-hardening-integration`
- worktree: `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-hardening-integration`

## Safety boundaries

- Do not loosen `ReportDocumentWriterV1`, `ReportEvidenceWriterV1`, or
  `EvidenceProjectionV1` ownership checks.
- Do not restore raw model-result, raw-report-mapping, or path-based fallback
  authority.
- Do not change the C0/C1/C2 host resolver contract in this line.
- Do not claim browser, provider, full-host-gate, merge, tag, or release
  acceptance from this focused implementation line.

## Boundary
- Affected paths: `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-report-compose-closure-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-report-compose-closure.md`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/reporting.py`, `backend/workbench/exports.py`, `tests/test_workflow_runtime.py`
- Allowed paths: `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-report-compose-closure-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-report-compose-closure.md`, `backend/workbench/agent/workflow_runtime.py`, `backend/workbench/reporting.py`, `backend/workbench/exports.py`, `tests/test_workflow_runtime.py`
- Protected paths: `backend/workbench/report_export.py`, `backend/workbench/services/results_service.py`, `frontend`
- Dependencies: `v1-8-9-hardening-integration`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_workflow_runtime.py tests/test_v189_workflow_truth.py`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/agent/workflow_runtime.py backend/workbench/reporting.py backend/workbench/exports.py`, `git diff --check`
- Known gates: `browser_acceptance_NOT_VERIFIED`, `provider_acceptance_NOT_VERIFIED`, `host_full_gate_NOT_VERIFIED`, `release_NOT_VERIFIED`

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

### v1-8-9-p0-workflow-truth-remediation-3 (2026-08-16T15:26:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-3; final_state=COMPLETED; failure_lesson_keys=unsupported-formal-status-command, workflow-remediation-3-red-before-fix

### v1-8-9-p0-workflow-truth-remediation-4 (2026-08-16T12:44:00.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-4; final_state=COMPLETED; failure_lesson_keys=test-selector-command-error, workflow-remediation-4-red-before-fix, workflow4-host-integration-dependency

### v1-8-9-p0-workflow-truth-remediation-2 (2026-08-16T11:10:20.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation-2; final_state=COMPLETED; failure_lesson_keys=workflow-persistence-and-lineage-gap, workflow-remediation-red-before-fix

### v1-8-9-p0-workflow-truth-remediation (2026-08-16T10:36:38.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-remediation; final_state=COMPLETED; failure_lesson_keys=admission-step-contract-binding, fd-persistence-separate-lane, focused-recompile-after-authority, reviewer-report-reference, workflow-truth-authority-boundary

### v1-8-9-p0-workflow-truth-core (2026-08-16T09:53:39.000Z)

Completed formal devline v1-8-9-p0-workflow-truth-core; final_state=COMPLETED; failure_lesson_keys=retry-admission-reservation, shared-gates-not-verified, typed-output-persistence

### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity
