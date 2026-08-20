# Frozen Context Pack

Line: `v1-8-9-p0-survey-absence-boundary`
Baseline SHA: `7756709aa9c34084ccfe1e2e9060af4c5a9423f9`

## Objective
# Workbench v1.8.9 P0 survey-absence boundary objective

## Objective

Close the workflow correctness regression at exact baseline
`7756709aa9c34084ccfe1e2e9060af4c5a9423f9`: an ordinary run that does not
declare a survey subpopulation is currently forwarded as the empty string and
rejected by the typed Survey adapter as `SURVEY_SUBPOP_INVALID`.

The fix must preserve the distinction between an omitted optional declaration
(`None`, meaning no subpopulation) and an explicitly invalid declaration
(including an empty string supplied through a typed programmatic boundary,
which remains fail-closed).

## Required behavior

- HTTP `/runs` and `/runs/batch` use `None` for an omitted survey subpopulation.
- `_submit_run` and `_bg_run` preserve `None` as absence and do not invent an
  empty expression.
- Explicit invalid typed values still reach the Survey adapter and fail closed.
- Existing declared Survey wiring, falsey-value rejection, FPC/design limits,
  and report evidence boundaries remain unchanged.
- Add a regression probe at the HTTP-to-dispatch boundary and run the focused
  Survey wiring plus affected workflow truth tests.

## Scope

Allowed product/test/document paths:

- `backend/workbench/http/runs_routes.py`
- `backend/workbench/services/run_service.py`
- `tests/test_survey_design_wiring_v187.py`
- `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-survey-absence-boundary-objective.md`
- `docs/superpowers/plans/2026-08-20-survey-absence-boundary.md`
- `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-survey-absence-boundary-handoff.md`

Protected paths include the Survey statistical engine, central Agent/Notebook/
Report cutover, other worktrees, release/merge/tag/push machinery, and all
historical formal records.

## Baseline, dependencies, and gates

- Exact baseline: `7756709aa9c34084ccfe1e2e9060af4c5a9423f9`.
- Dependency: `v1-8-9-p0-report-compose-closure` (read-only historical evidence).
- Required checks: TDD RED before production edits, focused Survey wiring and
  workflow truth tests, compileall, `git diff --check`, formal verify, and a
  formal retrospective.
- Known gates remain `NOT VERIFIED`: central candidate acceptance, browser,
  external provider/oracle, host, full gate, release readiness, merge, tag,
  and push.

## Completion target

The line may close only when the omitted HTTP declaration is proven to reach
the runtime as `None`, explicit invalid declarations remain rejected, the
focused suite is green, and the exact handoff is frozen before the final
formal state event.

## Boundary
- Affected paths: `backend/workbench/http/runs_routes.py`, `backend/workbench/services/run_service.py`, `tests/test_survey_design_wiring_v187.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-survey-absence-boundary-objective.md`, `docs/superpowers/plans/2026-08-20-survey-absence-boundary.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-survey-absence-boundary-handoff.md`
- Allowed paths: `backend/workbench/http/runs_routes.py`, `backend/workbench/services/run_service.py`, `tests/test_survey_design_wiring_v187.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-survey-absence-boundary-objective.md`, `docs/superpowers/plans/2026-08-20-survey-absence-boundary.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-survey-absence-boundary-handoff.md`
- Protected paths: none
- Dependencies: `v1-8-9-p0-report-compose-closure`
- Tests: `tests/test_survey_design_wiring_v187.py`, `tests/test_workflow_runtime.py`, `tests/test_v189_workflow_truth.py`
- Known gates: `central candidate acceptance remains NOT VERIFIED`, `browser/provider/host/full-gate/release remain NOT VERIFIED`

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

### local-contained-execution (2026-07-20T17:44:54.000Z)

Completed formal devline local-contained-execution; final_state=CLOSED; failure_lesson_keys=none

### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass
