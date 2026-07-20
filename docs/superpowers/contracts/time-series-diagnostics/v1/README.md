# Time Series Diagnostics v1 — C1 Contract Register

## Status and scope

This is a **contract-only** C1 register for the first Time Series Diagnostics
slice.  It is intentionally not an implementation authorization.  The slice
accepts one explicitly user-confirmed series, yields exactly one completed
assessment conclusion (`suitable_with_caveats`, `not_suitable`, or
`inconclusive`), defaults to `inconclusive` whenever complete interpretable
evidence is unavailable, and can emit only non-executable advisory objects.
It does not forecast, select a forecasting model, mutate data, automatically
difference, or automatically detrend.

This directory freezes portable evidence contracts only. It must not add a time-series pack declaration, model handler, pipeline stage, registry entry, HTTP route, Agent operation, UI feature registration, Compare projection, or dependency change. Those surfaces remain unavailable until the LMM adapter and frozen-containment prerequisites are independently accepted.

## Lock protocol

Each D-record below is **open** until its normative value, rationale, contract
version, policy version, named immutable fixture(s), and a passing test are
recorded in the same decision record.  A prose decision, example output, or
test without its paired fixture is not a lock.  A fixture without a passing
test is not a lock.  **A record becomes `locked` only after its fixture and
test both pass and that decision record records the resulting evidence SHA.**
The pending IDs below reserve audit locations only; they are not fixtures,
tests, evidence, or hashes.  No record may be treated as locked by implication
from a neighbouring record.

| Record | Subject | Owner | Current status | Decision record path | Contract / policy version | Fixture ID | Test ID | Evidence SHA | Lock evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D01 | Operation/result separation: the outer execution-envelope states (`rejected`, `completed`, `failed`, `cancelled`), completed-only assessment references, rejection/terminal reasons, cancellation, and confirmation idempotence. | Integration C1 | open | `records/D01-operation-result-separation.md` | contract `v1`; policy pending | `TS-C1-D01-fixtures` (pending) | `TS-C1-D01-tests` (pending) | pending until fixture/test evidence exists | Immutable fixtures for each terminal state, stale identity, cancelled confirmation, retry, and duplicate confirmation token; passing schema, lifecycle, and negative-reference tests. |
| D02 | Decision priority and component matrix: conclusion precedence, numeric minima, near-constant policy, lag reduction, and each unavailable-component effect. | Integration C1 | open | `records/D02-decision-component-matrix.md` | contract `v1`; policy pending | `TS-C1-D02-fixtures` (pending) | `TS-C1-D02-tests` (pending) | pending until fixture/test evidence exists | Constructed-facts fixtures covering every conclusion branch, every component unavailable branch, below-minimum cases, and every ADF/KPSS outcome combination; passing decision-policy matrix tests. |
| D03 | Time and single-series semantics: accepted time forms, canonical ordering and digest, no-mutation rule, regularity versus declared semantic frequency, calendar/timezone/DST rules, and seasonal-candidate-period source. | Integration C1 | open | `records/D03-time-single-series-semantics.md` | contract `v1`; policy pending | `TS-C1-D03-fixtures` (pending) | `TS-C1-D03-tests` (pending) | pending until fixture/test evidence exists | Immutable raw fixtures for sortable order, duplicates, missing/unparseable times, regular gaps, irregular spacing, calendar frequency, mixed timezones, ambiguous dates, and each candidate-period source; passing validation, digest, and immutability tests. |
| D04 | Statistical mechanics: ADF/KPSS alpha and boundary rule, lag policies, bounded p-values, warning policy, ACF/PACF methods and limits, and mandatory non-inference caveats. | Integration C1 | open | `records/D04-statistical-mechanics.md` | contract `v1`; policy pending | `TS-C1-D04-fixtures` (pending) | `TS-C1-D04-tests` (pending) | pending until fixture/test evidence exists | Independent numerical-oracle fixtures with frozen tolerances for ADF/KPSS/ACF/PACF plus boundary/warning fixtures; passing oracle and policy tests. |
| D05 | Descriptive-trend and advisory boundary: descriptive-trend eligibility/method/threshold, closed advisory list, three-state preconditions, advisory-only execution policy, and forecast-advisory absence. | Integration C1 | open | `records/D05-trend-advisory-boundary.md` | contract `v1`; policy pending | `TS-C1-D05-fixtures` (pending) | `TS-C1-D05-tests` (pending) | pending until fixture/test evidence exists | Constructed facts fixtures for absent/present/undetermined/unavailable trend and every advisory precondition combination; passing advisory cardinality, non-execution, and no-forecast tests. |
| D06 | Packet identity: one-way Facts → Assessment derivation, caveats, canonical JSON, content/envelope digests, stale identity, and proposal/advisory namespaces. | Integration C1 | open | `records/D06-packet-identity.md` | contract `v1`; policy pending | `TS-C1-D06-fixtures` (pending) | `TS-C1-D06-tests` (pending) | pending until fixture/test evidence exists | Canonical packet fixtures covering ordering, null/number/time normalization, digest exclusions, malformed/unknown values, and stale references; passing digest, schema, and fail-closed adapter tests. |
| D07 | Evaluation and gates: independent oracle source, fixture catalogue, resource budgets, supported dependency manifest, negative discoverability tests, and prerequisites for later registration. | Integration C1 | open | `records/D07-evaluation-gating.md` | contract `v1`; policy pending | `TS-C1-D07-fixtures` (pending) | `TS-C1-D07-tests` (pending) | pending until fixture/test evidence exists | Exact-clean-candidate fixtures and evidence for resource limits, registry/route/catalog/capability non-discoverability, malformed transport, and a browser **negative** acceptance check that Time Series is not discoverable in the existing UI. This is not Time Series feature UI acceptance; C1 has no UI feature. Passing independent-evidence and negative-capability tests are required. |

## Non-negotiable interpretation rules

- `operation_status=completed` is an execution fact, not a statistical
  conclusion.  Only a completed envelope may carry both facts and assessment
  references; all other terminal states carry neither.
- `inconclusive` is the safe default whenever required evidence is unavailable,
  boundary-limited, conflicting, or not interpretable under the locked policy.
  It does not imply that the series cannot be forecast with some future model.
- A declared seasonal candidate period is input provenance, not detected
  seasonality.  The Agent must not infer it from timestamps, ACF, or domain
  text.
- Trend is descriptive evidence only.  It neither proves a data-generating
  process nor authorizes a transformation.
- Advisory objects are packet-owned presentation facts.  They cannot perform
  an operation, issue a confirmation token, or create a forecast.

## Relationship to the design charter

The normative C1 charter is
[`2026-07-19-time-series-diagnostics-design.md`](../../../specs/2026-07-19-time-series-diagnostics-design.md).
This register makes its seven blocking decisions auditable; it does not replace
the charter or relax any of its non-goals.
