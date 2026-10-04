"""Contract-first tests for the standalone synthetic-control pack."""

from __future__ import annotations

import json

import pytest

from workbench.contracts.common.envelope import ContractError


def _solver_policy() -> dict[str, object]:
    return {
        "solver": "scipy_slsqp",
        "max_iter": 500,
        "tolerance": 1e-10,
        "constraint_tolerance": 1e-8,
    }


def _fit_input(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "operation_id": "synthetic_control.fit",
        "treated_unit": "treated",
        "donor_pool": ["d1", "d2", "d3"],
        "periods": [0, 1, 2, 3, 4, 5],
        "pre_periods": [0, 1, 2],
        "post_periods": [3, 4, 5],
        "predictor_policy": "pre_outcome_v1",
        "weight_policy": "simplex_nonnegative_v1",
        "solver_policy": _solver_policy(),
        "tolerance_policy": {
            "weight_sum": 1e-8,
            "constraint": 1e-8,
            "finite": 0.0,
        },
        "placebo_policy": None,
    }
    value.update(overrides)
    return value


def test_synthetic_control_contract_declares_closed_operations_and_round_trips() -> None:
    from workbench.contracts.model.synthetic_control import (
        SYNTHETIC_CONTROL_CONTRACT_VERSION,
        SYNTHETIC_CONTROL_OPERATION_IDS,
        SyntheticControlInput,
    )

    assert SYNTHETIC_CONTROL_CONTRACT_VERSION == "1.0"
    assert SYNTHETIC_CONTROL_OPERATION_IDS == frozenset(
        {"synthetic_control.fit", "synthetic_control.placebo"}
    )
    request = SyntheticControlInput.from_dict(_fit_input())
    assert request.to_dict() == _fit_input()
    assert json.loads(json.dumps(request.to_dict())) == _fit_input()


@pytest.mark.parametrize(
    "bad",
    [
        {**_fit_input(), "unknown": True},
        {key: value for key, value in _fit_input().items() if key != "donor_pool"},
        {**_fit_input(), "operation_id": "synthetic_control.auto"},
        {**_fit_input(), "donor_pool": ["treated", "d1"]},
        {**_fit_input(), "donor_pool": ["d1", "d1"]},
        {**_fit_input(), "periods": [0, 2, 1, 3, 4, 5]},
        {**_fit_input(), "pre_periods": [0]},
        {**_fit_input(), "post_periods": [2, 3]},
        {**_fit_input(), "weight_policy": "unconstrained"},
        {**_fit_input(), "solver_policy": {"solver": "quadprog"}},
        {**_fit_input(), "tolerance_policy": {"weight_sum": -1.0}},
    ],
)
def test_synthetic_control_contract_rejects_infeasible_or_implicit_policy(bad: dict[str, object]) -> None:
    from workbench.contracts.model.synthetic_control import SyntheticControlInput

    with pytest.raises(ContractError):
        SyntheticControlInput.from_dict(bad)


def test_placebo_contract_requires_explicit_bounded_placebo_policy() -> None:
    from workbench.contracts.model.synthetic_control import SyntheticControlInput

    value = _fit_input(
        operation_id="synthetic_control.placebo",
        placebo_policy={
            "unit_policy": "explicit",
            "placebo_units": ["d1", "d2"],
            "max_placebos": 2,
            "donor_policy": "exclude_original_treated",
            "failure_policy": "reject",
        },
    )
    request = SyntheticControlInput.from_dict(value)
    assert request.placebo_policy == value["placebo_policy"]


def test_synthetic_control_result_binds_digest_and_scope_without_raw_matrix() -> None:
    from workbench.contracts.model.synthetic_control import (
        make_synthetic_control_result,
        validate_synthetic_control_result,
    )

    scope = {
        "estimand": "post-treatment treated-minus-synthetic outcome gap",
        "input_semantics": "one treated unit, explicit donor pool, and ordered periods",
        "assumptions": ["the donor pool spans the treated unit's untreated path"],
        "limitations": ["interference and donor contamination are not tested"],
        "not_claimed": ["pre-fit quality does not prove causal identification"],
        "unsupported_extensions": ["automatic donor selection is not included"],
    }
    envelope = make_synthetic_control_result(
        operation_id="synthetic_control.fit",
        status="completed",
        reason_code="SYNTHETIC_CONTROL_COMPLETED",
        n_units=4,
        n_periods=6,
        result={"scope": scope, "weights": [{"unit": "d1", "weight": 1.0}]},
    )
    validate_synthetic_control_result(envelope)
    bad = dict(envelope)
    bad["result"] = {**envelope["result"], "raw_matrix": [[1.0]]}
    with pytest.raises(ContractError):
        validate_synthetic_control_result(bad)
