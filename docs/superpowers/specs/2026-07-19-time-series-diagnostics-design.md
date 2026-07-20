# Time Series Diagnostics First Design

## Status

**High-level design frozen as the C1 charter; C1 contract lock remains
blocked; implementation is not authorized.** This document defines the next
model-family work after the LMM public result adapter and frozen-containment
evaluator are available. The P0 contract decisions below must be frozen before
feature implementation. This document does not authorize dependency
installation, registration, merge, or release.

## Goal

Add a user-confirmed, single-series diagnostic capability that determines
whether the selected series meets the structural and numerical prerequisites
for this first diagnostic slice. It reports evidence about time structure,
level-stationarity, correlation structure, descriptive trend assessment, and
seasonality-assessment eligibility. It does not determine whether a series is
generally suitable for forecasting, a particular time-series model, production
use, or causal inference.

## Timing and dependency order

Time-series implementation starts only after the current LMM integration work
has produced:

1. a reviewed public adapter from versioned model packets to runtime/API/Agent
   consumers, including one canonical figure-data shape; and
2. a reproducible frozen-containment executor that can evaluate an exact
   integration candidate.

Time-series design and contract work may proceed before those gates, but no
time-series Model Pack is registered or connected to runtime before them. This
prevents a second model family from duplicating the current public-transport
and evidence-security gaps.

## P0 contract freeze before implementation

The C1-style contract sprint must produce one reviewed decision table and one
packet-field catalogue before any time-series feature work starts. The decision
table is mutually exclusive and exhaustive over requests whose
`operation_status` is `completed`. Every completed Pack terminal state maps to
exactly one conclusion and zero or more closed-set advisory codes. Rejected,
failed, and cancelled operations are outside the statistical decision table and
never produce an assessment.

| Observed state | Frozen conclusion meaning |
| --- | --- |
| Valid request and bound source data, but nonnumeric/boolean outcome; time missing or unparseable; nonfinite outcome; duplicate time; no unique canonical order; zero variance; below the absolute minimum observation count | `not_suitable`: the selected data does not meet this Pack's hard input requirements. It says nothing about all possible time-series methods. |
| Valid input structure, but grid regularity is irregular/undetermined; a declared semantic frequency conflicts with observed values; an expected point is absent under a declared calendar frequency; required component evidence is unavailable; or a normalized statistical diagnostic is unavailable | `inconclusive`: the Pack cannot form complete, interpretable evidence. |
| ADF/KPSS signals conflict, or both fail to reject their respective null hypotheses | `inconclusive`: neither stationary nor non-stationary is asserted. |
| Any required ADF or KPSS null-test outcome is `undetermined` | `inconclusive`: an incomplete, boundary-limited, or policy-conflicted null-test result cannot support a directional level-stationarity statement. |
| Valid regular series with complete diagnostics and a non-conflicting, interpretable evidence group | `suitable_with_caveats`: the series can produce first-slice diagnostic evidence; it is not forecast or model-fit eligibility. |

C1 must freeze the numeric minimum observation count, supported frequency
classes, resource limits, statistic policies, and each code used in this table.
`reject`, `fail_to_reject`, and `undetermined` are the only null-test outcomes;
the contracts must never use `accept_null`.

### Operation status is not a statistical conclusion

Every request has an independent `operation_status` before an assessment can
exist:

| Operation state | Meaning | Assessment packet |
| --- | --- | --- |
| `rejected` | Schema invalid; proposal/dataset/row-scope/column identity is stale or mismatched; selected stable column is absent; authorization fails; or the request is otherwise invalid. | Never produced. |
| `completed` | The request reached a deterministic Pack terminal result: validation and normalization completed; every eligible component either completed or has a closed `not_run`/`unavailable` reason. | Produced with exactly one three-state conclusion. Hard data-input failure is therefore `completed + not_suitable`; ADF/KPSS/ACF/PACF may be `not_run`. |
| `failed` | Unexpected exception, timeout, OOM, terminated executor, or corrupt Pack output. | Never produced. |
| `cancelled` | A user or authorized runtime cancellation reached a terminal lifecycle state. | Never produced; it is not a statistical failure. |

