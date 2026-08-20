# Frozen Context Pack

Line: `v1-8-9-p1-survey-remediation-4`
Baseline SHA: `945da48f91101aad99548cf273088a97ad19d163`

## Objective
# Workbench v1.8.9 P1 Survey remediation-4 objective

## Objective

Repair the independent specification findings against the exact remediation-3
final tip `945da48f91101aad99548cf273088a97ad19d163` without changing the
Survey statistical engine or any central consumer. The repair must close the
low-level Agent/Notebook/Report projection boundaries and preserve the
fail-closed typed evidence contract.

## Required behavior

- P1-A: term keys and coefficient maps are admitted only when their source
  values are bounded and valid. Empty terms, overlong terms, invalid nested
  coefficient maps, and empty nested structures are omitted. A declared
  invalid projection retains only bounded typed
  `projection_status=unavailable` and `unavailable_reason`; it must not
  synthesize `None`, `[]`, `{}`, or placeholder cells.
- P1-B: every artifact numeric field uses finite, field-specific bounds and
  ordering checks. `p_value` is in `[0,1]`, counts are bounded and
  nonnegative, standard errors are positive, confidence intervals are finite
  and ordered, and invalid values do not enter Agent, Notebook, Report, or
  LLM context. Invalid declared fields fail closed with typed status/reason.
- P1-C: P7 nested result projection is depth-bounded and cannot recurse without
  a cap. A payload deeper than the cap becomes a bounded typed unavailable or
  invalid result; it must not raise a bare `RecursionError` or leak nested raw
  content.
- Add pure and real Agent/Notebook/Report probes for all three findings,
  including a deep payload probe and row-count/ordering edge cases.
- Preserve Survey engine, ordinary and replicate weights, falsey declarations,
  exposure, FPC, Survey Report visibility, Notebook receipt boundaries, and
  existing foreign/admitted failure ownership.
- Record the prior remediation-3 objective EOF/selector/digest audit and the
  prior formal `open`/`accepted` versus resolved-incident contradictions by
  CLI events or bounded audit references. Do not edit remediation-3 or older
  events, objectives, Context Packs, manifests, or retrospectives.

## Scope

Allowed product/test/document paths:

- `backend/workbench/agent/context_tools.py`
- `tests/test_agent_context_tools.py`
- `tests/test_agent_reads_v187_results.py`
- `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-survey-remediation-4-objective.md`
- `docs/superpowers/plans/2026-08-20-survey-remediation-4.md`
- `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-remediation-4-handoff.md`

Protected paths:

- `.agent/devlines/v1-8-9-p1-survey-remediation-3`
- `.agent/devlines/v1-8-9-p1-survey-remediation-2`
- `backend/workbench/survey`
- `backend/workbench/report_view_model.py`
- central integration, browser/provider/host, full-gate, release, merge, tag,
  and push machinery

## Baseline and dependencies

- Exact baseline: `945da48f91101aad99548cf273088a97ad19d163`
- Previous product tip: `6a2ebc2d49f998d017da670554141aeabf0270ff`
- Previous handoff:
  `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-remediation-3-handoff.md`
- Dependency: `v1-8-9-p1-survey-remediation-3`
- Historical documentation audit: the prior objective at the `9328c3f3...`
  baseline has an EOF blank-line drift in the later tip; record and correct
  only through this new exact-tip handoff, never by editing its old formal
  evidence.

## Tests and gates

- Pure P1-A/P1-B/P1-C probes in `tests/test_agent_context_tools.py`.
- Real Agent/Notebook/Report probes in the two existing Agent test files.
- `tests/test_agent_context_tools.py` and
  `tests/test_agent_reads_v187_results.py`.
- `tests/test_report_view_model.py` and selected
  `tests/test_reporting_exports.py` projection tests.
- Survey GLM/design/composition/limits/visibility/wiring regression suite.
- Deep payload probes at and beyond the recursion depth cap.
- `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`
  and `git diff --check`.
- Formal `scripts/devline_control.py verify` and `retrospective`.

Known gates remain `NOT VERIFIED`: foreign-owner/admitted fixture failures,
central Notebook/Report cutover, browser acceptance, external provider/oracle
evidence, host acceptance, full gate, release readiness, merge/tag/push.

