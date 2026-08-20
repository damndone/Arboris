# Frozen Context Pack

Line: `v1-8-9-p1-classification-production-remediation-18`
Baseline SHA: `df8f7ce69ddbd66cb8fbab683456d73617e298ca`

## Objective
# Workbench v1.8.9 P1 classification production remediation-18 objective

- Exact baseline: `df8f7ce69ddbd66cb8fbab683456d73617e298ca`.
- Formal line: `v1-8-9-p1-classification-production-remediation-18`.
- Target worktree: `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p1-classification-production`.
- Scope: close the independent quality-review P2 in the Workbench-owned
  generic artifact download Range boundary without changing other security
  boundaries, the root checkout, or any other worktree.

## Required outcome

1. A present but empty `Range` header must fail explicitly with the existing
   malformed-range `400`; it must never silently downgrade to a full `200`
   response. Other malformed present Range values retain the same explicit
   `400` boundary.
2. A missing `Range` header must continue to return the normal full artifact
   download with `200`, without `Content-Range`.
3. Preserve the Workbench-owned parser, strict range-set grammar, valid
   satisfiability filtering, `If-Range`, compatibility headers, same-FD
   bounded streaming, cleanup, and all existing artifact integrity/security
   boundaries. Do not alter unrelated security seams.
4. Add direct parser and live HTTP regressions covering empty/present-invalid
   versus missing Range headers, while retaining the existing range and stream
   regressions.

## Allowed paths

- `backend/workbench/http/runs_routes.py`
- `tests/test_v189_classification_production.py`
- `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-production-remediation-18-objective.md`
- `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-18-handoff.md`
- `.agent/devlines/v1-8-9-p1-classification-production-remediation-18/**` (only
  through `scripts/devline_control.py`).

## Protected boundaries

- The repository root checkout and every other worktree are out of scope.
- No `reset`, `checkout`, deletion, or overwrite of existing user work.
- Existing remediation-17 and earlier formal records, Context Packs,
  retrospectives, and handoffs are immutable.
- `backend/workbench/repository/file_integrity.py`, classification
  list/index/consumer seams, central Agent/Notebook/Report consumers, and
  unrelated artifact integrity/security boundaries are unchanged.

## Verification contract

- TDD RED then GREEN for the direct parser and live HTTP Range regressions.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider tests/test_v189_classification_production.py -q -k 'range or stream or cleanup or mutation or symlink'`.
- Full `tests/test_v189_classification_production.py` and relevant
  classification contract/production suites.
- Direct parser/HTTP probes, `compileall`, and `git diff --check` against the
  exact baseline.
- Formal `verify` and CLI-generated `retrospective`, with `unresolved=0`.

## Known gates

Inherited fixture/environment gates and central Agent/Notebook/Report,
browser-visible acceptance, external provider, host/full gate, performance,
release, merge, push, and tag verification remain `NOT VERIFIED` unless
explicitly rerun and evidenced in this line.

## Boundary
- Affected paths: `backend/workbench/http/runs_routes.py`, `tests/test_v189_classification_production.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-production-remediation-18-objective.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-18-handoff.md`
- Allowed paths: `backend/workbench/http/runs_routes.py`, `tests/test_v189_classification_production.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-production-remediation-18-objective.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-18-handoff.md`
- Protected paths: `.agent/devlines/v1-8-9-p1-classification-production-remediation-17/context-pack.md`, `.agent/devlines/v1-8-9-p1-classification-production-remediation-17/context-pack.manifest.json`, `.agent/devlines/v1-8-9-p1-classification-production-remediation-17/events.jsonl`, `.agent/devlines/v1-8-9-p1-classification-production-remediation-17/RETROSPECTIVE.md`
- Dependencies: none
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider tests/test_v189_classification_production.py -q -k "range or stream or cleanup or mutation or symlink"`, `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider tests/test_v189_classification_production.py -q`
- Known gates: `Inherited rem17 fixture/environment and central integration gates remain NOT VERIFIED unless rerun in this line.`

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