Preflight resource limits are validated deterministic input facts: a request
that exceeds a public limit completes with the frozen `inconclusive` reason.
Unexpected resource exhaustion is an operation failure. Malformed packets are
adapter/consumer fail-closed errors, not `inconclusive` conclusions.

`operation_status` belongs to an outer `OperationExecutionEnvelope`, not to a
Pack-produced packet. That envelope owns execution reason codes and, only when
completed, references the facts and assessment packets. Each statistical
component independently records `completed`, `not_eligible`, `not_run`, or
`unavailable` plus a closed reason code. A cancelled confirmation, retry, and
duplicate confirmation token must follow the platform's existing idempotent
operation lifecycle and have dedicated fixtures.

### Component completeness and decision precedence

C1 freezes the following precedence before any implementation: `hard_input_min`
is evaluated first; only a series at or above it can enter component checks.
Each component then has a separately frozen minimum and an explicit impact.

| Component | Required for a completed conclusion | Unavailable behaviour |
| --- | --- | --- |
| Time/value structure | Yes | hard-input violation → `not_suitable`; otherwise incomplete structure evidence → `inconclusive`. |
| ADF and KPSS level evidence | Yes | `inconclusive`. |
| ACF | Yes, once `minimum_effective_lag` can be met | below that minimum → `inconclusive`; otherwise a reduced lag cap is a recorded caveat. |
| PACF | Yes, once `minimum_effective_lag` can be met | below that minimum → `inconclusive`; otherwise a reduced lag cap is a recorded caveat. |
| Descriptive trend | No | suppresses trend-specific advisory only. |
| Seasonality-assessment eligibility | No | `false` or `undetermined` is a complete fact, not an operation failure. |

C1 freezes `hard_input_min`, `adf_min`, `kpss_min`, `acf_min`, `pacf_min`,
`trend_min`, `minimum_effective_lag`, and `minimum_complete_cycles`. A reduced
ACF/PACF lag is permitted only when the effective lag remains at or above
`minimum_effective_lag`; otherwise the relevant component is unavailable.

### Time, source-data, and single-series policy

- A non-monotonic input is not an error when every selected time value is
  parseable and unique. The Pack creates a non-destructive canonical analysis
  order and records `original_order_monotonic`, `canonical_order_applied`,
  `rows_reordered_count`, and `canonical_order_digest`.
- C1 must separately encode `TIME_VALUE_MISSING`, `TIME_PARSE_FAILED`,
  `EXPECTED_TIME_POINT_ABSENT`, and `IRREGULAR_SPACING`. Expected-point absence
  is permitted only after a declared frequency has been established; unknown
  frequency cannot be described as missing time points.
- The first slice accepts only explicitly typed or explicitly formatted time
  values. Ambiguous date strings are rejected; heuristic locale-dependent date
  parsing is forbidden. C1 must specify supported integer-index, date, and
  timestamp forms, timezone normalization, mixed aware/naive behaviour, DST
  ambiguity, and calendar-frequency rules.
- Grid regularity and semantic frequency are separate facts. The Pack computes
  `grid_regularity` as `exact_regular`, `irregular`, or `undetermined`, with
  `grid_basis` of `contiguous_integer_step`, `exact_fixed_duration_step`,
  `declared_calendar_frequency`, or `none`. Exact equality against an already
  selected order is deterministic validation, not heuristic frequency guessing.
  A regular grid is enough for ADF/KPSS/ACF/PACF; it does not assert whether a
  step means an hour, day, month, or experiment cycle.
- `semantic_frequency_source` is exactly `user_confirmed`,
  `artifact_metadata`, or `none`. User confirmation includes an optional
  frequency declaration and its unit/calendar rule; no declaration is required
  for a regular-grid diagnostic. Semantic frequency is never inferred from a
  majority interval, minimum interval, GCD, or guessed missing-point pattern.
  A declared monthly/quarterly frequency is checked against calendar rules, not
  equal nanosecond deltas. A declaration conflict produces
  `FREQUENCY_DECLARATION_MISMATCH` and an `inconclusive` assessment.
