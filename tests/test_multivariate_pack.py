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


def test_pca_supports_kaiser_and_cumulative_variance_selection_policies():
    from workbench.engine.packs.multivariate import fit_pca
    from workbench.engine.packs.multivariate.common import MultivariatePackError

    frame = _unequal_scale_frame()
    columns = ["small", "large", "middle"]
    kaiser = fit_pca(
        frame,
        columns,
        matrix="correlation",
        component_selection="kaiser",
    )
    cumulative = fit_pca(
        frame,
        columns,
        matrix="correlation",
        component_selection="cumulative_variance",
        variance_threshold=0.8,
    )

    assert 1 <= kaiser["result"]["n_components"] <= len(columns)
    selected = cumulative["result"]["n_components"]
    cumulative_values = cumulative["result"]["cumulative_explained_variance"]
    assert cumulative_values[selected - 1] >= 0.8
    if selected > 1:
        assert cumulative_values[selected - 2] < 0.8
    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_UNSUPPORTED_OPTION"):
        fit_pca(
            frame,
            columns,
            matrix="covariance",
            component_selection="kaiser",
        )


def _reliability_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "item_1": [1.0, 2.0, 3.0, 4.0, 5.0],
            "item_2": [2.0, 3.0, 4.0, 5.0, 6.0],
            "item_3": [1.0, 3.0, 5.0, 7.0, 9.0],
        }
    )


def test_cronbach_alpha_matches_standard_identity_and_item_diagnostics():
    from workbench.engine.packs.multivariate import cronbach_alpha

    frame = _reliability_frame()
    items = ["item_1", "item_2", "item_3"]
    result = cronbach_alpha(frame, items)
    payload = result["result"]

    item_variance_sum = frame[items].var(ddof=1).sum()
    total_variance = frame[items].sum(axis=1).var(ddof=1)
    expected_alpha = len(items) / (len(items) - 1) * (
        1.0 - item_variance_sum / total_variance
    )
    assert result["operation_id"] == "multivariate.cronbach_alpha"
    assert result["status"] == "completed"
    assert payload["item_order"] == items
    assert payload["alpha"] == pytest.approx(expected_alpha)
    assert len(payload["item_diagnostics"]) == len(items)
    for diagnostic, item in zip(payload["item_diagnostics"], items):
        rest = frame[items].sum(axis=1) - frame[item]
        expected_correlation = np.corrcoef(frame[item], rest)[0, 1]
        assert diagnostic["item"] == item
        assert diagnostic["corrected_item_total_correlation"] == pytest.approx(
            expected_correlation
        )


def test_cronbach_alpha_reports_alpha_if_deleted_and_explicit_reverse_manifest():
    from workbench.engine.packs.multivariate import cronbach_alpha

    frame = pd.DataFrame(
        {
            "q1": [1.0, 2.0, 3.0, 4.0, 5.0],
            "q2_reverse": [5.0, 4.0, 3.0, 2.0, 1.0],
            "q3": [1.0, 2.0, 3.0, 4.0, 5.0],
        }
    )
    result = cronbach_alpha(
        frame,
        ["q1", "q2_reverse", "q3"],
        reverse_scored=["q2_reverse"],
        reverse_bounds={"q2_reverse": (1.0, 5.0)},
    )
    payload = result["result"]

    assert payload["reverse_scoring"] == [
        {
            "item": "q2_reverse",
            "minimum": 1.0,
            "maximum": 5.0,
        }
    ]
    diagnostics = {row["item"]: row for row in payload["item_diagnostics"]}
    assert diagnostics["q2_reverse"]["alpha_if_deleted"] is not None
    assert payload["alpha"] == pytest.approx(1.0)


