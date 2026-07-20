# Time Series Diagnostics C1 Contract-Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze and prove the first-slice Time Series Diagnostics public contract without registering, executing, or presenting the capability.

**Architecture:** C1 adds only strict contract types, pure decision-policy functions, canonical fixture packets, and reviewed decision records. A future `time_series_diagnostics` Pack will consume these contracts, but this plan deliberately creates no Pack runner, registry declaration, HTTP route, Agent operation, UI component, figure writer, or dependency change. The existing LMM public-adapter and frozen-containment gates remain prerequisites for all of those runtime surfaces.

**Tech Stack:** Python 3.14, existing `statsmodels 0.14.6`, pandas, NumPy, SciPy, pytest, and the existing `workbench.analysis_loop.canonical` canonical-JSON/SHA-256 primitives. No package installation, provider call, real API key, push, PR, merge, tag, or release is part of this plan.

---

## Scope and C1 exit rule

This is a contract-only sprint in `/Users/jiayuanren/项目规划/.worktrees/integration-v1.7.3` at C1 baseline `0251f0a30d984bdbb2cfab404e6c646deab60cae`. It does not modify protected adversarial tests, existing LMM contracts, `backend/workbench/engine/pack.py`, `registry.py`, `capabilities.py`, runtime stages, routes, Agent orchestration, frontend, or dependency files.

C1 is locked only when all seven records below have `status: locked`, the contract-only pytest suite is green, canonical fixtures parse and verify their digests, and an Integration reviewer records the exact C1 commit in the release-train receipt. Until then this plan produces evidence, not a runnable feature.

## File structure

| Path | Responsibility |
| --- | --- |
| `docs/superpowers/specs/2026-07-19-time-series-diagnostics-design.md` | Frozen high-level C1 charter and scope boundary. |
| `docs/superpowers/contracts/time-series-diagnostics/v1/README.md` | C1 index, lock checklist, cross-record invariants, and named owners. |
| `docs/superpowers/contracts/time-series-diagnostics/v1/decision-0{1..7}-*.md` | One fixture-backed decision record per C1 blocker. |
| `docs/superpowers/contracts/time-series-diagnostics/v1/packet-schema.md` | Exact Facts, Assessment, Advisory, and OperationExecutionEnvelope fields. |
| `docs/superpowers/contracts/time-series-diagnostics/v1/reason-code-catalogue.md` | Closed reason/caveat/advisory code namespace and owner. |
| `docs/superpowers/contracts/time-series-diagnostics/v1/policy-manifest.json` | Machine-readable C1 policy values and numeric-runtime-manifest shape. |
| `docs/superpowers/contracts/time-series-diagnostics/v1/fixture-catalogue.md` | Fixture identity, expected contract state, oracle source, and test owner. |
| `backend/workbench/contracts/model/time_series_diagnostics.py` | Strict contract-only parsers, digest projections, and pure assessment-policy derivation. |
| `tests/contracts/test_time_series_diagnostics_contracts.py` | Schema, operation-envelope, strict-enum, and digest-projection tests. |
| `tests/contracts/test_time_series_diagnostics_policy.py` | Complete decision table and advisory-precondition tests over constructed facts. |
| `tests/contracts/test_time_series_diagnostics_canonical_packets.py` | Committed-packet parsing, content-digest verification, and set-order tests. |
| `tests/fixtures/models/time_series_diagnostics/packets/*.json` | Versioned packet and execution-envelope fixtures only; no runtime outputs. |
| `tests/fixtures/models/time_series_diagnostics/raw/*.csv` | Immutable source-data fixtures for the later Pack/evaluator boundary. |

### Task 1: Freeze the corrected C1 charter and establish the contract index

**Files:**
- Modify: `docs/superpowers/specs/2026-07-19-time-series-diagnostics-design.md`
- Create: `docs/superpowers/contracts/time-series-diagnostics/v1/README.md`