- With `semantic_frequency_source = none`, the Pack never emits
  `EXPECTED_TIME_POINT_ABSENT`. It can still complete an assessment when the
  grid is exact regular and every other required component completes; seasonal
  eligibility remains `undetermined` unless a separately declared candidate
  period exists.
- A seasonal candidate period has the separate source `user_confirmed`,
  `artifact_metadata`, or `none`. The Agent never selects one from raw ACF,
  timestamps, or domain text. With no declared candidate period, seasonality
  eligibility is `undetermined` with `NO_DECLARED_CANDIDATE_PERIOD`.
- The Pack never inserts rows, drops rows, fills values, averages duplicates,
  resamples, aggregates, or mutates source data. Internal canonical sorting is
  a view only. Any data preparation belongs to a separate, confirmed operation.
- The user confirmation binds the dataset revision/artifact hash, row-scope
  hash, selected stable column identifiers, outcome column, time column, and a
  `single_series_assertion`. The UI states that no entity column is implicitly
  grouped. A panel must first be reduced by a separate confirmed row-scope
  operation.
- Any missing or nonfinite outcome, numeric-string coercion ambiguity, boolean
  outcome, constant series, or below-threshold near-constant series follows the
  frozen table without silent complete-case deletion. Packets record all input,
  parseable-time, unique-time, finite-outcome, duplicate-time, missing-time,
  missing-outcome, and usable-observation counts.

## User flow

1. The Agent may observe that a selected dataset has a plausible time column
   and offer a pre-filled **Time Series Diagnostics** proposal.
2. The user explicitly confirms the proposal, including the dataset/row-scope
   identity, single-series assertion, outcome column, time column, and optional
   semantic-frequency and seasonal-candidate-period declarations. A confirmed
   candidate period is an integer number of `lag_steps`, is at least two and
   less than the usable-observation count, and may be declared without a
   semantic frequency; it never asserts a calendar unit. No classifier or
   Agent suggestion auto-runs analysis.
3. The diagnostic pack validates the series, produces a versioned facts packet
   and its one-way-derived assessment packet, and the UI renders only their
   server-produced facts.
4. The packet conclusion is one of `suitable_with_caveats`,
   `not_suitable`, or `inconclusive`.
5. The Agent may surface only advisory objects already present in a successfully
   parsed assessment packet. It never evaluates advisory preconditions itself.
   An advisory never changes data or starts a forecast.

## First-slice scope

The first slice supports exactly one selected numeric outcome ordered by one
selected time column. It provides:

- canonical, non-destructive ordering of the selected time column;
- duplicate-time, parsing, ordering, frequency, spacing, and sample-size facts;
- level-stationarity evidence: ADF with a constant and KPSS with a
  level-stationarity null, using fully frozen lag and p-value policies;
- ACF and PACF facts for a bounded diagnostic lag range;
- descriptive trend evidence and seasonality-assessment eligibility facts; and
- bounded, explainable advisory facts.

The first slice excludes forecasting, automatic differencing, automatic
detrending, automatic seasonality selection, multivariate VAR/VECM, Granger
causality, cointegration, panel time-series models, GARCH, Compare projection,
and provider-backed interpretation. The Integration adapter must not advertise
Compare capability for this slice.

## Statistical truthfulness and proposal rules

- ADF and KPSS are separate facts. Each packet records null hypothesis,
  regression/deterministic-term specification, max-lag and lag-selection
  policy, effective/used lag, `nobs`, statistic, critical values, information
  criterion when applicable, warning/failure codes, and p-value status. A
  p-value is encoded as `exact`, `approximate`, `lower_bound`, `upper_bound`,
  or `unavailable`; the UI cannot display a bounded value as exact. C1 permits
  ADF only `approximate` or `unavailable`, and KPSS only `approximate`,
  `lower_bound`, `upper_bound`, or `unavailable`; neither test emits `exact`.
  A bounded KPSS value records its inequality direction rather than presenting
  a table boundary as an exact p-value.
- ACF and PACF each record requested lag cap, effective lag cap, reduction
  reason, method, confidence level, lag-zero policy, and output bounds. Their
  limits are public decision-policy fields, not hidden `min(...)` constants.
  Every emitted raw-level ACF/PACF result carries
  `RAW_LEVEL_CORRELATION_ONLY` and `NO_MODEL_ORDER_INFERENCE`; the first slice
  never infers AR, MA, or ARIMA order from them.
