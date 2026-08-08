from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, replace
import json
from typing import Any

import pytest

from workbench.contracts.model.replicate_combine import (
    COMBINER_IDS,
    MAX_EVIDENCE_SCALARS,
    MAX_REQUESTED_REPLICATES,
    REPLICATE_COMBINE_CONTRACT,
    REPLICATE_COMBINE_CONTRACT_VERSION,
    REPLICATE_KINDS,
    ReplicateContractError,
    ReplicatePlan,
)
from workbench.engine.replicate_combine import (
    ReplicateAdapter,
    ReplicateBatch,
    ReplicateCombineError,
    ReplicateEvidence,
    ReplicateExecutionError,
    ReplicateRegistry,
    ReplicateStrategy,
    dispatch_combiner,
    execute,
)


_STRATEGY_ID = "test.deterministic_scalar.v1"
_ADAPTER_ID = "test.scalar_evidence.v1"
_RAW_SENTINEL = 918273645.125


class _DeterministicStrategy(ReplicateStrategy):
    strategy_id = _STRATEGY_ID

    def generate(
        self,
        *,
        plan: ReplicatePlan,
        replicate_index: int,
        seed: int,
    ) -> ReplicateEvidence:
        # The runner may hash these bounded scalar values, but must not publish
        # the per-replicate evidence as rows/values in its provenance envelope.
        return ReplicateEvidence(
            scalars={
                "score": _RAW_SENTINEL + float(seed % 97),
                "replicate_index": float(replicate_index),
            }
        )


class _ScalarAdapter(ReplicateAdapter):
    adapter_id = _ADAPTER_ID

    def adapt(
        self,
        evidence: ReplicateEvidence,
        *,
        plan: ReplicatePlan,
        replicate_index: int,
    ) -> ReplicateEvidence:
        assert plan.kind in REPLICATE_KINDS
        assert replicate_index >= 0
        return evidence


@dataclass(frozen=True)
class _FailingStrategy(_DeterministicStrategy):
    fail_indices: frozenset[int] = frozenset()

    def generate(
        self,
        *,
        plan: ReplicatePlan,
        replicate_index: int,
        seed: int,
    ) -> ReplicateEvidence:
        if replicate_index in self.fail_indices:
            raise ReplicateExecutionError(
                reason_code="REPLICATE_STRATEGY_FAILED",
                message="fixture strategy rejected this replicate",
            )
        return super().generate(
            plan=plan,
            replicate_index=replicate_index,
            seed=seed,
        )


class _VectorEvidenceStrategy(_DeterministicStrategy):
    def generate(
        self,
        *,
        plan: ReplicatePlan,
        replicate_index: int,
        seed: int,
    ) -> ReplicateEvidence:
        # Deliberately violate the scalar-only evidence boundary.
        return ReplicateEvidence(  # type: ignore[arg-type]
            scalars={"raw_vector": [_RAW_SENTINEL, float(replicate_index)]}
        )


def _plan(**overrides: Any) -> ReplicatePlan:
    values: dict[str, Any] = {
        "kind": "multiple_imputation",
        "requested_replicates": 4,
        "seed": 123,
        "strategy_id": _STRATEGY_ID,
        "adapter_id": _ADAPTER_ID,
        "combiner_id": "rubin_pool",
        "max_failures": 1,
        "max_evidence_scalars": 8,
    }
    values.update(overrides)
    return ReplicatePlan(**values)


def _registry(
    strategy: ReplicateStrategy | None = None,
    adapter: ReplicateAdapter | None = None,
) -> ReplicateRegistry:
    registry = ReplicateRegistry()
    registry.register_strategy(strategy or _DeterministicStrategy())
    registry.register_adapter(adapter or _ScalarAdapter())
    return registry


def _assert_reason(error: BaseException, reason_code: str) -> None:
    assert isinstance(error, (ReplicateContractError, ReplicateCombineError))
    assert getattr(error, "reason_code", None) == reason_code


