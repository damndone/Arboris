# D05 — Descriptive Trend and Advisory Boundary

## Status and evidence

**Status:** open

**Evidence:** unsealed. The current pure-policy tests prove only the declared
object boundary; named immutable advisory fixtures, the full precondition
truth table, and an evidence SHA remain required before D05 can be locked.

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
