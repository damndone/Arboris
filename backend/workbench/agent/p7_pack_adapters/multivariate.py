"""Multivariate pack adapters (PCA, EFA, reliability, clustering, correspondence, discriminant, MANOVA)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, TypeAlias, cast
import numpy as np
import pandas as pd
from workbench.contracts.model.categorical import CategoricalResultEnvelope
from workbench.contracts.model.glm_extensions import (
    GLMExtensionResultEnvelope,
)
from workbench.contracts.model.iv_gmm import validate_iv_gmm_result
from workbench.contracts.model.matching import validate_matching_result
from workbench.contracts.model.meta_analysis import MetaAnalysisResultEnvelope
from workbench.contracts.model.power_analysis import POWER_ANALYSIS_SOLVE_TARGETS
from workbench.contracts.model.missing_data import validate_missing_data_result
from workbench.contracts.model.model_diagnostics import ModelDiagnosticsResultEnvelope
from workbench.contracts.model.multiple_comparisons import validate_multiple_comparisons_result
from workbench.contracts.model.multivariate import MultivariateResultEnvelope
from workbench.contracts.model.nonparametric import NonparametricResultEnvelope
from workbench.contracts.model.power_analysis import PowerAnalysisResult
from workbench.contracts.model.repeated_measures_anova import (
    RepeatedMeasuresAnovaResultEnvelope,
)
from workbench.contracts.model.resampling import validate_resampling_result
from workbench.contracts.model.roc_diagnostics import RocDiagnosticsResultEnvelope
from workbench.contracts.model.spatial_statistics import validate_spatial_statistics_result
from workbench.contracts.model.survival_analysis import SurvivalAnalysisResultEnvelope
from workbench.contracts.model.synthetic_control import validate_synthetic_control_result
from workbench.contracts.model.time_series_pack import (
    TIME_SERIES_PACK_CONTRACT,
    TIME_SERIES_PACK_CONTRACT_VERSION,
    TimeSeriesResultEnvelope,
)
from .base import P7PackAdapterError, Request, RequestValidator, Result, _binding, _binding_columns, _frame, _option, _request_parts, _require_columns, _validate_declared_bindings


def validate_multivariate_request(request: Request) -> Request:
    operation_id = _request_parts(request)[0]
    try:
        return _MULTIVARIATE_REQUEST_VALIDATORS[operation_id](request)
    except KeyError as exc:
        raise P7PackAdapterError(
            f"multivariate adapter received unsupported operation: {operation_id}"
        ) from exc


def _validate_multivariate_default(request: Request) -> Request:
    return _validate_declared_bindings(request)


def _validate_multivariate_efa(request: Request) -> Request:
    _operation_id, _bindings, options = _request_parts(request)
    _validate_declared_bindings(request)
    for name in ("n_factors", "extraction", "rotation", "kmo_threshold", "bartlett_alpha"):
        _option(options, name)
    return request


def _validate_multivariate_manova(request: Request) -> Request:
    _operation_id, _bindings, options = _request_parts(request)
    _validate_declared_bindings(request)
    for name in ("interaction_terms", "intercept", "missing_policy"):
        _option(options, name)
    return request


def _validate_multivariate_discriminant(request: Request) -> Request:
    _operation_id, _bindings, options = _request_parts(request)
    _validate_declared_bindings(request)
    for name in ("method", "prior_policy", "regularization", "evaluation"):
        _option(options, name)
    return request


def execute_multivariate(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    _require_columns(source, bindings)
    try:
        return _MULTIVARIATE_EXECUTORS[operation_id](source, bindings, options)
    except KeyError as exc:
        raise P7PackAdapterError(
            f"multivariate adapter received unsupported operation: {operation_id}"
        ) from exc


def _multivariate_missing_policy(options: Mapping[str, object]) -> str:
    return str(_option(options, "missing_policy", "complete_case_v1"))


def _execute_multivariate_pca(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.multivariate import fit_pca

    return fit_pca(
        source,
        _binding_columns(bindings, "columns"),
        matrix=str(_option(options, "matrix", "correlation")),
        component_selection=str(_option(options, "component_selection", "all")),
        n_components=cast(int | None, options.get("n_components")),
        variance_threshold=cast(float | None, options.get("variance_threshold")),
        missing_policy=_multivariate_missing_policy(options),
        include_scores=bool(_option(options, "include_scores", False)),
        max_score_rows=int(_option(options, "max_score_rows", 100)),
    )


def _execute_multivariate_efa(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.multivariate import fit_efa

    return fit_efa(
        source,
        _binding_columns(bindings, "columns"),
        n_factors=int(_option(options, "n_factors")),
        extraction=str(_option(options, "extraction")),
        rotation=str(_option(options, "rotation")),
        kmo_threshold=float(_option(options, "kmo_threshold")),
        bartlett_alpha=float(_option(options, "bartlett_alpha")),
        missing_policy=_multivariate_missing_policy(options),
    )


def _execute_multivariate_cronbach(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.multivariate import cronbach_alpha

    return cronbach_alpha(
        source,
        _binding_columns(bindings, "columns"),
        reverse_scored=cast(Sequence[str] | None, options.get("reverse_scored")),
        reverse_bounds=cast(Mapping[str, Sequence[float]] | None, options.get("reverse_bounds")),
        missing_policy=_multivariate_missing_policy(options),
    )


def _execute_multivariate_clustering(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.multivariate import fit_clustering

    return fit_clustering(
        source,
        _binding_columns(bindings, "columns"),
        algorithm=str(_option(options, "algorithm")),
        standardization=str(_option(options, "standardization")),
        selection=str(_option(options, "selection")),
        n_clusters=cast(int | None, options.get("n_clusters")),
        candidate_ks=cast(Sequence[int] | None, options.get("candidate_ks")),
        random_state=cast(int | None, options.get("random_state")),
        linkage=str(_option(options, "linkage", "ward")),
        metric=str(_option(options, "metric", "euclidean")),
        max_iter=int(_option(options, "max_iter", 300)),
        tol=float(_option(options, "tol", 0.0001)),
        include_assignments=bool(_option(options, "include_assignments", False)),
        max_assignment_rows=int(_option(options, "max_assignment_rows", 500)),
        missing_policy=_multivariate_missing_policy(options),
    )


def _execute_multivariate_correspondence(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.multivariate import fit_correspondence

    table = pd.crosstab(source[_binding(bindings, "row")], source[_binding(bindings, "column")])
    return fit_correspondence(table, n_dimensions=int(_option(options, "n_dimensions", 2)))


def _execute_multivariate_mca(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.multivariate import fit_mca

    return fit_mca(
        source,
        columns=_binding_columns(bindings, "columns"),
        n_dimensions=int(_option(options, "n_dimensions", 2)),
        missing_policy=_multivariate_missing_policy(options),
    )


def _execute_multivariate_discriminant(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.multivariate import fit_discriminant

    return fit_discriminant(
        source,
        features=_binding_columns(bindings, "features"),
        target=_binding(bindings, "target"),
        method=str(_option(options, "method")),
        prior_policy=str(_option(options, "prior_policy")),
        priors=cast(Mapping[str | int, float] | None, options.get("priors")),
        regularization=float(_option(options, "regularization")),
        evaluation=str(_option(options, "evaluation")),
        test_size=cast(float | None, options.get("test_size")),
        random_state=cast(int | None, options.get("random_state")),
        include_predictions=bool(_option(options, "include_predictions", False)),
        max_prediction_rows=int(_option(options, "max_prediction_rows", 500)),
        missing_policy=_multivariate_missing_policy(options),
    )


def _execute_multivariate_manova(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.multivariate import fit_manova

    interaction_terms = _option(options, "interaction_terms")
    if not isinstance(interaction_terms, Sequence) or isinstance(interaction_terms, (str, bytes)):
        raise P7PackAdapterError("multivariate interaction_terms must be an array")
    return fit_manova(
        source,
        response_columns=_binding_columns(bindings, "responses"),
        factor_columns=_binding_columns(bindings, "factors"),
        covariate_columns=(
            _binding_columns(bindings, "covariates") if "covariates" in bindings else ()
        ),
        interaction_terms=cast(Sequence[Sequence[str]], interaction_terms),
        intercept=bool(_option(options, "intercept")),
        missing_policy=str(_option(options, "missing_policy")),
        max_retained_positions=int(_option(options, "max_retained_positions", 500)),
    )


_MULTIVARIATE_EXECUTORS: Mapping[
    str, Callable[[pd.DataFrame, Mapping[str, object], Mapping[str, object]], Result]
] = MappingProxyType(
    {
        "multivariate.pca": _execute_multivariate_pca,
        "multivariate.efa": _execute_multivariate_efa,
        "multivariate.cronbach_alpha": _execute_multivariate_cronbach,
        "multivariate.clustering": _execute_multivariate_clustering,
        "multivariate.correspondence": _execute_multivariate_correspondence,
        "multivariate.mca": _execute_multivariate_mca,
        "multivariate.discriminant": _execute_multivariate_discriminant,
        "multivariate.manova": _execute_multivariate_manova,
    }
)


_MULTIVARIATE_REQUEST_VALIDATORS: Mapping[str, RequestValidator] = MappingProxyType(
    {
        operation_id: _validate_multivariate_default
        for operation_id in _MULTIVARIATE_EXECUTORS
    }
    | {
        "multivariate.efa": _validate_multivariate_efa,
        "multivariate.manova": _validate_multivariate_manova,
        "multivariate.discriminant": _validate_multivariate_discriminant,
    }
)
