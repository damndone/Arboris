# Retrospective — v1-8-5-b2-time-series-default-targets

## Goal

# v1.8.5 B2 — Time-Series Memory Default Targets Objective  This is the bounded B2 slice of \`2026-07-31-v1.8.5-typed-memory-and-model-family-design.md\`.  The parent design remains the only version-scope authority.  ## Objective  After C2 has published server-owned \`RecipeContract\` vocabularies, admit one strictly bounded \`suggest_default\` surface for each existing time-series Recipe: \`model_options.time_index_semantics\`.  The registry—not a memory's prose—owns the executable id, exact field, three literal values, method-risk presentation, source-column prerequisites, and provenance.  A memory can propose the interpretation of an already selected time index; it cannot select a series, infer a cadence, choose an estimator, choose ARMA/GARCH orders or transformations, alter a sample, or bypass a Recipe's planning/data validation.  ## Scope  - Publish the six exact targets for \`time_series.ets\` and   \`time_series.arma_garch\`: \`regular_calendar\`,   \`business_or_trading_observations\`, and \`observation_order\`. - Make every target require the Recipe's already-declared non-empty   \`time_column\` and \`value_column\` fields before a default can be injected.   Existing Recipe planning validation must still verify that those names occur   in current completed column evidence.  This is not frequency inference. - Publish the same target identifiers in the Recipe payload that the Notebook   gives the Agent, so a future approved memory cannot reference a hidden or   stale writable field. - Preserve B1 priority and safety semantics: explicit user/Agent values win;   conflicting same-scope memories do not choose a winner; unsupported or   legacy targets do not patch a proposal; every applied value carries an exact   \`memory_id\`, revision and target reference; revalidation is fail-closed. - Add red-first unit and planning-submission coverage for application,   explicit-value precedence, missing recipe inputs, source-column refusal, and   payload/registry identity. - Perform one visible Workbench acceptance on the existing local time-series   project using an approved local memory: planning → visible source/default →   confirmation → Draft validation.  Execution is optional only when the   generated specification is otherwise supported; no new estimator is added.  ## Explicit non-scope  - No automatic frequency inference, cadence detection, seasonal-period,   transform, ARMA/GARCH-order, dependent-variable, training-sample, or   estimator selection. - No arbitrary \`model_options\` patching, new Recipe, model family, estimator,   workflow, artifact type, retrieval system, or frontend redesign. - No relaxation of Proposal/Risk confirmation, evidence admission, current   source-column validation, or memory validity rules.  ## Acceptance  The new tests must fail before registry/payload implementation and pass after. The focused memory, Recipe and Notebook-planning suites must stay green, as must \`tests/test_no_exercise_specific_naming.py\` and TypeScript.  Browser evidence must distinguish a visible Draft/default from an executed Run; it must not claim a memory default proves calendar frequency or an estimator's statistical validity.

## Final status

STARTED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: N/A (sample=0)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- None recorded.

## Added tests

- No test evidence recorded.

## New rules

- No rule candidate recorded.

## Future guidance

- No guidance recorded.

## Event index

- #1: `4cf4d2f4-b5ab-49b0-92cd-52befcc1eb69` | 2026-08-01T18:33:06.151Z | STATE_CHANGE/line_started | incident=`fd75ddc1-64cf-4505-985b-67c3249879e9` | lesson_key=`frozen-context-before-start` | event_sha256=`d92099775b32fb3c52d6533063fccf442b1a9d6d387ad0d43863430cb7c5bd4a`
