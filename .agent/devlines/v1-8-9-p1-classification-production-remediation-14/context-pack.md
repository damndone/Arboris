# Frozen Context Pack

Line: `v1-8-9-p1-classification-production-remediation-14`
Baseline SHA: `9c968460d168a2e5c6164df1d41b2b4b5ccf2368`

## Objective
# Workbench v1.8.9 P1 Classification Production Remediation 14 Objective

Close the independent spec-review blocker from exact tip
`9c968460d168a2e5c6164df1d41b2b4b5ccf2368` without changing root or any other
worktree. Extend the remediation-13 descriptor-based artifact integrity seam
to every artifact byte consumer in scope, not only the artifacts-index list.

## Required behavior

- Create one shared repository/file-integrity seam for the server-owned bounded
  relative POSIX path grammar, no-follow descriptor traversal, regular-file
  `fstat`, same-open-descriptor SHA-256, and same-open-descriptor reads.
- Migrate `runs_routes.py` artifact download
  (`/runs/{run_id}/artifacts/{artifact_id}`) to that seam. A generic download
  must hash and read the opened object, return bytes from that object, and must
  not use path-based `FileResponse` after a path check. A classification
  download must obtain its typed wrapper only through the safe classification
  consumer seam.
- Migrate classification artifact and classification receipt reads in
  `predictive_research/consumer_projection.py` to the same shared seam. The
  artifact and receipt bytes must each be read and hashed from their opened
  descriptors.
- Preserve the existing list validator, artifact type vocabulary, index status
  mapping, duplicate/path/type/digest checks, classification server identity,
  evidence receipt, split/fold/OOF/holdout/weights/calibration/threshold
  contracts, and Agent/Notebook/Report typed projections.
- Add real HTTP and direct-consumer probes for valid success, non-race external
  symlink rejection, missing/non-regular/digest mismatch behavior, and a
  replacement callback that is patched at the live shared helper and asserts
  it actually executed. No probe may monkeypatch a removed symbol or use
  `raising=False` to create an empty callback.
- Keep the artifact allowlist unchanged; record producer-vocabulary drift as a
  bounded P2 follow-up in the remediation-14 handoff.

## Formal and verification boundaries

Use the unique formal line
`v1-8-9-p1-classification-production-remediation-14`, created only through
`scripts/devline_control.py start`, with exact baseline
`9c968460d168a2e5c6164df1d41b2b4b5ccf2368`.

Required evidence is TDD RED before production changes, then focused
production/HTTP/consumer/TOCTOU tests, classification contract suites,
`compileall`, `git diff --check`, formal verify and retrospective generation.
The handoff must include exact implementation and final tips, formal manifest
and tail SHA, reproducible commands and observed numbers, the known API
artifacts fixture gate if it remains, and formal `COMPLETED`/`unresolved=0`
state. Browser, external provider, central integration/cutover, host full
gate, full gate, merge, tag, and release remain `NOT VERIFIED`.

## Scope

- `backend/workbench/repository/file_integrity.py`
- `backend/workbench/repository/run_repository.py`
- `backend/workbench/http/runs_routes.py`
- `backend/workbench/predictive_research/consumer_projection.py`
- `tests/test_v189_classification_production.py`
- this objective, plan, and handoff
- the new remediation-14 formal line records

Do not modify `backend/workbench/prediction.py`,
`backend/workbench/reporting.py`,
`backend/workbench/http/notebook_routes.py`,
`backend/workbench/predictive_research/persistence.py`, the remediation-13
formal records, the repository root, or any other worktree.

## Boundary
- Affected paths: `backend/workbench/repository/file_integrity.py`, `backend/workbench/repository/run_repository.py`, `backend/workbench/http/runs_routes.py`, `backend/workbench/predictive_research/consumer_projection.py`, `tests/test_v189_classification_production.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-production-remediation-14-objective.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p1-classification-production-remediation-14.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-14-handoff.md`
- Allowed paths: none
- Protected paths: `backend/workbench/prediction.py`, `backend/workbench/reporting.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/predictive_research/persistence.py`, `.agent/devlines/v1-8-9-p1-classification-production-remediation-13/context-pack.md`, `.agent/devlines/v1-8-9-p1-classification-production-remediation-13/context-pack.manifest.json`, `.agent/devlines/v1-8-9-p1-classification-production-remediation-13/events.jsonl`, `.agent/devlines/v1-8-9-p1-classification-production-remediation-13/RETROSPECTIVE.md`
- Dependencies: none
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_v189_classification_production.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_api.py -q -k artifacts`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`
- Known gates: `tests/test_api.py -q -k artifacts may retain two async completed-run fixture failures`, `browser/provider/central/host/full-gate/release are NOT VERIFIED`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-9-p0-evidence-host-transport-hardening (2026-08-16T15:41:00.000Z)

Completed formal devline v1-8-9-p0-evidence-host-transport-hardening; final_state=COMPLETED; failure_lesson_keys=fd-transport-red-probes

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

### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none
