"""Shared request/result types, binding checks and option helpers for P7 pack adapters."""

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


Request: TypeAlias = Mapping[str, object]


Result: TypeAlias = Mapping[str, object]


ColumnExtractor: TypeAlias = Callable[[Request], tuple[str, ...]]


RequestValidator: TypeAlias = Callable[[Request], Request]


Executor: TypeAlias = Callable[[pd.DataFrame | None, Request], Result]


ResultValidator: TypeAlias = Callable[[Result], None]


FrameRequestValidator: TypeAlias = Callable[[pd.DataFrame | None, Request], None]


_MISSING: Final = object()


_COMMON_REQUEST_FIELDS = frozenset(
    {"operation_id", "input_mode", "column_bindings", "options"}
)


_RAW_REQUEST_KEYS = frozenset(
    {
        "raw_data",
        "raw_rows",
        "raw_values",
        "callback",
        "callable",
        "formula",
        "expression",
        "eval",
        "python",
        "shell",
        "command",
        "import_path",
        "path",
        "file_path",
        "source_path",
    }
)


class P7PackAdapterError(ValueError):
    """Raised when a typed workflow request cannot be adapted safely."""


def _request_parts(request: Request) -> tuple[str, Mapping[str, object], Mapping[str, object]]:
    if not isinstance(request, Mapping):
        raise P7PackAdapterError("P7 pack request must be an object")
    unknown = set(request) - _COMMON_REQUEST_FIELDS
    if unknown:
        raise P7PackAdapterError(
            "P7 pack request contains unknown field(s): " + ", ".join(sorted(unknown))
        )
    operation_id = request.get("operation_id")
    if type(operation_id) is not str or not operation_id:
        raise P7PackAdapterError("P7 pack request operation_id must be non-empty")
    input_mode = request.get("input_mode")
    if input_mode not in {"frame", "typed"}:
        raise P7PackAdapterError("P7 pack request input_mode must be 'frame' or 'typed'")
    bindings = request.get("column_bindings")
    if not isinstance(bindings, Mapping):
        raise P7PackAdapterError("P7 pack request column_bindings must be an object")
    options = request.get("options", {})
    if not isinstance(options, Mapping):
        raise P7PackAdapterError("P7 pack request options must be an object")
    _reject_raw_fields(request)
    return operation_id, bindings, options


