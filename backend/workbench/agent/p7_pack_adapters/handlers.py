"""Binding each pack operation to its request validator, executor and result validator."""

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
from .base import ColumnExtractor, Executor, FrameRequestValidator, P7PackAdapterError, Request, RequestValidator, Result, ResultValidator, _generic_columns, _no_columns, validate_frame_request_passthrough
from .models import execute_treatment_effects, validate_treatment_effects_request, execute_categorical, execute_glm, execute_iv, execute_matching, execute_meta, validate_categorical_request, validate_glm_request, validate_iv_request, validate_matching_request, validate_meta_request
from .diagnostics import execute_diagnostics, execute_missing, validate_diagnostics_request, validate_missing_request
from .comparisons import execute_multiple_comparisons, execute_nonparametric, execute_repeated_measures, execute_resampling, execute_roc, validate_multiple_comparisons_request, validate_nonparametric_request, validate_repeated_measures_request, validate_resampling_request, validate_roc_request
from .multivariate import execute_multivariate, validate_multivariate_request
from .spatial_survival import execute_spatial, execute_survival, validate_spatial_request, validate_survival_request
from .synthetic_power import execute_power, execute_synthetic, validate_power_request, validate_synthetic_frame_request, validate_synthetic_request
from .time_series import execute_time_series, validate_time_series_request
from .results import _validate_treatment_effects_result, P7OperationHandler, _validate_categorical_result, _validate_diagnostics_result, _validate_glm_result, _validate_iv_result, _validate_matching_result, _validate_meta_result, _validate_missing_result, _validate_multiple_comparisons_result, _validate_multivariate_result, _validate_nonparametric_result, _validate_power_result, _validate_repeated_result, _validate_resampling_result, _validate_roc_result, _validate_spatial_result, _validate_survival_result, _validate_synthetic_result, _validate_time_series_result


def _bound_handler(
    operation_id: str,
    *,
    validate_request: RequestValidator,
    execute: Executor,
    validate_result: ResultValidator,
    validate_frame_request: FrameRequestValidator = validate_frame_request_passthrough,
) -> P7OperationHandler:
    """Bind identity once so a family cannot silently handle another operation."""

    def request_handler(request: Request) -> Request:
        if request.get("operation_id") != operation_id:
            raise P7PackAdapterError(
                f"P7 operation handler {operation_id!r} received "
                f"request operation_id={request.get('operation_id')!r}"
            )
        return validate_request(request)

    def execute_handler(frame: pd.DataFrame | None, request: Request) -> Result:
        if request.get("operation_id") != operation_id:
            raise P7PackAdapterError(
                f"P7 operation handler {operation_id!r} received "
                f"request operation_id={request.get('operation_id')!r}"
            )
        return execute(frame, request)

    def result_handler(result: Result) -> None:
        if result.get("operation_id") != operation_id:
            raise P7PackAdapterError(
                f"P7 operation handler {operation_id!r} received "
                f"result operation_id={result.get('operation_id')!r}"
            )
        validate_result(result)

    def frame_handler(frame: pd.DataFrame | None, request: Request) -> None:
        if request.get("operation_id") != operation_id:
            raise P7PackAdapterError(
                f"P7 operation handler {operation_id!r} received "
                f"request operation_id={request.get('operation_id')!r}"
            )
        validate_frame_request(frame, request)

    return P7OperationHandler(
        validate_request=request_handler,
        execute=execute_handler,
        validate_result=result_handler,
        validate_frame_request=frame_handler,
    )


def _operation_handler_map(
    operation_ids: Sequence[str],
    *,
    validate_request: RequestValidator,
    execute: Executor,
    validate_result: ResultValidator,
    validate_frame_request: FrameRequestValidator = validate_frame_request_passthrough,
) -> Mapping[str, P7OperationHandler]:
    return MappingProxyType(
        {
            operation_id: _bound_handler(
                operation_id,
                validate_request=validate_request,
                execute=execute,
                validate_result=validate_result,
                validate_frame_request=validate_frame_request,
            )
            for operation_id in operation_ids
        }
    )


