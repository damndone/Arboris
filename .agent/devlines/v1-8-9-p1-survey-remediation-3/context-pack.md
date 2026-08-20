# Frozen Context Pack

Line: `v1-8-9-p1-survey-remediation-3`
Baseline SHA: `9328c3f3c1e96845042be735a3ecd789d0ea1496`

## Objective
# Workbench v1.8.9 Survey remediation-3 objective

## Objective

Close the independent code-quality review blockers against remediation-2/doc tip
9328c3f3c1e96845042be735a3ecd789d0ea1496 without changing root, other
worktrees, completed Survey formal lines, or the Survey statistical engine.
Make Agent-facing low-level projections closed typed schemas and make Notebook
receipt projection use an explicit declared allowlist.

## Required behavior

- _bounded_persisted_model_facts, _bounded_regression_table, and
  _public_requested_model_coefficients emit a field only when its source key
  exists and its bounded validator returns a valid typed value. Missing source
  fields disappear; no synthetic None, [], empty nested dictionaries, or empty
  placeholder cells are emitted. Invalid declared fields fail closed with
  typed status/reason where the projection contract requires a result.
- Pure-function probes and real Agent workflow probes cover sparse valid
  packets, invalid declared metadata, missing optional fields, and preservation
  of typed Survey provenance/design/replicate/coefficient metadata.
- _public_operation_artifact_result and committed Notebook receipt reads use an
  explicit typed allowlist per declared artifact family. Server-owned
  provenance, Survey design/replicate fields, coefficients, and existing
  declared statistical fields survive bounded validation. raw_rows and unknown
  extras never enter the Agent packet or LLM context; invalid declared packets
  are typed unavailable or omit only the invalid optional field.
- Preserve Survey falsey/fail-closed semantics, the shared
  OLS/Logit/Probit/Poisson variance engine, ordinary/replicate weights,
  exposure/FPC behavior, Report projection, and Notebook receipt boundaries.
- Record the remediation-2 handoff digest mismatch without editing its old
  events. The new line must have state_chain_mismatch=0; freeze the final
  handoff before the final CLI state event, make that event reference the
  exact handoff digest, and perform no post-closeout doc-only commit. Owned
  unresolved findings must be 0.

## Scope

Only these product/test/document paths are in scope:

- backend/workbench/agent/context_tools.py
- tests/test_agent_context_tools.py
- tests/test_agent_reads_v187_results.py
- docs/superpowers/objectives/2026-08-20-v1.8.9-p1-survey-remediation-3-objective.md
- docs/superpowers/plans/2026-08-20-survey-remediation-3.md
- docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-remediation-3-handoff.md

Do not modify root files, other worktrees, the completed
v1-8-9-p1-survey-remediation-2 events/Context Pack, any older Survey line,
backend/workbench/survey, backend/workbench/report_view_model.py, central
integration, browser/provider/host paths, or release machinery.

## Baseline and gates

- Exact baseline: 9328c3f3c1e96845042be735a3ecd789d0ea1496
- Dependency: v1-8-9-p1-survey-remediation-2
- The old remediation-2 final event records handoff digest
  ee3cf0551255e0d15567adf5ed210d238d757ec13826e2cfc8834614e02f8760;
  the later doc-only EOF commit changed that handoff without changing old
  events. This historical digest mismatch is a known GAP and must be
  recorded, not repaired in place.
- Central admitted Notebook/Report, browser, provider, host, full-gate, and
  release/merge/tag/push acceptance remain NOT VERIFIED.
- Known foreign-owner Agent fixtures and admitted Report receipt failures
  remain outside this line.

## Boundary
- Affected paths: `backend/workbench/agent/context_tools.py`, `tests/test_agent_context_tools.py`, `tests/test_agent_reads_v187_results.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-survey-remediation-3-objective.md`, `docs/superpowers/plans/2026-08-20-survey-remediation-3.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-remediation-3-handoff.md`
- Allowed paths: `backend/workbench/agent/context_tools.py`, `tests/test_agent_context_tools.py`, `tests/test_agent_reads_v187_results.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-survey-remediation-3-objective.md`, `docs/superpowers/plans/2026-08-20-survey-remediation-3.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-remediation-3-handoff.md`
- Protected paths: `.agent/devlines/v1-8-9-p1-survey-remediation-2`, `.agent/devlines/v1-8-9-p1-survey-spec-remediation`, `.agent/devlines/v1-8-9-p1-survey-formal-closeout-remediation`, `.agent/devlines/v1-8-9-p1-survey-extension`, `backend/workbench/survey`, `backend/workbench/report_view_model.py`, `central-integration`, `browser-provider-host-release`
- Dependencies: `v1-8-9-p1-survey-remediation-2`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_agent_context_tools.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_agent_reads_v187_results.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_report_view_model.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_reporting_exports.py -k 'survey_provenance or regression_table_projects or exported_result_table' -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_survey_glm_family_wiring_v189.py tests/test_survey_design_engine_v187.py tests/test_survey_design_composition_v187.py tests/test_survey_composition_limits_v187.py tests/test_survey_report_visibility_v187.py tests/test_survey_design_wiring_v187.py -q`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`
- Known gates: `central admitted Notebook and Report NOT VERIFIED`, `browser/provider/host acceptance NOT VERIFIED`, `foreign-owner Agent context failures NOT VERIFIED`, `admitted Report receipt failures NOT VERIFIED`, `full gate and release/merge/tag/push NOT VERIFIED`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-8-p7-agent-adoption (2026-08-09T03:20:32.000Z)

Completed formal devline v1-8-8-p7-agent-adoption; final_state=COMPLETED; failure_lesson_keys=browser-report-remains-not-verified, declaration-derived-option-boundaries, design-diagnostic-neutral-envelope, generated-tool-schema-runtime-validation, p7-artifact-identity-preserves-repeatability, parent-workflow-owns-child-vocabulary, workflow-errors-preserve-step-cause

### p4-data-management (2026-08-08T23:58:00.000Z)

Completed formal devline p4-data-management; final_state=COMPLETED; failure_lesson_keys=branch-local-schema-projection, execute-provider-handler-after-projection, formal-event-vocabulary, formal-start-normalized-tags, mutation-derived-values, mutation-live-projection, mutation-no-silent-dataset-omission, p4-contract-first, preserve-existing-branch-return, review-live-registry-api, strip-composition-fields-at-adapter, typed-adapter-parameter-boundary, typed-preview-field-fidelity

### v1-8-5-c3-recipe-preflight-projection (2026-08-01T21:47:00.000Z)

Completed formal devline v1-8-5-c3-recipe-preflight-projection; final_state=COMPLETED; failure_lesson_keys=c3-gate-dedicated-basetemp, recipe-preflight-before-draft

### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none