def _reject_raw_fields(value: object, path: str = "request") -> None:
    """Reject executable or path-like keys at every JSON nesting level."""

    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str) and key.lower() in _RAW_REQUEST_KEYS:
                raise P7PackAdapterError(
                    f"P7 pack request contains forbidden field: {path}.{key}"
                )
            _reject_raw_fields(nested, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, nested in enumerate(value):
            _reject_raw_fields(nested, f"{path}[{index}]")


def validate_frame_request_passthrough(
    _frame: pd.DataFrame | None,
    _request: Request,
) -> None:
    """Default declaration for operations with no extra frame-shape preflight."""


def _validate_bindings(
    request: Request,
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    shapes: Mapping[str, str] | None = None,
) -> Request:
    _operation_id, bindings, _options = _request_parts(request)
    unknown = set(bindings) - required - optional
    missing = required - set(bindings)
    if unknown:
        raise P7PackAdapterError(
            "P7 pack column_bindings contains unknown field(s): "
            + ", ".join(sorted(unknown))
        )
    if missing:
        raise P7PackAdapterError(
            "P7 pack column_bindings is missing: " + ", ".join(sorted(missing))
        )
    for name, value in bindings.items():
        shape = (shapes or {}).get(name)
        if shape == "column" and type(value) is not str:
            raise P7PackAdapterError(f"P7 pack binding {name} must be one column name")
        if shape == "columns" and (
            not isinstance(value, Sequence)
            or isinstance(value, (str, bytes))
        ):
            raise P7PackAdapterError(
                f"P7 pack binding {name} must be a column-name list"
            )
        if shape == "columns" and not value:
            raise P7PackAdapterError(
                f"P7 pack binding {name} must be a non-empty column-name list"
            )
        if shape == "column_or_columns" and type(value) is not str and not (
            isinstance(value, Sequence) and not isinstance(value, (str, bytes))
        ):
            raise P7PackAdapterError(
                f"P7 pack binding {name} must be a column name or column-name list"
            )
        if type(value) is str:
            if not value:
                raise P7PackAdapterError(f"P7 pack binding {name} must not be empty")
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            values = tuple(value)
            if not values or any(type(item) is not str or not item for item in values):
                raise P7PackAdapterError(
                    f"P7 pack binding {name} must contain non-empty column names"
                )
            if len(set(values)) != len(values):
                raise P7PackAdapterError(f"P7 pack binding {name} contains duplicates")
        else:
            raise P7PackAdapterError(
                f"P7 pack binding {name} must be a column name or column-name list"
            )
    return request


def _validate_declared_bindings(request: Request) -> Request:
    """Use the registry declaration for every adapter's binding vocabulary."""

    from ..p7_pack_registry import p7_request_schema

    operation_id = request.get("operation_id")
    if type(operation_id) is not str:
        raise P7PackAdapterError("P7 pack request operation_id must be non-empty")
    schema = p7_request_schema(operation_id)
    return _validate_bindings(
        request,
        required=frozenset(schema.required_bindings),
        optional=frozenset(schema.optional_bindings),
        shapes=schema.binding_shapes,
    )


def _frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise P7PackAdapterError("P7 pack workflow execution requires a source DataFrame")
    if frame.columns.duplicated().any():
        raise P7PackAdapterError("P7 pack source DataFrame has duplicate columns")
    return frame


def _binding(bindings: Mapping[str, object], name: str) -> str:
    value = bindings.get(name)
    if type(value) is not str or not value:
        raise P7PackAdapterError(f"P7 pack binding {name} must be one column name")
    return value


def _binding_columns(bindings: Mapping[str, object], name: str) -> tuple[str, ...]:
    value = bindings.get(name)
    if isinstance(value, str):
        if not value:
            raise P7PackAdapterError(f"P7 pack binding {name} must not be empty")
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        columns = tuple(value)
        if not columns or any(type(item) is not str or not item for item in columns):
            raise P7PackAdapterError(
                f"P7 pack binding {name} must contain non-empty column names"
            )
        if len(set(columns)) != len(columns):
            raise P7PackAdapterError(f"P7 pack binding {name} contains duplicates")
        return columns
    raise P7PackAdapterError(f"P7 pack binding {name} must be a column-name list")


def _require_columns(frame: pd.DataFrame, bindings: Mapping[str, object]) -> None:
    requested: list[str] = []
    for value in bindings.values():
        if isinstance(value, str):
            requested.append(value)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            requested.extend(str(item) for item in value)
    missing = sorted(set(requested) - set(str(column) for column in frame.columns))
    if missing:
        raise P7PackAdapterError(
            "P7 pack source is missing bound column(s): " + ", ".join(missing)
        )


def _options(request: Request) -> Mapping[str, object]:
    _operation_id, _bindings, options = _request_parts(request)
    return options


def _option(options: Mapping[str, object], name: str, default: object = _MISSING) -> object:
    if name in options:
        return options[name]
    if default is not _MISSING:
        return default
    raise P7PackAdapterError(f"P7 pack policy option is required: {name}")


def _bool_option(options: Mapping[str, object], name: str, default: bool = False) -> bool:
    value = _option(options, name, default)
    if type(value) is not bool:
        raise P7PackAdapterError(f"P7 pack option {name} must be boolean")
    return value


def _columns_for_request(request: Request) -> tuple[str, ...]:
    _operation_id, bindings, _options = _request_parts(request)
    columns: list[str] = []
    for value in bindings.values():
        if isinstance(value, str):
            columns.append(value)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            columns.extend(str(item) for item in value)
    return tuple(dict.fromkeys(columns))


def _result_operation(result: Result, operation_id: str) -> None:
    if result.get("operation_id") != operation_id:
        raise P7PackAdapterError(
            f"P7 adapter {operation_id} returned {result.get('operation_id')!r}"
        )


def _validate_envelope(result: Result, operation_id: str, validator: Callable[[Mapping[str, object]], object]) -> None:
    _result_operation(result, operation_id)
    try:
        validator(result)
    except Exception as exc:
        raise P7PackAdapterError(
            f"P7 adapter {operation_id} returned an invalid result envelope: {exc}"
        ) from exc


def _validate_from_dict(cls: type[object], result: Result, operation_id: str) -> None:
    _result_operation(result, operation_id)
    try:
        from_dict = getattr(cls, "from_dict")
        from_dict(result)
    except Exception as exc:
        raise P7PackAdapterError(
            f"P7 adapter {operation_id} returned an invalid result envelope: {exc}"
        ) from exc


def _make_validator(
    validator: Callable[[Mapping[str, object]], object] | type[object],
) -> ResultValidator:
    def validate(result: Result) -> None:
        operation_id = result.get("operation_id")
        if type(operation_id) is not str:
            raise P7PackAdapterError("P7 adapter result operation_id must be a string")
        if isinstance(validator, type):
            _validate_from_dict(validator, result, operation_id)
        else:
            _validate_envelope(result, operation_id, validator)

    return validate


def _row_matrix(frame: pd.DataFrame, columns: Sequence[str]) -> np.ndarray:
    values = frame.loc[:, list(columns)].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise P7PackAdapterError("P7 pack numeric source contains non-finite values")
    return values


def _values(frame: pd.DataFrame, column: str) -> np.ndarray:
    values = frame.loc[:, column].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise P7PackAdapterError(f"P7 pack numeric source contains non-finite values: {column}")
    return values


def _mapping_options(options: Mapping[str, object], name: str) -> Mapping[str, object]:
    value = options.get(name)
    if not isinstance(value, Mapping):
        raise P7PackAdapterError(f"P7 pack option {name} must be an object")
    return value


def _no_columns(_request: Request) -> tuple[str, ...]:
    return ()


def _generic_columns(request: Request) -> tuple[str, ...]:
    return _columns_for_request(request)
