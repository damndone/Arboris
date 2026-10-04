from __future__ import annotations

import json

import pytest

from workbench.canonical import sha256_canonical
from workbench.contracts.common.envelope import ContractError
from workbench.contracts.model.spatial_statistics import (
    SPATIAL_STATISTICS_CONTRACT,
    SPATIAL_STATISTICS_CONTRACT_VERSION,
    PermutationPolicy,
    SpatialStatisticsRequest,
    SpatialWeightPolicy,
    SpatialWeightsSpec,
    make_spatial_statistics_result,
    validate_spatial_statistics_result,
)


def _weights() -> SpatialWeightsSpec:
    return SpatialWeightsSpec.from_matrix(
        [
            [0.0, 1.0, 0.0, 0.0],
            [1.0, 0.0, 1.0, 0.0],
            [0.0, 1.0, 0.0, 1.0],
            [0.0, 0.0, 1.0, 0.0],
        ]
    )


def _weight_policy(**overrides: object) -> SpatialWeightPolicy:
    values: dict[str, object] = {
        "normalization": "none",
        "symmetry_policy": "require_symmetric",
        "row_sum_policy": "require_positive",
        "zero_diagonal_policy": "require_zero",
        "islands_policy": "reject",
        "negative_weight_policy": "reject",
    }
    values.update(overrides)
    return SpatialWeightPolicy(**values)


def _permutation_policy(**overrides: object) -> PermutationPolicy:
    values: dict[str, object] = {
        "n_permutations": 99,
        "seed": 17,
        "tail": "two-sided",
        "plus_one": True,
    }
    values.update(overrides)
    return PermutationPolicy(**values)


def test_request_round_trips_only_explicit_weight_and_permutation_policies() -> None:
    request = SpatialStatisticsRequest(
        operation_id="spatial.moran_i",
        values=(1.0, 2.0, 4.0, 8.0),
        weights=_weights(),
        weight_policy=_weight_policy(),
        permutation_policy=_permutation_policy(),
    )

    payload = request.to_dict()
    assert SpatialStatisticsRequest.from_dict(payload).to_dict() == payload
    assert payload["weights"]["kind"] == "matrix"
    assert payload["weight_policy"]["normalization"] == "none"
    assert payload["permutation_policy"]["plus_one"] is True
    json.dumps(payload, allow_nan=False)


@pytest.mark.parametrize(
    "bad",
    [
        {"operation_id": "spatial.local_moran", "values": [1, 2, 3, 4]},
        {"operation_id": "spatial.moran_i", "values": [1, 2, float("nan")]},
        {"operation_id": "spatial.moran_i", "values": [True, 2, 3, 4]},
    ],
)
def test_request_rejects_unsupported_or_unsafe_vector_declarations(
    bad: dict[str, object],
) -> None:
    with pytest.raises(ContractError):
        SpatialStatisticsRequest.from_dict(
            {
                **bad,
                "weights": _weights().to_dict(),
                "weight_policy": _weight_policy().to_dict(),
                "permutation_policy": _permutation_policy().to_dict(),
            }
        )


def test_weight_spec_rejects_duplicate_edges_and_mixed_representations() -> None:
    with pytest.raises(ContractError):
        SpatialWeightsSpec.from_edges(
            3,
            [(0, 1, 1.0), (0, 1, 2.0)],
        )

    with pytest.raises(ContractError):
        SpatialWeightsSpec.from_dict(
            {
                "kind": "matrix",
                "n_nodes": 3,
                "matrix": [[0.0, 1.0, 0.0]] * 3,
                "edges": [(0, 1, 1.0)],
            }
        )


def test_result_envelope_is_versioned_and_forbids_raw_permutation_rows() -> None:
    result = {
        "statistic": "moran_i",
        "observed_statistic": 0.25,
        "expected_statistic": -1.0 / 3.0,
        "reference_semantics": "finite-population permutation expectation",
        "null_summary": {
            "n_permutations": 99,
            "successful_permutations": 99,
            "mean": -0.333,
            "standard_error": 0.1,
            "minimum": -0.9,
            "maximum": 0.4,
        },
        "permutation": {
            "seed": 17,
            "tail": "two-sided",
            "plus_one": True,
            "p_value": 0.1,
            "extreme_count": 9,
            "p_value_semantics": "monte_carlo_plus_one",
        },
        "weight_summary": {
            "n_nodes": 4,
            "n_edges": 6,
            "normalization": "none",
            "n_islands": 0,
            "n_components": 1,
        },
        "scope": {
            "estimand": "global spatial association statistic",
            "input_semantics": "finite numeric vector and explicit weight graph",
            "assumptions": ["the declared weight semantics are appropriate"],
            "limitations": ["permutation evidence is conditional on the weights"],
            "not_claimed": [
                "not a local hotspot result, causal effect, or spatial regression coefficient"
            ],
            "unsupported_extensions": [
                "local Moran, local Getis, spatial lag/error regression, learned adjacency"
            ],
        },
    }
    digest = sha256_canonical({"operation_id": "spatial.moran_i", "result": result})
    envelope = make_spatial_statistics_result(
        operation_id="spatial.moran_i",
        status="completed",
        reason_code="SPATIAL_COMPLETED",
        n_observations=4,
        n_edges=6,
        result=result,
        evidence_digest=digest,
    )

    assert envelope["contract"] == SPATIAL_STATISTICS_CONTRACT
    assert envelope["contract_version"] == SPATIAL_STATISTICS_CONTRACT_VERSION
    validate_spatial_statistics_result(envelope)
    assert "permutation_rows" not in json.dumps(envelope)

    bad = {**envelope, "result": {**result, "permutation_rows": [0.0, 1.0]}}
    with pytest.raises(ContractError):
        validate_spatial_statistics_result(bad)
