# Frozen Context Pack

Line: `v1-8-9-p0-evidence-report-remediation-6`
Baseline SHA: `5daa3dfc5542fabdf5466261431da401547710d2`

## Objective
# v1.8.9 P0 Evidence/Report Hardening — remediation-6 objective

## Objective

Close the independent remediation-5 Evidence/Report review findings at the
exact clean baseline `5daa3dfc5542fabdf5466261431da401547710d2`.  Every legacy
presentation, Report export, and document-writer path must fail closed before
facts, templates, artifact hashes, or filesystem IO unless the exact
server-issued C0 owner and projection admission are present.

## Required outcomes

1. `build_report_view_model` must reject missing, caller-shaped, or forged
   owner/projection inputs before `_build_legacy_presentation`, template reads,
   staged fact reads, or filesystem IO.  The valid server-admitted owner path
   must still return the admitted typed facts and preserve the legacy
   presentation projection only after admission.
2. Report/evidence HTTP and export entrances must complete a real
   server-owned owner/proof/receipt/canonical admission before reading an
   artifact index, hashing an artifact, or reading artifact bytes.  Add direct
   order probes for both the evidence and export paths.
3. `EvidenceProjectionV1`, `ReportEvidenceWriterV1`, and
   `ReportDocumentWriterV1` must require an unforgeable-in-practice
   server-issued exact-object identity/issuer registry in addition to copied
   fields, markers, and digests.  `object.__new__` clones and copied/serialized
   projections must fail before facts or writer/filesystem IO; the real owner
   issued projection/writer remains usable.
4. The normal `ReportStage` must adapt a server-owned C0 report owner and
   projection from its existing stage context/receipt admission into
   `render_legacy_html_report`.  If no exact owner/projection is available it
   must emit typed unavailable/blocked report state and never restore a raw
   summary fallback.  Add a positive stage probe and a no-owner negative probe.

## TDD and verification

For each outcome, add a real RED probe first and run it against this exact
baseline before changing production code.  Run the focused Evidence/Report,
HTTP, export, and ReportStage suites in a socket-capable host; run direct
no-IO/order/object-clone/positive owner probes; run compileall, diff check,
and formal retrospective/verify.  Record exact RED/GREEN commands and counts
in the remediation-6 handoff.  Browser, provider, central Agent/Notebook,
live production host, full repository gate, and release acceptance remain
`NOT VERIFIED`.

## Boundaries

Only this target worktree may change.  In scope are the Evidence/Report
backend seams, the minimal normal ReportStage/HTTP adapter needed to preserve
the valid owner path, focused tests, and remediation-6 objective/plan/handoff
and formal records.  Do not modify central Agent/Notebook semantic engines,
providers, estimators, live-host code, frontend, dependencies, deployment
wiring, the root worktree, or another worktree unless a focused fixture makes
it unavoidable.  Push, merge, tag, and release remain out of scope.

## Boundary
- Affected paths: `backend/workbench/report_view_model.py`, `backend/workbench/report_export.py`, `backend/workbench/reporting.py`, `backend/workbench/http/runs_routes.py`, `backend/workbench/services/results_service.py`, `backend/workbench/engine/stages/report.py`, `tests/test_v189_evidence_report_boundary.py`, `tests/test_report_view_model.py`, `tests/test_report_export.py`, `tests/test_reporting_exports.py`, `tests/test_narrative_contract.py`, `tests/test_statistical_exploration_reporting.py`, `tests/test_events.py`, `tests/test_devline_control_events.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-6.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-6.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-6-handoff.md`
- Allowed paths: `backend/workbench/report_view_model.py`, `backend/workbench/report_export.py`, `backend/workbench/reporting.py`, `backend/workbench/http/runs_routes.py`, `backend/workbench/services/results_service.py`, `backend/workbench/engine/stages/report.py`, `tests/test_v189_evidence_report_boundary.py`, `tests/test_report_view_model.py`, `tests/test_report_export.py`, `tests/test_reporting_exports.py`, `tests/test_narrative_contract.py`, `tests/test_statistical_exploration_reporting.py`, `tests/test_events.py`, `tests/test_devline_control_events.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-6.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-6.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-evidence-report-hardening-remediation-6-handoff.md`
- Protected paths: `backend/workbench/agent`, `backend/workbench/http/agent_routes.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/providers`, `backend/workbench/estimator`, `backend/workbench/live_host`
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_evidence_report_boundary.py tests/test_report_view_model.py tests/test_report_export.py tests/test_reporting_exports.py tests/test_narrative_contract.py tests/test_statistical_exploration_reporting.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_events.py tests/test_devline_control_events.py -q`, `PYTHONPATH=backend .venv/bin/python -m compileall backend/workbench/report_view_model.py backend/workbench/report_export.py backend/workbench/reporting.py backend/workbench/http/runs_routes.py backend/workbench/services/results_service.py backend/workbench/engine/stages/report.py`, `git diff --check`
- Known gates: `browser acceptance remains NOT VERIFIED`, `provider execution and production C0/live-host wiring remain NOT VERIFIED`, `central Agent/Notebook/provider/estimator/live-host integration remains NOT VERIFIED and protected`, `full repository gate and release acceptance remain NOT VERIFIED`, `merge/push/tag/deployment/release remain NOT VERIFIED`

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

### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none
