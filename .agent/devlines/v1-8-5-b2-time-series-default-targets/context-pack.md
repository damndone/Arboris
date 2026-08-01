# Frozen Context Pack

Line: `v1-8-5-b2-time-series-default-targets`
Baseline SHA: `4f8105c7d833edfe0d661f29e47f4ecd04b1d9a6`

## Objective
# v1.8.5 B2 — Time-Series Memory Default Targets Objective

This is the bounded B2 slice of
`2026-07-31-v1.8.5-typed-memory-and-model-family-design.md`.  The parent
design remains the only version-scope authority.

## Objective

After C2 has published server-owned `RecipeContract` vocabularies, admit one
strictly bounded `suggest_default` surface for each existing time-series
Recipe: `model_options.time_index_semantics`.

The registry—not a memory's prose—owns the executable id, exact field, three
literal values, method-risk presentation, source-column prerequisites, and
provenance.  A memory can propose the interpretation of an already selected
time index; it cannot select a series, infer a cadence, choose an estimator,
choose ARMA/GARCH orders or transformations, alter a sample, or bypass a
Recipe's planning/data validation.

## Scope

- Publish the six exact targets for `time_series.ets` and
  `time_series.arma_garch`: `regular_calendar`,
  `business_or_trading_observations`, and `observation_order`.
- Make every target require the Recipe's already-declared non-empty
  `time_column` and `value_column` fields before a default can be injected.
  Existing Recipe planning validation must still verify that those names occur
  in current completed column evidence.  This is not frequency inference.
- Publish the same target identifiers in the Recipe payload that the Notebook
  gives the Agent, so a future approved memory cannot reference a hidden or
  stale writable field.
- Preserve B1 priority and safety semantics: explicit user/Agent values win;
  conflicting same-scope memories do not choose a winner; unsupported or
  legacy targets do not patch a proposal; every applied value carries an exact
  `memory_id`, revision and target reference; revalidation is fail-closed.
- Add red-first unit and planning-submission coverage for application,
  explicit-value precedence, missing recipe inputs, source-column refusal, and
  payload/registry identity.
- Perform one visible Workbench acceptance on the existing local time-series
  project using an approved local memory: planning → visible source/default →
  confirmation → Draft validation.  Execution is optional only when the
  generated specification is otherwise supported; no new estimator is added.

## Explicit non-scope

- No automatic frequency inference, cadence detection, seasonal-period,
  transform, ARMA/GARCH-order, dependent-variable, training-sample, or
  estimator selection.
- No arbitrary `model_options` patching, new Recipe, model family, estimator,
  workflow, artifact type, retrieval system, or frontend redesign.
- No relaxation of Proposal/Risk confirmation, evidence admission, current
  source-column validation, or memory validity rules.

## Acceptance

The new tests must fail before registry/payload implementation and pass after.
The focused memory, Recipe and Notebook-planning suites must stay green, as
must `tests/test_no_exercise_specific_naming.py` and TypeScript.  Browser
evidence must distinguish a visible Draft/default from an executed Run; it
must not claim a memory default proves calendar frequency or an estimator's
statistical validity.

## Boundary
- Affected paths: `backend/workbench/agent/notebook/memory_defaults.py`
- Allowed paths: `docs/superpowers/specs/2026-08-01-v1.8.5-b2-time-series-default-targets-objective.md`, `backend/workbench/agent/notebook/memory_defaults.py`, `backend/workbench/agent/recipe_contracts.py`, `tests/test_notebook_memory_defaults.py`, `tests/test_recipe_contracts.py`, `tests/test_notebook_planning_agent.py`
- Protected paths: `backend/workbench/domain_memory`, `backend/workbench/contracts`, `backend/workbench/engine`, `backend/workbench/model_options.py`, `backend/workbench/agent/workflow_contracts.py`, `backend/workbench/agent/workflow_runtime.py`, `frontend`, `docs/superpowers/plans`
- Dependencies: `v1-8-5-b1-default-target-registry`, `v1-8-5-c2-time-series-recipe`
- Tests: `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_notebook_memory_defaults.py tests/test_recipe_contracts.py tests/test_notebook_planning_agent.py`, `LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python -m pytest -q tests/test_no_exercise_specific_naming.py`, `npx tsc --noEmit`
- Known gates: `Do not start or retain Vite during backend gates.`, `Current Codex nested Seatbelt may make sandbox-exec fail with sandbox_apply: Operation not permitted; record it and do not skip or xfail.`, `Run TypeScript directly; do not pipe npx tsc through tail.`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-5-b1-default-target-registry (2026-08-01T13:00:04.000Z)

Completed formal devline v1-8-5-b1-default-target-registry; final_state=COMPLETED; failure_lesson_keys=default-target-registry-needs-explicit-scope-and-vocabulary, memory-default-source-roundtrip-exact-keys, memory-projection-versioned-authority-boundary
