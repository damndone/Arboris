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

Each D-record below is **locked for the contract-only C1 scope** only after its
normative value, rationale, contract/policy version, named immutable fixture(s),
passing test, and evidence SHA are recorded together. A prose decision, example
output, or test without its paired fixture is not a lock. This lock does not
authorize a runtime, registry, route, Agent, UI, forecast, provider, or data
mutation surface; deferred runtime/parser evidence remains explicitly outside
the lock.
The pending IDs below reserve audit locations only; they are not fixtures,
tests, evidence, or hashes.  No record may be treated as locked by implication
from a neighbouring record.

| Record | Subject | Owner | Current status | Decision record path | Contract / policy version | Fixture ID | Test ID | Evidence SHA | Lock evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D01 | Operation/result separation: the outer execution-envelope states (`rejected`, `completed`, `failed`, `cancelled`), completed-only assessment references, rejection/terminal reasons, cancellation, and confirmation idempotence. | Integration C1 | locked — contract-only | `decision-01-operation-envelope.md` | contract `v1`; policy `time_series_diagnostics_c1_v1` | `tests/fixtures/models/time_series_diagnostics/packets/envelope-*.json` | `test_terminal_envelope_fixtures_are_strictly_parseable`; `test_terminal_envelope_negative_fixtures_fail_closed` | `fff74cd7f69669cb2457eabb17d34804fb1731e08bbb98d96cd458ce4af61452` | Terminal-state and negative-reference fixtures pass. Confirmation/idempotence remains a platform lifecycle dependency and is not enabled by this lock. |
| D02 | Decision priority and component matrix: conclusion precedence, numeric minima, near-constant policy, lag reduction, and each unavailable-component effect. | Integration C1 | locked — contract-only | `decision-02-decision-matrix.md` | contract `v1`; policy `time_series_diagnostics_c1_v1` | `tests/contracts/test_time_series_diagnostics_policy.py`; `packets/facts-packet.json` | `test_completed_null_test_truth_table_has_one_conclusion`; `test_unavailable_or_undetermined_required_evidence_is_inconclusive` | `fff74cd7f69669cb2457eabb17d34804fb1731e08bbb98d96cd458ce4af61452` | Pure normalized-facts matrix and immutable Facts evidence pass; no raw-data evaluator is enabled. |
| D03 | Time and single-series semantics: accepted time forms, canonical ordering and digest, no-mutation rule, regularity versus declared semantic frequency, calendar/timezone/DST rules, and seasonal-candidate-period source. | Integration C1 | locked — contract-only | `decision-03-time-semantics.md` | contract `v1`; policy `time_series_diagnostics_c1_v1` | `raw/regular-grid.csv`; `raw/irregular-grid.csv`; proposal contract tests | `test_raw_fixture_transport_is_ordered_small_and_not_mutated`; proposal boundary tests in `test_time_series_diagnostics_contracts.py` | `fff74cd7f69669cb2457eabb17d34804fb1731e08bbb98d96cd458ce4af61452` | Grid/provenance contract and immutable transport evidence pass. Date parser, timezone/DST normalization, and calendar inference remain deferred and unauthorized. |
| D04 | Statistical mechanics: ADF/KPSS alpha and boundary rule, lag policies, bounded p-values, warning policy, ACF/PACF methods and limits, and mandatory non-inference caveats. | Integration C1 | locked — contract-only | `decision-04-statistical-mechanics.md` | contract `v1`; policy `time_series_diagnostics_c1_v1` | `oracle/independent-diagnostic-oracle.json`; `oracle/supported-runtime-manifest.json`; `packets/facts-packet.json` | `test_oracle_is_independent_and_binds_to_a_frozen_runtime_manifest`; policy/contract tests | `fff74cd7f69669cb2457eabb17d34804fb1731e08bbb98d96cd458ce4af61452` | Oracle values, tolerances, manifest binding, and non-inference caveats are frozen as evidence only; no statistical runtime is enabled. |
| D05 | Descriptive-trend and advisory boundary: descriptive-trend eligibility/method/threshold, closed advisory list, three-state preconditions, advisory-only execution policy, and forecast-advisory absence. | Integration C1 | locked — contract-only | `decision-05-trend-advisory.md` | contract `v1`; policy `time_series_diagnostics_c1_v1` | `packets/post-run-advisory.json`; `packets/stale-pre-run-confirmation.json`; policy tests | `test_stale_identity_and_advisory_fixtures_are_non_executable`; advisory truth-table tests | `fff74cd7f69669cb2457eabb17d34804fb1731e08bbb98d96cd458ce4af61452` | Advisory remains packet-owned and non-executable; no forecast advisory or operation token is accepted. |
| D06 | Packet identity: one-way Facts → Assessment derivation, caveats, canonical JSON, content/envelope digests, stale identity, and proposal/advisory namespaces. | Integration C1 | locked — contract-only | `decision-06-packet-identity.md` | contract `v1`; policy `time_series_diagnostics_c1_v1` | `packets/facts-packet.json`; `packets/assessment-packet.json`; canonical packet tests | `test_facts_and_assessment_fixtures_parse_and_recompute_their_digests`; canonical packet test module | `fff74cd7f69669cb2457eabb17d34804fb1731e08bbb98d96cd458ce4af61452` | Canonical projections, stale binding, malformed inputs, and advisory sorting pass. |
| D07 | Evaluation and gates: independent oracle source, fixture catalogue, resource budgets, supported dependency manifest, negative discoverability tests, and prerequisites for later registration. | Integration C1 | locked — contract-only | `decision-07-evaluation-gating.md` | contract `v1`; policy `time_series_diagnostics_c1_v1` | `evidence-manifest.json`; oracle/manifest fixtures; packet/raw fixtures | `test_evidence_manifest_binds_fixture_bytes_and_test_sources`; negative discoverability tests | `fff74cd7f69669cb2457eabb17d34804fb1731e08bbb98d96cd458ce4af61452` | Exact evidence manifest, unsupported-manifest rejection, negative capability surfaces, and legacy-runner distinction pass. |

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
