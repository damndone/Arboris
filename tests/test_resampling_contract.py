from __future__ import annotations

import copy
import pytest

from workbench.canonical import sha256_canonical
from workbench.contracts.model.resampling import (
    RESAMPLING_CONTRACT,
    RESAMPLING_CONTRACT_VERSION,
    ResamplingContractError,
    make_resampling_result,
    validate_resampling_result,
)


def _batch() -> dict[str, object]:
    return {
        "contract": "replicate_combine.batch",
        "contract_version": "1.0",
        "kind": "bootstrap",
        "requested_count": 5,
        "succeeded_count": 5,
        "failed_count": 0,
        "seed": 123,
        "status": "completed",
        "reason_code": "REPLICATE_COMPLETED",
        "failure_reasons": {},
        "provenance": {"provenance_commitment": "a" * 64},
        "digest": "b" * 64,
    }


def test_resampling_result_is_versioned_json_safe_and_round_trips() -> None:
    result = {"estimate": 2.5, "confidence_interval": [-1.0, 4.0]}
    digest = sha256_canonical({"batch": _batch(), "result": result})
    envelope = make_resampling_result(
        operation_id="resampling.bootstrap",
        status="completed",
        reason_code="RESAMPLING_COMPLETED",
        n_observations=12,
        result=result,
        batch=_batch(),
        evidence_digest=digest,
    )

    assert envelope["contract"] == RESAMPLING_CONTRACT
    assert envelope["contract_version"] == RESAMPLING_CONTRACT_VERSION
    validate_resampling_result(copy.deepcopy(envelope))


def test_resampling_result_rejects_unknown_top_level_fields_and_raw_values() -> None:
    envelope = make_resampling_result(
        operation_id="resampling.bootstrap",
        status="rejected",
        reason_code="RESAMPLING_INVALID_INPUT",
        n_observations=0,
        result={"message": "invalid"},
        batch=None,
        evidence_digest=None,
    )

    unknown = dict(envelope)
    unknown["replicate_values"] = [1.0]
    with pytest.raises(ResamplingContractError):
        validate_resampling_result(unknown)

    with pytest.raises(ResamplingContractError):
        make_resampling_result(
            operation_id="resampling.bootstrap",
            status="completed",
            reason_code="RESAMPLING_COMPLETED",
            n_observations=2,
            result={"replicate_values": [1.0, 2.0]},
            batch=_batch(),
            evidence_digest="c" * 64,
        )


def test_resampling_result_requires_batch_and_digest_for_completed_state() -> None:
    with pytest.raises(ResamplingContractError):
        make_resampling_result(
            operation_id="resampling.permutation",
            status="completed",
            reason_code="RESAMPLING_COMPLETED",
            n_observations=4,
            result={"p_value": 0.2},
            batch=None,
            evidence_digest=None,
        )


def test_resampling_result_rejects_a_digest_not_bound_to_its_payload() -> None:
    with pytest.raises(ResamplingContractError):
        make_resampling_result(
            operation_id="resampling.bootstrap",
            status="completed",
            reason_code="RESAMPLING_COMPLETED",
            n_observations=2,
            result={"estimate": 1.0},
            batch=_batch(),
            evidence_digest="c" * 64,
        )