- [ ] **Step 1: Verify the charter has the four required corrections before adding any C1 artifact.**

Run:

```bash
rg -n "operation_status.*completed|seasonal-candidate-period|descriptive trend|envelope_without_envelope_digest" \
  docs/superpowers/specs/2026-07-19-time-series-diagnostics-design.md
```

Expected: one or more matches for every term; no match for `parent_assessment_packet_id` or `descriptive deterministic-trend`.

- [ ] **Step 2: Write the C1 index with a hard, machine-checkable lock rule.**

The index begins with this table and states that every row needs a named fixture and a passing test before `status` becomes `locked`:

```markdown
| Record | Subject | Owner | Lock evidence |
| --- | --- | --- | --- |
| D01 | Operation/result separation | Integration C1 | envelope fixtures + contract test |
| D02 | Decision priority/component matrix | Integration C1 | constructed-facts policy matrix |
| D03 | Time semantics and seasonal period | Integration C1 | raw fixtures + parser contract test |
| D04 | Statistical mechanics | Integration C1 | independent oracle manifest + boundary tests |
| D05 | Trend/advisory boundary | Integration C1 | advisory truth-table test |
| D06 | Packet identity/digests | Integration C1 | canonical packet/digest tests |
| D07 | Evaluation/gating | Integration C1 | fixture catalogue + negative-capability checklist |
```

- [ ] **Step 3: Record the non-negotiable C1 boundary.**

Add this exact constraint to the index:

```text
This directory freezes portable evidence contracts only. It must not add a
time-series pack declaration, model handler, pipeline stage, registry entry,
HTTP route, Agent operation, UI feature registration, Compare projection, or
dependency change. Those surfaces remain unavailable until the LMM adapter and
frozen-containment prerequisites are independently accepted.
```

- [ ] **Step 4: Review the documentation-only diff.**

Run:

```bash
git diff --check
git diff -- docs/superpowers/specs/2026-07-19-time-series-diagnostics-design.md \
  docs/superpowers/contracts/time-series-diagnostics/v1/README.md
```

Expected: no whitespace errors; the diff changes only C1 documentation.

### Task 2: Lock D01 — operation execution envelope and packet-reference invariant

**Files:**
- Create: `docs/superpowers/contracts/time-series-diagnostics/v1/decision-01-operation-envelope.md`
- Modify: `docs/superpowers/contracts/time-series-diagnostics/v1/packet-schema.md`
- Test: `tests/contracts/test_time_series_diagnostics_contracts.py`

- [ ] **Step 1: Write failing tests for the only legal operation/packet combinations.**

```python
@pytest.mark.parametrize(
    ("status", "facts_ref", "assessment_ref"),
    [
        ("completed", "facts:fixture", "assessment:fixture"),
        ("rejected", None, None),
        ("failed", None, None),
        ("cancelled", None, None),
    ],
)
def test_execution_envelope_packet_reference_invariant(
    status: str, facts_ref: str | None, assessment_ref: str | None,
) -> None:
    envelope = OperationExecutionEnvelope.from_dict({
        "operation_status": status,
        "reason_code": "FIXTURE_STATE",
        "facts_packet_ref": facts_ref,
        "assessment_packet_ref": assessment_ref,
    })
    assert envelope.operation_status == status


def test_non_completed_execution_envelope_rejects_packet_references() -> None:
    with pytest.raises(ContractError, match="packet refs require completed"):
        OperationExecutionEnvelope.from_dict({
            "operation_status": "failed",
            "reason_code": "EXECUTOR_TIMEOUT",
            "facts_packet_ref": "facts:forbidden",
            "assessment_packet_ref": "assessment:forbidden",
        })
```

- [ ] **Step 2: Run the focused test to prove the contract does not exist yet.**

Run:

```bash
/Users/jiayuanren/项目规划/.venv/bin/python -m pytest \
  tests/contracts/test_time_series_diagnostics_contracts.py -q
```

