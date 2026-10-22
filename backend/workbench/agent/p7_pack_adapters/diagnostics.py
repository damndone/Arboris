"""Missing-data and regression-diagnostic pack adapters."""

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
from .base import P7PackAdapterError, Request, RequestValidator, Result, _binding, _binding_columns, _bool_option, _frame, _option, _request_parts, _require_columns, _row_matrix, _validate_declared_bindings, _values


def validate_missing_request(request: Request) -> Request:
    operation_id = _request_parts(request)[0]
    try:
        return _MISSING_REQUEST_VALIDATORS[operation_id](request)
    except KeyError as exc:
        raise P7PackAdapterError(
            f"missing-data adapter received unsupported operation: {operation_id}"
        ) from exc


def _validate_missing_profile_request(request: Request) -> Request:
    return _validate_declared_bindings(request)


def _validate_missing_rubin_pool_request(request: Request) -> Request:
    _operation_id, _bindings, options = _request_parts(request)
    if "model_results" not in options:
        raise P7PackAdapterError("missing_data.rubin_pool requires options.model_results")
    if not isinstance(options["model_results"], Sequence):
        raise P7PackAdapterError("missing_data.rubin_pool model_results must be an array")
    return _validate_declared_bindings(request)


def execute_missing(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, _bindings, options = _request_parts(request)
    try:
        return _MISSING_EXECUTORS[operation_id](source, options)
    except KeyError as exc:
        raise P7PackAdapterError(
            f"missing-data adapter received unsupported operation: {operation_id}"
        ) from exc


def _execute_missing_profile(
    source: pd.DataFrame, _options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.missing_data import profile_missingness

    return profile_missingness(source)


def _execute_missing_rubin_pool(
    _source: pd.DataFrame, options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.missing_data import rubin_pool

    model_results = cast(Sequence[Mapping[str, object]], options["model_results"])
    kwargs = {
        name: options[name]
        for name in ("alpha", "null_value", "complete_data_degrees_of_freedom")
        if name in options
    }
    return rubin_pool(model_results, **kwargs)


_MISSING_EXECUTORS: Mapping[
    str, Callable[[pd.DataFrame, Mapping[str, object]], Result]
] = MappingProxyType(
    {
        "missingness.profile": _execute_missing_profile,
        "missing_data.rubin_pool": _execute_missing_rubin_pool,
    }
)


_MISSING_REQUEST_VALIDATORS: Mapping[str, RequestValidator] = MappingProxyType(
    {
        "missingness.profile": _validate_missing_profile_request,
        "missing_data.rubin_pool": _validate_missing_rubin_pool_request,
    }
)


def validate_diagnostics_request(request: Request) -> Request:
    operation_id = _request_parts(request)[0]
    try:
        return _DIAGNOSTIC_REQUEST_VALIDATORS[operation_id](request)
    except KeyError as exc:
        raise P7PackAdapterError(
            f"diagnostics adapter received unsupported operation: {operation_id}"
        ) from exc


def _validate_diagnostics_default(request: Request) -> Request:
    return _validate_declared_bindings(request)


def _validate_diagnostics_breusch_godfrey(request: Request) -> Request:
    _operation_id, _bindings, options = _request_parts(request)
    _validate_declared_bindings(request)
    _option(options, "lag")
    _option(options, "time_order")
    return request


def _validate_diagnostics_reset(request: Request) -> Request:
    _operation_id, _bindings, options = _request_parts(request)
    _validate_declared_bindings(request)
    _option(options, "reset_powers")
    return request


def _diagnostic_design(
    source: pd.DataFrame,
    bindings: Mapping[str, object],
    options: Mapping[str, object],
) -> tuple[np.ndarray, list[str], bool, str | None, np.ndarray | None, np.ndarray | None, np.ndarray | None, dict[str, object]]:
    design_columns = _binding_columns(bindings, "design")
    intercept = _bool_option(options, "intercept", True)
    intercept_column = options.get("intercept_column", "const")
    if intercept_column is not None and type(intercept_column) is not str:
        raise P7PackAdapterError("diagnostics intercept_column must be a string or null")
    matrix = _row_matrix(source, design_columns)
    names = list(design_columns)
    if intercept:
        if intercept_column is None:
            raise P7PackAdapterError("diagnostics intercept_column is required when intercept is true")
        if intercept_column in names:
            raise P7PackAdapterError(
                "diagnostics design already contains the declared intercept column"
            )
        matrix = np.column_stack((np.ones(len(matrix)), matrix))
        names.insert(0, intercept_column)
    if "response" not in bindings:
        return matrix, names, intercept, cast(str | None, intercept_column), None, None, None, {}
    response = _values(source, _binding(bindings, "response"))
    import statsmodels.api as sm

    fitted = sm.OLS(response, matrix).fit()
    residuals = np.asarray(fitted.resid, dtype=float)
    fitted_values = np.asarray(fitted.fittedvalues, dtype=float)
    metadata = {
        "model_type": "ols",
        "parameter_count": int(fitted.df_model + 1),
        "residual_df": int(fitted.df_resid),
        "residual_variance": float(fitted.mse_resid),
        "covariance": "unadjusted",
        "parameter_names": names,
    }
    return matrix, names, intercept, cast(str | None, intercept_column), response, residuals, fitted_values, metadata


def _design_only_vif_metadata(design_columns: Sequence[str], observation_count: int) -> dict[str, object]:
    """Build the neutral metadata envelope required by the frozen VIF engine.

    VIF is a design-matrix diagnostic and does not need a response or fitted
    residuals.  The shared frozen diagnostics contract still requires OLS
    metadata, so provide only algebraic dimensions; never fabricate
    coefficients, residuals, or a model-validity claim.
    """

    parameter_count = len(design_columns)
    residual_df = observation_count - parameter_count
    if residual_df < 1:
        raise P7PackAdapterError(
            "diagnostics.vif requires more observations than design columns"
        )
    return {
        "model_type": "ols",
        "parameter_count": parameter_count,
        "residual_df": residual_df,
        "residual_variance": 0.0,
        "covariance": "unadjusted",
        "parameter_names": list(design_columns),
    }


def _diagnostics_metadata_passthrough(
    metadata: object,
    _design_columns: Sequence[str],
    _observation_count: int,
) -> object:
    return metadata


def _diagnostics_metadata_vif(
    metadata: object,
    design_columns: Sequence[str],
    observation_count: int,
) -> object:
    return (
        _design_only_vif_metadata(design_columns, observation_count)
        if not metadata
        else metadata
    )


_DIAGNOSTIC_METADATA_PREPARERS: Mapping[
    str, Callable[[object, Sequence[str], int], object]
] = MappingProxyType(
    {
        "diagnostics.vif": _diagnostics_metadata_vif,
        "diagnostics.breusch_pagan": _diagnostics_metadata_passthrough,
        "diagnostics.white": _diagnostics_metadata_passthrough,
        "diagnostics.breusch_godfrey": _diagnostics_metadata_passthrough,
        "diagnostics.reset": _diagnostics_metadata_passthrough,
        "diagnostics.influence": _diagnostics_metadata_passthrough,
    }
)


def execute_diagnostics(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    _require_columns(source, bindings)
    (
        design,
        design_columns,
        intercept,
        intercept_column,
        response,
        residuals,
        fitted_values,
        generated_metadata,
    ) = _diagnostic_design(source, bindings, options)
    metadata = _DIAGNOSTIC_METADATA_PREPARERS[operation_id](
        options.get("model_metadata", generated_metadata),
        design_columns,
        len(design),
    )
    if not isinstance(metadata, Mapping):
        raise P7PackAdapterError("diagnostics model_metadata must be an object")
    common: dict[str, object] = {
        "design_columns": design_columns,
        "intercept": intercept,
        "intercept_column": intercept_column,
        "model_metadata": dict(metadata),
    }
    try:
        return _DIAGNOSTIC_EXECUTORS[operation_id](
            response, design, residuals, fitted_values, common, options
        )
    except KeyError as exc:
        raise P7PackAdapterError(
            f"diagnostics adapter received unsupported operation: {operation_id}"
        ) from exc


def _diagnostics_fitted_inputs(
    response: np.ndarray | None,
    residuals: np.ndarray | None,
    fitted_values: np.ndarray | None,
    common: Mapping[str, object],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, object]]:
    if response is None or residuals is None or fitted_values is None:
        raise P7PackAdapterError("diagnostics operation requires a response column")
    return response, residuals, fitted_values, {**common, "fitted_values": fitted_values}


def _execute_diagnostics_vif(
    _response: np.ndarray | None,
    design: np.ndarray,
    _residuals: np.ndarray | None,
    _fitted_values: np.ndarray | None,
    common: Mapping[str, object],
    options: Mapping[str, object],
) -> Result:
    from workbench.engine.packs.model_diagnostics import run_vif

    return run_vif(
        design,
        max_output_rows=cast(int | None, options.get("max_output_rows")),
        **dict(common),
    )


def _execute_diagnostics_breusch_pagan(
    response: np.ndarray | None,
    design: np.ndarray,
    residuals: np.ndarray | None,
    fitted_values: np.ndarray | None,
    common: Mapping[str, object],
    _options: Mapping[str, object],
) -> Result:
    from workbench.engine.packs.model_diagnostics import run_breusch_pagan

    response, residuals, _fitted, common = _diagnostics_fitted_inputs(
        response, residuals, fitted_values, common
    )
    return run_breusch_pagan(response, design, residuals, **common)


def _execute_diagnostics_white(
    response: np.ndarray | None,
    design: np.ndarray,
    residuals: np.ndarray | None,
    fitted_values: np.ndarray | None,
    common: Mapping[str, object],
    _options: Mapping[str, object],
) -> Result:
    from workbench.engine.packs.model_diagnostics import run_white

    response, residuals, _fitted, common = _diagnostics_fitted_inputs(
        response, residuals, fitted_values, common
    )
    return run_white(response, design, residuals, **common)


def _execute_diagnostics_breusch_godfrey(
    response: np.ndarray | None,
    design: np.ndarray,
    residuals: np.ndarray | None,
    fitted_values: np.ndarray | None,
    common: Mapping[str, object],
    options: Mapping[str, object],
) -> Result:
    from workbench.engine.packs.model_diagnostics import run_breusch_godfrey

    response, residuals, _fitted, common = _diagnostics_fitted_inputs(
        response, residuals, fitted_values, common
    )
    return run_breusch_godfrey(
        response,
        design,
        residuals,
        lag=int(_option(options, "lag")),
        time_order=str(_option(options, "time_order")),
        **common,
    )


def _execute_diagnostics_reset(
    response: np.ndarray | None,
    design: np.ndarray,
    residuals: np.ndarray | None,
    fitted_values: np.ndarray | None,
    common: Mapping[str, object],
    options: Mapping[str, object],
) -> Result:
    from workbench.engine.packs.model_diagnostics import run_reset

    response, residuals, _fitted, common = _diagnostics_fitted_inputs(
        response, residuals, fitted_values, common
    )
    powers = _option(options, "reset_powers")
    if not isinstance(powers, Sequence) or isinstance(powers, (str, bytes)):
        raise P7PackAdapterError("diagnostics reset_powers must be an array")
    return run_reset(
        response,
        design,
        residuals,
        reset_powers=tuple(int(value) for value in powers),
        **common,
    )


def _execute_diagnostics_influence(
    response: np.ndarray | None,
    design: np.ndarray,
    residuals: np.ndarray | None,
    fitted_values: np.ndarray | None,
    common: Mapping[str, object],
    options: Mapping[str, object],
) -> Result:
    from workbench.engine.packs.model_diagnostics import run_influence

    response, residuals, _fitted, common = _diagnostics_fitted_inputs(
        response, residuals, fitted_values, common
    )
    return run_influence(
        response,
        design,
        residuals,
        max_output_rows=cast(int | None, options.get("max_output_rows")),
        **common,
    )


_DIAGNOSTIC_EXECUTORS: Mapping[
    str,
    Callable[
        [
            np.ndarray | None,
            np.ndarray,
            np.ndarray | None,
            np.ndarray | None,
            Mapping[str, object],
            Mapping[str, object],
        ],
        Result,
    ],
] = MappingProxyType(
    {
        "diagnostics.vif": _execute_diagnostics_vif,
        "diagnostics.breusch_pagan": _execute_diagnostics_breusch_pagan,
        "diagnostics.white": _execute_diagnostics_white,
        "diagnostics.breusch_godfrey": _execute_diagnostics_breusch_godfrey,
        "diagnostics.reset": _execute_diagnostics_reset,
        "diagnostics.influence": _execute_diagnostics_influence,
    }
)


_DIAGNOSTIC_REQUEST_VALIDATORS: Mapping[str, RequestValidator] = MappingProxyType(
    {
        operation_id: _validate_diagnostics_default
        for operation_id in _DIAGNOSTIC_EXECUTORS
    }
    | {
        "diagnostics.breusch_godfrey": _validate_diagnostics_breusch_godfrey,
        "diagnostics.reset": _validate_diagnostics_reset,
    }
)
