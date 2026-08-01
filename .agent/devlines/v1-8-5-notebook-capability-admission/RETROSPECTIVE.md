# Retrospective — v1-8-5-notebook-capability-admission

## Goal

# v1.8.5 slice objective — Notebook workflow capability admission  ## Objective  Make the Notebook planner's native capability catalog derive its workflow-executable set from server-owned \`ModelFamilyContract\` and \`RecipeContract\` registrations. Legacy UI aliases such as \`glm:*\` remain available to the manual capability surface, but must not be advertised to the Notebook Agent until they publish an independent contract for inputs, result shape, diagnostics, and artifact projection.  This is a general admission rule, not a model-specific prompt restriction: new model families become Notebook-plannable by registering their contract; the planner must never infer workflow eligibility from the presence of a handler or a legacy UI alias alone.  ## Scope  - Add one server-owned helper for the native Notebook workflow capability set. - Use it when the Notebook route builds its native planning manifest and when   it creates a persisted source projection's available-capability list. - Preserve deployment-provided capability projections; this slice does not   change custom capability authority or manual \`/capabilities\` output. - Add focused regression tests proving the contract-derived allowlist excludes   uncontracted aliases and includes the registered regression/Recipe families.  ## Explicit non-goals  - Do not remove or rename legacy manual capabilities. - Do not add a new model family, estimator, alias, prompt exception, or   frontend-only filter. - Do not change estimation, artifact payloads, proposal authorization, or   browser behavior.  ## Acceptance evidence  - A red test demonstrates that the native Notebook set is not currently   contract-derived. - Focused Notebook route/planning tests pass after the change. - Existing model-family, Recipe, and frontend type checks remain green. - No browser-acceptance or full-gate claim is made by this slice.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/5 (20.0%; 20.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=180000 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-01T22:31:00.000Z `tdd_red_notebook_capability_contract_admission`; cause_status: `known`; cause: The Notebook route derives its native planning catalog from the broad legacy capability manifest, so an uncontracted GLM alias is eligible even though v1.8.5 does not publish a workflow contract for it.; resolution: `open`; lesson: Notebook workflow eligibility must come from the shared server-owned ModelFamilyContract or RecipeContract registry; handler or legacy UI presence is insufficient.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `notebook-admission-must-require-published-contract`: occurrences=1; cause_status: `known`; root cause: The Notebook route derives its native planning catalog from the broad legacy capability manifest, so an uncontracted GLM alias is eligible even though v1.8.5 does not publish a workflow contract for it.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `notebook-admission-must-require-published-contract`: line experience occurrence(s)=1

## Future guidance

- Notebook workflow eligibility must come from the shared server-owned ModelFamilyContract or RecipeContract registry; handler or legacy UI presence is insufficient.

## Event index

- #1: `da05c08a-cc7f-4c45-bc6b-85f33eb81d65` | 2026-08-01T22:27:36.260Z | STATE_CHANGE/line_started | incident=`2047f8d3-0226-4876-abf9-12a9d3583cec` | lesson_key=`frozen-context-before-start` | event_sha256=`1a9ad0aba51c8aa3f55950cc11ee0f403099ed852ee786af92d13089b4de4d73`
- #2: `5f80d2f4-bc10-45ae-bd5a-35e54d8dfb49` | 2026-08-01T22:31:00.000Z | FAILURE/tdd_red_notebook_capability_contract_admission | incident=`5f80d2f4-bc10-45ae-bd5a-35e54d8dfb49` | lesson_key=`notebook-admission-must-require-published-contract` | event_sha256=`f5451563a6ca083e6e0b03252e8639ae30a237c2905d59ff37d10064f4854bc9`
- #3: `e3a878d8-5907-4745-8bd5-895b0e32f6aa` | 2026-08-01T22:34:00.000Z | REVIEW/notebook_capability_contract_admission_resolved | incident=`5f80d2f4-bc10-45ae-bd5a-35e54d8dfb49` | lesson_key=`notebook-admission-must-require-published-contract` | event_sha256=`154a81650fd13ad85e3f2d9763e966c2bb12020c01d989252543832401ade137`
- #4: `78a8b19a-fbd1-40c4-a23d-e9029a2d1137` | 2026-08-01T22:35:00.000Z | GATE/notebook_capability_contract_admission_gate_passed | incident=`5f80d2f4-bc10-45ae-bd5a-35e54d8dfb49` | lesson_key=`notebook-admission-must-require-published-contract` | event_sha256=`5fee256cd0e56278fb279eaabf2e70c5589799bff0b997f7f35005174eb627a4`
- #5: `e6f73d77-7fd1-4a69-872b-3d1524aa9db8` | 2026-08-01T22:35:30.000Z | STATE_CHANGE/notebook_capability_admission_completed | incident=`5f80d2f4-bc10-45ae-bd5a-35e54d8dfb49` | lesson_key=`notebook-admission-must-require-published-contract` | event_sha256=`05bcd195e021a8f2cff8cb260ad81758cc0c6fb3de168969384af83a630f41c0`