Expected: collection failure because `time_series_diagnostics` has not been created.

- [ ] **Step 3: Freeze the D01 record and schema paragraph.**

The decision record must lock these rules verbatim:

```text
completed -> facts_packet_ref present and assessment_packet_ref present
rejected | failed | cancelled -> facts_packet_ref absent and assessment_packet_ref absent
only completed reaches the statistical decision table
hard data-input failure is completed + not_suitable
unexpected timeout, OOM, terminated executor, or corrupt Pack output is failed
```

It also names `rejected`, `completed`, `failed`, and `cancelled` as the complete closed set, records idempotent confirmation/cancellation as an existing platform-lifecycle dependency, and assigns no statistical conclusion to the other three states.

- [ ] **Step 4: Implement the minimal strict envelope parser.**

```python
@dataclass(frozen=True)
class OperationExecutionEnvelope:
    operation_status: Literal["rejected", "completed", "failed", "cancelled"]
    reason_code: str
    facts_packet_ref: str | None
    assessment_packet_ref: str | None

    def __post_init__(self) -> None:
        refs_present = self.facts_packet_ref is not None or self.assessment_packet_ref is not None
        if self.operation_status == "completed":
            if self.facts_packet_ref is None or self.assessment_packet_ref is None:
                raise ContractError("completed requires both packet refs")
        elif refs_present:
            raise ContractError("packet refs require completed")
```

`from_dict` uses `require_exact_keys`, rejects unknown status/reason values, and never defaults absent fields.

- [ ] **Step 5: Run the focused test.**

Run:

```bash
/Users/jiayuanren/项目规划/.venv/bin/python -m pytest \
  tests/contracts/test_time_series_diagnostics_contracts.py -q
```

Expected: PASS.

### Task 3: Lock D02 and D05 — decision matrix, components, trend, and advisory-only boundary

**Files:**
- Create: `docs/superpowers/contracts/time-series-diagnostics/v1/decision-02-decision-matrix.md`
- Create: `docs/superpowers/contracts/time-series-diagnostics/v1/decision-05-trend-advisory.md`
- Modify: `docs/superpowers/contracts/time-series-diagnostics/v1/policy-manifest.json`
- Modify: `backend/workbench/contracts/model/time_series_diagnostics.py`
- Test: `tests/contracts/test_time_series_diagnostics_policy.py`

- [ ] **Step 1: Freeze the numeric component policy in the manifest.**

```json
{
  "policy_version": "time_series_diagnostics_c1_v1",
  "minimums": {
    "hard_input_min": 20,
    "adf_min": 20,
    "kpss_min": 20,
    "acf_min": 20,
    "pacf_min": 20,
    "trend_min": 8,
    "minimum_effective_lag": 5,
    "minimum_complete_cycles": 2
  },
  "conclusion_values": ["suitable_with_caveats", "not_suitable", "inconclusive"],
  "null_test_outcomes": ["reject", "fail_to_reject", "undetermined"]
}
```

The D02 record explains that these are first-slice evidence minima, not universal time-series adequacy thresholds; every value is tied to a named boundary fixture.

- [ ] **Step 2: Write failing policy truth-table tests.**

```python
@pytest.mark.parametrize(
    ("adf", "kpss", "expected"),
    [
        ("reject", "fail_to_reject", "suitable_with_caveats"),
        ("fail_to_reject", "reject", "suitable_with_caveats"),
        ("reject", "reject", "inconclusive"),
        ("fail_to_reject", "fail_to_reject", "inconclusive"),
        ("undetermined", "reject", "inconclusive"),
        ("reject", "undetermined", "inconclusive"),
    ],
)
def test_completed_required_null_test_outcomes_have_one_conclusion(
    adf: str, kpss: str, expected: str,
) -> None:
    assert derive_assessment(_complete_facts(adf=adf, kpss=kpss)).conclusion == expected
```

