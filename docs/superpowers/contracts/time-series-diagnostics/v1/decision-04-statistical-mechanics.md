# D04 — Statistical Mechanics

## Status and evidence

**Status:** open

**Evidence:** unsealed. Independent numerical-oracle fixtures, warning
fixtures, and boundary evidence have not been supplied. Fixture/evidence SHA
is **pending**; these contract additions do not lock D04 or authorize any
statistical execution.

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

## Deferred evidence and boundary

Exact lag caps, comparison operators at the alpha boundary, primary
p-value-versus-critical-value precedence, warning escalation, numerical
tolerances, and independent oracle provenance remain pending D04 fixture and
evidence work. This record remains open/unsealed and cannot be presented as a
locked statistical policy. It adds no statistical engine, Pack, registry,
HTTP, Agent, UI, forecast, provider, or dependency surface.
