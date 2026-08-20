# Frozen Context Pack

Line: `v1-8-9-p0-evidence-report-hardening-remediation-3`
Baseline SHA: `363812ee8063cd61b12ca82750b777e002a0e782`

## Objective
# Workbench v1.8.9 P0 Evidence/Report Remediation 3

Remediate the remaining independent-review `NOT COMPLIANT` findings from the
exact closeout baseline `363812ee8063cd61b12ca82750b777e002a0e782` in the
existing evidence/report hardening worktree. This is a new formal line; do not
edit the predecessor formal line or its records.

Required TDD outcomes:

1. Remove the importable `_REPORT_OWNER_FACTORY_TOKEN` and
   `_REPORT_FACTORY_TOKEN` trust roots. Report owner construction must require
   the existing C0/deployment `HostAuthorityEndpointV1` and a host-issued
   opaque proof bound to the report purpose, scope, subject, canonical root and
   payload. Caller-selected resolver/config/token, JSON/pickle/object.__new__
   and same-process forged objects must fail closed before projection, writer,
   or any XLSX/HTML/PDF/filesystem IO. Add real untrusted import probes and a
   controlled server-host harness probe that obtains the capability through the
   existing host channel.
2. Make every required provenance field strict and canonical: artifact,
   run/model/result identity, source/admission, commit, envelope, confirmation,
   and projection digest must be present and mutually consistent. Missing,
   partial, tampered, and self-consistent forged provenance returns typed
   unavailable/blocked and never becomes Report facts or writer input. Reuse
   the existing canonical digest semantics.
3. Keep classification/raw artifact JSON in `ReportWorkspaceContext` strictly
   display-only NON-CITABLE compatibility state. It must not enter formal
   evidence facts, writer input, or LLM context. Add a real Report render and
   selection-path probe.
4. Preserve the server-generated strict append timestamp strategy and the
   existing `tests/test_events.py` plus `tests/test_devline_control_events.py`
   17-pass behavior.

Protected boundaries: do not modify central Agent, Notebook, provider,
estimator, or live-host execution code. Browser, provider production wiring,
central integration, host acceptance, full-gate, and release acceptance remain
NOT VERIFIED.

## Boundary
- Affected paths: `backend/workbench/services/results_service.py`, `backend/workbench/report_export.py`, `backend/workbench/report_view_model.py`, `backend/workbench/reporting.py`, `backend/workbench/exports.py`, `frontend/src/report/ReportWorkspaceContext.tsx`, `frontend/src/report/ReportView.tsx`, `frontend/src/report/factTable.ts`, `frontend/src/report/ReportEvidenceBoundary.v189.test.tsx`, `frontend/src/report/ReportWorkspaceContext.v189.test.tsx`, `frontend/src/report/ReportView.test.tsx`, `tests/test_v189_evidence_report_boundary.py`, `tests/test_v189_consumer_projection.py`, `tests/test_report_export.py`, `tests/test_reporting.py`, `tests/test_report_view_model.py`, `tests/test_reporting_exports.py`, `tests/test_devline_control_events.py`, `tests/test_events.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-3.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-3.md`, `task_plan.md`, `findings.md`, `progress.md`
- Allowed paths: `backend/workbench/services/results_service.py`, `backend/workbench/report_export.py`, `backend/workbench/report_view_model.py`, `backend/workbench/reporting.py`, `backend/workbench/exports.py`, `frontend/src/report/ReportWorkspaceContext.tsx`, `frontend/src/report/ReportView.tsx`, `frontend/src/report/factTable.ts`, `frontend/src/report/ReportEvidenceBoundary.v189.test.tsx`, `frontend/src/report/ReportWorkspaceContext.v189.test.tsx`, `frontend/src/report/ReportView.test.tsx`, `tests/test_v189_evidence_report_boundary.py`, `tests/test_v189_consumer_projection.py`, `tests/test_report_export.py`, `tests/test_reporting.py`, `tests/test_report_view_model.py`, `tests/test_reporting_exports.py`, `tests/test_devline_control_events.py`, `tests/test_events.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-3.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-3.md`, `task_plan.md`, `findings.md`, `progress.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/http/agent_routes.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/engine`, `backend/workbench/econometrics`, `backend/workbench/providers`, `backend/workbench/estimator`, `backend/workbench/live_host`
- Dependencies: `v1-8-9-p0-evidence-report-hardening-remediation-2@363812ee8063cd61b12ca82750b777e002a0e782`, `v1-8-9-p0-evidence-report-hardening-remediation@dc74ef64f9cba6d0983f81c85c7366b60712a655`, `v1-8-9-p0-evidence-report-hardening@9dec06c3cee8e00466f773c6168a11994489bd84`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_evidence_report_boundary.py tests/test_v189_consumer_projection.py tests/test_report_export.py tests/test_reporting.py tests/test_report_view_model.py tests/test_reporting_exports.py tests/test_devline_control_events.py tests/test_events.py -q`, `cd frontend && npm test -- --run src/report/ReportEvidenceBoundary.v189.test.tsx src/report/ReportWorkspaceContext.v189.test.tsx src/report/ReportView.test.tsx`, `cd frontend && npm run typecheck`, `PYTHONPATH=backend .venv/bin/python -m compileall backend/workbench/services/results_service.py backend/workbench/report_export.py backend/workbench/report_view_model.py backend/workbench/reporting.py backend/workbench/exports.py`, `git diff --check`, `.venv/bin/python scripts/devline_control.py retrospective --line v1-8-9-p0-evidence-report-hardening-remediation-3`, `.venv/bin/python scripts/devline_control.py verify --line v1-8-9-p0-evidence-report-hardening-remediation-3`
- Known gates: `browser acceptance remains NOT VERIFIED`, `provider execution and production C0/live-host wiring remain NOT VERIFIED`, `central Agent/Notebook/provider/estimator/live-host integration remains NOT VERIFIED and protected`, `full repository gate and release acceptance remain NOT VERIFIED`, `merge/push/tag/deployment remain NOT VERIFIED`

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

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-8-agent-chain-hardening (2026-08-10T01:59:47.000Z)

Completed formal devline v1-8-8-agent-chain-hardening; final_state=COMPLETED; failure_lesson_keys=host-gate-calendar-and-projection, host-gate-integration-before-claim, manual-browser-coverage-gap, qa-runner-is-not-cryptographic-witness, report-upstream-retry-visible, typed-failure-fail-closed

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-implementation-planning-review (2026-07-26T03:14:00.000Z)

Completed formal devline v1-8-3-implementation-planning-review; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none