- [ ] **Step 3: Define the two advisory truth tables in D05.**

`CONSIDER_DIFFERENCING` exists exactly when all required components are completed, ADF is `fail_to_reject`, KPSS is `reject`, and descriptive trend is `absent`. `REVIEW_TREND_HANDLING` exists exactly when trend status is `completed`, trend evidence is `present` or `undetermined`, and its documented preconditions are all `true`. Both have `advisory_only` effect and `execution_available: false`; neither contains a confirmation token, patch, or operation ID.

- [ ] **Step 4: Implement only the pure policy derivation.**

```python
def derive_assessment(facts: TimeSeriesDiagnosticFacts) -> TimeSeriesDiagnosticAssessment:
    if facts.has_hard_input_violation:
        return TimeSeriesDiagnosticAssessment.not_suitable(facts)
    if facts.required_component_unavailable or "undetermined" in facts.required_null_outcomes:
        return TimeSeriesDiagnosticAssessment.inconclusive(facts)
    return _derive_complete_level_evidence_assessment(facts)
```

The implementation accepts already-normalized facts; it must not parse a DataFrame, call statsmodels, mutate data, register a Pack, or issue an operation.

- [ ] **Step 5: Run the policy suite.**

Run:

```bash
/Users/jiayuanren/项目规划/.venv/bin/python -m pytest \
  tests/contracts/test_time_series_diagnostics_policy.py -q
```

Expected: PASS, including no-advisory cases for ADF/KPSS conflict, unavailable trend, and every `unknown` advisory precondition.

### Task 4: Lock D03 and D04 — time/seasonal semantics and statistical mechanics

**Files:**
- Create: `docs/superpowers/contracts/time-series-diagnostics/v1/decision-03-time-semantics.md`
- Create: `docs/superpowers/contracts/time-series-diagnostics/v1/decision-04-statistical-mechanics.md`
- Modify: `docs/superpowers/contracts/time-series-diagnostics/v1/policy-manifest.json`
- Test: `tests/contracts/test_time_series_diagnostics_contracts.py`
- Create: `tests/fixtures/models/time_series_diagnostics/raw/exact_regular_no_semantic_frequency.csv`
- Create: `tests/fixtures/models/time_series_diagnostics/raw/candidate_period_lag_steps.csv`

- [ ] **Step 1: Freeze the time and seasonal declarations.**

The D03 record defines `grid_regularity` as `exact_regular`, `irregular`, or `undetermined`; `grid_basis` as `contiguous_integer_step`, `exact_fixed_duration_step`, `declared_calendar_frequency`, or `none`; and `semantic_frequency_source` as `user_confirmed`, `artifact_metadata`, or `none`. It accepts a seasonal candidate period only as:

```json
{
  "value": 12,
  "unit": "lag_steps",
  "source": "user_confirmed"
}
```

Validation requires integer `value >= 2` and `value < usable_observation_count`. A `lag_steps` period remains valid when semantic frequency is `none`; seasonality eligibility then says nothing about calendar units.

- [ ] **Step 2: Freeze the p-value and lag policies.**

Add this D04 manifest fragment:

```json
{
  "alpha": 0.05,
  "adf": {"regression": "c", "p_value_statuses": ["approximate", "unavailable"]},
  "kpss": {"null": "level_stationarity", "p_value_statuses": ["approximate", "lower_bound", "upper_bound", "unavailable"]},
  "acf": {"lag_zero": "included", "confidence_level": 0.95},
  "pacf": {"method": "ywm", "lag_zero": "included", "confidence_level": 0.95}
}
```

The record states that a KPSS reported lower table endpoint means `actual_p_value > endpoint` and `lower_bound`; a reported upper table endpoint means `actual_p_value < endpoint` and `upper_bound`. It also locks `RAW_LEVEL_CORRELATION_ONLY`, `NO_MODEL_ORDER_INFERENCE`, `LEVEL_STATIONARITY_ONLY`, `NO_FORECAST_ELIGIBILITY`, `NO_MODEL_SELECTION`, and `STRUCTURAL_BREAKS_NOT_ASSESSED` as applicable caveats.