_FAMILY_HANDLER_SPECS: Mapping[
    str,
    tuple[RequestValidator, Executor, ResultValidator, FrameRequestValidator],
] = {
    "categorical": (
        validate_categorical_request,
        execute_categorical,
        _validate_categorical_result,
        validate_frame_request_passthrough,
    ),
    "glm_extensions": (
        validate_glm_request,
        execute_glm,
        _validate_glm_result,
        validate_frame_request_passthrough,
    ),
    "iv_gmm": (validate_iv_request, execute_iv, _validate_iv_result, validate_frame_request_passthrough),
    "treatment_effects": (validate_treatment_effects_request, execute_treatment_effects, _validate_treatment_effects_result, validate_frame_request_passthrough),
    "matching": (validate_matching_request, execute_matching, _validate_matching_result, validate_frame_request_passthrough),
    "meta_analysis": (validate_meta_request, execute_meta, _validate_meta_result, validate_frame_request_passthrough),
    "missing_data": (validate_missing_request, execute_missing, _validate_missing_result, validate_frame_request_passthrough),
    "model_diagnostics": (validate_diagnostics_request, execute_diagnostics, _validate_diagnostics_result, validate_frame_request_passthrough),
    "multiple_comparisons": (validate_multiple_comparisons_request, execute_multiple_comparisons, _validate_multiple_comparisons_result, validate_frame_request_passthrough),
    "multivariate": (validate_multivariate_request, execute_multivariate, _validate_multivariate_result, validate_frame_request_passthrough),
    "nonparametric": (validate_nonparametric_request, execute_nonparametric, _validate_nonparametric_result, validate_frame_request_passthrough),
    "power_analysis": (validate_power_request, execute_power, _validate_power_result, validate_frame_request_passthrough),
    "repeated_measures_anova": (validate_repeated_measures_request, execute_repeated_measures, _validate_repeated_result, validate_frame_request_passthrough),
    "resampling": (validate_resampling_request, execute_resampling, _validate_resampling_result, validate_frame_request_passthrough),
    "roc_diagnostics": (validate_roc_request, execute_roc, _validate_roc_result, validate_frame_request_passthrough),
    "spatial_statistics": (validate_spatial_request, execute_spatial, _validate_spatial_result, validate_frame_request_passthrough),
    "survival_analysis": (validate_survival_request, execute_survival, _validate_survival_result, validate_frame_request_passthrough),
    "synthetic_control": (validate_synthetic_request, execute_synthetic, _validate_synthetic_result, validate_synthetic_frame_request),
    "time_series": (validate_time_series_request, execute_time_series, _validate_time_series_result, validate_frame_request_passthrough),
}


def build_p7_family_handler_maps() -> Mapping[str, Mapping[str, P7OperationHandler]]:
    """Project family handlers from the registry's live declarations."""

    from ..p7_pack_registry import P7_FAMILY_DECLARATIONS

    maps: dict[str, Mapping[str, P7OperationHandler]] = {}
    for declaration in P7_FAMILY_DECLARATIONS:
        try:
            validate_request, execute, validate_result, validate_frame_request = _FAMILY_HANDLER_SPECS[
                declaration.pack_family
            ]
        except KeyError as exc:
            raise P7PackAdapterError(
                f"P7 family has no handler specification: {declaration.pack_family!r}"
            ) from exc
        maps[declaration.pack_family] = _operation_handler_map(
            declaration.operation_ids,
            validate_request=validate_request,
            execute=execute,
            validate_result=validate_result,
            validate_frame_request=validate_frame_request,
        )
    return MappingProxyType(maps)


P7_FAMILY_HANDLER_MAPS = build_p7_family_handler_maps()


@dataclass(frozen=True)
class P7FamilyAdapter:
    """Resolve operation-specific hooks through one family-local map."""

    handlers: Mapping[str, P7OperationHandler]
    extract_columns: ColumnExtractor

    def _handler(self, operation_id: object) -> P7OperationHandler:
        if type(operation_id) is not str:
            raise P7PackAdapterError("P7 operation_id must be a string")
        try:
            return self.handlers[operation_id]
        except KeyError as exc:
            raise P7PackAdapterError(
                f"P7 family has no handler for operation: {operation_id!r}"
            ) from exc

    def validate_request(self, request: Request) -> Request:
        return self._handler(request.get("operation_id")).validate_request(request)

    def execute(self, frame: pd.DataFrame | None, request: Request) -> Result:
        return self._handler(request.get("operation_id")).execute(frame, request)

    def validate_result(self, result: Result) -> None:
        self._handler(result.get("operation_id")).validate_result(result)

    def validate_frame_request(self, frame: pd.DataFrame | None, request: Request) -> None:
        self._handler(request.get("operation_id")).validate_frame_request(frame, request)


P7_FAMILY_ADAPTERS: Mapping[str, P7FamilyAdapter] = {
    family: P7FamilyAdapter(
        handlers,
        _no_columns if family == "power_analysis" else _generic_columns,
    )
    for family, handlers in P7_FAMILY_HANDLER_MAPS.items()
}


def p7_family_adapter(pack_family: str) -> P7FamilyAdapter:
    try:
        return P7_FAMILY_ADAPTERS[pack_family]
    except KeyError as exc:
        raise P7PackAdapterError(
            f"P7 pack family has no typed adapter: {pack_family!r}"
        ) from exc


__all__ = [
    "P7FamilyAdapter",
    "P7OperationHandler",
    "P7PackAdapterError",
    "P7_FAMILY_ADAPTERS",
    "P7_FAMILY_HANDLER_MAPS",
    "p7_family_adapter",
]
