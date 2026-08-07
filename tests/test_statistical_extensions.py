from __future__ import annotations

import json
import shutil
import subprocess

import numpy as np
import pandas as pd
import pytest


def test_extension_contract_declares_clustering_and_discriminant_without_agent_registration():
    from workbench.contracts.model.multivariate import (
        MULTIVARIATE_ALL_OPERATION_IDS,
        MULTIVARIATE_EXTENSION_OPERATION_IDS,
    )

    assert MULTIVARIATE_EXTENSION_OPERATION_IDS == frozenset(
        {
            "multivariate.clustering",
            "multivariate.discriminant",
            "multivariate.correspondence",
            "multivariate.mca",
        }
    )
    assert MULTIVARIATE_EXTENSION_OPERATION_IDS <= MULTIVARIATE_ALL_OPERATION_IDS


def _ca_table() -> pd.DataFrame:
    return pd.DataFrame(
        [[20.0, 10.0, 10.0], [10.0, 20.0, 10.0], [10.0, 10.0, 20.0]],
        index=["row_a", "row_b", "row_c"],
        columns=["col_x", "col_y", "col_z"],
    )


def test_correspondence_analysis_returns_masses_coordinates_contributions_and_inertia():
    from workbench.engine.packs.multivariate import fit_correspondence

    result = fit_correspondence(_ca_table(), n_dimensions=2)
    payload = result["result"]
    assert result["operation_id"] == "multivariate.correspondence"
    assert payload["method"] == "ca"
    assert payload["row_labels"] == ["row_a", "row_b", "row_c"]
    assert payload["column_labels"] == ["col_x", "col_y", "col_z"]
    assert payload["row_masses"] == pytest.approx([1 / 3] * 3)
    assert payload["column_masses"] == pytest.approx([1 / 3] * 3)
    assert len(payload["singular_values"]) == 2
    assert len(payload["row_principal_coordinates"]) == 3
    assert len(payload["column_principal_coordinates"]) == 3
    assert len(payload["row_contributions"]) == 3
    assert payload["total_inertia"] > 0
    json.dumps(result, allow_nan=False)


def test_mca_constructs_deterministic_indicator_ca_without_raw_rows():
    from workbench.engine.packs.multivariate import fit_mca

    frame = pd.DataFrame(
        {
            "color": ["red", "blue", "red", "green", "blue", "green"],
            "size": ["S", "M", "L", "S", "L", "M"],
        }
    )
    first = fit_mca(frame, columns=["color", "size"], n_dimensions=2)
    second = fit_mca(frame, columns=["color", "size"], n_dimensions=2)
    assert first == second
    payload = first["result"]
    assert first["operation_id"] == "multivariate.mca"
    assert payload["method"] == "mca"
    assert payload["construction"] == "indicator_ca"
    assert payload["indicator_columns"] == [
        "color=blue",
        "color=green",
        "color=red",
        "size=L",
        "size=M",
        "size=S",
    ]
    assert payload["n_observations"] == 6
    assert "raw_rows" not in payload
    json.dumps(first, allow_nan=False)


def test_ca_mca_reject_negative_counts_missing_values_and_category_overflow():
    from workbench.engine.packs.multivariate import fit_correspondence, fit_mca
    from workbench.engine.packs.multivariate.common import MultivariatePackError

    negative = _ca_table()
    negative.loc["row_a", "col_x"] = -1.0
    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_INVALID_CATEGORY_TABLE"):
        fit_correspondence(negative, n_dimensions=2)

    missing = pd.DataFrame({"a": ["x", None, "y"], "b": ["u", "v", "v"]})
    complete_case = fit_mca(
        missing,
        columns=["a", "b"],
        n_dimensions=1,
        missing_policy="complete_case_v1",
    )
    assert complete_case["result"]["retained_positions"] == [0, 2]
    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_UNSUPPORTED_MISSING_POLICY"):
        fit_mca(missing, columns=["a", "b"], n_dimensions=1, missing_policy="reject")

    overflow = pd.DataFrame(
        {"a": [f"level_{index}" for index in range(101)], "b": ["same"] * 101}
    )
    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_CATEGORY_OVERFLOW"):
        fit_mca(overflow, columns=["a", "b"], n_dimensions=2)


def _assert_svd_columns_match_up_to_sign(actual: np.ndarray, expected: np.ndarray) -> None:
    assert actual.shape == expected.shape
    for dimension in range(actual.shape[1]):
        assert np.allclose(
            actual[:, dimension], expected[:, dimension], rtol=1e-12, atol=1e-12
        ) or np.allclose(
            actual[:, dimension], -expected[:, dimension], rtol=1e-12, atol=1e-12
        )


def test_correspondence_matches_independent_base_r_svd_oracle():
    rscript = shutil.which("Rscript")
    if rscript is None:
        pytest.skip("Rscript unavailable; external CA oracle is not installed")
    from workbench.engine.packs.multivariate import fit_correspondence

    oracle_table = pd.DataFrame(
        [[30.0, 5.0, 2.0], [8.0, 25.0, 4.0], [3.0, 7.0, 20.0]],
        index=["row_a", "row_b", "row_c"],
        columns=["col_x", "col_y", "col_z"],
    )
    script = r"""
table <- matrix(c(30, 5, 2, 8, 25, 4, 3, 7, 20), nrow=3, byrow=TRUE)
probability <- table / sum(table)
row_mass <- rowSums(probability)
column_mass <- colSums(probability)
standardized <- diag(1 / sqrt(row_mass)) %*% (probability - row_mass %o% column_mass) %*% diag(1 / sqrt(column_mass))
decomposition <- svd(standardized, nu=3, nv=3)
row_coordinates <- sweep(decomposition$u[, 1:2, drop=FALSE], 2, decomposition$d[1:2], "*")
column_coordinates <- sweep(decomposition$v[, 1:2, drop=FALSE], 2, decomposition$d[1:2], "*")
cat(paste(sprintf("%.17g", decomposition$d[1:2]), collapse=","), "\n")
cat(paste(sprintf("%.17g", as.vector(row_coordinates)), collapse=","), "\n")
cat(paste(sprintf("%.17g", as.vector(column_coordinates)), collapse=","), "\n")
"""
    completed = subprocess.run(
        [rscript, "--vanilla", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    assert len(lines) == 3
    singular_values = np.fromstring(lines[0], sep=",")
    row_coordinates = np.fromstring(lines[1], sep=",").reshape(3, 2, order="F")
    column_coordinates = np.fromstring(lines[2], sep=",").reshape(3, 2, order="F")

    result = fit_correspondence(oracle_table, n_dimensions=2)["result"]
    assert np.allclose(result["singular_values"], singular_values, rtol=1e-12, atol=1e-12)
    _assert_svd_columns_match_up_to_sign(
        np.asarray(result["row_principal_coordinates"]), row_coordinates
    )
    _assert_svd_columns_match_up_to_sign(
        np.asarray(result["column_principal_coordinates"]), column_coordinates
    )


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
