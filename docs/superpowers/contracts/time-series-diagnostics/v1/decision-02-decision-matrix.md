# D02 — Decision Priority and Component Matrix

## Status and evidence

**Status:** locked — contract-only C1

**Evidence:** `5b18d7c2e59b89f54afdb85b9e6fed34dfd8783032d2bb5efc948b3fb19c6d16`.
The pure normalized-facts matrix and immutable Facts packet are covered by the
focused contract suite. This locks decision precedence only; no raw-data
evaluator or runtime capability is authorized.

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

## Lock evidence

- `tests/contracts/test_time_series_diagnostics_policy.py`
- `tests/fixtures/models/time_series_diagnostics/packets/facts-packet.json`
- Evidence manifest: `tests/fixtures/models/time_series_diagnostics/evidence-manifest.json`