## Boundary
- Affected paths: `backend/workbench/agent/context_tools.py`, `tests/test_agent_context_tools.py`, `tests/test_agent_reads_v187_results.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-survey-remediation-4-objective.md`, `docs/superpowers/plans/2026-08-20-survey-remediation-4.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-remediation-4-handoff.md`
- Allowed paths: `backend/workbench/agent/context_tools.py`, `tests/test_agent_context_tools.py`, `tests/test_agent_reads_v187_results.py`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p1-survey-remediation-4-objective.md`, `docs/superpowers/plans/2026-08-20-survey-remediation-4.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p1-survey-remediation-4-handoff.md`
- Protected paths: `.agent/devlines/v1-8-9-p1-survey-remediation-3`, `.agent/devlines/v1-8-9-p1-survey-remediation-2`, `backend/workbench/survey`, `backend/workbench/report_view_model.py`, `central-integration`, `browser-provider-host-release`
- Dependencies: `v1-8-9-p1-survey-remediation-3`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_agent_context_tools.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_agent_reads_v187_results.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_report_view_model.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_reporting_exports.py -k 'survey_provenance or regression_table_projects or exported_result_table' -q`, `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_survey_glm_family_wiring_v189.py tests/test_survey_design_engine_v187.py tests/test_survey_design_composition_v187.py tests/test_survey_composition_limits_v187.py tests/test_survey_report_visibility_v187.py tests/test_survey_design_wiring_v187.py -q`, `PYTHONPATH=backend .venv/bin/python -m pytest deep_p1_projection_tests -q`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend/workbench tests`
- Known gates: `foreign-owner Agent context failures NOT VERIFIED`, `admitted Report receipt failures NOT VERIFIED`, `central Notebook/Report cutover NOT VERIFIED`, `browser/provider/oracle/host acceptance NOT VERIFIED`, `full gate and release/merge/tag/push NOT VERIFIED`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-8-statistical-truth-cleanup (2026-08-13T10:11:25.000Z)

Completed formal devline v1-8-8-statistical-truth-cleanup; final_state=COMPLETED; failure_lesson_keys=none

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

### v1-8-4-agent-model-composition (2026-07-31T02:50:00.000Z)

Completed formal devline v1-8-4-agent-model-composition; final_state=COMPLETED; failure_lesson_keys=action-mode-route-enforcement, agent-covariance-interpretation-guardrail, agent-provider-and-tool-boundaries, bounded-model-specification-evidence, bounded-node-evidence-visibility, browser-blocked-run-lineage-identity, browser-policy-blocked-ui-acceptance, canonical-terminal-inspection-reuse, checkpoint-host-gate-separation, closing-event-timestamp-must-follow-the-incident, coefficient-batch-limit-protocol, covariance-comparison-interpretation-boundary, declared-white-test-post-estimation, derive-workflow-artifacts-server-side, existing-genesis-route-tests-failed, failed-inspection-retry, fms-event-enums-must-match-contract, fms-event-input-must-be-repository-relative, formal-event-redaction-text-ambiguity, formal-event-requires-real-evidence-digest, genesis-draft-url-visibility, genesis-draft-visibility-regression, global-agent-model-figure-evidence, global-agent-numeric-evidence-transcription, global-agent-workflow-answer-path, historical-proposal-terminal-message, inherited-suite-failures-must-be-baselined, notebook-persisted-lifecycle, notebook-planner-must-recover-to-server-pinned-rerun-target, notebook-planner-proposes-rerun-outside-active-head-lineage, notebook-planning-deadline-must-be-explicit-and-user-aligned, notebook-planning-evidence-admission, notebook-planning-exceeds-visible-timeout-without-terminal-state, notebook-workflow-dependency-shape-correction, notebook-workflow-evidence-bridge, panel-workflow-model-composition, persisted-draft-hydration-before-empty, planning-elapsed-counter-resets-on-remount, post-estimation-must-reproduce-declared-covariance, post-estimation-requires-explicit-step, predictor-residual-diagnostic-evidence, preexisting-backend-suite-failures, progress-clock-anchors-to-attempt, proposal-ready-boundary-updates-call-count, proposal-ready-terminal-state, provider-catalog-expectation-mismatch, provider-catalog-test-alignment, real-run-tests-must-claim-a-clean-slot, rescope-leaf-path-depth, separate-existing-route-failure, structured-evidence-not-prose-token, verified-categorical-indicator-reuse, white-test-auxiliary-rank-stability, white-test-own-rank-policy, workflow-branch-covariance-preservation, workflow-pin-registry-artifact-identity

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none
