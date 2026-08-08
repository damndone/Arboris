"""Contract-first tests for the standalone matching pack."""

from __future__ import annotations

import json

import pytest

from workbench.contracts.common.envelope import ContractError


def _propensity_policy() -> dict[str, object]:
    return {
        "model": "logit",
        "solver": "newton",
        "max_iter": 200,
        "tolerance": 1e-10,
        "min_probability": 1e-6,
        "max_probability": 1.0 - 1e-6,
    }


def _matching_input(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "operation_id": "matching.att",
        "treatment_column": "treated",
        "outcome_column": "outcome",
        "covariate_columns": ["x", "z"],
        "id_column": "unit",
        "estimand": "ATT",
        "propensity_policy": _propensity_policy(),
        "distance_policy": "logit",
        "ratio": 1,
        "caliper": 0.75,
        "replacement": False,
        "tie_policy": "stable_first",
        "common_support_policy": "trim",
        "unmatched_policy": "reject",
        "balance_threshold": 0.1,
        "missing_policy": "reject",
    }
    value.update(overrides)
    return value


def test_matching_contract_declares_closed_operations_and_exact_request() -> None:
    from workbench.contracts.model.matching import (
        MATCHING_CONTRACT_VERSION,
        MATCHING_OPERATION_IDS,
        MatchingInput,
    )

    assert MATCHING_CONTRACT_VERSION == "1.0"
    assert MATCHING_OPERATION_IDS == frozenset({"matching.att", "matching.balance"})

    request = MatchingInput.from_dict(_matching_input())
    assert request.to_dict() == _matching_input()
    assert json.loads(json.dumps(request.to_dict())) == _matching_input()


@pytest.mark.parametrize(
    "bad",
    [
        {**_matching_input(), "unknown": True},
        {key: value for key, value in _matching_input().items() if key != "estimand"},
        {**_matching_input(), "operation_id": "matching.auto"},
        {**_matching_input(), "estimand": "ATE"},
        {**_matching_input(), "covariate_columns": ["x", "x"]},
        {**_matching_input(), "propensity_policy": {"model": "auto"}},
        {**_matching_input(), "ratio": 0},
        {**_matching_input(), "caliper": -1.0},
        {**_matching_input(), "replacement": "yes"},
        {**_matching_input(), "tie_policy": "arbitrary"},
        {**_matching_input(), "common_support_policy": "infer"},
        {**_matching_input(), "unmatched_policy": "infer"},
        {**_matching_input(), "balance_threshold": float("nan")},
    ],
)
def test_matching_contract_rejects_implicit_or_invalid_policies(bad: dict[str, object]) -> None:
    from workbench.contracts.model.matching import MatchingInput

    with pytest.raises(ContractError):
        MatchingInput.from_dict(bad)


def test_matching_result_requires_scope_digest_and_excludes_raw_rows() -> None:
    from workbench.contracts.model.matching import (
        MATCHING_CONTRACT,
        make_matching_result,
        validate_matching_result,
    )

    scope = {
        "estimand": "ATT among supported treated units under declared matching design",
        "input_semantics": "binary treatment, numeric outcome, and numeric covariates",
        "assumptions": ["conditional exchangeability within measured covariates"],
        "limitations": ["unmeasured confounding and model misspecification remain possible"],
        "not_claimed": ["the matched difference is not an unconditional causal claim"],
        "unsupported_extensions": ["ATE and automatic method selection are not included"],
    }
    result = {
        "scope": scope,
        "matched_treated_count": 2,
        "causal_claim_eligible": False,
    }
    envelope = make_matching_result(
        operation_id="matching.att",
        status="completed",
        reason_code="MATCHING_COMPLETED",
        n_observations=4,
        result=result,
    )
    assert envelope["contract"] == MATCHING_CONTRACT
    assert envelope["evidence_digest"]
    validate_matching_result(envelope)

    bad = dict(envelope)
    bad["result"] = {**result, "raw_rows": [{"outcome": 1.0}]}
    with pytest.raises(ContractError):
        validate_matching_result(bad)


def test_matching_balance_request_does_not_require_outcome_column() -> None:
    from workbench.contracts.model.matching import MatchingInput

    request = MatchingInput.from_dict(
        _matching_input(
            operation_id="matching.balance",
            outcome_column=None,
            estimand="covariate_balance",
        )
    )
    assert request.outcome_column is None
    assert request.to_dict()["outcome_column"] is None