- [ ] **Step 3: Write boundary tests before parser implementation.**

```python
def test_candidate_period_without_semantic_frequency_is_lag_steps_only() -> None:
    proposal = TimeSeriesDiagnosticProposal.from_dict(_proposal(
        semantic_frequency_source="none",
        seasonal_candidate_period={"value": 12, "unit": "lag_steps", "source": "user_confirmed"},
    ))
    assert proposal.seasonal_candidate_period["unit"] == "lag_steps"


def test_adf_rejects_exact_p_value_status() -> None:
    with pytest.raises(ContractError, match="ADF p_value_status"):
        AdfFact.from_dict(_adf_fact(p_value_status="exact"))
```

- [ ] **Step 4: Implement strict declared-value validation only.**

Use frozen literal sets for frequency sources, time-grid values, p-value statuses, and candidate-period shape. Do not parse dates or calculate ADF/KPSS in C1; those are future Pack responsibilities tested later through the raw fixtures.

- [ ] **Step 5: Run the contract suite.**

Run:

```bash
/Users/jiayuanren/项目规划/.venv/bin/python -m pytest \
  tests/contracts/test_time_series_diagnostics_contracts.py -q
```

Expected: PASS; an undeclared semantic frequency, guessed period, `exact` ADF p-value, ambiguous time form, or unknown enum is rejected rather than coerced.

### Task 5: Lock D06 — strict packet schema and non-cyclic digest projections

**Files:**
- Create: `docs/superpowers/contracts/time-series-diagnostics/v1/decision-06-packet-identity.md`
- Create: `docs/superpowers/contracts/time-series-diagnostics/v1/packet-schema.md`
- Create: `docs/superpowers/contracts/time-series-diagnostics/v1/reason-code-catalogue.md`
- Modify: `backend/workbench/contracts/model/time_series_diagnostics.py`
- Test: `tests/contracts/test_time_series_diagnostics_contracts.py`
- Test: `tests/contracts/test_time_series_diagnostics_canonical_packets.py`

- [ ] **Step 1: Write digest-order tests.**

```python
def test_assessment_digest_is_invariant_to_advisory_input_order() -> None:
    left = _assessment(advisories=[_review_trend(), _consider_differencing()])
    right = _assessment(advisories=[_consider_differencing(), _review_trend()])
    assert assessment_content_digest(left) == assessment_content_digest(right)


def test_envelope_digest_excludes_only_its_own_field() -> None:
    envelope = _completed_envelope()
    assert envelope_digest(envelope) == envelope_digest({**envelope, "envelope_digest": "forged"})
    assert envelope_digest(envelope) != envelope_digest({**envelope, "reason_code": "CHANGED"})
```

- [ ] **Step 2: Define exact projections in D06 and the schema catalogue.**

```python
def facts_content_projection(packet: Mapping[str, object]) -> dict[str, object]:
    return _select(packet, {
        "contract", "contract_version", "producer_version", "policy_version",
        "input_identity", "configuration", "numeric_runtime_manifest_digest", "facts",
    })


def assessment_content_projection(packet: Mapping[str, object]) -> dict[str, object]:
    return _select(packet, {
        "facts_content_digest", "decision_policy_version", "assessment_scope",
        "conclusion", "caveat_codes", "caveat_fact_refs", "advisories",
    })
```

The schema describes `packet_id`, `run_id`, `execution_timestamp`, and all digest fields as excluded from content projections. `envelope_digest` hashes `envelope_without_envelope_digest`. `caveat_codes` sort by code, advisories by `(advisory_code, advisory_version)`, and evidence references by canonical fact path. Advisory containment establishes its parent: the normative embedded advisory schema excludes parent packet ID.

