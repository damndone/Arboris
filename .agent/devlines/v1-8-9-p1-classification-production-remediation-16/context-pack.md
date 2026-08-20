# Frozen Context Pack

Line: `v1-8-9-p1-classification-production-remediation-16`
Baseline SHA: `b57cc22de59f55cee9e349360dae281f7b3016cf`

## Objective
# Workbench v1.8.9 P1 classification production remediation-16 objective

- Exact baseline: `b57cc22de59f55cee9e349360dae281f7b3016cf`.
- Formal line: `v1-8-9-p1-classification-production-remediation-16`.
- Scope: close the independent quality-review P1 in the classification-owned
  generic artifact download path without changing central Agent, Notebook, or
  Report behavior.

## Required outcome

1. Replace the generic artifact route's private Starlette
   `FileResponse._parse_range_header` call with a Workbench-owned bounded Range
   parser. Preserve single-range and multipart-range behavior, `If-Range`,
   `400`/`416` boundaries, compatibility headers, the 64 KiB stream chunk and
   512 MiB size policy, same-FD reads, cleanup, and read-time TOCTOU checks.
2. Add regression coverage for `os.pread` failure, iterator failure,
   inode/device replacement, and `Last-Modified`/`If-Range` behavior. Keep
   replacement callbacks `raising=True` and execute the direct probes.
3. Produce exact formal evidence and a new implementation/formal-closeout
   handoff. Do not edit remediation-15 events, Context Pack, or retrospective.

## Allowed paths

- `backend/workbench/http/runs_routes.py`
- `tests/test_v189_classification_production.py`
- `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-production-remediation-16-objective.md`
- `docs/superpowers/plans/2026-08-20-v1.8.9-p1-classification-production-remediation-16.md`
- `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-16-handoff.md`
- `.agent/devlines/v1-8-9-p1-classification-production-remediation-16/**` (only
  through `scripts/devline_control.py`).

## Protected boundaries

- `backend/workbench/predictive_research/consumer_projection.py` and the
  remediation-15 whole-body `consumer_projection` residual are out of scope.
- Central Agent, Notebook, and Report consumers and their tests are out of
  scope.
- Existing remediation-15 formal events, manifest, Context Pack, and
  retrospective are immutable.

## Verification contract

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider tests/test_v189_classification_production.py -q -k 'stream or range or cleanup or mutation or symlink'`
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider tests/test_v189_classification_production.py -q`
- Relevant classification contract/production tests, direct probes, and
  `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/http/runs_routes.py backend/workbench/repository/file_integrity.py`.
- `git diff --check b57cc22de59f55cee9e349360dae281f7b3016cf..HEAD`.
- Formal verify and retrospective through `scripts/devline_control.py`.

## Known gates

Inherited fixture and environment gates remain explicit `NOT VERIFIED` unless
rerun in this line: `tests/test_api.py -q -k artifacts` (remediation-15 had
2 failed, 6 passed, 31 deselected, 1 warning),
`tests/predictive_research/test_consumer_projection_v186.py` (remediation-15
had 1 failed, 3 passed), and `tests/test_v189_artifact_integrity.py`
(remediation-15 had 3 failed, 1 warning). Central Agent/Notebook/Report,
browser-visible acceptance, external provider calls, host gate/full gate,
performance, release, merge, push, and tag verification remain
`NOT VERIFIED`.

## Boundary
- Affected paths: `backend/workbench/http/runs_routes.py`, `tests/test_v189_classification_production.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-production-remediation-16-objective.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p1-classification-production-remediation-16.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-16-handoff.md`
- Allowed paths: `backend/workbench/http/runs_routes.py`, `tests/test_v189_classification_production.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-production-remediation-16-objective.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p1-classification-production-remediation-16.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-16-handoff.md`
- Protected paths: `backend/workbench/predictive_research/consumer_projection.py`, `backend/workbench/repository/run_repository.py`, `backend/workbench/prediction.py`, `backend/workbench/reporting.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/predictive_research/persistence.py`, `.agent/devlines/v1-8-9-p1-classification-production-remediation-15`
- Dependencies: `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-15-handoff.md`, `.agent/devlines/v1-8-9-p1-classification-production-remediation-15/RETROSPECTIVE.md`
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider tests/test_v189_classification_production.py -q -k 'stream or range or cleanup or mutation or symlink'`, `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider tests/test_v189_classification_production.py -q`, `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/http/runs_routes.py backend/workbench/repository/file_integrity.py`, `git diff --check b57cc22de59f55cee9e349360dae281f7b3016cf..HEAD`
- Known gates: `Inherited API artifact fixture: tests/test_api.py -q -k artifacts had 2 failed, 6 passed, 31 deselected, 1 warning in remediation-15; rerun or keep NOT VERIFIED`, `Inherited consumer_projection fixture: tests/predictive_research/test_consumer_projection_v186.py had 1 failed, 3 passed in remediation-15; out of scope`, `Inherited artifact-integrity fixture: tests/test_v189_artifact_integrity.py had 3 failed, 1 warning in remediation-15; rerun or keep NOT VERIFIED`, `Central Agent, Notebook, Report, browser, external provider, host/full gate, performance, release, merge, push, and tag acceptance remain NOT VERIFIED unless explicitly run`

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

### v1-8-3-document-authority-consolidation (2026-07-26T03:30:00.000Z)

Completed formal devline v1-8-3-document-authority-consolidation; final_state=COMPLETED; failure_lesson_keys=none
