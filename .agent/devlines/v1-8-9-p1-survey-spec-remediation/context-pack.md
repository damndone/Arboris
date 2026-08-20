# Frozen Context Pack

Line: `v1-8-9-p1-survey-spec-remediation`
Baseline SHA: `319249e6541d202345f2acb63484cf90c7dc3153`

## Objective
# Workbench v1.8.9 P1 Survey specification remediation objective

## Objective

Repair only the independent Survey P1 specification blockers at the existing
workflow, Agent result-summary, and Report projection seams. Preserve the
shared OLS/Logit/Probit/Poisson survey variance engine, sampling weights,
replicate weights, and Poisson exposure validation. Do not modify central
integration, browser/provider/host acceptance, or release machinery.

## Required behavior

- Every survey declaration distinguishes absent from present falsey values.
  `0`, `False`, empty weight/subpopulation frames, and other declared values
  must not be swallowed by defaults. A present value with the wrong type or
  invalid content fails closed with a typed Survey error and cannot continue as
  an ordinary model.
- Agent result summaries and consumer projections omit optional fields that are
  absent from persisted evidence. They must not invent `survey_design=None`,
  `marginal_effects=[]`, or equivalent placeholders. Persisted survey design,
  variance source, provenance, and replicate metadata remain bounded and typed.
- Real workflow and Agent/Report probes cover the falsey and no-invention
  boundaries. Existing shared variance, weights, replicate weights, and
  exposure safety must remain green.
- Formal records use only `scripts/devline_control.py`; every material review,
  gap, failure, state change, and gate is appended through the CLI. The final
  handoff reports the exact product tip and current test numbers and keeps
  central admitted Report, browser, provider, host, full-gate, and release
  evidence explicitly `NOT VERIFIED`.

## Boundary

This is a package-local remediation. It may change only the Survey declaration
and projection seams, their directly affected tests, this objective, the new
formal line records, and the exact handoff. It must not alter the historical
`v1-8-9-p1-survey-extension` line or the completed
`v1-8-9-p1-survey-formal-closeout-remediation` line.

## Baseline and gates

- Baseline SHA: `319249e6541d202345f2acb63484cf90c7dc3153`
- Dependencies: `v1-8-9-p1-survey-formal-closeout-remediation`,
  `v1-8-9-p1-survey-extension`
- Known gates: central admitted Report, browser acceptance, provider evidence,
  host acceptance, full gate, release/merge/tag remain `NOT VERIFIED`.

## Boundary
- Affected paths: `backend/workbench/survey/adapters.py`, `backend/workbench/engine/stages/pre_estimation_checks.py`, `backend/workbench/engine/stages/estimation.py`, `backend/workbench/orchestrator/__init__.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/survey/projection.py`, `backend/workbench/report_view_model.py`, `tests/test_survey_design_engine_v187.py`, `tests/test_survey_design_wiring_v187.py`, `tests/test_survey_glm_family_wiring_v189.py`, `tests/test_agent_reads_v187_results.py`, `tests/test_report_view_model.py`, `docs/superpowers/objectives/2026-08-19-v1.8.9-p1-survey-spec-remediation-objective.md`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p1-survey-spec-remediation-handoff.md`
- Allowed paths: `backend/workbench/survey/adapters.py`, `backend/workbench/engine/stages/pre_estimation_checks.py`, `backend/workbench/engine/stages/estimation.py`, `backend/workbench/orchestrator/__init__.py`, `backend/workbench/agent/context_tools.py`, `backend/workbench/survey/projection.py`, `backend/workbench/report_view_model.py`, `tests/test_survey_design_engine_v187.py`, `tests/test_survey_design_wiring_v187.py`, `tests/test_survey_glm_family_wiring_v189.py`, `tests/test_agent_reads_v187_results.py`, `tests/test_report_view_model.py`, `docs/superpowers/objectives/2026-08-19-v1.8.9-p1-survey-spec-remediation-objective.md`, `docs/superpowers/handoff/2026-08-19-v1.8.9-p1-survey-spec-remediation-handoff.md`
- Protected paths: `.agent/devlines/v1-8-9-p1-survey-extension`, `.agent/devlines/v1-8-9-p1-survey-formal-closeout-remediation`, `central-integration`, `browser-provider-host-release`
- Dependencies: none
- Tests: none
- Known gates: none

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

### v1-8-8-p7-agent-adoption (2026-08-09T03:20:32.000Z)

Completed formal devline v1-8-8-p7-agent-adoption; final_state=COMPLETED; failure_lesson_keys=browser-report-remains-not-verified, declaration-derived-option-boundaries, design-diagnostic-neutral-envelope, generated-tool-schema-runtime-validation, p7-artifact-identity-preserves-repeatability, parent-workflow-owns-child-vocabulary, workflow-errors-preserve-step-cause

### p4-data-management (2026-08-08T23:58:00.000Z)

Completed formal devline p4-data-management; final_state=COMPLETED; failure_lesson_keys=branch-local-schema-projection, execute-provider-handler-after-projection, formal-event-vocabulary, formal-start-normalized-tags, mutation-derived-values, mutation-live-projection, mutation-no-silent-dataset-omission, p4-contract-first, preserve-existing-branch-return, review-live-registry-api, strip-composition-fields-at-adapter, typed-adapter-parameter-boundary, typed-preview-field-fidelity

### v1-8-5-a5-model-packet-lineage-label (2026-08-01T22:24:00.000Z)

Completed formal devline v1-8-5-a5-model-packet-lineage-label; final_state=COMPLETED; failure_lesson_keys=model-packet-downstream-boundary

### v1-8-5-c4-projection-registry (2026-08-01T21:58:07.000Z)

Completed formal devline v1-8-5-c4-projection-registry; final_state=COMPLETED; failure_lesson_keys=projection-registry-before-recipe-growth

### v1-8-5-c3-recipe-preflight-projection (2026-08-01T21:47:00.000Z)

Completed formal devline v1-8-5-c3-recipe-preflight-projection; final_state=COMPLETED; failure_lesson_keys=c3-gate-dedicated-basetemp, recipe-preflight-before-draft
