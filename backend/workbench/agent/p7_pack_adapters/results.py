"""Validators for each pack family's result envelope."""

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
from .base import Executor, FrameRequestValidator, P7PackAdapterError, RequestValidator, Result, ResultValidator, _validate_envelope, _validate_from_dict, validate_frame_request_passthrough


def _validate_categorical_result(result: Result) -> None:
    _validate_from_dict(CategoricalResultEnvelope, result, str(result.get("operation_id")))


def _validate_glm_result(result: Result) -> None:
    _validate_from_dict(GLMExtensionResultEnvelope, result, str(result.get("operation_id")))


def _validate_iv_result(result: Result) -> None:
    _validate_envelope(result, str(result.get("operation_id")), validate_iv_gmm_result)


def _validate_matching_result(result: Result) -> None:
    _validate_envelope(result, str(result.get("operation_id")), validate_matching_result)


def _validate_meta_result(result: Result) -> None:
    _validate_from_dict(MetaAnalysisResultEnvelope, result, str(result.get("operation_id")))


def _validate_missing_result(result: Result) -> None:
    _validate_envelope(result, str(result.get("operation_id")), validate_missing_data_result)


def _validate_diagnostics_result(result: Result) -> None:
    _validate_from_dict(ModelDiagnosticsResultEnvelope, result, str(result.get("operation_id")))


def _validate_multiple_comparisons_result(result: Result) -> None:
    _validate_envelope(
        result,
        str(result.get("operation_id")),
        validate_multiple_comparisons_result,
    )


def _validate_multivariate_result(result: Result) -> None:
    _validate_from_dict(MultivariateResultEnvelope, result, str(result.get("operation_id")))


def _validate_nonparametric_result(result: Result) -> None:
    _validate_from_dict(NonparametricResultEnvelope, result, str(result.get("operation_id")))


def _validate_power_result(result: Result) -> None:
    operation_id = result.get("operation_id")
    if type(operation_id) is not str:
        raise P7PackAdapterError("power adapter result operation_id must be a string")
    payload = result.get("payload")
    if not isinstance(payload, Mapping):
        raise P7PackAdapterError("power adapter result payload must be an object")
    try:
        PowerAnalysisResult.from_dict(payload)
    except Exception as exc:
        raise P7PackAdapterError(
            f"P7 adapter {operation_id} returned an invalid result envelope: {exc}"
        ) from exc


def _validate_repeated_result(result: Result) -> None:
    _validate_from_dict(
        RepeatedMeasuresAnovaResultEnvelope,
        result,
        str(result.get("operation_id")),
    )


def _validate_resampling_result(result: Result) -> None:
    _validate_envelope(result, str(result.get("operation_id")), validate_resampling_result)


def _validate_roc_result(result: Result) -> None:
    _validate_from_dict(RocDiagnosticsResultEnvelope, result, str(result.get("operation_id")))


def _validate_spatial_result(result: Result) -> None:
    _validate_envelope(
        result,
        str(result.get("operation_id")),
        validate_spatial_statistics_result,
    )


def _validate_survival_result(result: Result) -> None:
    _validate_from_dict(SurvivalAnalysisResultEnvelope, result, str(result.get("operation_id")))


def _validate_synthetic_result(result: Result) -> None:
    _validate_envelope(
        result,
        str(result.get("operation_id")),
        validate_synthetic_control_result,
    )


def _validate_time_series_result(result: Result) -> None:
    operation_id = result.get("operation_id")
    if type(operation_id) is not str:
        raise P7PackAdapterError("time-series result operation_id must be a string")
    required = {
        "contract",
        "contract_version",
        "operation_id",
        "status",
        "reason_code",
        "n_observations",
        "variables",
        "result",
    }
    if set(result) != required:
        raise P7PackAdapterError("time-series result envelope has unexpected fields")
    if result.get("contract") != TIME_SERIES_PACK_CONTRACT:
        raise P7PackAdapterError("time-series result contract is not declared")
    if result.get("contract_version") != TIME_SERIES_PACK_CONTRACT_VERSION:
        raise P7PackAdapterError("time-series result version is not declared")
    try:
        TimeSeriesResultEnvelope(
            operation_id=operation_id,
            status=cast(str, result["status"]),
            reason_code=cast(str, result["reason_code"]),
            n_observations=cast(int, result["n_observations"]),
            variables=tuple(cast(Sequence[str], result["variables"])),
            result=cast(Mapping[str, object], result["result"]),
        )
    except Exception as exc:
        raise P7PackAdapterError(
            f"P7 adapter {operation_id} returned an invalid result envelope: {exc}"
        ) from exc


@dataclass(frozen=True)
class P7OperationHandler:
    """One immutable operation-specific projection of a P7 family adapter."""

    validate_request: RequestValidator
    execute: Executor
    validate_result: ResultValidator
    validate_frame_request: FrameRequestValidator = validate_frame_request_passthrough
