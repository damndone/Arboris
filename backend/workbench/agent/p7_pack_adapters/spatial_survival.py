"""Spatial-autocorrelation and survival pack adapters."""

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
from .base import P7PackAdapterError, Request, Result, _binding, _binding_columns, _frame, _mapping_options, _request_parts, _require_columns, _row_matrix, _validate_declared_bindings, _values


def validate_spatial_request(request: Request) -> Request:
    return _validate_declared_bindings(request)


def execute_spatial(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    _require_columns(source, bindings)
    weight_columns = _binding_columns(bindings, "weights")
    weights = _row_matrix(source, weight_columns)
    values = _values(source, _binding(bindings, "values"))
    weight_policy = _mapping_options(options, "weight_policy")
    permutation_policy = _mapping_options(options, "permutation_policy")
    kwargs = {
        "weight_policy": weight_policy,
        "permutation_policy": permutation_policy,
    }
    try:
        return _SPATIAL_EXECUTORS[operation_id](values, weights, kwargs)
    except KeyError as exc:
        raise P7PackAdapterError(
            f"spatial adapter received unsupported operation: {operation_id}"
        ) from exc


def _execute_spatial_moran(
    values: np.ndarray, weights: np.ndarray, kwargs: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.spatial_statistics import run_moran_i

    return run_moran_i(values, weights, **dict(kwargs))


def _execute_spatial_geary(
    values: np.ndarray, weights: np.ndarray, kwargs: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.spatial_statistics import run_geary_c

    return run_geary_c(values, weights, **dict(kwargs))


def _execute_spatial_getis(
    values: np.ndarray, weights: np.ndarray, kwargs: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.spatial_statistics import run_getis_ord_g

    return run_getis_ord_g(values, weights, **dict(kwargs))


_SPATIAL_EXECUTORS: Mapping[
    str, Callable[[np.ndarray, np.ndarray, Mapping[str, object]], Result]
] = MappingProxyType(
    {
        "spatial.moran_i": _execute_spatial_moran,
        "spatial.geary_c": _execute_spatial_geary,
        "spatial.getis_ord_g": _execute_spatial_getis,
    }
)


def validate_survival_request(request: Request) -> Request:
    return _validate_declared_bindings(request)


def execute_survival(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    _require_columns(source, bindings)
    from workbench.engine.packs.survival_analysis import run_survival_operation

    request_options = {
        "duration_column": _binding(bindings, "duration"),
        "event_column": _binding(bindings, "event"),
        "entry_column": (
            _binding(bindings, "entry") if bindings.get("entry") is not None else None
        ),
        "group_column": (
            _binding(bindings, "group") if bindings.get("group") is not None else None
        ),
        **dict(options),
    }
    return run_survival_operation(operation_id, source, request_options)
