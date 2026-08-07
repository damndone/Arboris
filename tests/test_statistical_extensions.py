from __future__ import annotations

import json

import pandas as pd
import pytest


def test_extension_contract_declares_clustering_and_discriminant_without_agent_registration():
    from workbench.contracts.model.multivariate import (
        MULTIVARIATE_ALL_OPERATION_IDS,
        MULTIVARIATE_EXTENSION_OPERATION_IDS,
    )

    assert MULTIVARIATE_EXTENSION_OPERATION_IDS == frozenset(
        {"multivariate.clustering", "multivariate.discriminant"}
    )
    assert MULTIVARIATE_EXTENSION_OPERATION_IDS <= MULTIVARIATE_ALL_OPERATION_IDS


def _cluster_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "x": [1.0, 1.2, 0.8, 1.1, 8.0, 8.2, 7.8, 8.1],
            "y": [100.0, 102.0, 98.0, 101.0, 800.0, 802.0, 798.0, 801.0],
            "constant_scale": [10.0] * 8,
        }
    )


def test_kmeans_requires_explicit_policy_and_is_deterministic_with_bounded_assignments():
    from workbench.engine.packs.multivariate import fit_clustering

    frame = _cluster_frame()
    columns = ["x", "y"]
    first = fit_clustering(
        frame,
        columns,
        algorithm="kmeans",
        standardization="zscore_sample",
        selection="fixed",
        n_clusters=2,
        random_state=17,
        include_assignments=True,
        max_assignment_rows=3,
    )
    second = fit_clustering(
        frame,
        columns,
        algorithm="kmeans",
        standardization="zscore_sample",
        selection="fixed",
        n_clusters=2,
        random_state=17,
        include_assignments=True,
        max_assignment_rows=3,
    )

    assert first == second
    assert first["operation_id"] == "multivariate.clustering"
    assert first["status"] == "completed"
    assert first["result"]["algorithm"] == "kmeans"
    assert first["result"]["standardization"] == "zscore_sample"
    assert first["result"]["n_clusters"] == 2
    assert first["result"]["assignments_available"] is True
    assert first["result"]["assignments_row_count"] == 3
    assert first["result"]["assignments_truncated"] is True
    assert len(first["result"]["assignments"]) == 3
    assert first["result"]["iterations"] > 1


def test_kmeans_candidate_selection_returns_all_evidence_and_declared_winner():
    from workbench.engine.packs.multivariate import fit_clustering

    result = fit_clustering(
        _cluster_frame(),
        ["x", "y"],
        algorithm="kmeans",
        standardization="zscore_sample",
        selection="silhouette_candidates",
        candidate_ks=[2, 3],
        random_state=17,
    )
    payload = result["result"]

    assert payload["selection"] == "silhouette_candidates"
    assert payload["candidate_ks"] == [2, 3]
    assert [row["n_clusters"] for row in payload["candidate_metrics"]] == [2, 3]
    assert payload["selected_by"] == "maximum_silhouette_tie_break_smallest_k"
    assert payload["n_clusters"] == 2
    assert payload["assignments_available"] is False
    assert "assignments" not in payload
    json.dumps(result, allow_nan=False)


def test_hierarchical_clustering_enforces_linkage_metric_contract_and_is_repeatable():
    from workbench.engine.packs.multivariate import fit_clustering
    from workbench.engine.packs.multivariate.common import MultivariatePackError

    first = fit_clustering(
        _cluster_frame(),
        ["x", "y"],
        algorithm="hierarchical",
        standardization="none",
        selection="fixed",
        n_clusters=2,
        linkage="ward",
        metric="euclidean",
    )
    second = fit_clustering(
        _cluster_frame(),
        ["x", "y"],
        algorithm="hierarchical",
        standardization="none",
        selection="fixed",
        n_clusters=2,
        linkage="ward",
        metric="euclidean",
    )
    assert first == second
    assert first["result"]["linkage"] == "ward"
    assert first["result"]["metric"] == "euclidean"

    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_UNSUPPORTED_OPTION"):
        fit_clustering(
            _cluster_frame(),
            ["x", "y"],
            algorithm="hierarchical",
            standardization="none",
            selection="fixed",
            n_clusters=2,
            linkage="ward",
            metric="cityblock",
        )


