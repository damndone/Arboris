# Frozen Context Pack

Line: `v1-8-9-central-evidence-consumer-mount`
Baseline SHA: `91ee6a05eab2a1892844c8a3057e1e607359a29e`

## Objective
# v1.8.9 Central Evidence Consumer Mount Objective

## Objective

Mount the already-persisted, typed v1.8.9 evidence into the real central
Agent, Notebook, and Report consumer paths. The central surfaces must read a
server-owned evidence envelope and its receipt, project only the consumer
contract, and return `UNAVAILABLE`/`DEGRADED` when the evidence is missing,
stale, foreign, or unverifiable. They must never reconstruct statistical
results from raw model-result JSON or infer a result from labels.

## Required behavior

1. A central run-detail request is bound to server-observed actor, project,
   session, run, model-run, and confirmation identity before it reads a
   projection.
2. Agent and Notebook result tools use the same typed persisted-evidence
   source and the same projection registry. A natural-language request may
   choose the consumer surface, but cannot choose a filesystem path, raw
   result packet, provider callable, or alternate model result.
3. Report view-model and export routes consume only the owner-admitted typed
   projection and receipt. If the artifact hash, receipt, registry, or scope
   is invalid, the response is an explicit unavailable/degraded packet rather
   than a guessed table or recalculated statistic.
4. Existing compatibility fields remain visibly non-authoritative until they
   are backed by the typed evidence projection. No second capability table or
   consumer-specific statistical calculation is introduced.
5. Tests cover the same path for Agent, Notebook, and Report, including
   missing/stale/foreign evidence, forged identity, malformed digest, raw
   model-result fallback, and positive persisted-evidence rendering.

## Non-goals

- No new estimator/model family or statistical formula.
- No native `.sav/.zsav/.dta` dependency work.
- No browser/provider/cross-process/full-gate/release claim unless separately
  executed on the candidate SHA.
- No migration of the legacy `prediction.py` classification entrypoint in
  this line; that is a separate typed host-port production migration.

## Acceptance boundary

Focused central consumer tests may prove the server route/service/view-model
join. Browser-visible acceptance, real provider startup, cross-process
authority persistence, full repository gate, and release readiness remain
`NOT VERIFIED` until explicitly run.

## Boundary
- Affected paths: `backend/workbench/http/runs_routes.py`, `backend/workbench/services/results_service.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/notebook/evidence.py`, `backend/workbench/report_view_model.py`, `tests/test_v189_central_evidence_consumer_mount.py`, `tests/test_v189_agent_notebook_runtime_bridge.py`, `tests/test_v189_evidence_report_boundary.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-central-evidence-consumer-mount-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-central-evidence-consumer-mount.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-central-evidence-consumer-mount-handoff.md`
- Allowed paths: `backend/workbench/http/runs_routes.py`, `backend/workbench/services/results_service.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/agent/notebook/evidence.py`, `backend/workbench/report_view_model.py`, `tests/test_v189_central_evidence_consumer_mount.py`, `tests/test_v189_agent_notebook_runtime_bridge.py`, `tests/test_v189_evidence_report_boundary.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-central-evidence-consumer-mount-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-central-evidence-consumer-mount.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-central-evidence-consumer-mount-handoff.md`
- Protected paths: `backend/workbench/evidence`, `backend/workbench/engine`, `frontend/src`, `backend/workbench/prediction.py`
- Dependencies: `v1-8-9-contract-lock`, `v1-8-9-consumer-projection-core`, `v1-8-9-report-evidence-core`, `v1-8-9-agent-notebook-runtime-bootstrap`, `v1-8-9-central-consumer-execution`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_central_evidence_consumer_mount.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_agent_notebook_runtime_bridge.py tests/test_v189_evidence_report_boundary.py -q`, `git diff --check`, `python3 -m compileall -q backend/workbench`
- Known gates: `browser acceptance NOT VERIFIED`, `real provider startup NOT VERIFIED`, `cross-process authority NOT VERIFIED`, `full repository gate NOT VERIFIED`, `release/merge/tag NOT VERIFIED`

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

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-8-agent-chain-hardening (2026-08-10T01:59:47.000Z)

Completed formal devline v1-8-8-agent-chain-hardening; final_state=COMPLETED; failure_lesson_keys=host-gate-calendar-and-projection, host-gate-integration-before-claim, manual-browser-coverage-gap, qa-runner-is-not-cryptographic-witness, report-upstream-retry-visible, typed-failure-fail-closed

### v1-8-8-p7-agent-adoption (2026-08-09T03:20:32.000Z)

Completed formal devline v1-8-8-p7-agent-adoption; final_state=COMPLETED; failure_lesson_keys=browser-report-remains-not-verified, declaration-derived-option-boundaries, design-diagnostic-neutral-envelope, generated-tool-schema-runtime-validation, p7-artifact-identity-preserves-repeatability, parent-workflow-owns-child-vocabulary, workflow-errors-preserve-step-cause

### p4-data-management (2026-08-08T23:58:00.000Z)

Completed formal devline p4-data-management; final_state=COMPLETED; failure_lesson_keys=branch-local-schema-projection, execute-provider-handler-after-projection, formal-event-vocabulary, formal-start-normalized-tags, mutation-derived-values, mutation-live-projection, mutation-no-silent-dataset-omission, p4-contract-first, preserve-existing-branch-return, review-live-registry-api, strip-composition-fields-at-adapter, typed-adapter-parameter-boundary, typed-preview-field-fidelity

### v1-8-5-c4-projection-registry (2026-08-01T21:58:07.000Z)

Completed formal devline v1-8-5-c4-projection-registry; final_state=COMPLETED; failure_lesson_keys=projection-registry-before-recipe-growth
