"""Typed, fail-closed adapters for the frozen P7 statistical packs.

Workflow specs carry server-owned column bindings and an explicit policy
object.  Adapters turn those bindings into the frozen pack APIs; they never
accept Agent-supplied code, paths, callbacks, or raw replacement frames.
"""

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

    from .p7_pack_registry import p7_request_schema

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


# ── categorical counts ──────────────────────────────────────────────────


def validate_categorical_request(request: Request) -> Request:
    return _validate_declared_bindings(request)


def execute_categorical(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    _require_columns(source, bindings)
    table = pd.crosstab(source[_binding(bindings, "row")], source[_binding(bindings, "column")])
    values = table.to_numpy(dtype=int).tolist()
    try:
        return _CATEGORICAL_EXECUTORS[operation_id](values, options)
    except KeyError as exc:
        raise P7PackAdapterError(
            f"categorical adapter received unsupported operation: {operation_id}"
        ) from exc


def _execute_categorical_cramers(
    values: list[list[int]], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.categorical import fit_cramers_v

    return fit_cramers_v(values, correction=_bool_option(options, "correction"))


def _execute_categorical_mcnemar(
    values: list[list[int]], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.categorical import fit_mcnemar

    return fit_mcnemar(
        values,
        exact=_bool_option(options, "exact"),
        correction=_bool_option(options, "correction"),
    )


_CATEGORICAL_EXECUTORS: Mapping[
    str, Callable[[list[list[int]], Mapping[str, object]], Result]
] = MappingProxyType(
    {
        "categorical.cramers_v": _execute_categorical_cramers,
        "categorical.mcnemar": _execute_categorical_mcnemar,
    }
)


# ── GLM extensions ───────────────────────────────────────────────────────


def validate_glm_request(request: Request) -> Request:
    return _validate_declared_bindings(request)


def execute_glm(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    _require_columns(source, bindings)
    outcome = _binding(bindings, "outcome")
    predictors = _binding_columns(bindings, "predictors")
    y = source[outcome].to_numpy()
    design = source.loc[:, list(predictors)]
    from workbench.engine.packs.glm_extensions import run_glm_extension

    return run_glm_extension(
        operation_id,
        y,
        design,
        predictor_columns=predictors,
        **dict(options),
    )


# ── IV/GMM ───────────────────────────────────────────────────────────────


def validate_iv_request(request: Request) -> Request:
    return _validate_declared_bindings(request)


def execute_iv(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    _require_columns(source, bindings)
    y = _values(source, _binding(bindings, "outcome"))
    exog_columns = _binding_columns(bindings, "exog")
    endog_columns = _binding_columns(bindings, "endog")
    instrument_columns = _binding_columns(bindings, "instruments")
    exog = _row_matrix(source, exog_columns)
    endog = _row_matrix(source, endog_columns)
    instruments = _row_matrix(source, instrument_columns)
    names = dict(options)
    names.setdefault("exog_names", list(exog_columns))
    names.setdefault("endog_names", list(endog_columns))
    names.setdefault("instrument_names", list(instrument_columns))
    try:
        return _IV_EXECUTORS[operation_id](y, exog, endog, instruments, names)
    except KeyError as exc:
        raise P7PackAdapterError(
            f"IV adapter received unsupported operation: {operation_id}"
        ) from exc


def _execute_iv_gmm(
    y: np.ndarray,
    exog: np.ndarray,
    endog: np.ndarray,
    instruments: np.ndarray,
    names: Mapping[str, object],
) -> Result:
    from workbench.engine.packs.iv_gmm import fit_gmm

    return fit_gmm(y, exog, endog, instruments, **dict(names))


def _execute_iv_weak_instruments(
    _y: np.ndarray,
    exog: np.ndarray,
    endog: np.ndarray,
    instruments: np.ndarray,
    names: Mapping[str, object],
) -> Result:
    from workbench.engine.packs.iv_gmm import diagnose_weak_instruments

    allowed = {
        key: names[key]
        for key in ("exog_names", "endog_names", "instrument_names")
        if key in names
    }
    return diagnose_weak_instruments(exog, endog, instruments, **allowed)


_IV_EXECUTORS: Mapping[
    str,
    Callable[[np.ndarray, np.ndarray, np.ndarray, np.ndarray, Mapping[str, object]], Result],
] = MappingProxyType(
    {
        "iv.gmm": _execute_iv_gmm,
        "iv.weak_instruments": _execute_iv_weak_instruments,
    }
)


# ── matching ─────────────────────────────────────────────────────────────


def validate_matching_request(request: Request) -> Request:
    return _validate_declared_bindings(request)


def _matching_options(options: Mapping[str, object]) -> dict[str, object]:
    required = (
        "propensity_policy",
        "matching_geometry_policy",
        "support_distance_policy",
        "ratio",
        "caliper",
        "replacement",
        "tie_policy",
        "common_support_policy",
        "unmatched_policy",
        "balance_threshold",
        "missing_policy",
    )
    value = {name: _option(options, name) for name in required}
    return value


def execute_matching(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    _require_columns(source, bindings)
    try:
        return _MATCHING_EXECUTORS[operation_id](source, bindings, options)
    except KeyError as exc:
        raise P7PackAdapterError(
            f"matching adapter received unsupported operation: {operation_id}"
        ) from exc


def _execute_matching_att(
    source: pd.DataFrame,
    bindings: Mapping[str, object],
    options: Mapping[str, object],
) -> Result:
    from workbench.engine.packs.matching import estimate_att

    common = {
        "treatment_column": _binding(bindings, "treatment"),
        "outcome_column": _binding(bindings, "outcome"),
        "covariate_columns": list(_binding_columns(bindings, "covariates")),
        "id_column": _binding(bindings, "id"),
    }
    return estimate_att(source, **common, **_matching_options(options))


def _execute_matching_balance(
    source: pd.DataFrame,
    bindings: Mapping[str, object],
    options: Mapping[str, object],
) -> Result:
    from workbench.engine.packs.matching import assess_balance

    matched_pairs = options.get("matched_pairs")
    if matched_pairs is not None and not isinstance(matched_pairs, Sequence):
        raise P7PackAdapterError("matching matched_pairs must be an array")
    return assess_balance(
        source,
        treatment_column=_binding(bindings, "treatment"),
        covariate_columns=list(_binding_columns(bindings, "covariates")),
        id_column=_binding(bindings, "id"),
        matched_pairs=cast(Sequence[Mapping[str, object]] | None, matched_pairs),
        balance_threshold=_option(options, "balance_threshold"),
        missing_policy=_option(options, "missing_policy"),
    )


_MATCHING_EXECUTORS: Mapping[
    str, Callable[[pd.DataFrame, Mapping[str, object], Mapping[str, object]], Result]
] = MappingProxyType(
    {
        "matching.att": _execute_matching_att,
        "matching.balance": _execute_matching_balance,
    }
)


# ── meta analysis ────────────────────────────────────────────────────────


def validate_meta_request(request: Request) -> Request:
    return _validate_declared_bindings(request)


def _meta_studies(frame: pd.DataFrame, bindings: Mapping[str, object]) -> list[dict[str, object]]:
    _require_columns(frame, bindings)
    study = _binding(bindings, "study_id")
    effect = _binding(bindings, "effect")
    variance = _binding(bindings, "variance")
    rows: list[dict[str, object]] = []
    for index, row in frame.iterrows():
        rows.append(
            {
                "study_id": str(row[study]),
                "yi": float(row[effect]),
                "vi": float(row[variance]),
            }
        )
    return rows


def execute_meta(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    studies = _meta_studies(source, bindings)
    try:
        return _META_EXECUTORS[operation_id](studies, options)
    except KeyError as exc:
        raise P7PackAdapterError(
            f"meta adapter received unsupported operation: {operation_id}"
        ) from exc


def _execute_meta_combine(
    studies: list[dict[str, object]], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.meta_analysis import combine_effects

    return combine_effects(studies, **dict(options))


def _execute_meta_effect_size(
    studies: list[dict[str, object]], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.meta_analysis import convert_effect_size

    return convert_effect_size(studies, **dict(options))


_META_EXECUTORS: Mapping[
    str, Callable[[list[dict[str, object]], Mapping[str, object]], Result]
] = MappingProxyType(
    {
        "meta.combine": _execute_meta_combine,
        "meta.effect_size": _execute_meta_effect_size,
    }
)


# ── missing-data evidence ────────────────────────────────────────────────


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


# ── model diagnostics ────────────────────────────────────────────────────


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


# ── multiple comparisons ─────────────────────────────────────────────────


def validate_multiple_comparisons_request(request: Request) -> Request:
    return _validate_declared_bindings(request)


def _groups(source: pd.DataFrame, bindings: Mapping[str, object]) -> dict[str, list[float]]:
    group_column = _binding(bindings, "group")
    value_column = _binding(bindings, "value")
    groups: dict[str, list[float]] = {}
    for label, series in source.groupby(group_column, sort=True, dropna=False)[value_column]:
        values = series.to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise P7PackAdapterError("P7 group values contain non-finite values")
        groups[str(label)] = [float(value) for value in values]
    return groups


def execute_multiple_comparisons(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    _require_columns(source, bindings)
    groups = _groups(source, bindings)
    alpha = float(_option(options, "alpha", 0.05))
    try:
        return _MULTIPLE_COMPARISON_EXECUTORS[operation_id](groups, alpha)
    except KeyError as exc:
        raise P7PackAdapterError(
            f"multiple-comparisons adapter received unsupported operation: {operation_id}"
        ) from exc


def _execute_games_howell(
    groups: dict[str, list[float]], alpha: float
) -> Result:
    from workbench.engine.packs.multiple_comparisons import run_games_howell

    return run_games_howell(groups, alpha=alpha)


def _execute_scheffe(groups: dict[str, list[float]], alpha: float) -> Result:
    from workbench.engine.packs.multiple_comparisons import run_scheffe

    return run_scheffe(groups, alpha=alpha)


_MULTIPLE_COMPARISON_EXECUTORS: Mapping[
    str, Callable[[dict[str, list[float]], float], Result]
] = MappingProxyType(
    {
        "multiple_comparisons.games_howell": _execute_games_howell,
        "multiple_comparisons.scheffe": _execute_scheffe,
    }
)


# ── multivariate ─────────────────────────────────────────────────────────


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


# ── non-parametric inference ─────────────────────────────────────────────


def validate_nonparametric_request(request: Request) -> Request:
    operation_id = _request_parts(request)[0]
    if operation_id not in _NONPARAMETRIC_EXECUTORS:
        raise P7PackAdapterError(
            f"nonparametric adapter received unsupported operation: {operation_id}"
        )
    return _validate_declared_bindings(request)


def execute_nonparametric(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    _require_columns(source, bindings)
    try:
        return _NONPARAMETRIC_EXECUTORS[operation_id](source, bindings, options)
    except KeyError as exc:
        raise P7PackAdapterError(
            f"nonparametric adapter received unsupported operation: {operation_id}"
        ) from exc


def _execute_nonparametric_friedman(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.nonparametric import run_friedman

    columns = _binding_columns(bindings, "columns")
    values = source.loc[:, list(columns)].to_numpy(dtype=float).T.tolist()
    return run_friedman(values, **dict(options))


def _execute_nonparametric_kruskal(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.nonparametric import run_kruskal_wallis

    return run_kruskal_wallis(_groups(source, bindings), **dict(options))


def _execute_nonparametric_robust(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.nonparametric import run_robust_summary

    return run_robust_summary(_values(source, _binding(bindings, "values")), **dict(options))


def _execute_nonparametric_pair(
    source: pd.DataFrame,
    bindings: Mapping[str, object],
    options: Mapping[str, object],
    function: Callable[[np.ndarray, np.ndarray], Result],
) -> Result:
    x = _values(source, _binding(bindings, "x"))
    y = _values(source, _binding(bindings, "y"))
    return function(x, y, **dict(options))


def _execute_nonparametric_mann_whitney(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.nonparametric import run_mann_whitney

    return _execute_nonparametric_pair(source, bindings, options, run_mann_whitney)


def _execute_nonparametric_wilcoxon(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.nonparametric import run_wilcoxon_signed_rank

    return _execute_nonparametric_pair(source, bindings, options, run_wilcoxon_signed_rank)


def _execute_nonparametric_spearman(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.nonparametric import run_spearman

    return _execute_nonparametric_pair(source, bindings, options, run_spearman)


def _execute_nonparametric_kendall(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.nonparametric import run_kendall

    return _execute_nonparametric_pair(source, bindings, options, run_kendall)


_NONPARAMETRIC_EXECUTORS: Mapping[
    str, Callable[[pd.DataFrame, Mapping[str, object], Mapping[str, object]], Result]
] = MappingProxyType(
    {
        "nonparametric.friedman": _execute_nonparametric_friedman,
        "nonparametric.kruskal_wallis": _execute_nonparametric_kruskal,
        "nonparametric.robust_summary": _execute_nonparametric_robust,
        "nonparametric.mann_whitney": _execute_nonparametric_mann_whitney,
        "nonparametric.wilcoxon_signed_rank": _execute_nonparametric_wilcoxon,
        "nonparametric.spearman": _execute_nonparametric_spearman,
        "nonparametric.kendall": _execute_nonparametric_kendall,
    }
)


# ── repeated-measures ANOVA ──────────────────────────────────────────────


def validate_repeated_measures_request(request: Request) -> Request:
    return _validate_declared_bindings(request)


def execute_repeated_measures(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    _require_columns(source, bindings)
    from workbench.engine.packs.repeated_measures_anova import fit_repeated_measures_anova

    between = bindings.get("between")
    return fit_repeated_measures_anova(
        source,
        operation_id=operation_id,
        response_column=_binding(bindings, "response"),
        subject_column=_binding(bindings, "subject"),
        within_factor_columns=_binding_columns(bindings, "within"),
        between_factor_column=(
            _binding(bindings, "between") if between is not None else None
        ),
        correction=str(_option(options, "correction", "none")),
    )


# ── resampling ──────────────────────────────────────────────────────────


def validate_resampling_request(request: Request) -> Request:
    operation_id = _request_parts(request)[0]
    if operation_id not in _RESAMPLING_EXECUTORS:
        raise P7PackAdapterError(
            f"resampling adapter received unsupported operation: {operation_id}"
        )
    return _validate_declared_bindings(request)


def execute_resampling(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    _require_columns(source, bindings)
    try:
        return _RESAMPLING_EXECUTORS[operation_id](source, bindings, options)
    except KeyError as exc:
        raise P7PackAdapterError(
            f"resampling adapter received unsupported operation: {operation_id}"
        ) from exc


def _execute_resampling_bootstrap(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.resampling import run_bootstrap

    return run_bootstrap(_values(source, _binding(bindings, "values")), **dict(options))


def _execute_resampling_permutation(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.resampling import run_permutation

    return run_permutation(
        _values(source, _binding(bindings, "left")),
        _values(source, _binding(bindings, "right")),
        **dict(options),
    )


_RESAMPLING_EXECUTORS: Mapping[
    str,
    Callable[[pd.DataFrame, Mapping[str, object], Mapping[str, object]], Result],
] = MappingProxyType(
    {
        "resampling.bootstrap": _execute_resampling_bootstrap,
        "resampling.permutation": _execute_resampling_permutation,
    }
)


# ── ROC diagnostics ──────────────────────────────────────────────────────


def validate_roc_request(request: Request) -> Request:
    return _validate_declared_bindings(request)


def execute_roc(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    _require_columns(source, bindings)
    from workbench.engine.packs.roc_diagnostics import run_roc_diagnostics

    positive_label = _option(options, "positive_label")
    kwargs = {
        key: options[key]
        for key in (
            "score_semantics",
            "threshold_policy",
            "quantile_grid_size",
            "max_thresholds",
            "missing_policy",
            "constraint_policy",
            "cost_policy",
            "calibration_method",
            "n_bins",
            "max_bins",
        )
        if key in options
    }
    return run_roc_diagnostics(
        operation_id,
        source[_binding(bindings, "truth")].to_numpy(),
        _values(source, _binding(bindings, "scores")),
        positive_label=positive_label,
        **kwargs,
    )


# ── global spatial statistics ────────────────────────────────────────────


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


# ── survival analysis ────────────────────────────────────────────────────


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


# ── synthetic control ────────────────────────────────────────────────────


def validate_synthetic_request(request: Request) -> Request:
    operation_id = _request_parts(request)[0]
    try:
        return _SYNTHETIC_REQUEST_VALIDATORS[operation_id](request)
    except KeyError as exc:
        raise P7PackAdapterError(
            f"synthetic-control adapter received unsupported operation: {operation_id}"
        ) from exc


def _validate_synthetic_common(request: Request) -> tuple[Mapping[str, object], Request]:
    _operation_id, _bindings, options = _request_parts(request)
    _validate_declared_bindings(request)
    for name in ("treated_unit", "donor_pool", "periods", "pre_periods", "post_periods"):
        _option(options, name)
    return options, request


def _validate_synthetic_fit_request(request: Request) -> Request:
    _options, normalized = _validate_synthetic_common(request)
    return normalized


def _validate_synthetic_placebo_request(request: Request) -> Request:
    options, normalized = _validate_synthetic_common(request)
    policy = _mapping_options(options, "placebo_policy")
    required_policy_fields = {
        "unit_policy",
        "placebo_units",
        "max_placebos",
        "donor_policy",
        "failure_policy",
    }
    placebo_units = policy.get("placebo_units")
    donor_pool = options.get("donor_pool")
    treated_unit = options.get("treated_unit")
    max_placebos = policy.get("max_placebos")
    if (
        set(policy) != required_policy_fields
        or policy.get("unit_policy") != "explicit"
        or policy.get("donor_policy") != "exclude_original_treated"
        or policy.get("failure_policy") != "reject"
        or not isinstance(placebo_units, Sequence)
        or isinstance(placebo_units, (str, bytes))
        or not isinstance(donor_pool, Sequence)
        or isinstance(donor_pool, (str, bytes))
        or type(max_placebos) is not int
        or max_placebos < len(placebo_units)
        or any(type(unit) is not str or not unit for unit in placebo_units)
        or any(type(unit) is not str or not unit for unit in donor_pool)
        or treated_unit in placebo_units
        or len(set(placebo_units)) != len(placebo_units)
        or any(unit not in donor_pool for unit in placebo_units)
    ):
        raise P7PackAdapterError(
            "SYNTHETIC_CONTROL_INVALID_PLACEBO_POLICY: "
            "placebo_policy must be explicit, closed, and bounded to unique donors"
        )
    return normalized


def validate_synthetic_frame_request(
    frame: pd.DataFrame | None,
    request: Request,
) -> None:
    """Reject a period vector that cannot index the immutable source rows."""

    source = _frame(frame)
    _operation_id, _bindings, options = _request_parts(request)
    periods = _option(options, "periods")
    if not isinstance(periods, Sequence) or isinstance(periods, (str, bytes)):
        raise P7PackAdapterError(
            "SYNTHETIC_CONTROL_INVALID_PERIODS: periods must be an array"
        )
    if len(periods) != len(source):
        raise P7PackAdapterError(
            "SYNTHETIC_CONTROL_PERIOD_COUNT_MISMATCH: "
            f"periods has {len(periods)} values but the source has {len(source)} rows"
        )


def execute_synthetic(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    _require_columns(source, bindings)
    outcome_columns = _binding_columns(bindings, "outcomes")
    outcomes = source.loc[:, list(outcome_columns)].to_numpy(dtype=float).T
    unit_labels = list(outcome_columns)
    predictors = None
    if "predictors" in bindings:
        predictors = source.loc[:, list(_binding_columns(bindings, "predictors"))].to_numpy(dtype=float)
    common = {
        "outcome_matrix": outcomes,
        "treated_unit": str(_option(options, "treated_unit")),
        "donor_pool": list(cast(Sequence[str], _option(options, "donor_pool"))),
        "unit_labels": unit_labels,
        "periods": list(cast(Sequence[int | float], _option(options, "periods"))),
        "pre_periods": list(cast(Sequence[int | float], _option(options, "pre_periods"))),
        "post_periods": list(cast(Sequence[int | float], _option(options, "post_periods"))),
        "predictor_matrix": predictors,
        "solver_policy": cast(Mapping[str, object] | None, options.get("solver_policy")),
        "tolerance_policy": cast(Mapping[str, object] | None, options.get("tolerance_policy")),
    }
    try:
        return _SYNTHETIC_EXECUTORS[operation_id](common, options)
    except KeyError as exc:
        raise P7PackAdapterError(
            f"synthetic-control adapter received unsupported operation: {operation_id}"
        ) from exc


def _execute_synthetic_fit(
    common: Mapping[str, object], _options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.synthetic_control import fit_synthetic_control

    return fit_synthetic_control(**dict(common))


def _execute_synthetic_placebo(
    common: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.synthetic_control import run_placebo

    return run_placebo(
        **dict(common),
        placebo_policy=cast(Mapping[str, object], _mapping_options(options, "placebo_policy")),
    )


_SYNTHETIC_EXECUTORS: Mapping[
    str, Callable[[Mapping[str, object], Mapping[str, object]], Result]
] = MappingProxyType(
    {
        "synthetic_control.fit": _execute_synthetic_fit,
        "synthetic_control.placebo": _execute_synthetic_placebo,
    }
)

_SYNTHETIC_REQUEST_VALIDATORS: Mapping[str, RequestValidator] = MappingProxyType(
    {
        "synthetic_control.fit": _validate_synthetic_fit_request,
        "synthetic_control.placebo": _validate_synthetic_placebo_request,
    }
)


# ── power analysis ───────────────────────────────────────────────────────


def validate_power_request(request: Request) -> Request:
    operation_id = _request_parts(request)[0]
    try:
        return _POWER_REQUEST_VALIDATORS[operation_id](request)
    except KeyError as exc:
        raise P7PackAdapterError(
            f"power adapter received unsupported operation: {operation_id}"
        ) from exc


def _validate_power_common(request: Request) -> tuple[Mapping[str, object], Request]:
    _operation_id, _bindings, options = _request_parts(request)
    for name in ("design", "solve_for"):
        _option(options, name)
    return options, _validate_declared_bindings(request)


def _validate_power_solve_request(request: Request) -> Request:
    _options, normalized = _validate_power_common(request)
    return normalized


def _validate_power_sensitivity_request(request: Request) -> Request:
    options, normalized = _validate_power_common(request)
    _option(options, "axes")
    return normalized


def _power_parameters(options: Mapping[str, object]) -> dict[str, object]:
    design = str(_option(options, "design"))
    if design == "independent_t":
        values: dict[str, object] = {
            "effect_size_type": "cohens_d",
            "alpha": 0.05,
            "power": 0.8,
            "sample_size": 40.0,
            "effect_size": 0.5,
            "ratio": 1.0,
            "alternative": "two-sided",
            "k_groups": None,
        }
    elif design == "one_way_anova":
        values = {
            "effect_size_type": "cohens_f",
            "alpha": 0.05,
            "power": 0.8,
            "sample_size": 90.0,
            "effect_size": 0.25,
            "ratio": None,
            "alternative": None,
            "k_groups": 4,
        }
    elif design == "two_proportion_z":
        values = {
            "effect_size_type": "cohens_h",
            "alpha": 0.05,
            "power": 0.8,
            "sample_size": 40.0,
            "effect_size": 0.5,
            "ratio": 1.0,
            "alternative": "two-sided",
            "k_groups": None,
        }
    else:
        raise P7PackAdapterError(f"power design is not declared: {design}")
    values.update(
        {
            key: value
            for key, value in options.items()
            if key not in {"axes", "sensitivity_grid"}
        }
    )
    solve_for = str(_option(options, "solve_for"))
    if solve_for not in {"power", "sample_size", "effect_size", "alpha"}:
        raise P7PackAdapterError(f"power solve_for is not declared: {solve_for}")
    values["design"] = design
    values["solve_for"] = solve_for
    values[solve_for] = None
    return values


def execute_power(frame: pd.DataFrame | None, request: Request) -> Result:
    operation_id, _bindings, options = _request_parts(request)
    params = _power_parameters(options)
    try:
        payload = _POWER_EXECUTORS[operation_id](params, options)
    except KeyError as exc:
        raise P7PackAdapterError(
            f"power adapter received unsupported operation: {operation_id}"
        ) from exc
    # The frozen power contract predates the workflow operation envelope and
    # therefore has no operation_id field.  Keep that contract byte-for-byte
    # intact and add a small adapter envelope so the generic registry can
    # still validate identity without inventing a field inside the result.
    return {"operation_id": operation_id, "payload": payload}


def _execute_power_solve(
    params: Mapping[str, object], options: Mapping[str, object]
) -> Mapping[str, object]:
    from workbench.engine.packs.power_analysis import solve_power

    sensitivity_grid = options.get("sensitivity_grid")
    return solve_power(
        **dict(params),
        sensitivity_grid=cast(Mapping[str, Sequence[object]] | None, sensitivity_grid),
    )


def _execute_power_grid(
    params: Mapping[str, object], options: Mapping[str, object]
) -> Mapping[str, object]:
    from workbench.engine.packs.power_analysis import solve_power_grid

    axes = _option(options, "axes")
    if not isinstance(axes, Mapping):
        raise P7PackAdapterError("power sensitivity-grid axes must be an object")
    return solve_power_grid(
        axes=cast(Mapping[str, Sequence[object]], axes),
        **dict(params),
    )


_POWER_EXECUTORS: Mapping[
    str, Callable[[Mapping[str, object], Mapping[str, object]], Mapping[str, object]]
] = MappingProxyType(
    {
        "power_analysis.solve": _execute_power_solve,
        "power_analysis.sensitivity_grid": _execute_power_grid,
    }
)

_POWER_REQUEST_VALIDATORS: Mapping[str, RequestValidator] = MappingProxyType(
    {
        "power_analysis.solve": _validate_power_solve_request,
        "power_analysis.sensitivity_grid": _validate_power_sensitivity_request,
    }
)


# ── time-series pack ─────────────────────────────────────────────────────


def validate_time_series_request(request: Request) -> Request:
    _operation_id, _bindings, options = _request_parts(request)
    _validate_declared_bindings(request)
    _option(options, "time_order")
    return request


def execute_time_series(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    _require_columns(source, bindings)
    try:
        return _TIME_SERIES_EXECUTORS[operation_id](source, bindings, options)
    except KeyError as exc:
        raise P7PackAdapterError(
            f"time-series adapter received unsupported operation: {operation_id}"
        ) from exc


def _time_columns(
    bindings: Mapping[str, object], options: Mapping[str, object]
) -> tuple[str, str]:
    return _binding(bindings, "time"), str(_option(options, "time_order"))


def _execute_time_series_acf(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.time_series import run_acf

    time_column, time_order = _time_columns(bindings, options)
    return run_acf(
        frame=source,
        time_column=time_column,
        value_column=_binding(bindings, "value"),
        time_order=time_order,
        nlags=int(_option(options, "nlags")),
        confidence_level=float(_option(options, "confidence_level", 0.95)),
        adjusted=bool(_option(options, "adjusted", False)),
    )


def _execute_time_series_pacf(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.time_series import run_pacf

    time_column, time_order = _time_columns(bindings, options)
    return run_pacf(
        frame=source,
        time_column=time_column,
        value_column=_binding(bindings, "value"),
        time_order=time_order,
        nlags=int(_option(options, "nlags")),
        confidence_level=float(_option(options, "confidence_level", 0.95)),
        method=str(_option(options, "method", "ywm")),
    )


def _execute_time_series_adf(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.time_series import run_adf

    time_column, time_order = _time_columns(bindings, options)
    return run_adf(
        source,
        time_column=time_column,
        value_column=_binding(bindings, "value"),
        time_order=time_order,
        regression=str(_option(options, "regression", "c")),
        autolag=str(_option(options, "autolag", "aic")),
        max_lag=int(_option(options, "max_lag", 12)),
    )


def _execute_time_series_kpss(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.time_series import run_kpss

    time_column, time_order = _time_columns(bindings, options)
    return run_kpss(
        source,
        time_column=time_column,
        value_column=_binding(bindings, "value"),
        time_order=time_order,
        regression=str(_option(options, "regression", "c")),
        nlags=cast(str | int, _option(options, "nlags", "auto")),
    )


def _execute_time_series_arima(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.time_series import fit_arima

    time_column, time_order = _time_columns(bindings, options)
    return fit_arima(
        source,
        time_column=time_column,
        value_column=_binding(bindings, "value"),
        time_order=time_order,
        order=cast(Sequence[int], _option(options, "order")),
        seasonal_order=cast(Sequence[int], _option(options, "seasonal_order", (0, 0, 0, 0))),
        trend=str(_option(options, "trend", "c")),
        forecast_horizon=int(_option(options, "forecast_horizon", 1)),
        confidence_level=float(_option(options, "confidence_level", 0.95)),
    )


def _execute_time_series_var(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.time_series import fit_var

    time_column, time_order = _time_columns(bindings, options)
    return fit_var(
        source,
        time_column=time_column,
        value_columns=_binding_columns(bindings, "values"),
        time_order=time_order,
        lags=int(_option(options, "lags")),
        trend=str(_option(options, "trend", "c")),
        forecast_horizon=int(_option(options, "forecast_horizon", 1)),
        confidence_level=float(_option(options, "confidence_level", 0.95)),
        stability_policy=str(_option(options, "stability_policy", "reject_unstable")),
    )


def _execute_time_series_irf(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.time_series import run_irf

    time_column, time_order = _time_columns(bindings, options)
    return run_irf(
        source,
        time_column=time_column,
        value_columns=_binding_columns(bindings, "values"),
        time_order=time_order,
        lags=int(_option(options, "lags")),
        trend=str(_option(options, "trend", "c")),
        horizon=int(_option(options, "horizon", 10)),
        orthogonalized=bool(_option(options, "orthogonalized", True)),
        confidence_level=float(_option(options, "confidence_level", 0.95)),
        ci_method=str(_option(options, "ci_method", "asymptotic_normal")),
        stability_policy=str(_option(options, "stability_policy", "reject_unstable")),
    )


def _execute_time_series_cointegration(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.time_series import run_cointegration

    time_column, time_order = _time_columns(bindings, options)
    return run_cointegration(
        source,
        time_column=time_column,
        value_columns=_binding_columns(bindings, "values"),
        time_order=time_order,
        method=str(_option(options, "method")),
        confidence_level=float(_option(options, "confidence_level", 0.95)),
        max_lag=int(_option(options, "max_lag", 1)),
        trend=str(_option(options, "trend", "c")),
        det_order=int(_option(options, "det_order", 0)),
        k_ar_diff=int(_option(options, "k_ar_diff", 1)),
    )


def _execute_time_series_vecm(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.time_series import fit_vecm

    time_column, time_order = _time_columns(bindings, options)
    return fit_vecm(
        source,
        time_column=time_column,
        value_columns=_binding_columns(bindings, "values"),
        time_order=time_order,
        det_order=int(_option(options, "det_order", 0)),
        k_ar_diff=int(_option(options, "k_ar_diff", 1)),
        deterministic=str(_option(options, "deterministic")),
        forecast_horizon=int(_option(options, "forecast_horizon", 1)),
        confidence_level=float(_option(options, "confidence_level", 0.95)),
    )


def _execute_time_series_granger(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.time_series import run_granger

    time_column, time_order = _time_columns(bindings, options)
    return run_granger(
        source,
        time_column=time_column,
        cause=_binding(bindings, "cause"),
        effect=_binding(bindings, "effect"),
        time_order=time_order,
        max_lag=int(_option(options, "max_lag")),
        test=str(_option(options, "test", "ssr_ftest")),
    )


_TIME_SERIES_EXECUTORS: Mapping[
    str, Callable[[pd.DataFrame, Mapping[str, object], Mapping[str, object]], Result]
] = MappingProxyType(
    {
        "time_series.acf": _execute_time_series_acf,
        "time_series.pacf": _execute_time_series_pacf,
        "time_series.adf": _execute_time_series_adf,
        "time_series.kpss": _execute_time_series_kpss,
        "time_series.arima": _execute_time_series_arima,
        "time_series.var": _execute_time_series_var,
        "time_series.irf": _execute_time_series_irf,
        "time_series.cointegration": _execute_time_series_cointegration,
        "time_series.vecm": _execute_time_series_vecm,
        "time_series.granger": _execute_time_series_granger,
    }
)


# ── family adapter projection ────────────────────────────────────────────


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

    from .p7_pack_registry import P7_FAMILY_DECLARATIONS

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
