"""Contract-first tests for the standalone matching pack.

Ported in v1.8.10 from the P7 branch (0ef1110c) and adapted to the current
contract: geometry and support distance are separate declared policies, and
common support is reject-disjoint with no trimming. The old `distance_policy`
and `trim` semantics are asserted to be rejected, not restored.
"""

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
        "matching_geometry_policy": "standardized_covariate_euclidean_v1",
        "support_distance_policy": "absolute_logit_difference",
        "ratio": 1,
        "caliper": 0.75,
        "replacement": False,
        "tie_policy": "stable_first",
        "common_support_policy": "reject_disjoint_no_trim_v1",
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
        # The P7 branch's semantics, which the current contract replaced:
        {**_matching_input(), "distance_policy": "logit"},
        {**_matching_input(), "common_support_policy": "trim"},
    ],
)
def test_matching_contract_rejects_implicit_or_invalid_policies(bad: dict[str, object]) -> None:
    from workbench.contracts.model.matching import MatchingInput

    with pytest.raises(ContractError):
        MatchingInput.from_dict(bad)


def test_matching_result_requires_scope_digest_and_excludes_raw_rows() -> None:
    """A real completed result validates; the same result carrying raw rows,
    re-digested so only the rows differ, does not."""
    from tests.test_matching_pack import _frame, _policy
    from workbench.canonical import sha256_canonical
    from workbench.contracts.model.matching import MATCHING_CONTRACT, validate_matching_result
    from workbench.engine.packs.matching import estimate_att

    envelope = estimate_att(_frame(), **_policy())
    assert envelope["contract"] == MATCHING_CONTRACT
    assert envelope["evidence_digest"]
    assert envelope["result"]["scope"]["not_claimed"]
    validate_matching_result(envelope)

    bad = dict(envelope)
    bad["result"] = {**envelope["result"], "raw_rows": [{"outcome": 1.0}]}
    bad["evidence_digest"] = sha256_canonical({"operation_id": bad["operation_id"], "result": bad["result"]})
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
