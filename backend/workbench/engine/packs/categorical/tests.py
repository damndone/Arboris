from __future__ import annotations

import json

import pytest


def test_categorical_result_contract_is_versioned_exact_and_json_safe() -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.categorical import (
        CATEGORICAL_CONTRACT,
        CATEGORICAL_CONTRACT_VERSION,
        CategoricalResultEnvelope,
    )

    envelope = CategoricalResultEnvelope(
        operation_id="categorical.cramers_v",
        result={
            "chi_square": 1.25,
            "degrees_of_freedom": 1,
            "p_value": 0.25,
            "sample_size": 20,
            "cramers_v": 0.25,
            "expected_counts": [[5.0, 5.0], [5.0, 5.0]],
            "expected_count_diagnostics": {
                "cells_below_5": 0,
                "cells_total": 4,
                "fraction_below_5": 0.0,
                "maximum": 5.0,
                "minimum": 5.0,
            },
            "method": "pearson_chi_square",
            "correction": False,
            "correction_policy": "uncorrected",
        },
    )
    value = envelope.to_dict()

    assert value == {
        "contract": CATEGORICAL_CONTRACT,
        "contract_version": CATEGORICAL_CONTRACT_VERSION,
        "operation_id": "categorical.cramers_v",
        "result": envelope.to_dict()["result"],
    }
    assert CategoricalResultEnvelope.from_dict(value) == envelope
    assert json.loads(json.dumps(value, allow_nan=False)) == value

    with pytest.raises(ContractError, match="unknown categorical result field"):
        CategoricalResultEnvelope.from_dict({**value, "extra": True})

    with pytest.raises(ContractError, match="finite"):
        CategoricalResultEnvelope(
            operation_id="categorical.cramers_v",
            result={"chi_square": float("nan")},
        )
