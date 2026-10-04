from __future__ import annotations

import pytest

from workbench.canonical import sha256_canonical
from workbench.contracts.model.multiple_comparisons import (
    MULTIPLE_COMPARISONS_CONTRACT,
    MULTIPLE_COMPARISONS_CONTRACT_VERSION,
    MultipleComparisonsContractError,
    make_multiple_comparisons_result,
    validate_multiple_comparisons_result,
)


def test_multiple_comparisons_contract_is_digest_bound() -> None:
    result = {"method": "scheffe", "comparisons": []}
    digest = sha256_canonical(
        {
            "operation_id": "multiple_comparisons.scheffe",
            "n_observations": 10,
            "group_names": ["a", "b"],
            "result": result,
        }
    )
    envelope = make_multiple_comparisons_result(
        operation_id="multiple_comparisons.scheffe",
        status="completed",
        reason_code="MULTIPLE_COMPARISONS_COMPLETED",
        n_observations=10,
        group_names=["a", "b"],
        result=result,
        evidence_digest=digest,
    )
    assert envelope["contract"] == MULTIPLE_COMPARISONS_CONTRACT
    assert envelope["contract_version"] == MULTIPLE_COMPARISONS_CONTRACT_VERSION
    validate_multiple_comparisons_result(envelope)


def test_multiple_comparisons_contract_rejects_raw_observations() -> None:
    with pytest.raises(MultipleComparisonsContractError):
        make_multiple_comparisons_result(
            operation_id="multiple_comparisons.scheffe",
            status="completed",
            reason_code="MULTIPLE_COMPARISONS_COMPLETED",
            n_observations=10,
            group_names=["a", "b"],
            result={"observations": [1.0]},
            evidence_digest="a" * 64,
        )
