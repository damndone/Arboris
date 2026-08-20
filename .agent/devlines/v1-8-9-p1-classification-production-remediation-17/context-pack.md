# Frozen Context Pack

Line: `v1-8-9-p1-classification-production-remediation-17`
Baseline SHA: `1a910c6c83d5d57b35d37031ca84b5d8b15b3255`

## Objective
# Workbench v1.8.9 P1 classification production remediation-17 objective

- Exact baseline: `1a910c6c83d5d57b35d37031ca84b5d8b15b3255`.
- Formal line: `v1-8-9-p1-classification-production-remediation-17`.
- Scope: correct the independent code-quality P1 in the Workbench-owned
  generic artifact Range parser without changing the root checkout or any
  other worktree.

## Required outcome

1. Keep the 64 KiB Range-header and 64-range bounds, Workbench ownership,
   single/multipart ranges, `If-Range`, compatibility headers, same-FD bounded
   streaming, cleanup, and existing 400/416 response boundaries.
2. Enforce a strict ASCII numeric grammar for byte-range components. Any
   malformed range component or malformed range-set must fail explicitly with
   the existing malformed-range `400`; it must never be silently discarded.
   For example, `garbage` and `+1-2` are invalid.
3. Apply RFC byte-range-set semantics after syntax validation: syntactically
   valid but unsatisfiable components are ignored when at least one
   syntactically valid component is satisfiable; return `416` only when no
   component is satisfiable. Preserve malformed ordering as `400`.
4. Add TDD regression tests for mixed valid/unsatisfiable ranges, mixed valid/
   malformed ranges, signed numeric syntax, all-unsatisfiable ranges, and
   the existing Range/If-Range/header/stream cleanup boundaries.

## Allowed paths

- `backend/workbench/http/runs_routes.py`
- `tests/test_v189_classification_production.py`
- `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-production-remediation-17-objective.md`
- `docs/superpowers/plans/2026-08-20-v1.8.9-p1-classification-production-remediation-17.md`
- `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-17-handoff.md`
- `.agent/devlines/v1-8-9-p1-classification-production-remediation-17/**` (only
  through `scripts/devline_control.py`).

## Protected boundaries

- The repository root checkout and every other worktree are out of scope.
- Existing remediation-16 formal events, Context Pack, manifest,
  retrospective, and handoff are immutable.
- `backend/workbench/repository/file_integrity.py` is unchanged in this line;
  the rem16 64 KiB/512 MiB/same-FD/cleanup/TOCTOU seam remains the consumer.
- Classification list/index/consumer seams, central Agent/Notebook/Report
  consumers, and the remediation-15 `consumer_projection` whole-body residual
  are out of scope.

## Verification contract

- RED, then GREEN focused parser/range tests with
  `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider`.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider tests/test_v189_classification_production.py -q -k 'stream or range or cleanup or mutation or symlink'`.
- Full `tests/test_v189_classification_production.py`, classification contract
  suites, direct parser/route probes, and the existing replacement callbacks
  with `raising=True`.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/http/runs_routes.py backend/workbench/repository/file_integrity.py`.
- `git diff --check 1a910c6c83d5d57b35d37031ca84b5d8b15b3255..HEAD`.
- Formal `verify` and CLI-generated `retrospective`, with `unresolved=0`.

## Known gates

Inherited rem16 fixture/environment gates remain explicit `NOT VERIFIED`
unless rerun in this line: `tests/test_api.py -q -k artifacts` (remediation-15
recorded 2 failed, 6 passed, 31 deselected, 1 warning),
`tests/predictive_research/test_consumer_projection_v186.py` (1 failed,
3 passed), and `tests/test_v189_artifact_integrity.py` (3 failed, 1 warning).
Central Agent/Notebook/Report, browser-visible acceptance, external provider,
host/full gate, performance, release, merge, push, and tag verification remain
`NOT VERIFIED`.

## Boundary
- Affected paths: `backend/workbench/http/runs_routes.py`, `tests/test_v189_classification_production.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-production-remediation-17-objective.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p1-classification-production-remediation-17.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-17-handoff.md`
- Allowed paths: `backend/workbench/http/runs_routes.py`, `tests/test_v189_classification_production.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-production-remediation-17-objective.md`, `docs/superpowers/plans/2026-08-20-v1.8.9-p1-classification-production-remediation-17.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-17-handoff.md`
- Protected paths: `.agent/devlines/v1-8-9-p1-classification-production-remediation-16`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-16-handoff.md`, `backend/workbench/repository/file_integrity.py`, `backend/workbench/predictive_research/consumer_projection.py`, `backend/workbench/repository/run_repository.py`, `backend/workbench/prediction.py`, `backend/workbench/reporting.py`, `backend/workbench/http/notebook_routes.py`, `backend/workbench/predictive_research/persistence.py`
- Dependencies: `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-16-handoff.md`, `.agent/devlines/v1-8-9-p1-classification-production-remediation-16/RETROSPECTIVE.md`
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider tests/test_v189_classification_production.py -q -k 'stream or range or cleanup or mutation or symlink'`, `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider tests/test_v189_classification_production.py -q`, `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider tests/predictive_research/test_classification_contracts_v189.py tests/predictive_research/test_classification_protocol_v189.py tests/predictive_research/test_classification_leakage_v189.py tests/predictive_research/test_classification_consumers_v189.py -q`, `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/http/runs_routes.py backend/workbench/repository/file_integrity.py`, `git diff --check 1a910c6c83d5d57b35d37031ca84b5d8b15b3255..HEAD`
- Known gates: `Inherited API artifact fixture: tests/test_api.py -q -k artifacts had 2 failed, 6 passed, 31 deselected, 1 warning in rem15; keep NOT VERIFIED`, `Inherited consumer_projection fixture: tests/predictive_research/test_consumer_projection_v186.py had 1 failed, 3 passed; out of scope`, `Inherited artifact-integrity fixture: tests/test_v189_artifact_integrity.py had 3 failed, 1 warning; keep NOT VERIFIED`, `Central Agent, Notebook, Report, browser, external provider, host/full gate, performance, release, merge, push, and tag acceptance remain NOT VERIFIED`

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
