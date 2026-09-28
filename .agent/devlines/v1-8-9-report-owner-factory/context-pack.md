# Frozen Context Pack

Line: `v1-8-9-report-owner-factory`
Baseline SHA: `afc7649c81eb54ee8adcb89edc6be14fc8378d6f`

## Objective
# Workbench v1.8.9 Report Owner Factory Objective

## Objective

Close the remaining P0 runtime boundary for ordinary model runs: a completed
run must publish one server-owned typed evidence packet and Report/Agent/
Notebook must resolve that packet by the exact run identity. Add a host-owned,
typed owner factory and a per-run owner catalog. The Workbench process may
consume an externally admitted authority and persist evidence, but must never
mint authority, accept request-supplied identity, or fall back to raw model
result files. Concurrent runs must not replace one another's Report owner.

## Required outcomes

1. A deployment can install an exact host-owned factory without a generic
   callable or in-process authority server.
2. The completed workflow creates a canonical evidence envelope from the
   server-produced report payload, admits it into the existing registry/store,
   commits it once, and records a run-bound owner and indexed provenance.
3. Report, results, Agent and Notebook consumers resolve the owner by exact
   actor/project/session/scope/run/model/confirmation identity.
4. Missing host capability, invalid envelope, foreign run, tampered file, and
   concurrent-owner mismatch remain typed unavailable/blocked; no raw fallback.
5. Existing package-local C0 tests remain green and a real external authority
   fixture proves ordinary OLS completion through Report evidence.

## Exact baseline

- baseline SHA: `afc7649c81eb54ee8adcb89edc6be14fc8378d6f`
- candidate worktree: `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-hardening-integration`

## Boundaries

- affected paths: `backend/workbench/app.py`, `backend/workbench/services/results_service.py`, `backend/workbench/services/report_evidence_owner_factory.py`, `backend/workbench/engine/stages/report.py`, `backend/workbench/orchestrator/__init__.py`, `backend/workbench/http/runs_routes.py`, `backend/workbench/artifacts.py`, `tests/test_v189_report_owner_factory.py`, `tests/test_v189_evidence_report_boundary.py`
- allowed paths: same as affected paths
- protected paths: `backend/workbench/agent`, `backend/workbench/predictive_research`, `frontend/src`
- tests: owner-factory focused tests, report boundary tests, ordinary OLS integration test
- known gates: browser/provider/host full gate/release remain NOT VERIFIED

## Boundary
- Affected paths: `backend/workbench/app.py`, `backend/workbench/services/results_service.py`, `backend/workbench/services/report_evidence_owner_factory.py`, `backend/workbench/engine/stages/report.py`, `backend/workbench/orchestrator/__init__.py`, `backend/workbench/http/runs_routes.py`, `backend/workbench/artifacts.py`, `backend/workbench/repository/run_repository.py`, `tests/test_v189_report_owner_factory.py`, `tests/test_v189_evidence_report_boundary.py`
- Allowed paths: `backend/workbench/app.py`, `backend/workbench/services/results_service.py`, `backend/workbench/services/report_evidence_owner_factory.py`, `backend/workbench/engine/stages/report.py`, `backend/workbench/orchestrator/__init__.py`, `backend/workbench/http/runs_routes.py`, `backend/workbench/artifacts.py`, `backend/workbench/repository/run_repository.py`, `tests/test_v189_report_owner_factory.py`, `tests/test_v189_evidence_report_boundary.py`
- Protected paths: `backend/workbench/agent`, `backend/workbench/predictive_research`, `frontend/src`
- Dependencies: none
- Tests: `PYTHONPATH=backend:tests .venv/bin/pytest tests/test_v189_report_owner_factory.py tests/test_v189_evidence_report_boundary.py -q`
- Known gates: `browser_acceptance_NOT_VERIFIED`, `provider_acceptance_NOT_VERIFIED`, `host_full_gate_NOT_VERIFIED`, `release_NOT_VERIFIED`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-5-a2-memory-settings-management (2026-08-01T12:19:00.000Z)

Completed formal devline v1-8-5-a2-memory-settings-management; final_state=COMPLETED; failure_lesson_keys=memory-library-management-safe-identification, memory-retrieval-storage-failure-is-503, notebook-memory-server-owned-settings, preference-store-reject-symlink-ancestor, preference-write-complete-before-replace, tdd-red-a2-local-preferences-confirmation

### v1-8-5-a1-local-memory-bootstrap (2026-08-01T11:27:52.000Z)

Completed formal devline v1-8-5-a1-local-memory-bootstrap; final_state=COMPLETED; failure_lesson_keys=tdd-red-local-memory-bootstrap

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-cf4-notebook-provider-injection (2026-07-26T22:45:00.000Z)

Completed formal devline v1-8-3-cf4-notebook-provider-injection; final_state=COMPLETED; failure_lesson_keys=formal-rescope-boundary, tdd-red-before-provider-injection

### local-contained-execution (2026-07-20T17:44:54.000Z)

Completed formal devline local-contained-execution; final_state=CLOSED; failure_lesson_keys=none

### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass
