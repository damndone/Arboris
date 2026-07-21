# D03 — Time and Seasonal Semantics

## Status and evidence

**Status:** locked — contract-only C1

**Evidence:** `5b18d7c2e59b89f54afdb85b9e6fed34dfd8783032d2bb5efc948b3fb19c6d16`.
The regular/irregular UTF-8 raw fixtures, no-mutation transport test, and
proposal boundary tests are committed. This locks declared grid/provenance
semantics only; date parsing, timezone/DST normalization, and calendar
inference remain deferred and unauthorized.

## Contract-layer decision

The contract records time-grid semantics without parsing dates, inferring a
frequency, sorting rows, filling gaps, or mutating source data. The closed
values are:

| Field | Declared values |
| --- | --- |
| `grid_regularity` | `exact_regular`, `irregular`, `undetermined` |
| `grid_basis` | `contiguous_integer_step`, `exact_fixed_duration_step`, `declared_calendar_frequency`, `none` |
| `semantic_frequency_source` | `user_confirmed`, `artifact_metadata`, `none` |
| candidate-period `unit` | `lag_steps` |

`seasonal_candidate_period` is either `null` or exactly `{value, unit,
source}`. Its `value` is a strict integer, at least `2`, and strictly less than
`usable_observation_count`. Its source is closed to `user_confirmed`,
`artifact_metadata`, and `none`; a declared `lag_steps` value remains valid
when `semantic_frequency_source` is `none`. It describes a lag distance only,
not a calendar month, quarter, day, or other inferred time unit.

Unknown fields, unknown enum values, booleans masquerading as integers, floats,
and malformed candidate-period shapes are rejected. No omitted field receives
a default.

## Deferred runtime boundary

Accepted time representations, timezone normalization, DST ambiguity, calendar
rules, duplicate handling, and missing-point semantics require a later parser
slice. This record is not a time parser or a seasonal detector and adds no
runtime, registry, HTTP, Agent, UI, forecast, provider, or dependency surface.

## Lock evidence

- `tests/fixtures/models/time_series_diagnostics/raw/regular-grid.csv`
- `tests/fixtures/models/time_series_diagnostics/raw/irregular-grid.csv`
- `tests/contracts/test_time_series_diagnostics_evaluation_gates.py`
- `tests/contracts/test_time_series_diagnostics_contracts.py`
- Evidence manifest: `tests/fixtures/models/time_series_diagnostics/evidence-manifest.json`