def test_replicate_plan_is_versioned_immutable_and_json_safe() -> None:
    plan = _plan()

    assert REPLICATE_COMBINE_CONTRACT == "replicate_combine.plan"
    assert REPLICATE_COMBINE_CONTRACT_VERSION == "1.0"
    assert plan.to_dict() == {
        "contract": REPLICATE_COMBINE_CONTRACT,
        "contract_version": REPLICATE_COMBINE_CONTRACT_VERSION,
        "kind": "multiple_imputation",
        "requested_replicates": 4,
        "seed": 123,
        "strategy_id": _STRATEGY_ID,
        "adapter_id": _ADAPTER_ID,
        "combiner_id": "rubin_pool",
        "max_failures": 1,
        "max_evidence_scalars": 8,
    }

    serialized = json.loads(json.dumps(plan.to_dict(), allow_nan=False))
    assert ReplicatePlan.from_dict(serialized) == plan

    with pytest.raises(FrozenInstanceError):
        plan.seed = 999  # type: ignore[misc]


@pytest.mark.parametrize(
    "kind",
    ["multiple_imputation", "bootstrap", "permutation", "survey_replicate"],
)
def test_replicate_plan_accepts_only_the_declared_replicate_kinds(kind: str) -> None:
    assert REPLICATE_KINDS == frozenset(
        {"multiple_imputation", "bootstrap", "permutation", "survey_replicate"}
    )
    assert _plan(kind=kind).kind == kind


@pytest.mark.parametrize("kind", ["jackknife", "", None, 1, True])
def test_replicate_plan_rejects_unknown_or_non_string_kind(kind: Any) -> None:
    with pytest.raises(ReplicateContractError) as caught:
        _plan(kind=kind)
    _assert_reason(caught.value, "REPLICATE_INVALID_KIND")


@pytest.mark.parametrize("requested", [0, -1, 1.5, True, "4"])
def test_replicate_plan_requires_a_positive_exact_integer_count(requested: Any) -> None:
    with pytest.raises(ReplicateContractError) as caught:
        _plan(requested_replicates=requested)
    _assert_reason(caught.value, "REPLICATE_INVALID_REQUESTED_COUNT")


def test_replicate_plan_rejects_a_count_above_the_hard_limit() -> None:
    assert MAX_REQUESTED_REPLICATES > 0
    with pytest.raises(ReplicateContractError) as caught:
        _plan(requested_replicates=MAX_REQUESTED_REPLICATES + 1)
    _assert_reason(caught.value, "REPLICATE_REQUESTED_COUNT_EXCEEDS_LIMIT")


@pytest.mark.parametrize("seed", [-1, 1.5, True, "123"])
def test_replicate_plan_requires_an_explicit_non_negative_integer_seed(seed: Any) -> None:
    with pytest.raises(ReplicateContractError) as caught:
        _plan(seed=seed)
    _assert_reason(caught.value, "REPLICATE_INVALID_SEED")


@pytest.mark.parametrize("field_name", ["strategy_id", "adapter_id", "combiner_id"])
@pytest.mark.parametrize("value", ["", " ", None, 1, True, "../python.path"])
def test_replicate_plan_rejects_invalid_strategy_adapter_and_combiner_ids(
    field_name: str, value: Any
) -> None:
    with pytest.raises(ReplicateContractError) as caught:
        _plan(**{field_name: value})
    _assert_reason(caught.value, "REPLICATE_INVALID_ID")


def test_replicate_plan_rejects_an_undeclared_combiner_id() -> None:
    assert COMBINER_IDS == frozenset(
        {"rubin_pool", "distribution_ci", "permutation_null", "replicate_covariance"}
    )
    with pytest.raises(ReplicateContractError) as caught:
        _plan(combiner_id="not_a_declared_combiner")
    _assert_reason(caught.value, "REPLICATE_UNKNOWN_COMBINER")


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("callback", lambda value: value),
        ("callable", lambda value: value),
        ("formula", "mean(x)")
        ,
        ("python", "__import__('os')"),
        ("import_path", "os.system"),
        ("shell", "rm -rf /"),
        ("command", "python -c 'print(1)'"),
        ("expression", "x + 1"),
    ],
)
def test_serialized_plan_rejects_executable_fields(
    field_name: str, value: Any
) -> None:
    payload = _plan().to_dict()
    payload[field_name] = value

    with pytest.raises(ReplicateContractError) as caught:
        ReplicatePlan.from_dict(payload)
    _assert_reason(caught.value, "REPLICATE_UNSAFE_EXECUTION_FIELD")


