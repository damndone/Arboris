# D04 — Statistical Mechanics

## Status and evidence

**Status:** locked — contract-only C1

**Evidence:** `5b18d7c2e59b89f54afdb85b9e6fed34dfd8783032d2bb5efc948b3fb19c6d16`.
The independent reference oracle, frozen runtime-manifest digest, policy
manifest, and focused policy tests are committed. These are evidence and
contract locks only; no statistical execution is authorized.

## Contract-layer decision

The v1 policy manifest is the machine-readable source for these declared
values:

- `alpha` is `0.05`; ADF uses regression `c` and permits only
  `approximate` or `unavailable` p-value status.
- KPSS uses the `level_stationarity` null and permits only `approximate`,
  `lower_bound`, `upper_bound`, or `unavailable` p-value status. A lower table
  endpoint means the actual p-value is above that endpoint; an upper endpoint
  means it is below that endpoint. Neither bound is rendered as an exact
  p-value.
- ACF uses the `standard` method; PACF uses `ywm`; both include lag zero and
  use a `0.95` confidence level.

The contract parser validates only normalized declarations and p-value
provenance. It performs no ADF/KPSS/ACF/PACF calculation, lag selection,
warning escalation, or model inference.

## Mandatory caveats

When the corresponding raw-level diagnostic facts are emitted, the applicable
closed caveat codes are `RAW_LEVEL_CORRELATION_ONLY`,
`NO_MODEL_ORDER_INFERENCE`, `LEVEL_STATIONARITY_ONLY`,
`NO_FORECAST_ELIGIBILITY`, `NO_MODEL_SELECTION`, and
`STRUCTURAL_BREAKS_NOT_ASSESSED`. These are explanatory contract facts, not
runtime decisions.

## Deferred runtime boundary

Exact lag caps, comparison operators at the alpha boundary, primary
p-value-versus-critical-value precedence, and warning escalation remain
runtime adapter responsibilities. The recorded tolerances and oracle
provenance are frozen evidence, not a statistical engine. This record adds no
Pack, registry, HTTP, Agent, UI, forecast, provider, or dependency surface.

## Lock evidence

- `tests/fixtures/models/time_series_diagnostics/oracle/independent-diagnostic-oracle.json`
- `tests/fixtures/models/time_series_diagnostics/oracle/supported-runtime-manifest.json`
- `docs/superpowers/contracts/time-series-diagnostics/v1/policy-manifest.json`
- `tests/contracts/test_time_series_diagnostics_evaluation_gates.py`
- Evidence manifest: `tests/fixtures/models/time_series_diagnostics/evidence-manifest.json`
