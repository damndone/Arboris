# Frozen Context Pack

Line: `v1-8-9-p0-evidence-report-hardening-remediation`
Baseline SHA: `94a96fb5f4919a38c40662ab28784368897d7162`

## Objective
# Workbench v1.8.9 P0 Evidence and Report Hardening Remediation

Remediate the independent-reviewer `NOT COMPLIANT` findings at baseline
`94a96fb5f4919a38c40662ab28784368897d7162` in the existing
`workbench-v1.8.9-p0-evidence-report-hardening` worktree.

Required outcomes:

- `issue_report_projection`, `report_export`, and `results_service` must bind
  facts and `projectionDigest` to the actual canonical server-owned evidence
  envelope. Forged facts, forged projection digests, and synchronized forged
  outer index fields must fail closed. The issued wire must be immutable.
- Report persistence/writer factories must reject caller raw `table_rows`,
  arbitrary Mapping fake view models, and foreign `canonical_run_root`; the
  public `ServerOwnedReportEvidencePersistenceV1` constructor must not mint
  authority from caller-supplied identity metadata.
- `TableView` and `FamilyEvidence` must not display raw
  `detail.model_results`, `detail.post_estimation_results`, artifact JSON, or
  an `allowLegacyPresentation` raw fallback. Missing typed evidence renders
  only the typed unavailable state.
- Formal event verification must reject timestamp/order reversal. The new
  line's event stream, terminal state, generated retrospective, and handoff
  must agree; temporary files must be removed.

Preserve the real C0 owner boundary, shared Agent/Notebook/Report fact
identity/value/status/digest/concurrency assertions, historical reporting
assertions, and existing evidence-envelope tests. Do not modify central Agent,
Notebook, provider, estimator, or live-host execution code. Browser/provider
and full-host release acceptance remain separate gates.

## Boundary
- Affected paths: `backend/workbench/report_export.py`, `backend/workbench/reporting.py`, `backend/workbench/exports.py`, `backend/workbench/services/results_service.py`, `backend/workbench/report_view_model.py`, `backend/workbench/development_control/events.py`, `frontend/src/report/FamilyEvidence.tsx`, `frontend/src/report/FamilyEvidence.test.tsx`, `frontend/src/report/ReportWorkspaceContext.tsx`, `frontend/src/report/ReportEvidenceBoundary.v189.test.tsx`, `frontend/src/workbench/views/TableView.tsx`, `frontend/src/workbench/views/TableView.test.tsx`, `tests/test_v189_evidence_report_boundary.py`, `tests/test_v189_consumer_projection.py`, `tests/test_report_export.py`, `tests/test_reporting.py`, `tests/test_report_view_model.py`, `tests/test_reporting_exports.py`, `tests/test_development_control_events.py`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p0-evidence-report-hardening-handoff.md`, `docs/superpowers/objectives/2026-08-19-v1.8.9-p0-evidence-report-hardening-remediation.md`
- Allowed paths: `backend/workbench/report_export.py`, `backend/workbench/reporting.py`, `backend/workbench/exports.py`, `backend/workbench/services/results_service.py`, `backend/workbench/report_view_model.py`, `backend/workbench/development_control/events.py`, `frontend/src/report/FamilyEvidence.tsx`, `frontend/src/report/FamilyEvidence.test.tsx`, `frontend/src/report/ReportWorkspaceContext.tsx`, `frontend/src/report/ReportEvidenceBoundary.v189.test.tsx`, `frontend/src/workbench/views/TableView.tsx`, `frontend/src/workbench/views/TableView.test.tsx`, `tests/test_v189_evidence_report_boundary.py`, `tests/test_v189_consumer_projection.py`, `tests/test_report_export.py`, `tests/test_reporting.py`, `tests/test_report_view_model.py`, `tests/test_reporting_exports.py`, `tests/test_development_control_events.py`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p0-evidence-report-hardening-handoff.md`, `docs/superpowers/objectives/2026-08-19-v1.8.9-p0-evidence-report-hardening-remediation.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/http/agent_routes.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/engine`, `backend/workbench/econometrics`
- Dependencies: `v1-8-9-p0-evidence-report-hardening@94a96fb5f4919a38c40662ab28784368897d7162`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_evidence_report_boundary.py tests/test_v189_consumer_projection.py tests/test_report_export.py tests/test_reporting.py tests/test_report_view_model.py tests/test_reporting_exports.py tests/test_development_control_events.py -q`, `cd frontend && npm test -- --run src/report/ReportEvidenceBoundary.v189.test.tsx src/report/FamilyEvidence.test.tsx src/workbench/views/TableView.test.tsx`, `cd frontend && npm run typecheck`, `PYTHONPATH=backend .venv/bin/python -m compileall backend/workbench/report_export.py backend/workbench/reporting.py backend/workbench/exports.py backend/workbench/services/results_service.py backend/workbench/report_view_model.py backend/workbench/development_control/events.py`, `.venv/bin/python scripts/devline_control.py verify --line v1-8-9-p0-evidence-report-hardening-remediation`
- Known gates: `browser acceptance remains separate and is not verified here`, `provider execution and production C0 host wiring remain NOT VERIFIED`, `central Agent/Notebook engine and routes are protected and out of scope`, `predecessor line has historical timestamp inversions; its verify must fail after the validator hardening`

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

### integration-v1-7-3 (2026-07-20T17:43:14.000Z)

Completed formal devline integration-v1-7-3; final_state=CLOSED; failure_lesson_keys=c1-c2-execution-boundary, cross-boundary-fixture-parity, declared-owner-no-test-shadowing, entrypoint-contract-coverage, runtime-contract-assembly, versioned-result-visible-reader-adapter

### v1-8-8-agent-chain-hardening (2026-08-10T01:59:47.000Z)

Completed formal devline v1-8-8-agent-chain-hardening; final_state=COMPLETED; failure_lesson_keys=host-gate-calendar-and-projection, host-gate-integration-before-claim, manual-browser-coverage-gap, qa-runner-is-not-cryptographic-witness, report-upstream-retry-visible, typed-failure-fail-closed
