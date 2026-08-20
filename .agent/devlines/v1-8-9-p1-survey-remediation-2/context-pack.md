# Frozen Context Pack

Line: `v1-8-9-p1-survey-remediation-2`
Baseline SHA: `35898162aa6f15420997665a05f70c4f589e6f97`

## Objective
# Workbench v1.8.9 Survey remediation-2 objective

## Objective

Repair the independent Survey spec-review-2 blockers after product tip
`35898162aa6f15420997665a05f70c4f589e6f97`, only at the Agent result,
diagnostics, and committed Notebook packet projection seams. Make absent
persisted fields disappear rather than becoming synthetic `None`/`[]` values,
while preserving typed unavailable status/reason and the existing bounded
Survey metadata contract.

## Required behavior

- `_agent_result_unavailable()` and every Agent result/diagnostics unavailable
  path omit `survey_design`, `regression_table`, `marginal_effects`, and any
  other optional persisted field that is not present. Ordinary non-Survey
  result/diagnostic paths must not synthesize those fields either. Typed
  `available`, status, and reason fields remain present.
- Real Agent workflow probes cover invalid server-owned model artifacts and
  ordinary non-Survey diagnostic/result reads, asserting omission rather than
  `None`/empty placeholders.
- A real committed Notebook receipt probe projects a persisted Survey packet
  through the bounded Agent public-result seam, preserving typed Survey
  metadata when present and omitting it when absent. If admitted Notebook
  coverage is not reachable from this package-local line, record that boundary
  explicitly as `NOT VERIFIED`.
- Existing Survey declaration falsey semantics, fail-closed validation, shared
  OLS/Logit/Probit/Poisson variance engine, weights, replicate weights,
  exposure safety, and Report projection remain unchanged and green.

## Boundary

This is a new package-local remediation line only. It may change the Agent
context projection and directly affected Agent/Notebook/Report tests, this
objective/plan, formal records, and the exact handoff. Do not modify root,
other worktrees, the completed `v1-8-9-p1-survey-spec-remediation` line, the
historical `v1-8-9-p1-survey-extension` line, central integration, or release
machinery.

## Baseline and gates

- Baseline SHA: `35898162aa6f15420997665a05f70c4f589e6f97`
- Dependencies: `v1-8-9-p1-survey-spec-remediation`,
  `v1-8-9-p1-survey-formal-closeout-remediation`
- Central admitted Report, browser acceptance, provider evidence, host
  acceptance, full gate, and release/merge/tag/push remain `NOT VERIFIED`.
- Historical line state-chain breaks are a known formal GAP; remediation-2
  must report the computed number and must not relabel the historical line as
  zero-mismatch.

## Boundary
- Affected paths: `backend/workbench/agent/context_tools.py`, `tests/test_agent_context_tools.py`, `tests/test_agent_reads_v187_results.py`, `tests/test_report_view_model.py`, `tests/test_survey_glm_family_wiring_v189.py`, `tests/test_survey_design_engine_v187.py`, `tests/test_survey_design_wiring_v187.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-survey-remediation-2-objective.md`, `docs/superpowers/plans/2026-08-20-survey-remediation-2.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-remediation-2-handoff.md`
- Allowed paths: `backend/workbench/agent/context_tools.py`, `tests/test_agent_context_tools.py`, `tests/test_agent_reads_v187_results.py`, `tests/test_report_view_model.py`, `tests/test_survey_glm_family_wiring_v189.py`, `tests/test_survey_design_engine_v187.py`, `tests/test_survey_design_wiring_v187.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-survey-remediation-2-objective.md`, `docs/superpowers/plans/2026-08-20-survey-remediation-2.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-remediation-2-handoff.md`
- Protected paths: `.agent/devlines/v1-8-9-p1-survey-spec-remediation`, `.agent/devlines/v1-8-9-p1-survey-extension`, `.agent/devlines/v1-8-9-p1-survey-formal-closeout-remediation`, `central-integration`, `browser-provider-host-release`
- Dependencies: `v1-8-9-p1-survey-spec-remediation`, `v1-8-9-p1-survey-formal-closeout-remediation`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_agent_context_tools.py tests/test_agent_reads_v187_results.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_report_view_model.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_survey_glm_family_wiring_v189.py tests/test_survey_design_engine_v187.py tests/test_survey_design_wiring_v187.py -q`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`
- Known gates: `central admitted Report NOT VERIFIED`, `browser/provider/host acceptance NOT VERIFIED`, `full gate and release/merge/tag/push NOT VERIFIED`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

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

### wo-a-live-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-live-agent; final_state=CLOSED; failure_lesson_keys=none

### v1-8-8-p7-agent-adoption (2026-08-09T03:20:32.000Z)

Completed formal devline v1-8-8-p7-agent-adoption; final_state=COMPLETED; failure_lesson_keys=browser-report-remains-not-verified, declaration-derived-option-boundaries, design-diagnostic-neutral-envelope, generated-tool-schema-runtime-validation, p7-artifact-identity-preserves-repeatability, parent-workflow-owns-child-vocabulary, workflow-errors-preserve-step-cause

### p4-data-management (2026-08-08T23:58:00.000Z)

Completed formal devline p4-data-management; final_state=COMPLETED; failure_lesson_keys=branch-local-schema-projection, execute-provider-handler-after-projection, formal-event-vocabulary, formal-start-normalized-tags, mutation-derived-values, mutation-live-projection, mutation-no-silent-dataset-omission, p4-contract-first, preserve-existing-branch-return, review-live-registry-api, strip-composition-fields-at-adapter, typed-adapter-parameter-boundary, typed-preview-field-fidelity

### v1-8-5-c3-recipe-preflight-projection (2026-08-01T21:47:00.000Z)

Completed formal devline v1-8-5-c3-recipe-preflight-projection; final_state=COMPLETED; failure_lesson_keys=c3-gate-dedicated-basetemp, recipe-preflight-before-draft
