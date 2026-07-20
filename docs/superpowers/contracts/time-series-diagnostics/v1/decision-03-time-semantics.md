# D03 — Time and Seasonal Semantics

## Status and evidence

**Status:** open

**Evidence:** unsealed. This contract-layer slice has no immutable raw-fixture
or canonical-order evidence yet. Fixture/evidence SHA is **pending**; the
current parser tests are boundary tests only and do not lock D03 or authorize
a runtime capability.

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

## Deferred evidence and boundary

Accepted time representations, timezone normalization, DST ambiguity, calendar
rules, canonical-order digests, duplicate handling, missing-point semantics,
and source immutability still require the named D03 fixtures and evidence SHA.
They remain open questions for the later Pack/evaluator work. This record is
not a time parser or a seasonal detector and adds no runtime, registry, HTTP,
Agent, UI, forecast, provider, or dependency surface.