def test_cronbach_alpha_requires_bounds_and_never_infers_reverse_scoring_from_names():
    from workbench.engine.packs.multivariate import cronbach_alpha
    from workbench.engine.packs.multivariate.common import MultivariatePackError

    frame = pd.DataFrame(
        {
            "positive": [1.0, 2.0, 3.0, 4.0, 5.0],
            "reverse_worded": [5.0, 4.0, 2.0, 2.0, 1.0],
        }
    )

    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_INVALID_OPTION"):
        cronbach_alpha(frame, ["positive", "reverse_worded"], reverse_scored=["reverse_worded"])

    no_inference = cronbach_alpha(frame, ["positive", "reverse_worded"])
    assert no_inference["result"]["reverse_scoring"] == []


def _efa_frame() -> pd.DataFrame:
    rng = np.random.default_rng(20260807)
    factor_1 = rng.normal(size=120)
    factor_2 = rng.normal(size=120)
    noise = rng.normal(scale=0.25, size=(120, 6))
    return pd.DataFrame(
        {
            "v1": factor_1 + noise[:, 0],
            "v2": 0.9 * factor_1 + noise[:, 1],
            "v3": 0.8 * factor_1 + noise[:, 2],
            "v4": factor_2 + noise[:, 3],
            "v5": 0.9 * factor_2 + noise[:, 4],
            "v6": 0.8 * factor_2 + noise[:, 5],
        }
    )


def _near_identity_frame() -> pd.DataFrame:
    values = np.arange(1.0, 13.0)
    base = np.column_stack(
        [np.sin(values), np.cos(values), np.sin(2.0 * values)]
    )
    base[:, 1] += 0.05 * base[:, 0]
    base[:, 2] += 0.05 * base[:, 0]
    return pd.DataFrame(base, columns=["x1", "x2", "x3"])


def test_efa_reports_kmo_bartlett_policy_and_supports_declared_methods_and_rotations():
    from workbench.engine.packs.multivariate import fit_efa

    columns = ["v1", "v2", "v3", "v4", "v5", "v6"]
    for extraction in ("principal_axis", "maximum_likelihood"):
        for rotation in ("none", "varimax", "promax", "oblimin"):
            result = fit_efa(
                _efa_frame(),
                columns,
                n_factors=2,
                extraction=extraction,
                rotation=rotation,
                kmo_threshold=0.6,
                bartlett_alpha=0.05,
            )
            payload = result["result"]
            assert result["operation_id"] == "multivariate.efa"
            assert result["status"] == "completed"
            assert payload["n_factors"] == 2
            assert payload["extraction"] == extraction
            assert payload["rotation"] == rotation
            assert 0.0 <= payload["kmo"] <= 1.0
            assert payload["bartlett"]["p_value"] < 0.05
            assert len(payload["loadings"]) == len(columns)
            assert len(payload["loadings"][0]) == 2


def test_efa_hard_rejects_low_kmo_and_non_significant_bartlett_before_extraction():
    from workbench.engine.packs.multivariate import fit_efa
    from workbench.engine.packs.multivariate.common import MultivariatePackError

    orthogonal = pd.DataFrame(
        {
            "x1": [1.0, -1.0, 0.0, 0.0, 0.0, 0.0],
            "x2": [0.0, 0.0, 1.0, -1.0, 0.0, 0.0],
            "x3": [0.0, 0.0, 0.0, 0.0, 1.0, -1.0],
        }
    )
    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_FACTORABILITY_FAILED"):
        fit_efa(
            orthogonal,
            ["x1", "x2", "x3"],
            n_factors=1,
            extraction="principal_axis",
            rotation="none",
            kmo_threshold=0.6,
            bartlett_alpha=0.05,
        )

    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_FACTORABILITY_FAILED"):
        fit_efa(
            _near_identity_frame(),
            ["x1", "x2", "x3"],
            n_factors=1,
            extraction="principal_axis",
            rotation="none",
            kmo_threshold=0.4,
            bartlett_alpha=0.05,
        )


