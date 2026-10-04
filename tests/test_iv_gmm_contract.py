from __future__ import annotations

import pytest

from workbench.canonical import sha256_canonical
from workbench.contracts.model.iv_gmm import (
    IV_GMM_CONTRACT,
    IV_GMM_CONTRACT_VERSION,
    IVGMMContractError,
    make_iv_gmm_result,
    validate_iv_gmm_result,
)


def test_iv_gmm_result_is_digest_bound_and_versioned() -> None:
    result = {"coefficients": {"x": {"estimate": 1.5}}}
    digest = sha256_canonical(
        {
            "operation_id": "iv.gmm",
            "n_observations": 10,
            "parameter_names": ["x"],
            "result": result,
        }
    )
    envelope = make_iv_gmm_result(
        operation_id="iv.gmm",
        status="completed",
        reason_code="IV_GMM_COMPLETED",
        n_observations=10,
        parameter_names=["x"],
        result=result,
        evidence_digest=digest,
    )
    assert envelope["contract"] == IV_GMM_CONTRACT
    assert envelope["contract_version"] == IV_GMM_CONTRACT_VERSION
    validate_iv_gmm_result(envelope)


def test_iv_gmm_contract_rejects_raw_rows_and_unbound_digest() -> None:
    result = {"raw_rows": [1, 2]}
    with pytest.raises(IVGMMContractError):
        make_iv_gmm_result(
            operation_id="iv.gmm",
            status="completed",
            reason_code="IV_GMM_COMPLETED",
            n_observations=2,
            parameter_names=["x"],
            result=result,
            evidence_digest="a" * 64,
        )
    with pytest.raises(IVGMMContractError):
        make_iv_gmm_result(
            operation_id="iv.gmm",
            status="completed",
            reason_code="IV_GMM_COMPLETED",
            n_observations=2,
            parameter_names=["x"],
            result={"estimate": 1.0},
            evidence_digest="a" * 64,
        )