- Trend evidence is descriptive, not proof of a data-generating mechanism. C1
  must freeze its eligibility rule, method, effect-size representation,
  threshold, `trend_component_status`, and `present`/`absent`/`undetermined`
  result. `undetermined` is permitted only when the trend component completed
  but its predeclared evidence lies in an ambiguity interval. A component that
  is not eligible or unavailable has `trend_evidence: null`, emits
  `TREND_NOT_ASSESSED`, and suppresses every trend advisory. The first slice may
  report seasonality-assessment eligibility, a declared candidate period source,
  candidate period, and complete cycles observed; it must not assert that
  seasonality exists or create a seasonality-model advisory.
- The pre-run `RUN_TIME_SERIES_DIAGNOSTICS` proposal and post-run assessment
  advisories have different schemas and lifecycles. The pre-run proposal is a
  confirmation-bound request for this Pack. Post-run objects are a closed,
  versioned advisory set owned only by the assessment packet.
- Every advisory precondition is `true`, `false`, or `unknown`; an advisory is
  present exactly once only when all of its preconditions are `true`. It
  includes `advisory_code`, `advisory_version`, `evidence_fact_refs`,
  precondition results, `source_facts_content_digest`, decision-policy version,
  effects summary, incompatibility codes, and the bound
  dataset/row-scope/column identity. The Agent and UI only surface it.
  An embedded advisory has no parent packet ID: its parent is established by
  assessment-packet containment. A standalone transport locator may add a
  parent reference outside the advisory's normative content projection.
- The first slice defines all post-run objects as `advisory_only` with
  `execution_available: false`; it emits no confirmation token and connects to
  no transformation operation. ADF/KPSS conflict produces no transformation
  advisory. When every frozen `CONSIDER_DIFFERENCING` precondition is true,
  consistent non-stationary level evidence with absent descriptive trend makes
  that advisory present exactly once. When the trend component completed and
  every frozen `REVIEW_TREND_HANDLING` precondition is true, present or
  undetermined descriptive trend makes only that advisory present exactly once,
  never a detrending recommendation.
  Forecasting-preparation advisories are always absent in this slice.

## Architecture

### Model Pack and packets

The implementation creates a dedicated `time_series_diagnostics` Model Pack,
not a branch inside generic diagnostics. It owns input validation, deterministic
statistics, result normalization, diagnostics, and canonical fixtures.

Its public facts use versioned `PacketEnvelope` values. C1 freezes two packets
with a one-way derivation: `TimeSeriesDiagnosticFactsPacket` contains validated
input and statistical facts; the Pack's versioned decision policy derives
`TimeSeriesDiagnosticAssessmentPacket` from it. The assessment packet carries
the facts packet ID/hash, decision-policy version, a closed `caveat_codes` set,
and `caveat_fact_refs`. Only the assessment packet owns the conclusion and
advisory set. Its mandatory `assessment_scope` is
`first_slice_diagnostic_evidence`; UI copy must not display a generic
"eligible" or "suitable" label. Integration validates references and hashes
but never recomputes statistics or decisions.

Every packet records schema/version, packet ID, producer/policy version, run
ID, dataset artifact identity, row-scope hash, stable selected columns,
dependency versions, locale/timezone policy, execution timestamp, configuration
snapshot, and JSON-safe values (`null` plus a reason code for unavailable
numeric facts). C1 freezes canonical JSON, key order, timestamp representation,
float normalization, hash algorithm, and schema inclusion.

