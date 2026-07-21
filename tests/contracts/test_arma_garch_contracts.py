from __future__ import annotations

from copy import deepcopy

import pytest

from workbench.canonical import sha256_canonical


def _minimal_payload() -> dict[str, object]:
    return {
        "dataset_ref": "dataset:vix-like:1",
        "time_column": "date",
        "value_column": "value",
        "time_index_semantics": "business_or_trading_observations",
        "transform": "log_return_pct",
        "transform_confirmed": True,
        "validation": {},
    }


def _contract_types():
    from workbench.contracts.model.arma_garch import (
        ArmaGarchAnalysisContract,
        ArmaGarchContractError,
    )

    return ArmaGarchAnalysisContract, ArmaGarchContractError


def test_minimal_input_expands_to_frozen_approved_defaults() -> None:
    contract_type, _ = _contract_types()

    contract = contract_type.from_dict(_minimal_payload())

    expected = {
        "pack_id": "time_series.arma_garch",
        "contract_version": "1.0",
        **_minimal_payload(),
        "analysis_goal": "balanced",
        "selection_mode": "auto",
        "arma": {
            "p": None,
            "q": None,
            "constant_mode": "auto",
            "auto_max_p": 3,
            "auto_max_q": 3,
            "auto_max_total_order": 4,
        },
        "variance": {
            "model": "auto",
            "arch_p": None,
            "garch_p": None,
            "garch_q": None,
            "auto_arch_max_p": 10,
            "include_garch_1_1": True,
        },
        "estimation_strategy": "auto",
        "innovation_distribution": "normal",
        "missing_value_policy": "block",
        "validation": {
            "method": "expanding_window_one_step",
            "validation_n": None,
            "refit_every": 1,
            "selection_repeated_during_validation": False,
        },
        "forecast": {
            "horizon": 1,
            "interval_level": 0.95,
            "lower_quantile": 0.05,
        },
        "random_seed": 0,
    }
    assert contract.to_dict() == expected
    assert contract.contract_hash == sha256_canonical(expected)

    mutable_copy = contract.to_dict()
    mutable_copy["arma"]["auto_max_p"] = 1
    assert contract.to_dict() == expected


def test_manual_orders_are_explicit_and_round_trip() -> None:
    contract_type, _ = _contract_types()
    payload = {
        **_minimal_payload(),
        "selection_mode": "manual",
        "arma": {"p": 2, "q": 1, "constant_mode": "include"},
        "variance": {
            "model": "garch",
            "garch_p": 1,
            "garch_q": 1,
        },
        "estimation_strategy": "sequential",
        "innovation_distribution": "student_t",
    }

    contract = contract_type.from_dict(payload)

    assert contract.arma.p == 2
    assert contract.arma.q == 1
    assert contract.variance.garch_p == 1
    assert contract.variance.garch_q == 1
    assert contract.to_dict()["variance"]["auto_arch_max_p"] == 10


@pytest.mark.parametrize(
    ("section", "field", "value", "expected_limit"),
    [
        ("arma", "p", 11, 10),
        ("arma", "q", 11, 10),
        ("arma", "auto_max_p", 4, 3),
        ("arma", "auto_max_q", 4, 3),
        ("variance", "arch_p", 11, 10),
        ("variance", "auto_arch_max_p", 11, 10),
        ("variance", "garch_p", 6, 5),
        ("variance", "garch_q", 6, 5),
    ],
)
def test_server_order_caps_fail_closed(
    section: str, field: str, value: int, expected_limit: int
) -> None:
    contract_type, error_type = _contract_types()
    payload = {
        **_minimal_payload(),
        "selection_mode": "manual",
        "arma": {"p": 1, "q": 0, "constant_mode": "include"},
        "variance": {"model": "arch", "arch_p": 1},
    }
    payload[section][field] = value

    with pytest.raises(error_type) as exc_info:
        contract_type.from_dict(payload)

    assert exc_info.value.code == "CANDIDATE_LIMIT_EXCEEDED"
    assert exc_info.value.evidence == {
        "field": f"{section}.{field}",
        "limit": expected_limit,
        "value": value,
    }


def test_automatic_total_order_cannot_exceed_the_approved_grid() -> None:
    contract_type, error_type = _contract_types()
    payload = {
        **_minimal_payload(),
        "arma": {"auto_max_total_order": 5},
    }

    with pytest.raises(error_type) as exc_info:
        contract_type.from_dict(payload)

    assert exc_info.value.code == "CANDIDATE_LIMIT_EXCEEDED"
    assert exc_info.value.evidence == {
        "field": "arma.auto_max_total_order",
        "limit": 4,
        "value": 5,
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"transform_confirmed": False}),
        lambda value: value.update({"selection_mode": "manual"}),
        lambda value: value.update(
            {"arma": {"p": 1, "q": None, "constant_mode": "include"}}
        ),
        lambda value: value.update(
            {"arma": {"p": 1, "q": 0, "constant_mode": "include"}}
        ),
        lambda value: value.update({"forecast": {"horizon": 2}}),
    ],
)
def test_confirmation_mode_and_horizon_constraints_fail_closed(mutate) -> None:
    contract_type, error_type = _contract_types()
    payload = _minimal_payload()
    mutate(payload)

    with pytest.raises(error_type) as exc_info:
        contract_type.from_dict(payload)

    assert exc_info.value.code == "INVALID_ORDER"


def test_joint_ma_request_returns_structured_unsupported_error() -> None:
    contract_type, error_type = _contract_types()
    payload = {
        **_minimal_payload(),
        "selection_mode": "manual",
        "arma": {"p": 1, "q": 1, "constant_mode": "include"},
        "variance": {
            "model": "garch",
            "garch_p": 1,
            "garch_q": 1,
        },
        "estimation_strategy": "joint",
    }

    with pytest.raises(error_type) as exc_info:
        contract_type.from_dict(payload)

    error = exc_info.value
    assert error.to_dict() == {
        "severity": "blocking",
        "code": "UNSUPPORTED_JOINT_ARMA_GARCH",
        "message": "v1.8 does not support joint estimation when arma.q is greater than zero",
        "evidence": {"arma_q": 1, "estimation_strategy": "joint"},
        "impact": "当前公共后端不能联合估计包含 MA 项的 ARMA-GARCH",
        "recommended_actions": [
            {
                "operation": "model.rerun",
                "patch": {"estimation_strategy": "sequential"},
            },
            {
                "operation": "model.rerun",
                "patch": {"arma": {"q": 0}, "estimation_strategy": "joint"},
            },
        ],
    }


def test_contract_rejects_unknown_fields_without_mutating_input() -> None:
    contract_type, error_type = _contract_types()
    payload = _minimal_payload()
    payload["surprise"] = True
    original = deepcopy(payload)

    with pytest.raises(error_type):
        contract_type.from_dict(payload)

    assert payload == original


def test_validation_plan_must_be_explicitly_submitted_before_freeze() -> None:
    contract_type, error_type = _contract_types()
    payload = _minimal_payload()
    del payload["validation"]

    with pytest.raises(error_type, match="missing ARMA-GARCH input field: validation"):
        contract_type.from_dict(payload)
