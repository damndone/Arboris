"""Contract-first tests for the standalone nonparametric P7 pack."""

from __future__ import annotations

import json

import pytest

from workbench.contracts.common.envelope import ContractError
from workbench.contracts.model.nonparametric import (
    NONPARAMETRIC_OPERATION_IDS,
    NonparametricResultEnvelope,
)


def _scope() -> dict[str, object]:
    return {
        "estimand": "rank-based distribution location evidence",
        "input_semantics": "two finite independent numeric samples",
        "assumptions": ["observations are independent within the declared design"],
        "limitations": ["rank evidence is not a mean difference"],
        "not_claimed": ["does not establish a causal effect"],
        "unsupported_extensions": ["complex survey rank variance is not included"],
    }


def test_operation_surface_is_closed() -> None:
    assert NONPARAMETRIC_OPERATION_IDS == {
        "nonparametric.mann_whitney",
        "nonparametric.wilcoxon_signed_rank",
        "nonparametric.kruskal_wallis",
        "nonparametric.friedman",
        "nonparametric.spearman",
        "nonparametric.kendall",
        "nonparametric.robust_summary",
    }


def test_result_envelope_round_trips_and_is_json_safe() -> None:
    result = {
        "method": "mann_whitney",
        "scope": _scope(),
        "statistic": 12.0,
        "p_value": 0.05,
    }
    envelope = NonparametricResultEnvelope(
        operation_id="nonparametric.mann_whitney",
        status="completed",
        reason_code="NONPARAMETRIC_COMPLETED",
        n_observations=8,
        result=result,
    )

    payload = envelope.to_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert NonparametricResultEnvelope.from_dict(payload).to_dict() == payload


@pytest.mark.parametrize(
    "bad",
    [
        {"operation_id": "nonparametric.unknown", "status": "completed", "reason_code": "NONPARAMETRIC_COMPLETED", "n_observations": 1, "result": {"scope": _scope()}},
        {"operation_id": "nonparametric.mann_whitney", "status": "completed", "reason_code": "UNKNOWN", "n_observations": 1, "result": {"scope": _scope()}},
        {"operation_id": "nonparametric.mann_whitney", "status": "completed", "reason_code": "NONPARAMETRIC_COMPLETED", "n_observations": -1, "result": {"scope": _scope()}},
        {"operation_id": "nonparametric.mann_whitney", "status": "completed", "reason_code": "NONPARAMETRIC_COMPLETED", "n_observations": 1, "result": {"scope": _scope(), "raw_rows": [[1, 2]]}},
    ],
)
def test_result_envelope_rejects_invalid_shapes(bad: dict[str, object]) -> None:
    with pytest.raises(ContractError):
        NonparametricResultEnvelope(
            operation_id=bad["operation_id"],  # type: ignore[arg-type]
            status=bad["status"],  # type: ignore[arg-type]
            reason_code=bad["reason_code"],  # type: ignore[arg-type]
            n_observations=bad["n_observations"],  # type: ignore[arg-type]
            result=bad["result"],  # type: ignore[arg-type]
        )