`facts_content_digest` is
`H(canonical_json(facts_content_projection))`; its projection includes the
facts contract/version/producer and policy versions, normalized input identity,
configuration snapshot, numeric-runtime-manifest digest, and facts, but
excludes packet ID, run ID, execution timestamp, and every digest field.
`assessment_content_digest` is
`H(canonical_json(assessment_content_projection))`; its projection includes
the facts content digest, decision-policy version, assessment scope,
conclusion, caveat set, caveat fact references, and the complete advisory set,
but excludes packet ID, run ID, execution timestamp, and every digest field.
`envelope_digest` is
`H(canonical_json(envelope_without_envelope_digest))`; it excludes only its own
`envelope_digest` field and can therefore never hash itself. Closed-set arrays
are sorted before projection (`caveat_codes` by code, advisories by
`advisory_code` then `advisory_version`, and evidence references by canonical
fact path); ordered statistical vectors retain their declared order. Canonical
JSON uses literal `null`, finite-number and signed-zero normalization, Unicode
NFC, deterministic key order, and UTC RFC 3339 timestamps. There is no public
forecast packet in this slice.

The shared Integration adapter remains the sole bridge into runtime, HTTP,
Agent, Compare, and UI. The pack cannot write an unversioned legacy result into
`model_results`, add itself to the builtin registry, or create a second public
figure protocol.

### Agent and UI

The Agent consumes only parsed, versioned time-series packets. It can create
only the pre-filled diagnostic-run proposal; it can only surface post-run
advisories already owned by the parsed assessment packet. It may not infer
stationarity from raw data, evaluate advisory conditions, emit a transformation
patch, or execute a proposal.

The UI displays the selected series/time inputs, validation facts, test facts,
the three-way conclusion, caveats, the pre-run proposal, and post-run
advisories. It never recomputes ADF,
KPSS, ACF, PACF, trend, seasonality, or a conclusion. Unknown diagnostic codes
and malformed packets fail closed to a safe unsupported state.

### Evaluation

Independent evaluation runs only against an exact, clean integration candidate
using the frozen-containment executor. It has three non-substitutable layers:

1. a versioned numeric oracle from an independent calculation or manually
   verified source for frozen ADF/KPSS/ACF/PACF vectors and tolerances;
2. direct decision-policy tests over constructed facts packets, including every
   ADF/KPSS outcome combination, p-value boundary, trend state, proposal state,
   and stale identity; and
3. end-to-end immutable raw fixtures through validation, statistics, packets,
   adapter, Agent, and UI.

Fixtures cover valid regular data, short/constant/near-constant data, sortable
input, duplicates, missing/unparseable time, missing/nonfinite outcome,
regular-frequency gaps, irregular spacing, calendar frequency, mixed timezone,
ambiguous date, malformed/unknown packets, stale proposals, and no-proposal
execution attempts. Tests also prove source-data immutability, no silent row
removal/aggregation, confirmation idempotence, bounded resources, no UI/Agent
recalculation, no forecast proposal, and registry/route/catalog/capability
non-discoverability until every LMM prerequisite gate is satisfied. Observed
series, ACF, and PACF figures must conform to the existing canonical figure-data
shape; their points and intervals come from packets, never UI calculation.
Compare remains unavailable and has an explicit negative capability test.
Browser acceptance remains a separate gate.

## Dependencies

The first slice uses the already-public `statsmodels`, `pandas`, `numpy`, and
`scipy` dependencies. Local verification confirms `statsmodels 0.14.6` exposes
ADF/KPSS, ACF/PACF support, STL, SARIMAX, exponential smoothing, VAR, VECM,
cointegration, and Granger tooling. No dependency is added for the diagnostic
slice.

Later, separately approved work packages may add optional dependencies only
when their model family requires them:

| Future capability | Preferred dependency decision | Preconditions |
| --- | --- | --- |
| Explicit ARIMA/SARIMA, Holt-Winters, STL, VAR, VECM, cointegration, Granger | Keep using `statsmodels` | Forecast/causal semantics, fixture oracle, performance budget, and result contracts are frozen. |
| Auto-ARIMA convenience | Evaluate `pmdarima` as an optional dependency | Model-selection policy, search bounds, reproducibility, explainability, and fallback behaviour are specified. |
| ARCH/GARCH volatility | Evaluate `arch` as an optional dependency | Financial-volatility scope, distribution choices, diagnostics, and independent numerical oracle are specified. |
| Business-oriented forecasting convenience | Evaluate Prophet only as an optional dependency | Seasonality/holiday semantics, operational dependency cost, forecast provenance, and comparison policy are specified. |

