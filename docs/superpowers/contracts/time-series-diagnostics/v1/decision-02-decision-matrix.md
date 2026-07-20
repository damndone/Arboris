# D02 — Decision Priority and Component Matrix

## Status and evidence

**Status:** open

**Evidence:** unsealed. The current pure-policy tests cover the declared
truth table, but D02 has no named immutable boundary fixtures or evidence SHA.
This record therefore does not lock the C1 decision policy or authorize a
runtime capability.

## Declared v1 policy values

The machine-readable source is `policy-manifest.json`.

| Minimum | Value |
| --- | ---: |
| `hard_input_min` | 20 |
| `adf_min` | 20 |
| `kpss_min` | 20 |
| `acf_min` | 20 |
| `pacf_min` | 20 |
| `trend_min` | 8 |
| `minimum_effective_lag` | 5 |
| `minimum_complete_cycles` | 2 |

These are first-slice evidence minima, not universal claims of time-series
adequacy. The only conclusion values are `suitable_with_caveats`,
`not_suitable`, and `inconclusive`. The only normalized null-test outcomes are
`reject`, `fail_to_reject`, and `undetermined`.

## Priority and complete-evidence truth table

The policy receives already-normalized facts. It does not parse a DataFrame,
call a statistical library, infer missing evidence, or mutate its input.

1. A hard input violation returns `not_suitable`, regardless of every other
   fact.
2. An unavailable required component, or either required null-test outcome of
   `undetermined`, returns `inconclusive`.
3. With complete determinate ADF/KPSS evidence, matching outcomes return
   `inconclusive`; opposing outcomes return `suitable_with_caveats`.

| ADF | KPSS | Conclusion |
| --- | --- | --- |
| `reject` | `reject` | `inconclusive` |
| `reject` | `fail_to_reject` | `suitable_with_caveats` |
| `fail_to_reject` | `reject` | `suitable_with_caveats` |
| `fail_to_reject` | `fail_to_reject` | `inconclusive` |
| either `undetermined` | any | `inconclusive` |

No result in this decision table selects a forecasting model, proves forecast
eligibility, changes data, or triggers an operation.
