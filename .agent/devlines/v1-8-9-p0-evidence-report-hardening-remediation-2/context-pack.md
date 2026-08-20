# Frozen Context Pack

Line: `v1-8-9-p0-evidence-report-hardening-remediation-2`
Baseline SHA: `dc74ef64f9cba6d0983f81c85c7366b60712a655`

## Objective
# Workbench v1.8.9 P0 Evidence/Report Remediation 2

Remediate the independent-spec review findings from the exact prior closeout
baseline `dc74ef64f9cba6d0983f81c85c7366b60712a655` in the existing evidence
report hardening worktree. This is a new formal remediation line; do not edit
the predecessor formal line or its records.

Required TDD outcomes:

1. Replace the importable `_REPORT_FACTORY_TOKEN` trust seam with a real
   server-owned/C0 owner capability check. Caller-created tokens, copied or
   serialized owner-shaped objects, forged self-consistent projection wires,
   and unowned writer/export calls must fail closed before any filesystem or
   XLSX/PDF/HTML IO. Add real RED probes, then the smallest owner-bound GREEN
   implementation.
2. Make frontend `readReportEvidenceProjection` validate the existing
   canonical JSON projection digest semantics. Digest, identity, or provenance
   tampering must return the typed unavailable path before facts are rendered.
3. Ensure prediction evidence and legacy state cannot become citable Report
   facts through a bypass. They may remain historical compatibility inputs, but
   raw `model_results`, `post_estimation_results`, and artifact JSON must either
   enter the same server-owned typed evidence projection or render typed
   unavailable/non-citable. Add a real Report rendering-path probe.
4. Fix event timestamp generation at the real append writer: while holding the
   append lock, generate a server-side UTC timestamp strictly later than the
   current tail, preserving append-only hash-chain and anchor integrity. Do not
   relax strict verification and do not change tests to hide the collision.

Every required item must follow write RED probe -> run and observe the expected
failure -> minimal implementation -> GREEN rerun. Preserve the existing C0
owner, historical report assertions, and protected central Agent/Notebook,
provider, estimator, and live-host paths. Browser/provider/central integration,
host/full-gate, and release acceptance remain NOT VERIFIED.

## Boundary
- Affected paths: `backend/workbench/report_export.py`, `backend/workbench/reporting.py`, `backend/workbench/exports.py`, `backend/workbench/services/results_service.py`, `backend/workbench/development_control/events.py`, `frontend/src/report/factTable.ts`, `frontend/src/report/ReportEvidenceBoundary.v189.test.tsx`, `frontend/src/report/ReportWorkspaceContext.tsx`, `frontend/src/report/FamilyEvidence.tsx`, `frontend/src/report/FamilyEvidence.test.tsx`, `frontend/src/workbench/views/TableView.tsx`, `frontend/src/workbench/views/TableView.test.tsx`, `frontend/src/report/ReportView.tsx`, `tests/test_v189_evidence_report_boundary.py`, `tests/test_v189_consumer_projection.py`, `tests/test_report_export.py`, `tests/test_reporting.py`, `tests/test_report_view_model.py`, `tests/test_reporting_exports.py`, `tests/test_devline_control_events.py`, `tests/test_events.py`, `docs/superpowers/objectives/2026-08-19-v1.8.9-p0-evidence-report-hardening-remediation-2.md`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p0-evidence-report-hardening-remediation-2-handoff.md`, `task_plan.md`, `findings.md`, `progress.md`
- Allowed paths: `backend/workbench/report_export.py`, `backend/workbench/reporting.py`, `backend/workbench/exports.py`, `backend/workbench/services/results_service.py`, `backend/workbench/development_control/events.py`, `frontend/src/report/factTable.ts`, `frontend/src/report/ReportEvidenceBoundary.v189.test.tsx`, `frontend/src/report/ReportWorkspaceContext.tsx`, `frontend/src/report/FamilyEvidence.tsx`, `frontend/src/report/FamilyEvidence.test.tsx`, `frontend/src/workbench/views/TableView.tsx`, `frontend/src/workbench/views/TableView.test.tsx`, `frontend/src/report/ReportView.tsx`, `tests/test_v189_evidence_report_boundary.py`, `tests/test_v189_consumer_projection.py`, `tests/test_report_export.py`, `tests/test_reporting.py`, `tests/test_report_view_model.py`, `tests/test_reporting_exports.py`, `tests/test_devline_control_events.py`, `tests/test_events.py`, `docs/superpowers/objectives/2026-08-19-v1.8.9-p0-evidence-report-hardening-remediation-2.md`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p0-evidence-report-hardening-remediation-2-handoff.md`, `task_plan.md`, `findings.md`, `progress.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/http/agent_routes.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/engine`, `backend/workbench/econometrics`
- Dependencies: `v1-8-9-p0-evidence-report-hardening-remediation@dc74ef64f9cba6d0983f81c85c7366b60712a655`, `v1-8-9-p0-evidence-report-hardening@9dec06c3`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_evidence_report_boundary.py tests/test_v189_consumer_projection.py tests/test_report_export.py tests/test_reporting.py tests/test_report_view_model.py tests/test_reporting_exports.py tests/test_devline_control_events.py tests/test_events.py -q`, `cd frontend && npm test -- --run src/report/ReportEvidenceBoundary.v189.test.tsx src/report/FamilyEvidence.test.tsx src/workbench/views/TableView.test.tsx`, `cd frontend && npm run typecheck`, `PYTHONPATH=backend .venv/bin/python -m compileall backend/workbench/report_export.py backend/workbench/reporting.py backend/workbench/exports.py backend/workbench/services/results_service.py backend/workbench/development_control/events.py`, `git diff --check`, `.venv/bin/python scripts/devline_control.py retrospective --line v1-8-9-p0-evidence-report-hardening-remediation-2`, `.venv/bin/python scripts/devline_control.py verify --line v1-8-9-p0-evidence-report-hardening-remediation-2`
- Known gates: `browser acceptance remains NOT VERIFIED`, `provider execution and production C0/live host wiring remain NOT VERIFIED`, `central Agent/Notebook/provider/estimator/live host paths are protected and out of scope`, `full repository gate and release acceptance remain NOT VERIFIED`, `predecessor formal lines and records must remain unchanged`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

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

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-implementation-planning-review (2026-07-26T03:14:00.000Z)

Completed formal devline v1-8-3-implementation-planning-review; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-8-agent-chain-hardening (2026-08-10T01:59:47.000Z)

Completed formal devline v1-8-8-agent-chain-hardening; final_state=COMPLETED; failure_lesson_keys=host-gate-calendar-and-projection, host-gate-integration-before-claim, manual-browser-coverage-gap, qa-runner-is-not-cryptographic-witness, report-upstream-retry-visible, typed-failure-fail-closed

### integration-v1-7-3 (2026-07-20T17:43:14.000Z)

Completed formal devline integration-v1-7-3; final_state=CLOSED; failure_lesson_keys=c1-c2-execution-boundary, cross-boundary-fixture-parity, declared-owner-no-test-shadowing, entrypoint-contract-coverage, runtime-contract-assembly, versioned-result-visible-reader-adapter