def test_clustering_rejects_implicit_or_unsafe_numeric_choices():
    from workbench.engine.packs.multivariate import fit_clustering
    from workbench.engine.packs.multivariate.common import MultivariatePackError

    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_INVALID_OPTION"):
        fit_clustering(
            _cluster_frame(),
            ["x", "y"],
            algorithm="kmeans",
            standardization="zscore_sample",
            selection="fixed",
            n_clusters=2,
            random_state=None,
        )
    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_NUMERIC_DEGENERACY"):
        fit_clustering(
            _cluster_frame(),
            ["x", "constant_scale"],
            algorithm="kmeans",
            standardization="zscore_sample",
            selection="fixed",
            n_clusters=2,
            random_state=17,
        )
    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_INVALID_OPTION"):
        fit_clustering(
            _cluster_frame(),
            ["x", "y"],
            algorithm="kmeans",
            standardization="zscore_sample",
            selection="silhouette_candidates",
            candidate_ks=[1, 2],
            random_state=17,
        )


def _discriminant_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "x1": [0.0, 0.2, -0.1, 0.1, 4.9, 5.1, 5.2, 4.8, 0.0, 0.1, -0.2, 0.2],
            "x2": [0.1, -0.1, 0.2, 0.0, 5.0, 4.9, 5.2, 5.1, 4.8, 5.2, 5.1, 4.9],
            "target": ["A"] * 4 + ["B"] * 4 + ["C"] * 4,
        }
    )


def test_lda_and_qda_are_deterministic_and_return_bounded_holdout_evidence():
    from workbench.engine.packs.multivariate import fit_discriminant

    common = {
        "features": ["x1", "x2"],
        "target": "target",
        "prior_policy": "empirical",
        "regularization": 0.1,
        "evaluation": "holdout",
        "test_size": 0.25,
        "random_state": 11,
        "include_predictions": True,
        "max_prediction_rows": 2,
    }
    for method in ("lda", "qda"):
        first = fit_discriminant(_discriminant_frame(), method=method, **common)
        second = fit_discriminant(_discriminant_frame(), method=method, **common)
        assert first == second
        payload = first["result"]
        assert first["operation_id"] == "multivariate.discriminant"
        assert payload["method"] == method
        assert payload["class_order"] == ["A", "B", "C"]
        assert payload["evaluation"]["n_test"] == 3
        assert 0.0 <= payload["evaluation"]["accuracy"] <= 1.0
        assert payload["predictions_available"] is True
        assert payload["predictions_row_count"] == 2
        assert payload["predictions_truncated"] is True
        assert "raw_rows" not in payload
        json.dumps(first, allow_nan=False)


def test_discriminant_declared_priors_are_exact_and_validation_is_explicit():
    from workbench.engine.packs.multivariate import fit_discriminant
    from workbench.engine.packs.multivariate.common import MultivariatePackError

    result = fit_discriminant(
        _discriminant_frame(),
        features=["x1", "x2"],
        target="target",
        method="lda",
        prior_policy="declared",
        priors={"A": 0.2, "B": 0.3, "C": 0.5},
        regularization=0.1,
        evaluation="none",
    )
    assert result["result"]["prior_policy"] == "declared"
    assert result["result"]["priors"] == [
        {"class": "A", "probability": 0.2},
        {"class": "B", "probability": 0.3},
        {"class": "C", "probability": 0.5},
    ]
    assert result["result"]["evaluation"]["status"] == "not_requested"

    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_INVALID_OPTION"):
        fit_discriminant(
            _discriminant_frame(),
            features=["x1", "x2"],
            target="target",
            method="lda",
            prior_policy="declared",
            priors={"A": 0.5, "B": 0.5},
            regularization=0.1,
            evaluation="none",
        )
    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_INVALID_OPTION"):
        fit_discriminant(
            _discriminant_frame(),
            features=["x1", "x2"],
            target="target",
            method="lda",
            prior_policy="empirical",
            regularization=0.1,
            evaluation="holdout",
            test_size=0.25,
        )


def test_discriminant_singular_covariance_fails_closed_without_regularization():
    from workbench.engine.packs.multivariate import fit_discriminant
    from workbench.engine.packs.multivariate.common import MultivariatePackError

    singular = pd.DataFrame(
        {
            "x1": [0.0, 1.0, 2.0, 3.0, 5.0, 6.0, 7.0, 8.0],
            "x2": [0.0, 2.0, 4.0, 6.0, 10.0, 12.0, 14.0, 16.0],
            "target": ["A"] * 4 + ["B"] * 4,
        }
    )
    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_NUMERIC_DEGENERACY"):
        fit_discriminant(
            singular,
            features=["x1", "x2"],
            target="target",
            method="qda",
            prior_policy="empirical",
            regularization=0.0,
            evaluation="none",
        )
    regularized = fit_discriminant(
        singular,
        features=["x1", "x2"],
        target="target",
        method="qda",
        prior_policy="empirical",
        regularization=0.1,
        evaluation="none",
    )
    assert regularized["result"]["covariance_regularization"] == {
        "method": "diagonal_ridge",
        "value": 0.1,
    }