@pytest.mark.parametrize("field_name", ["extra", "options", "user_metadata"])
def test_serialized_plan_rejects_unknown_fields(field_name: str) -> None:
    payload = _plan().to_dict()
    payload[field_name] = True

    with pytest.raises(ReplicateContractError) as caught:
        ReplicatePlan.from_dict(payload)
    _assert_reason(caught.value, "REPLICATE_UNKNOWN_FIELD")


@pytest.mark.parametrize("field_name", ["replicate_rows", "replicate_values", "raw_data"])
def test_serialized_plan_rejects_raw_replicate_payloads(field_name: str) -> None:
    payload = _plan().to_dict()
    payload[field_name] = [[_RAW_SENTINEL]]

    with pytest.raises(ReplicateContractError) as caught:
        ReplicatePlan.from_dict(payload)
    _assert_reason(caught.value, "REPLICATE_RAW_VALUES_FORBIDDEN")


def test_serialized_plan_rejects_wrong_contract_version() -> None:
    payload = _plan().to_dict()
    payload["contract_version"] = "0.1"

    with pytest.raises(ReplicateContractError) as caught:
        ReplicatePlan.from_dict(payload)
    _assert_reason(caught.value, "REPLICATE_UNSUPPORTED_CONTRACT_VERSION")


@pytest.mark.parametrize(
    "combiner_id",
    ["rubin_pool", "distribution_ci", "permutation_null", "replicate_covariance"],
)
def test_combiner_dispatch_resolves_only_declared_ids_without_doing_combiner_math(
    combiner_id: str,
) -> None:
    descriptor = dispatch_combiner(combiner_id)

    assert descriptor.combiner_id == combiner_id
    assert descriptor.combiner_id in COMBINER_IDS


def test_combiner_dispatch_rejects_unknown_ids_with_a_stable_reason_code() -> None:
    with pytest.raises(ReplicateCombineError) as caught:
        dispatch_combiner("rubin_pool;__import__('os')")
    _assert_reason(caught.value, "REPLICATE_UNKNOWN_COMBINER")


def test_registry_rejects_a_callback_instead_of_treating_it_as_a_strategy() -> None:
    registry = ReplicateRegistry()

    with pytest.raises(ReplicateCombineError) as caught:
        registry.register_strategy(lambda **kwargs: kwargs)
    _assert_reason(caught.value, "REPLICATE_STRATEGY_NOT_TYPED")

    with pytest.raises(ReplicateCombineError) as caught:
        registry.register_adapter(lambda value: value)
    _assert_reason(caught.value, "REPLICATE_ADAPTER_NOT_TYPED")


def test_execute_requires_registered_strategy_and_adapter_ids() -> None:
    registry = ReplicateRegistry()

    with pytest.raises(ReplicateCombineError) as caught:
        execute(_plan(), registry=registry)
    _assert_reason(caught.value, "REPLICATE_STRATEGY_NOT_REGISTERED")

    registry.register_strategy(_DeterministicStrategy())
    with pytest.raises(ReplicateCombineError) as caught:
        execute(_plan(), registry=registry)
    _assert_reason(caught.value, "REPLICATE_ADAPTER_NOT_REGISTERED")


def test_execute_success_exposes_counts_and_bounded_scalar_provenance() -> None:
    plan = _plan()
    batch = execute(plan, registry=_registry())

    assert batch.status == "completed"
    assert batch.reason_code == "REPLICATE_COMPLETED"
    assert batch.requested_count == 4
    assert batch.succeeded_count == 4
    assert batch.failed_count == 0
    assert batch.failure_reasons == {}
    assert batch.provenance["strategy_id"] == _STRATEGY_ID
    assert batch.provenance["adapter_id"] == _ADAPTER_ID
    assert batch.provenance["replicate_order"] == [0, 1, 2, 3]
    assert batch.provenance["evidence_scalar_count"] <= plan.max_evidence_scalars


