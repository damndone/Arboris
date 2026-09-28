# Frozen Context Pack

Line: `v1-8-9-p0-legacy-consumer-gate-migration`
Baseline SHA: `f3836408cf15c3e7380823e5c1b303b4467c7aec`

## Objective
# v1.8.9 P0 Legacy Consumer Gate Migration Objective

Migrate the remaining legacy consumer seams to the current typed, server-owned
contracts using tests and fixtures only. Investigate every failure from the
required focused gate and make the smallest test-only or fixture-only change
that exercises the existing report, evidence, and proposal seams.

This line must not modify production code, restore raw model-result or unbound
report fallbacks, reintroduce caller-owned executor/path behavior, or add an
untyped proposal-store fallback. Existing unrelated dirty worktree changes
are outside this line and must remain untouched.

## Completion boundary

- All 22 focused failures are classified and either corrected in the owned
  tests/goldens or recorded as an unresolved production-owner blocker.
- The focused test command, backend compileall, and `git diff --check` have
  fresh evidence.
- Formal events, verification, retrospective, and handoff are produced through
  `scripts/devline_control.py` and the handoff records exact limits.
- No browser, provider, release, merge, or production-readiness claim is made
  by this test/fixture migration line.

## Boundary
- Affected paths: `tests/models/arma_garch/test_deliverables.py`, `tests/predictive_research/test_consumer_projection_v186.py`, `tests/test_agent_analysis_loop_lifecycle.py`, `tests/test_engine_golden.py`, `tests/golden`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-consumer-gate-migration-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-legacy-consumer-gate-migration.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-consumer-gate-migration-handoff.md`
- Allowed paths: `tests/models/arma_garch/test_deliverables.py`, `tests/predictive_research/test_consumer_projection_v186.py`, `tests/test_agent_analysis_loop_lifecycle.py`, `tests/test_engine_golden.py`, `tests/golden`, `docs/superpowers/objectives/2026-08-20-v1.8.9-p0-legacy-consumer-gate-migration-objective.md`, `docs/superpowers/release-trains/v1.8.9/work-orders/wo-p0-legacy-consumer-gate-migration.md`, `docs/superpowers/handoff/2026-08-20-v1.8.9-p0-legacy-consumer-gate-migration-handoff.md`
- Protected paths: `backend`, `frontend`, `scripts`, `.agent/devlines`
- Dependencies: `v1-8-6-predictive-research-integration`, `v1-8-8-statistical-truth-cleanup`, `v1-8-9-p1-data-consumer-runtime-port`
- Tests: `PYTHONPATH=backend .venv/bin/python -m pytest tests/models/arma_garch/test_deliverables.py tests/predictive_research/test_consumer_projection_v186.py tests/test_agent_analysis_loop_lifecycle.py tests/test_engine_golden.py -q`, `PYTHONPATH=backend .venv/bin/python -m compileall -q backend`, `git diff --check`
- Known gates: `no production changes; browser/provider/full-gate/release evidence remain NOT VERIFIED`, `all 22 focused failures must be classified before close`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-agent-evidence-loop (2026-07-28T15:52:01.000Z)

Completed formal devline v1-8-4-agent-evidence-loop; final_state=COMPLETED; failure_lesson_keys=agent-completed-operation-evidence-boundary, public-artifact-aggregate-budget

### v1-8-3-integration-acceptance (2026-07-28T12:11:00.000Z)

Completed formal devline v1-8-3-integration-acceptance; final_state=COMPLETED; failure_lesson_keys=formal-cli-command-surface, formal-scope-narrowing, supported-host-containment-required

### v1-8-3-mem3-memory-curator-exact-baseline (2026-07-27T11:35:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator-exact-baseline; final_state=COMPLETED; failure_lesson_keys=curator-contract-first, review-api-awaits-response

### v1-8-3-mem3-memory-curator (2026-07-27T11:10:00.000Z)

Completed formal devline v1-8-3-mem3-memory-curator; final_state=CLOSED; failure_lesson_keys=none

### v1-8-5-c1-regression-family-admission (2026-08-01T13:48:08.000Z)

Completed formal devline v1-8-5-c1-regression-family-admission; final_state=COMPLETED; failure_lesson_keys=family-column-fields-preserve-elementwise, family-contract-drives-source-schema-validation, family-input-validation-before-genesis, materialization-uses-family-contract-not-ols-heuristic, model-family-field-ownership-fail-closed, normalized-fms-tag-before-start, notebook-delegates-to-shared-family-contract, regression-family-contract-before-admission