- [ ] **Step 3: Define the closed reason-code catalogue.**

Start the catalogue with these groups and require every emitted code to appear once with status, message key, packet placement, and fixture:

```text
input: TIME_VALUE_MISSING, TIME_PARSE_FAILED, IRREGULAR_SPACING,
       EXPECTED_TIME_POINT_ABSENT, FREQUENCY_DECLARATION_MISMATCH
component: TREND_NOT_ASSESSED, NO_DECLARED_CANDIDATE_PERIOD
caveat: RAW_LEVEL_CORRELATION_ONLY, NO_MODEL_ORDER_INFERENCE,
        LEVEL_STATIONARITY_ONLY, NO_FORECAST_ELIGIBILITY,
        NO_MODEL_SELECTION, STRUCTURAL_BREAKS_NOT_ASSESSED
advisory: CONSIDER_DIFFERENCING, REVIEW_TREND_HANDLING
execution: EXECUTOR_TIMEOUT, EXECUTOR_OOM, UNSUPPORTED_DEPENDENCY_MANIFEST
```

- [ ] **Step 4: Implement canonical projection helpers with the existing canonical JSON primitive.**

```python
def facts_content_digest(packet: Mapping[str, object]) -> str:
    return sha256_canonical(facts_content_projection(packet))


def envelope_digest(packet: Mapping[str, object]) -> str:
    return sha256_canonical({key: value for key, value in packet.items() if key != "envelope_digest"})
```

Reject non-finite values, unknown fields, unknown discriminators, unknown codes, and malformed references before a packet is exposed to another seam.

- [ ] **Step 5: Run the canonical packet tests.**

Run:

```bash
/Users/jiayuanren/项目规划/.venv/bin/python -m pytest \
  tests/contracts/test_time_series_diagnostics_contracts.py \
  tests/contracts/test_time_series_diagnostics_canonical_packets.py -q
```

Expected: PASS; advisory reordering preserves the digest, any advisory content change changes the assessment digest, and altered Facts digest prevents Assessment parsing.

### Task 6: Lock D07 — fixture catalogue, numerical runtime manifest, and negative capability evidence

**Files:**
- Create: `docs/superpowers/contracts/time-series-diagnostics/v1/decision-07-evaluation-gating.md`
- Create: `docs/superpowers/contracts/time-series-diagnostics/v1/fixture-catalogue.md`
- Modify: `docs/superpowers/contracts/time-series-diagnostics/v1/policy-manifest.json`
- Create: `tests/fixtures/models/time_series_diagnostics/packets/*.json`
- Create: `tests/fixtures/models/time_series_diagnostics/raw/*.csv`
- Modify: `tests/contracts/test_time_series_diagnostics_canonical_packets.py`

- [ ] **Step 1: Define the supported numerical runtime manifest.**

```json
{
  "numeric_runtime_manifest": {
    "python": "3.14",
    "platform_architecture": "required",
    "statsmodels": "0.14.6",
    "numpy": "required",
    "scipy": "required",
    "pandas": "required",
    "blas_lapack_provider": "required",
    "numeric_thread_settings": "required",
    "pack_policy_version": "time_series_diagnostics_c1_v1"
  }
}
```

The runtime manifest values are captured by the future frozen-containment executor and hashed as `numeric_runtime_manifest_digest`. An unsupported manifest is preflight `rejected` with no packet references; it is never silently tolerated.

- [ ] **Step 2: Commit fixture entries for every required boundary.**

The catalogue contains at least these named rows: `exact_regular_no_semantic_frequency`, `candidate_period_lag_steps`, `required_null_outcome_undetermined`, `trend_component_unavailable`, `trend_component_ambiguous`, `completed_missing_assessment_ref`, `terminal_noncompleted_with_refs`, `assessment_conclusion_mutated`, `advisory_reordered`, `advisory_content_changed`, `facts_digest_mismatch`, `unsupported_dependency_manifest`, `stale_pre_run_confirmation`, `post_run_advisory`, and `attempted_execution_of_advisory`.

