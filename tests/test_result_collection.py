"""v1.8.10 step 1d: the envelope a combinator returns.

By-group execution and multiple imputation both run one capability several
times. Their output is a collection: one member per group or imputation, each
either estimated or explicitly not estimable, and for imputation a pooled
result. Steps 5 and 7 produce these; this step fixes what they look like.
"""

from __future__ import annotations

import pytest

from workbench.contracts.model.result_collection import (
    RESULT_COLLECTION_CONTRACT,
    ResultCollectionError,
    build_result_collection,
    validate_result_collection,
)


def _members() -> list[dict]:
    return [
        {"key": "East", "status": "estimated", "nobs": 120, "result_ref": "groups/East/model_results/ols_1.json"},
        {"key": "West", "status": "estimated", "nobs": 98, "result_ref": "groups/West/model_results/ols_1.json"},
        {"key": "North", "status": "not_estimable", "nobs": 3,
         "reason": "3 rows for 4 parameters; at least 10 rows per parameter are required."},
    ]


def test_a_by_group_collection_lists_every_group_including_the_ones_it_could_not_estimate() -> None:
    collection = build_result_collection(
        combinator="by_group", capability="ols", parameters={"by": "region"}, members=_members(),
    )
    validate_result_collection(collection)
    assert collection["contract"] == RESULT_COLLECTION_CONTRACT
    assert [member["key"] for member in collection["members"]] == ["East", "West", "North"]
    assert collection["pooled"] is None


def test_an_imputation_collection_carries_its_pooled_result_and_seed() -> None:
    members = [
        {"key": str(index), "status": "estimated", "nobs": 200, "result_ref": f"imputations/{index}/ols_1.json"}
        for index in range(1, 6)
    ]
    collection = build_result_collection(
        combinator="multiple_imputation", capability="ols", parameters={"m": 5}, members=members,
        seed=20261002, pooled={"method": "rubin", "result_ref": "pooled/ols_1.json"},
    )
    validate_result_collection(collection)
    assert collection["seed"] == 20261002
    assert collection["pooled"]["method"] == "rubin"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda members: members.append(dict(members[0])),                  # duplicate key
        lambda members: members[2].pop("reason"),                           # unexplained gap
        lambda members: members[0].pop("result_ref"),                       # estimated without a result
        lambda members: members[0].update(status="maybe"),                  # unknown status
        lambda members: members[1].update(nobs=-1),                         # impossible size
    ],
)
def test_malformed_members_are_rejected(mutate) -> None:
    members = _members()
    mutate(members)
    with pytest.raises(ResultCollectionError):
        build_result_collection(combinator="by_group", capability="ols", parameters={}, members=members)


def test_a_pooled_result_must_name_its_method() -> None:
    with pytest.raises(ResultCollectionError):
        build_result_collection(
            combinator="multiple_imputation", capability="ols", parameters={"m": 2},
            members=_members()[:2], pooled={"result_ref": "pooled/ols_1.json"},
        )


def test_an_empty_collection_is_rejected() -> None:
    with pytest.raises(ResultCollectionError):
        build_result_collection(combinator="by_group", capability="ols", parameters={}, members=[])


def test_result_references_stay_inside_the_run() -> None:
    members = _members()
    members[0]["result_ref"] = "../other_run/model_results/ols_1.json"
    with pytest.raises(ResultCollectionError):
        build_result_collection(combinator="by_group", capability="ols", parameters={}, members=members)
