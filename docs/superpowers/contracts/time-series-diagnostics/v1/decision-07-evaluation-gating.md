# D07 — Evaluation and Gating

## Status and evidence

**Status:** locked — contract-only C1

**Evidence:** `5b18d7c2e59b89f54afdb85b9e6fed34dfd8783032d2bb5efc948b3fb19c6d16`.
The independent oracle, supported/unsupported runtime manifests, immutable
fixture catalogue, evidence manifest, negative discoverability tests, and
advisory/stale fixtures are committed. This record authorizes neither
registration nor execution.

## Normative direction

C1 evaluation has three separate evidence layers: independent numerical
oracle, direct policy/contract tests, and immutable raw-fixture transport
checks. An unsupported numeric runtime manifest is rejected before execution;
it is never silently recorded after an uncontrolled calculation.

The capability must remain absent from model registry, Pack registry, routes,
Agent tools, catalogue, Compare, and frontend discoverability. The negative
tests prove absence; they are not feature UI acceptance. No forecast proposal,
provider call, automatic data mutation, or advisory execution is allowed.

## Required lock evidence

- supported runtime manifest and its digest;
- independent ADF/KPSS/ACF/PACF oracle with tolerances;
- raw and packet fixture catalogue with passing parsers;
- registry/route/capability/catalogue negative tests;
- stale confirmation and advisory-execution negative fixtures;
- exact clean Integration candidate SHA and protected regression results.

## Recorded evidence

- `tests/fixtures/models/time_series_diagnostics/evidence-manifest.json`
- `tests/fixtures/models/time_series_diagnostics/oracle/independent-diagnostic-oracle.json`
- `tests/fixtures/models/time_series_diagnostics/oracle/supported-runtime-manifest.json`
- `tests/fixtures/models/time_series_diagnostics/oracle/unsupported-dependency-manifest.json`
- `tests/fixtures/models/time_series_diagnostics/oracle/resource-limits.json`
- `tests/contracts/test_time_series_diagnostics_evaluation_gates.py`

The existing `run_time_series_diagnostics` helper is a legacy generic
econometrics utility, not a registered C1 Pack, model, route, Agent capability,
Compare projection, or frontend feature. The negative test names this
distinction explicitly and does not make a broad claim that the repository has
no historical time-series code.