- [ ] **Step 3: Write fixture parsing tests before adding packet JSON.**

```python
def test_noncompleted_envelope_fixture_cannot_carry_packet_refs() -> None:
    with pytest.raises(ContractError):
        _load_envelope("terminal_noncompleted_with_refs.json")


def test_time_series_contract_is_not_discoverable_as_a_runtime_capability() -> None:
    assert "time_series_diagnostics" not in MODEL_REGISTRY
    assert "time_series_diagnostics" not in {item.pack_id for item in REGISTERED_PACKS}
```

- [ ] **Step 4: Add immutable raw data and packet fixtures.**

Each raw CSV is small, UTF-8, and has one stated property. Each packet fixture is strict JSON, carries a fixture ID, and is parsed through the C1 contract types. The numerical oracle record identifies a manually verified or independently calculated ADF/KPSS/ACF/PACF source, vector tolerances, and the platform manifest that produced it; it does not reuse a future Pack result as its oracle.

- [ ] **Step 5: Run the full C1 contract suite and the protected regression gates.**

Run:

```bash
/Users/jiayuanren/项目规划/.venv/bin/python -m pytest \
  tests/contracts/test_time_series_diagnostics_contracts.py \
  tests/contracts/test_time_series_diagnostics_policy.py \
  tests/contracts/test_time_series_diagnostics_canonical_packets.py \
  tests/contracts/test_lmm_contracts.py \
  tests/contracts/test_lmm_canonical_packets.py \
  tests/test_honest_did_adversarial.py \
  tests/test_honest_did_sd_adversarial.py -q
```

Expected: PASS. The new capability remains absent from model registry, pack registry, routes, catalogue, Agent tools, Compare, and frontend.

### Task 7: Perform the C1 lock review without starting implementation

**Files:**
- Modify: `docs/superpowers/contracts/time-series-diagnostics/v1/README.md`
- Modify: `docs/superpowers/release-trains/v1.7.3/README.md`
- Create: `docs/superpowers/release-trains/v1.7.3/time-series-c1-lock-receipt.md`

- [ ] **Step 1: Verify documentation and code scope.**

Run:

```bash
git diff --check
git diff --name-only 0251f0a30d984bdbb2cfab404e6c646deab60cae..HEAD
git status --short
```

Expected: only the C1 contract/docs/tests/fixtures paths listed in this plan differ; no engine registration, route, Agent/UI, dependency, or protected-test file appears.

- [ ] **Step 2: Mark records locked only after all fixture evidence is green.**

The receipt lists the exact C1 commit, policy-manifest digest, fixture catalogue digest, focused test command/output, baseline commit, and the explicit negative-capability result. It must retain these statements:

```text
Time Series Diagnostics is contract-locked, not feature-implemented.
No runtime capability is registered or advertised.
Time-series implementation remains blocked on the accepted LMM public adapter
and frozen-containment evaluator.
```

- [ ] **Step 3: Obtain an explicit implementation authorization before any next plan.**

Do not create a feature worktree or begin a Pack, executor, registry, HTTP, Agent, UI, figure, Compare, forecast, or dependency task from this receipt. The next plan begins only after the stated LMM prerequisites are accepted and the user authorizes the first implementation slice.

## Plan self-review

Coverage: D01–D07 each have a named documentation record, one contract/policy/fixture test path, and a C1 exit condition. The plan enforces the completed-only decision table, digest projection without self-reference, seasonal lag-step confirmation, descriptive trend language, p-value restrictions, numerical runtime evidence, and negative runtime capability boundary.

Deliberate exclusions: it does not calculate statistics, parse source dates at runtime, mutate data, install a dependency, create a model result, create figures, expose Compare, or add a forecast. Those omissions preserve the charter's current authorization boundary.
