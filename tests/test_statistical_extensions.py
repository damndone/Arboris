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
