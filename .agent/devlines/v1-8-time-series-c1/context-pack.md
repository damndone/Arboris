# Frozen Context Pack

Line: `v1-8-time-series-c1`
Baseline SHA: `b5258e966a28d95d2facd2c89a776fe7719b22cc`

## Objective
# v1.8 Time Series Diagnostics C1 Objective

## Objective

Freeze and prove the first-slice Time Series Diagnostics public contract.
This is a C1 contract sprint only: create strict contract parsers, pure
decision-policy derivation, canonical fixtures, and reviewed decision records.

## Scope boundary

The capability diagnoses exactly one user-confirmed numeric series ordered by
one user-confirmed time column. Its completed assessment concludes exactly one
of `suitable_with_caveats`, `not_suitable`, or `inconclusive`; the user-facing
default wording for the latter is “结论不充分”. It may provide only
packet-owned, conditional advice such as considering differencing or reviewing
trend handling. It never changes data or begins a forecast.

No C1 work may add a Model Pack runner or declaration, registry entry, engine
stage, HTTP route, Agent operation, UI feature, Compare projection, package,
or provider call. Forecasting and the possible Prophet, pmdarima, and arch
dependencies belong to later, separately approved runtime work after this
diagnostic contract and its evidence are accepted.

## Acceptance evidence

All C1 decision records D01–D07 are locked; strict contract and policy tests
pass; canonical packets verify their digests; and Integration records the
exact C1 commit. The detailed, approved execution sequence is
`2026-07-19-time-series-diagnostics-c1-contract-lock-plan.md`.

## Boundary
- Affected paths: `docs/superpowers/plans/2026-07-20-v1.8-time-series-diagnostics-c1-objective.md`, `docs/superpowers/specs/2026-07-19-time-series-diagnostics-design.md`, `docs/superpowers/contracts/time-series-diagnostics/v1`, `backend/workbench/contracts/model/time_series_diagnostics.py`, `tests/contracts/test_time_series_diagnostics_contracts.py`, `tests/contracts/test_time_series_diagnostics_policy.py`, `tests/contracts/test_time_series_diagnostics_canonical_packets.py`, `tests/fixtures/models/time_series_diagnostics`
- Allowed paths: `docs/superpowers/plans/2026-07-20-v1.8-time-series-diagnostics-c1-objective.md`, `docs/superpowers/specs/2026-07-19-time-series-diagnostics-design.md`, `docs/superpowers/contracts/time-series-diagnostics/v1`, `backend/workbench/contracts/model/time_series_diagnostics.py`, `tests/contracts/test_time_series_diagnostics_contracts.py`, `tests/contracts/test_time_series_diagnostics_policy.py`, `tests/contracts/test_time_series_diagnostics_canonical_packets.py`, `tests/fixtures/models/time_series_diagnostics`
- Protected paths: `backend/workbench/engine`, `backend/workbench/api`, `backend/workbench/agent`, `frontend`, `requirements.txt`, `pyproject.toml`
- Dependencies: `v1.7.3 public result adapter committed at b5258e9`, `No time-series runtime registration or dependency installation in C1`
- Tests: `contract-only pytest suite from approved C1 plan`
- Known gates: `C1 contracts only: no pack runner, registry, HTTP, Agent, UI, Compare, or dependency change`, `Future runtime must receive separate C2/evaluation decision; C1 must not claim C2 acceptance`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
No matching completed retrospective was selected.
