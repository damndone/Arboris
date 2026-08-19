# Frozen Context Pack

Line: `v1-8-9-p0-evidence-report-hardening`
Baseline SHA: `05362b5697e10eb25fd219da003641f96eeec082`

## Objective
# Workbench v1.8.9 P0 Evidence and Report Hardening Objective

Close the real consumer-boundary gaps between persisted workflow artifacts,
EvidenceEnvelope/EvidenceCommitBinding, and the Report UI.

Required outcomes:

- an indexed post-estimation artifact without a committed canonical evidence
  binding cannot create citable Report facts; it must render as
  `UNAVAILABLE`/`BLOCKED` with a typed reason;
- the actual ReportView path must receive and render the typed evidence
  projection, including status, envelope digest, provenance and bounded facts;
- no raw JSON fallback or recursive scalar extraction may bypass evidence
  status, digest, or admission checks;
- Agent, Notebook, and Report must preserve the same fact identity/value for a
  committed envelope;
- tests must prove both the accepted committed path and the rejected
  uncommitted/tampered path.

This line owns the run/report evidence loading and Report consumer paths plus
their tests. It does not modify Agent/Notebook routing, provider execution,
model estimators, or release sidecars. Browser/provider/full-host-gate
acceptance remains separate.

## Boundary
- Affected paths: `docs/superpowers/objectives/2026-08-19-v1.8.9-p0-evidence-report-hardening-objective.md`, `backend/workbench/http/runs_routes.py`, `backend/workbench/report_view_model.py`, `frontend/src/report/ReportView.tsx`, `frontend/src/report/ReportWorkspaceContext.tsx`, `frontend/src/report/factTable.ts`, `frontend/src/report/FamilyEvidence.tsx`, `tests/test_v189_evidence_report_boundary.py`, `frontend/src/report/ReportEvidenceBoundary.v189.test.tsx`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p0-evidence-report-hardening-handoff.md`
- Allowed paths: `docs/superpowers/objectives/2026-08-19-v1.8.9-p0-evidence-report-hardening-objective.md`, `backend/workbench/http/runs_routes.py`, `backend/workbench/report_view_model.py`, `frontend/src/report/ReportView.tsx`, `frontend/src/report/ReportWorkspaceContext.tsx`, `frontend/src/report/factTable.ts`, `frontend/src/report/FamilyEvidence.tsx`, `tests/test_v189_evidence_report_boundary.py`, `frontend/src/report/ReportEvidenceBoundary.v189.test.tsx`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p0-evidence-report-hardening-handoff.md`
- Protected paths: `backend/workbench/http/agent_routes.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/agent`, `backend/workbench/engine`, `scripts/gate.sh`
- Dependencies: `v1-8-9-foundation-integration`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_evidence_report_boundary.py tests/test_reporting.py -q`, `cd frontend && npm test -- --run src/report/ReportEvidenceBoundary.v189.test.tsx src/report/ReportView.v189.test.tsx src/report/ReportWorkspaceContext.v189.test.tsx`, `cd frontend && npm run typecheck`
- Known gates: `browser acceptance remains separate`, `provider execution remains NOT VERIFIED`, `full host gate and release remain separate`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-8-agent-chain-hardening (2026-08-10T01:59:47.000Z)

Completed formal devline v1-8-8-agent-chain-hardening; final_state=COMPLETED; failure_lesson_keys=host-gate-calendar-and-projection, host-gate-integration-before-claim, manual-browser-coverage-gap, qa-runner-is-not-cryptographic-witness, report-upstream-retry-visible, typed-failure-fail-closed

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none
