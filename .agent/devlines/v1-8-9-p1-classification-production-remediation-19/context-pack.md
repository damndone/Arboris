# Frozen Context Pack

Line: `v1-8-9-p1-classification-production-remediation-19`
Baseline SHA: `9cd2cef028ac8ee308862045f03000dd651d4630`

## Objective
# Workbench v1.8.9 P1 classification production remediation-19 objective

- Exact baseline: `9cd2cef028ac8ee308862045f03000dd651d4630`.
- Formal line: `v1-8-9-p1-classification-production-remediation-19`.
- Target worktree: `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-p1-classification-production`.
- Scope: close the independent quality-review P1 in the Workbench-owned
  generic artifact download Range/If-Range ordering boundary.

## Required outcome

1. When the `Range` header is present, strictly parse it before applying the
   existing `If-Range` gate. Present-but-empty and malformed values must always
   return the existing explicit malformed-range `400`, including with a stale
   `If-Range` value; they must never silently downgrade to a full `200`.
2. A syntactically valid Range with a stale `If-Range` must retain the existing
   full-download `200` semantics. A valid Range with a matching or absent
   `If-Range` must retain the existing partial response semantics.
3. A missing `Range` header must continue to return an ordinary full `200`
   download and must explicitly have no `Content-Range` header.
4. Preserve same-FD bounded streaming, compatibility headers, cleanup,
   integrity/TOCTOU checks, strict parser grammar and satisfiability semantics,
   and all classification contracts without regression.

## Allowed paths

- `backend/workbench/http/runs_routes.py`
- `tests/test_v189_classification_production.py`
- `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-production-remediation-19-objective.md`
- `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-19-handoff.md`
- `.agent/devlines/v1-8-9-p1-classification-production-remediation-19/**` (only through `scripts/devline_control.py`)

## Protected boundaries

- The repository root checkout and every other worktree are out of scope.
- Do not reset, checkout, delete, or overwrite existing user work.
- Existing remediation-18 and earlier formal records, Context Packs,
  retrospectives, objectives, and handoffs are immutable.
- `backend/workbench/repository/file_integrity.py`, classification
  list/index/consumer seams, central Agent/Notebook/Report consumers, and
  unrelated artifact integrity/security boundaries are unchanged.
- Do not push, merge, tag, or modify release state.

## Verification contract

- TDD RED then GREEN for stale `If-Range` plus empty, invalid, and valid Range
  regressions, with an explicit no-Range `Content-Range` absence assertion.
- Focused production Range/stream/cleanup/integrity/TOCTOU tests.
- Full `tests/test_v189_classification_production.py`.
- Classification contract suites:
  `tests/predictive_research/test_classification_contracts_v189.py`,
  `tests/predictive_research/test_classification_protocol_v189.py`,
  `tests/predictive_research/test_classification_leakage_v189.py`, and
  `tests/predictive_research/test_classification_consumers_v189.py`.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/http/runs_routes.py backend/workbench/repository/file_integrity.py`.
- `git diff --check` against the exact baseline.
- Formal `verify`, CLI-generated `retrospective`, formal GATE events, and a
  scoped commit with exact HEAD and source digests.

## Known gates

Inherited fixture/environment gates, central Agent/Notebook/Report integration,
browser-visible acceptance, external-provider calls, host/full gate,
performance, release, merge, push, and tag verification remain `NOT VERIFIED`
unless explicitly rerun and evidenced in this line.

## Boundary
- Affected paths: `backend/workbench/http/runs_routes.py`, `tests/test_v189_classification_production.py`
- Allowed paths: `backend/workbench/http/runs_routes.py`, `tests/test_v189_classification_production.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-classification-production-remediation-19-objective.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-19-handoff.md`, `.agent/devlines/v1-8-9-p1-classification-production-remediation-19`
- Protected paths: `backend/workbench/repository/file_integrity.py`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-classification-production-remediation-18-handoff.md`, `.agent/devlines/v1-8-9-p1-classification-production-remediation-18`
- Dependencies: `v1-8-9-p1-classification-production-remediation-18`
- Tests: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider tests/test_v189_classification_production.py -q -k 'range or stream or cleanup or mutation or symlink'`, `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider tests/test_v189_classification_production.py -q`, `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest -p no:cacheprovider tests/predictive_research/test_classification_contracts_v189.py tests/predictive_research/test_classification_protocol_v189.py tests/predictive_research/test_classification_leakage_v189.py tests/predictive_research/test_classification_consumers_v189.py -q`, `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench/http/runs_routes.py backend/workbench/repository/file_integrity.py`, `git diff --check`
- Known gates: `No push, merge, or tag`, `Browser-visible acceptance and central integration`, `Host/full gate and release readiness`

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
