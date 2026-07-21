# Frozen Context Pack

Line: `v1-8-arma-garch-runtime`
Baseline SHA: `d2cd1eec2583e528ba558cc13e06efd98254e73b`

## Objective
# v1.8 ARMA–GARCH Runtime Objective

## Objective

Implement and verify the approved generic `time_series.arma_garch` Model Pack for one confirmed time column and one numeric value column. Deliver bounded automatic and manual ARMA/ARCH/GARCH workflows, strict sequential versus joint semantics, one-step rolling validation, traceable artifacts, Graph/run lifecycle, UI, Agent proposals, Compare, synthetic known-truth acceptance, and conditional VIX regression acceptance.

## Scope boundary

Use `statsmodels` for ARMA and public `arch` APIs for ARCH/GARCH. Do not add a custom likelihood or optimizer, joint MA–GARCH, multivariate/exogenous/seasonal models, automatic interpolation/filling/aggregation, multi-step forecasts, or automatic VaR claims. Source datasets remain immutable and user confirmation is required for transform and time semantics.

The full approved requirements are in the user attachment and the execution checklist is `docs/superpowers/plans/2026-07-20-v1.8-arma-garch-volatility-workbench-implementation-plan.md`.

## Acceptance evidence

Focused TDD suites, deterministic synthetic known-truth tests, immutable-source and no-leakage proofs, Pack/Graph/Artifact/Agent/Compare/UI integration tests, visible UI smoke, quick and full repository gates, and explicit VIX skip evidence when no real repository VIX input exists.

## Boundary
- Affected paths: `backend/workbench/contracts/model`, `backend/workbench/engine/packs/arma_garch`, `backend/workbench/engine/packs/builtin_declarations.py`, `backend/workbench/services`, `backend/workbench/agent`, `frontend/src`, `tests`, `docs/superpowers/contracts/time-series-diagnostics/v1`, `pyproject.toml`
- Allowed paths: `backend/workbench/contracts/model`, `backend/workbench/engine/packs/arma_garch`, `backend/workbench/engine/packs/builtin_declarations.py`, `backend/workbench/services`, `backend/workbench/agent`, `backend/workbench/http`, `backend/workbench/lineage`, `frontend/src`, `tests`, `docs/superpowers`, `pyproject.toml`
- Protected paths: `backend/workbench/engine/packs/linear_mixed_effects`, `docs/superpowers/release-trains/v1.7.3`
- Dependencies: `v1.7.3 released baseline`, `statsmodels ARIMA and arch 8 public APIs`
- Tests: `focused ARMA-GARCH TDD suites`, `frontend tests and typecheck`, `quick and full repository gates`
- Known gates: `no source mutation or validation leakage`, `no sequential composite IC or silent joint MA downgrade`, `no push PR merge or tag without approval`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### wo-a-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-agent; final_state=CLOSED; failure_lesson_keys=filesystem-persistence-capability-bypass

### local-contained-execution (2026-07-20T17:44:54.000Z)

Completed formal devline local-contained-execution; final_state=CLOSED; failure_lesson_keys=none

### wo-a-live-agent (2026-07-20T17:44:54.000Z)

Completed formal devline wo-a-live-agent; final_state=CLOSED; failure_lesson_keys=none

### integration-v1-7-3 (2026-07-20T17:43:14.000Z)

Completed formal devline integration-v1-7-3; final_state=CLOSED; failure_lesson_keys=c1-c2-execution-boundary, cross-boundary-fixture-parity, declared-owner-no-test-shadowing, entrypoint-contract-coverage, runtime-contract-assembly, versioned-result-visible-reader-adapter

### v173-c2-native-acceptance (2026-07-20T16:55:33.000Z)

Completed formal devline v173-c2-native-acceptance; final_state=CLOSED; failure_lesson_keys=c2-runtime-trust-identity

### wo-b-model-pack (2026-07-20T17:44:54.000Z)

Completed formal devline wo-b-model-pack; final_state=CLOSED; failure_lesson_keys=versioned-public-result-contract

### wo-c-ui (2026-07-20T17:44:54.000Z)

Completed formal devline wo-c-ui; final_state=CLOSED; failure_lesson_keys=none
