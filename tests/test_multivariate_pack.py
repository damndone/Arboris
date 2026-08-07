from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest


def test_multivariate_contract_declares_three_closed_operations_and_exact_envelope():
    from workbench.contracts.model.multivariate import (
        MULTIVARIATE_CONTRACT_VERSION,
        MULTIVARIATE_OPERATION_IDS,
        MultivariateInput,
        MultivariateResultEnvelope,
    )

    assert MULTIVARIATE_CONTRACT_VERSION == "1.0"
    assert MULTIVARIATE_OPERATION_IDS == frozenset(
        {
            "multivariate.pca",
            "multivariate.efa",
            "multivariate.cronbach_alpha",
        }
    )

    request = MultivariateInput(
        operation_id="multivariate.pca",
        columns=("x1", "x2"),
        missing_policy="complete_case_v1",
    )
    assert request.to_dict() == {
        "operation_id": "multivariate.pca",
        "columns": ["x1", "x2"],
        "missing_policy": "complete_case_v1",
    }

    envelope = MultivariateResultEnvelope(
        operation_id="multivariate.pca",
        status="completed",
        reason_code="ANALYSIS_COMPLETED",
        n_observations=3,
        columns=("x1", "x2"),
        result={"eigenvalues": [1.0, 0.5]},
    )
    assert set(envelope.to_dict()) == {
        "contract",
        "contract_version",
        "operation_id",
        "status",
        "reason_code",
        "n_observations",
        "columns",
        "result",
    }
    assert json.loads(json.dumps(envelope.to_dict()))["result"] == {
        "eigenvalues": [1.0, 0.5]
    }


def test_numeric_boundary_rejects_non_numeric_columns_without_coercion():
    from workbench.engine.packs.multivariate.common import (
        MultivariatePackError,
        prepare_numeric_frame,
    )

    frame = pd.DataFrame({"numeric": [1, 2, 3], "text": ["1", "2", "3"]})

    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_NON_NUMERIC_COLUMN"):
        prepare_numeric_frame(frame, ["numeric", "text"])


def test_numeric_boundary_rejects_fewer_than_two_columns():
    from workbench.engine.packs.multivariate.common import (
        MultivariatePackError,
        prepare_numeric_frame,
    )

    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_TOO_FEW_COLUMNS"):
        prepare_numeric_frame(pd.DataFrame({"only": [1, 2, 3]}), ["only"])


def test_numeric_boundary_rejects_infinite_values_and_unknown_missing_policy():
    from workbench.engine.packs.multivariate.common import (
        MultivariatePackError,
        prepare_numeric_frame,
    )

    frame = pd.DataFrame({"x": [1.0, np.inf], "y": [2.0, 3.0]})

    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_NON_FINITE_VALUE"):
        prepare_numeric_frame(frame, ["x", "y"])

    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_UNSUPPORTED_MISSING_POLICY"):
        prepare_numeric_frame(frame, ["x", "y"], missing_policy="drop_anywhere")


def test_numeric_boundary_selects_complete_cases_deterministically():
    from workbench.engine.packs.multivariate.common import prepare_numeric_frame

    frame = pd.DataFrame(
        {"x": [10.0, np.nan, 30.0, 40.0], "y": [1.0, 2.0, np.nan, 4.0]},
        index=[8, 3, 5, 1],
    )

    first = prepare_numeric_frame(frame, ["x", "y"])
    second = prepare_numeric_frame(frame, ["x", "y"])

    assert first.n_input_rows == 4
    assert first.n_observations == 2
    assert first.retained_positions == (0, 3)
    pd.testing.assert_frame_equal(first.frame, second.frame)
    assert first.retained_positions == second.retained_positions


def _unequal_scale_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "small": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "large": [100.0, 101.0, 99.0, 102.0, 98.0, 103.0],
            "middle": [2.0, 4.0, 1.0, 5.0, 3.0, 6.0],
        }
    )


def test_pca_requires_explicit_matrix_and_component_selection():
    from workbench.engine.packs.multivariate import fit_pca
    from workbench.engine.packs.multivariate.common import MultivariatePackError

    frame = _unequal_scale_frame()

    with pytest.raises(TypeError):
        fit_pca(frame, ["small", "large", "middle"], component_selection="all")
    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_UNSUPPORTED_OPTION"):
        fit_pca(
            frame,
            ["small", "large", "middle"],
            matrix="standardized",
            component_selection="all",
        )
    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_INVALID_OPTION"):
        fit_pca(
            frame,
            ["small", "large", "middle"],
            matrix="correlation",
            component_selection="fixed",
        )


def test_pca_correlation_and_covariance_are_explicitly_distinct_and_deterministic():
    from workbench.engine.packs.multivariate import fit_pca

    frame = _unequal_scale_frame()
    columns = ["small", "large", "middle"]
    correlation = fit_pca(
        frame,
        columns,
        matrix="correlation",
        component_selection="all",
    )
    covariance = fit_pca(
        frame,
        columns,
        matrix="covariance",
        component_selection="all",
    )

    assert correlation["operation_id"] == "multivariate.pca"
    assert correlation["status"] == "completed"
    assert correlation["result"]["matrix"] == "correlation"
    assert covariance["result"]["matrix"] == "covariance"
    assert correlation["result"]["eigenvalues"] != covariance["result"]["eigenvalues"]
    assert correlation["result"]["eigenvalues"] == sorted(
        correlation["result"]["eigenvalues"], reverse=True
    )
    assert covariance["result"]["eigenvalues"] == sorted(
        covariance["result"]["eigenvalues"], reverse=True
    )
    assert sum(correlation["result"]["explained_variance_ratio"]) == pytest.approx(1.0)
    assert sum(covariance["result"]["explained_variance_ratio"]) == pytest.approx(1.0)
    assert correlation["result"]["scores_available"] is False
    assert correlation == fit_pca(
        frame,
        columns,
        matrix="correlation",
        component_selection="all",
    )


def test_pca_normalizes_component_signs_and_validates_selection_bounds():
    from workbench.engine.packs.multivariate import fit_pca
    from workbench.engine.packs.multivariate.common import MultivariatePackError

    frame = _unequal_scale_frame()
    columns = ["small", "large", "middle"]
    first = fit_pca(
        frame,
        columns,
        matrix="correlation",
        component_selection="fixed",
        n_components=2,
    )
    second = fit_pca(
        frame,
        columns,
        matrix="correlation",
        component_selection="fixed",
        n_components=2,
    )

    assert first == second
    assert len(first["result"]["loadings"]) == 3
    assert len(first["result"]["loadings"][0]) == 2

    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_INVALID_OPTION"):
        fit_pca(
            frame,
            columns,
            matrix="correlation",
            component_selection="fixed",
            n_components=0,
        )
    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_INVALID_OPTION"):
        fit_pca(
            frame,
            columns,
            matrix="correlation",
            component_selection="fixed",
            n_components=4,
        )
    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_INVALID_OPTION"):
        fit_pca(
            frame,
            columns,
            matrix="correlation",
            component_selection="cumulative_variance",
        )