No optional package is installed merely because it might be useful. New public
dependencies require a bounded work order, license/security review, explicit
fallback/error policy, lockfile verification, and isolated evaluation.
C1 also freezes a supported dependency manifest and lockfile digest. An
unsupported statistical-library version is rejected before execution rather
than being recorded after an uncontrolled calculation.

## C1 blocking decisions

The contract sprint may begin now, but its lock is blocked until the following
seven decision records have exact, fixture-backed answers:

1. **Operation/result separation:** exact
   `rejected`/`completed`/`failed`/`cancelled` executor-envelope schema,
   HTTP/manifest behaviour, cancellation/idempotence semantics, and the rule
   that only `completed` produces an assessment.
2. **Decision priority and component matrix:** the complete conclusion table,
   minimum observations per component, lag-reduction rule, near-constant rule,
   and the effect of every unavailable component.
3. **Time semantics:** accepted time representations, canonical-order digest,
   grid-regularity versus semantic-frequency policy, calendar rules,
   timezone/DST policy, seasonal period source, and no-mutation policy.
4. **Statistical mechanics:** ADF/KPSS alpha, comparison operator at the alpha
   boundary, primary p-value versus critical-value policy, bounded-p-value
   interpretation, warning escalation, exact lag policies, ACF/PACF methods,
   and mandatory caveats. `RAW_LEVEL_CORRELATION_ONLY` and
   `NO_MODEL_ORDER_INFERENCE` apply whenever raw-level ACF/PACF is emitted;
   `LEVEL_STATIONARITY_ONLY`, `NO_FORECAST_ELIGIBILITY`,
   `NO_MODEL_SELECTION`, and `STRUCTURAL_BREAKS_NOT_ASSESSED` apply whenever
   their first-slice scope is relevant.
5. **Trend and advisory boundary:** descriptive trend method/threshold and the
   closed advisory list. The first lock keeps transformation output
   `advisory_only`, uses `REVIEW_TREND_HANDLING` rather than detrending, and
   never emits a forecast advisory.
6. **Packet identity:** strict Facts → Assessment derivation, required caveats,
   canonical serialization, distinct facts/assessment/envelope digest rules
   without advisory self-reference, stale-identity validation, and
   proposal/advisory namespaces.
7. **Evaluation and gating:** independent numerical oracle source, fixture
   catalogue, resource budgets, registry/route/catalog/capability negative
   tests, supported dependency manifest, and exact prerequisites for any later
   registration.

The C1 decision records must include the chosen value, rationale, contract
version, policy version, fixtures that prove it, and an owner. No executable
Pack implementation, registry wiring, runtime route, or dependency change is
allowed before all seven records are locked.

## Acceptance criteria for the future implementation

- A user-selected valid univariate series produces parseable, one-way-derived
  versioned packets with fully recorded statistics configuration and a bounded
  conclusion.
- A raw Agent suggestion cannot start analysis; only the separately versioned
  pre-run proposal can request diagnostics after user confirmation.
- Every `operation_status=completed` terminal state maps through the C1
  decision table to exactly one conclusion. `rejected`, `failed`, and
  `cancelled` operations produce neither conclusion nor assessment packet.
  No source rows or values change during analysis.
- A `completed` envelope has both `facts_packet_ref` and
  `assessment_packet_ref`; a `rejected`, `failed`, or `cancelled` envelope has
  neither reference.
- An advisory is absent unless every documented three-state precondition is
  true; all first-slice advisories are non-executable and forecast advisories
  are always absent.
- The UI renders packet facts without recalculation and fails closed for
  malformed/unknown inputs.
- Missing required fields; unknown schema/version/discriminator, conclusion,
  advisory, or caveat values; forbidden extra fields under the strict-schema
  policy; and non-finite or otherwise non-JSON-safe values fail closed.
  Known-truth, contract, integration,
  independent-evidence, and browser gates pass on a clean integration candidate
  before release consideration.

## Explicit non-goals

This design does not broaden the current LMM scope, reopen its contract lock,
or make any existing candidate accepted. It does not authorize real provider
calls, automatic model selection, autonomous branching, data mutation,
forecast publication, push, PR, merge, tag, or release.