def test_efa_rejects_unsupported_methods_and_normalizes_signs_deterministically():
    from workbench.engine.packs.multivariate import fit_efa
    from workbench.engine.packs.multivariate.common import MultivariatePackError

    kwargs = {
        "n_factors": 2,
        "extraction": "principal_axis",
        "rotation": "none",
        "kmo_threshold": 0.6,
        "bartlett_alpha": 0.05,
    }
    first = fit_efa(_efa_frame(), ["v1", "v2", "v3", "v4", "v5", "v6"], **kwargs)
    second = fit_efa(_efa_frame(), ["v1", "v2", "v3", "v4", "v5", "v6"], **kwargs)
    assert first == second

    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_UNSUPPORTED_OPTION"):
        fit_efa(
            _efa_frame(),
            ["v1", "v2", "v3", "v4", "v5", "v6"],
            **{**kwargs, "extraction": "principal_components"},
        )
    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_UNSUPPORTED_OPTION"):
        fit_efa(
            _efa_frame(),
            ["v1", "v2", "v3", "v4", "v5", "v6"],
            **{**kwargs, "rotation": "quartimax"},
        )


def test_multivariate_surface_is_narrow_and_results_are_json_safe_and_deterministic():
    import workbench.engine.packs.multivariate as multivariate
    from workbench.canonical import canonical_json_v1
    from workbench.contracts.model.multivariate import (
        MULTIVARIATE_CONTRACT_VERSION,
        MULTIVARIATE_OPERATION_IDS,
    )

    assert set(multivariate.__all__) == {
        "cronbach_alpha",
        "fit_efa",
        "fit_pca",
        "MULTIVARIATE_CONTRACT_VERSION",
        "MULTIVARIATE_OPERATION_IDS",
        "PCA_COMPONENT_SELECTIONS",
            "PCA_MATRICES",
            "EFA_EXTRACTIONS",
            "EFA_ROTATIONS",
            "MANOVA_STATISTICS",
            "MANOVA_MAX_RETAINED_POSITIONS",
            "fit_manova",
            "CLUSTERING_ALGORITHMS",
        "CLUSTERING_LINKAGES",
        "CLUSTERING_METRICS",
        "CLUSTERING_SELECTIONS",
        "CLUSTERING_STANDARDIZATIONS",
        "fit_clustering",
        "DISCRIMINANT_EVALUATIONS",
        "DISCRIMINANT_METHODS",
            "DISCRIMINANT_PRIOR_POLICIES",
            "fit_discriminant",
            "MAX_CA_CATEGORIES",
            "MAX_CA_DIMENSIONS",
            "MCA_MISSING_POLICIES",
            "fit_correspondence",
            "fit_mca",
        }
    assert multivariate.MULTIVARIATE_CONTRACT_VERSION == MULTIVARIATE_CONTRACT_VERSION
    assert multivariate.MULTIVARIATE_OPERATION_IDS == MULTIVARIATE_OPERATION_IDS

    pca = multivariate.fit_pca(
        _unequal_scale_frame(),
        ["small", "large", "middle"],
        matrix="correlation",
        component_selection="fixed",
        n_components=2,
        include_scores=True,
        max_score_rows=2,
    )
    efa = multivariate.fit_efa(
        _efa_frame(),
        ["v1", "v2", "v3", "v4", "v5", "v6"],
        n_factors=2,
        extraction="principal_axis",
        rotation="varimax",
        kmo_threshold=0.6,
        bartlett_alpha=0.05,
    )
    alpha = multivariate.cronbach_alpha(_reliability_frame(), ["item_1", "item_2", "item_3"])

    for result in (pca, efa, alpha):
        json.dumps(result, ensure_ascii=False, allow_nan=False)
        assert canonical_json_v1(result) == canonical_json_v1(result)
    assert pca["result"]["scores_row_count"] == 2
    assert pca["result"]["scores_truncated"] is True
    assert canonical_json_v1(pca) == canonical_json_v1(
        multivariate.fit_pca(
            _unequal_scale_frame(),
            ["small", "large", "middle"],
            matrix="correlation",
            component_selection="fixed",
            n_components=2,
            include_scores=True,
            max_score_rows=2,
        )
    )