def test_execute_is_deterministic_for_same_plan_and_typed_registry() -> None:
    plan = _plan()

    first = execute(plan, registry=_registry())
    second = execute(plan, registry=_registry())

    assert first.to_dict() == second.to_dict()
    assert first.digest == second.digest
    assert first.provenance == second.provenance

    changed_seed = execute(replace(plan, seed=124), registry=_registry())
    assert changed_seed.digest != first.digest


def test_batch_serialization_is_versioned_roundtrippable_and_excludes_raw_values() -> None:
    batch = execute(_plan(), registry=_registry())
    payload = batch.to_dict()

    assert set(payload) == {
        "contract",
        "contract_version",
        "kind",
        "requested_count",
        "succeeded_count",
        "failed_count",
        "seed",
        "status",
        "reason_code",
        "failure_reasons",
        "provenance",
        "digest",
    }
    assert payload["contract"] == "replicate_combine.batch"
    assert payload["contract_version"] == REPLICATE_COMBINE_CONTRACT_VERSION
    assert payload["kind"] == "multiple_imputation"
    assert payload["requested_count"] == 4
    assert payload["succeeded_count"] == 4
    assert payload["failed_count"] == 0
    assert payload["seed"] == 123
    assert isinstance(payload["digest"], str)
    assert len(payload["digest"]) == 64
    assert all(character in "0123456789abcdef" for character in payload["digest"])

    provenance_json = json.dumps(payload["provenance"], allow_nan=False)
    assert "rows" not in provenance_json
    assert "values" not in provenance_json
    assert str(_RAW_SENTINEL) not in provenance_json
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload
    assert ReplicateBatch.from_dict(payload).to_dict() == payload


def test_execute_reports_allowed_replicate_failures_by_stable_reason_code() -> None:
    plan = _plan(max_failures=1)
    strategy = _FailingStrategy(fail_indices=frozenset({1}))

    batch = execute(plan, registry=_registry(strategy=strategy))

    assert batch.status == "completed_with_failures"
    assert batch.reason_code == "REPLICATE_PARTIAL_FAILURE"
    assert batch.requested_count == 4
    assert batch.succeeded_count == 3
    assert batch.failed_count == 1
    assert batch.failure_reasons == {"REPLICATE_STRATEGY_FAILED": 1}


def test_execute_fails_closed_when_failure_budget_is_exceeded() -> None:
    plan = _plan(max_failures=1)
    strategy = _FailingStrategy(fail_indices=frozenset({0, 1}))

    batch = execute(plan, registry=_registry(strategy=strategy))

    assert batch.status == "failed"
    assert batch.reason_code == "REPLICATE_FAILURE_BUDGET_EXCEEDED"
    assert batch.requested_count == 4
    assert batch.succeeded_count == 2
    assert batch.failed_count == 2
    assert batch.failure_reasons == {"REPLICATE_STRATEGY_FAILED": 2}
    assert batch.to_dict()["digest"] is None


def test_execute_fails_closed_when_scalar_evidence_budget_is_exceeded() -> None:
    plan = _plan(max_evidence_scalars=1)

    batch = execute(plan, registry=_registry())

    assert batch.status == "failed"
    assert batch.reason_code == "REPLICATE_EVIDENCE_BUDGET_EXCEEDED"
    assert batch.succeeded_count == 0
    assert batch.failed_count == 0
    assert batch.to_dict()["digest"] is None


def test_execute_rejects_non_scalar_evidence_before_digesting_or_publishing_it() -> None:
    plan = _plan()

    with pytest.raises(ReplicateCombineError) as caught:
        execute(plan, registry=_registry(strategy=_VectorEvidenceStrategy()))
    _assert_reason(caught.value, "REPLICATE_NON_SCALAR_EVIDENCE")
