# D05 — Descriptive Trend and Advisory Boundary

## Status and evidence

**Status:** locked — contract-only C1

**Evidence:** `5b18d7c2e59b89f54afdb85b9e6fed34dfd8783032d2bb5efc948b3fb19c6d16`.
The advisory-only and stale-confirmation fixtures, normalized-facts precondition
tests, and no-forecast/no-operation assertions are committed. This locks the
packet boundary only and authorizes no execution.

## Advisory-only rule

The only advisory codes are `CONSIDER_DIFFERENCING` and
`REVIEW_TREND_HANDLING`. Every advisory has exactly these public facts:

```json
{
  "effect": "advisory_only",
  "execution_available": false
}
```

It has no confirmation token, patch, operation ID, executor, or forecast
payload. An advisory is a packet-owned presentation fact, never an instruction
to transform data or begin a forecast.

Before testing advisory-specific conditions, the policy refuses all advice for
a hard input violation, unavailable required component, undetermined required
null-test outcome, or conflicting ADF/KPSS conclusion. Thus a non-empty
advisory list requires complete, determinate, non-conflicting evidence.

Within that global evidence gate:

| Code | Exact additional conditions |
| --- | --- |
| `CONSIDER_DIFFERENCING` | ADF is `fail_to_reject`, KPSS is `reject`, descriptive trend status is `completed`, and descriptive trend evidence is `absent`. |
| `REVIEW_TREND_HANDLING` | Descriptive trend status is `completed`, descriptive trend evidence is `present` or `undetermined`, and the normalized trend-advisory precondition is `true`. |

An unavailable or unknown precondition never becomes affirmative by default.
Trend is descriptive evidence only; it does not establish a
data-generating process, authorize differencing/detrending, or infer a
forecasting model.

## Lock evidence

- `tests/fixtures/models/time_series_diagnostics/packets/post-run-advisory.json`
- `tests/fixtures/models/time_series_diagnostics/packets/stale-pre-run-confirmation.json`
- `tests/contracts/test_time_series_diagnostics_evaluation_gates.py`
- `tests/contracts/test_time_series_diagnostics_policy.py`
- Evidence manifest: `tests/fixtures/models/time_series_diagnostics/evidence-manifest.json`
