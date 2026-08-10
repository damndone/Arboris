"""Typed, fail-closed adapters for the frozen P7 statistical packs.

Workflow specs carry server-owned column bindings and an explicit policy
object.  Adapters turn those bindings into the frozen pack APIs; they never
accept Agent-supplied code, paths, callbacks, or raw replacement frames.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, TypeAlias, cast

import numpy as np
import pandas as pd

from workbench.contracts.model.categorical import CategoricalResultEnvelope
from workbench.contracts.model.glm_extensions import GLMExtensionResultEnvelope
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
    if operation_id == "categorical.cramers_v":
        from workbench.engine.packs.categorical import fit_cramers_v

        return fit_cramers_v(values, correction=_bool_option(options, "correction"))
    if operation_id == "categorical.mcnemar":
        from workbench.engine.packs.categorical import fit_mcnemar

        return fit_mcnemar(
            values,
            exact=_bool_option(options, "exact"),
            correction=_bool_option(options, "correction"),
        )
    raise P7PackAdapterError(f"categorical adapter received unsupported operation: {operation_id}")


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
    from workbench.engine.packs.iv_gmm import diagnose_weak_instruments, fit_gmm

    names = dict(options)
    names.setdefault("exog_names", list(exog_columns))
    names.setdefault("endog_names", list(endog_columns))
    names.setdefault("instrument_names", list(instrument_columns))
    if operation_id == "iv.gmm":
        return fit_gmm(y, exog, endog, instruments, **names)
    if operation_id == "iv.weak_instruments":
        allowed = {
            key: names[key]
            for key in (
                "exog_names",
                "endog_names",
                "instrument_names",
            )
            if key in names
        }
        return diagnose_weak_instruments(exog, endog, instruments, **allowed)
    raise P7PackAdapterError(f"IV adapter received unsupported operation: {operation_id}")


# ── matching ─────────────────────────────────────────────────────────────


def validate_matching_request(request: Request) -> Request:
    return _validate_declared_bindings(request)


def _matching_options(options: Mapping[str, object]) -> dict[str, object]:
    required = (
        "propensity_policy",
        "distance_policy",
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
    from workbench.engine.packs.matching import assess_balance, estimate_att

    if operation_id == "matching.att":
        common = {
            "treatment_column": _binding(bindings, "treatment"),
            "outcome_column": _binding(bindings, "outcome"),
            "covariate_columns": list(_binding_columns(bindings, "covariates")),
            "id_column": _binding(bindings, "id"),
        }
        return estimate_att(source, **common, **_matching_options(options))
    if operation_id == "matching.balance":
        balance_options = {
            "balance_threshold": _option(options, "balance_threshold"),
            "missing_policy": _option(options, "missing_policy"),
        }
        matched_pairs = options.get("matched_pairs")
        if matched_pairs is not None and not isinstance(matched_pairs, Sequence):
            raise P7PackAdapterError("matching matched_pairs must be an array")
        return assess_balance(
            source,
            treatment_column=_binding(bindings, "treatment"),
            covariate_columns=list(_binding_columns(bindings, "covariates")),
            id_column=_binding(bindings, "id"),
            matched_pairs=cast(Sequence[Mapping[str, object]] | None, matched_pairs),
            **balance_options,
        )
    raise P7PackAdapterError(f"matching adapter received unsupported operation: {operation_id}")


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
    from workbench.engine.packs.meta_analysis import combine_effects, convert_effect_size

    if operation_id == "meta.combine":
        return combine_effects(studies, **dict(options))
    if operation_id == "meta.effect_size":
        return convert_effect_size(studies, **dict(options))
    raise P7PackAdapterError(f"meta adapter received unsupported operation: {operation_id}")


# ── missing-data evidence ────────────────────────────────────────────────


def validate_missing_request(request: Request) -> Request:
    operation_id, _bindings, options = _request_parts(request)
    if operation_id == "missingness.profile":
        return _validate_declared_bindings(request)
    if operation_id == "missing_data.rubin_pool":
        if "model_results" not in options:
            raise P7PackAdapterError("missing_data.rubin_pool requires options.model_results")
        if not isinstance(options["model_results"], Sequence):
            raise P7PackAdapterError("missing_data.rubin_pool model_results must be an array")
        return _validate_declared_bindings(request)
    raise P7PackAdapterError(f"missing-data adapter received unsupported operation: {operation_id}")


def execute_missing(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, _bindings, options = _request_parts(request)
    from workbench.engine.packs.missing_data import profile_missingness, rubin_pool

    if operation_id == "missingness.profile":
        return profile_missingness(source)
    if operation_id == "missing_data.rubin_pool":
        model_results = cast(Sequence[Mapping[str, object]], options["model_results"])
        kwargs = {
            name: options[name]
            for name in ("alpha", "null_value", "complete_data_degrees_of_freedom")
            if name in options
        }
        return rubin_pool(model_results, **kwargs)
    raise P7PackAdapterError(f"missing-data adapter received unsupported operation: {operation_id}")


# ── model diagnostics ────────────────────────────────────────────────────


def validate_diagnostics_request(request: Request) -> Request:
    operation_id, _bindings, options = _request_parts(request)
    _validate_declared_bindings(request)
    if operation_id == "diagnostics.breusch_godfrey":
        _option(options, "lag")
        _option(options, "time_order")
    if operation_id == "diagnostics.reset":
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
    metadata = options.get("model_metadata", generated_metadata)
    if operation_id == "diagnostics.vif" and not metadata:
        metadata = _design_only_vif_metadata(design_columns, len(design))
    if not isinstance(metadata, Mapping):
        raise P7PackAdapterError("diagnostics model_metadata must be an object")
    common: dict[str, object] = {
        "design_columns": design_columns,
        "intercept": intercept,
        "intercept_column": intercept_column,
        "model_metadata": dict(metadata),
    }
    from workbench.engine.packs.model_diagnostics import (
        run_breusch_godfrey,
        run_breusch_pagan,
        run_influence,
        run_reset,
        run_vif,
        run_white,
    )

    if operation_id == "diagnostics.vif":
        return run_vif(
            design,
            max_output_rows=cast(int | None, options.get("max_output_rows")),
            **common,
        )
    if response is None or residuals is None or fitted_values is None:
        raise P7PackAdapterError(f"{operation_id} requires a response column")
    common.update(
        {
            "fitted_values": fitted_values,
        }
    )
    if operation_id == "diagnostics.breusch_pagan":
        return run_breusch_pagan(response, design, residuals, **common)
    if operation_id == "diagnostics.white":
        return run_white(response, design, residuals, **common)
    if operation_id == "diagnostics.breusch_godfrey":
        return run_breusch_godfrey(
            response,
            design,
            residuals,
            lag=int(_option(options, "lag")),
            time_order=str(_option(options, "time_order")),
            **common,
        )
    if operation_id == "diagnostics.reset":
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
    if operation_id == "diagnostics.influence":
        return run_influence(
            response,
            design,
            residuals,
            max_output_rows=cast(int | None, options.get("max_output_rows")),
            **common,
        )
    raise P7PackAdapterError(f"diagnostics adapter received unsupported operation: {operation_id}")


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
    from workbench.engine.packs.multiple_comparisons import run_games_howell, run_scheffe

    alpha = float(_option(options, "alpha", 0.05))
    if operation_id == "multiple_comparisons.games_howell":
        return run_games_howell(groups, alpha=alpha)
    if operation_id == "multiple_comparisons.scheffe":
        return run_scheffe(groups, alpha=alpha)
    raise P7PackAdapterError(
        f"multiple-comparisons adapter received unsupported operation: {operation_id}"
    )


# ── multivariate ─────────────────────────────────────────────────────────


def validate_multivariate_request(request: Request) -> Request:
    operation_id, _bindings, options = _request_parts(request)
    if operation_id not in {
        "multivariate.pca",
        "multivariate.efa",
        "multivariate.cronbach_alpha",
        "multivariate.clustering",
        "multivariate.mca",
        "multivariate.discriminant",
        "multivariate.correspondence",
        "multivariate.manova",
    }:
        raise P7PackAdapterError(f"multivariate adapter received unsupported operation: {operation_id}")
    _validate_declared_bindings(request)
    if operation_id == "multivariate.efa":
        for name in ("n_factors", "extraction", "rotation", "kmo_threshold", "bartlett_alpha"):
            _option(options, name)
    if operation_id == "multivariate.manova":
        for name in ("interaction_terms", "intercept", "missing_policy"):
            _option(options, name)
    if operation_id == "multivariate.discriminant":
        for name in ("method", "prior_policy", "regularization", "evaluation"):
            _option(options, name)
    return request


def execute_multivariate(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    _require_columns(source, bindings)
    from workbench.engine.packs.multivariate import (
        cronbach_alpha,
        fit_clustering,
        fit_correspondence,
        fit_discriminant,
        fit_efa,
        fit_mca,
        fit_manova,
        fit_pca,
    )
    missing_policy = str(_option(options, "missing_policy", "complete_case_v1"))
    if operation_id == "multivariate.pca":
        return fit_pca(
            source,
            _binding_columns(bindings, "columns"),
            matrix=str(_option(options, "matrix", "correlation")),
            component_selection=str(_option(options, "component_selection", "all")),
            n_components=cast(int | None, options.get("n_components")),
            variance_threshold=cast(float | None, options.get("variance_threshold")),
            missing_policy=missing_policy,
            include_scores=bool(_option(options, "include_scores", False)),
            max_score_rows=int(_option(options, "max_score_rows", 100)),
        )
    if operation_id == "multivariate.efa":
        return fit_efa(
            source,
            _binding_columns(bindings, "columns"),
            n_factors=int(_option(options, "n_factors")),
            extraction=str(_option(options, "extraction")),
            rotation=str(_option(options, "rotation")),
            kmo_threshold=float(_option(options, "kmo_threshold")),
            bartlett_alpha=float(_option(options, "bartlett_alpha")),
            missing_policy=missing_policy,
        )
    if operation_id == "multivariate.cronbach_alpha":
        reverse_scored = options.get("reverse_scored")
        reverse_bounds = options.get("reverse_bounds")
        return cronbach_alpha(
            source,
            _binding_columns(bindings, "columns"),
            reverse_scored=cast(Sequence[str] | None, reverse_scored),
            reverse_bounds=cast(Mapping[str, Sequence[float]] | None, reverse_bounds),
            missing_policy=missing_policy,
        )
    if operation_id == "multivariate.clustering":
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
            missing_policy=missing_policy,
        )
    if operation_id == "multivariate.correspondence":
        table = pd.crosstab(source[_binding(bindings, "row")], source[_binding(bindings, "column")])
        return fit_correspondence(table, n_dimensions=int(_option(options, "n_dimensions", 2)))
    if operation_id == "multivariate.mca":
        return fit_mca(
            source,
            columns=_binding_columns(bindings, "columns"),
            n_dimensions=int(_option(options, "n_dimensions", 2)),
            missing_policy=missing_policy,
        )
    if operation_id == "multivariate.discriminant":
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
            missing_policy=missing_policy,
        )
    if operation_id == "multivariate.manova":
        covariates = _binding_columns(bindings, "covariates") if "covariates" in bindings else ()
        interaction_terms = _option(options, "interaction_terms")
        if not isinstance(interaction_terms, Sequence) or isinstance(interaction_terms, (str, bytes)):
            raise P7PackAdapterError("multivariate interaction_terms must be an array")
        return fit_manova(
            source,
            response_columns=_binding_columns(bindings, "responses"),
            factor_columns=_binding_columns(bindings, "factors"),
            covariate_columns=covariates,
            interaction_terms=cast(Sequence[Sequence[str]], interaction_terms),
            intercept=bool(_option(options, "intercept")),
            missing_policy=str(_option(options, "missing_policy")),
            max_retained_positions=int(_option(options, "max_retained_positions", 500)),
        )
    raise P7PackAdapterError(f"multivariate adapter received unsupported operation: {operation_id}")


# ── non-parametric inference ─────────────────────────────────────────────


def validate_nonparametric_request(request: Request) -> Request:
    operation_id, _bindings, _options = _request_parts(request)
    if operation_id in {
        "nonparametric.mann_whitney",
        "nonparametric.wilcoxon_signed_rank",
        "nonparametric.spearman",
        "nonparametric.kendall",
    }:
        pass
    elif operation_id in {"nonparametric.kruskal_wallis"}:
        pass
    elif operation_id == "nonparametric.friedman":
        pass
    elif operation_id == "nonparametric.robust_summary":
        pass
    else:
        raise P7PackAdapterError(f"nonparametric adapter received unsupported operation: {operation_id}")
    return _validate_declared_bindings(request)


def execute_nonparametric(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    _require_columns(source, bindings)
    from workbench.engine.packs.nonparametric import (
        run_friedman,
        run_kendall,
        run_kruskal_wallis,
        run_mann_whitney,
        run_robust_summary,
        run_spearman,
        run_wilcoxon_signed_rank,
    )
    if operation_id == "nonparametric.friedman":
        columns = _binding_columns(bindings, "columns")
        values = source.loc[:, list(columns)].to_numpy(dtype=float).T.tolist()
        return run_friedman(values, **dict(options))
    if operation_id == "nonparametric.kruskal_wallis":
        return run_kruskal_wallis(_groups(source, bindings), **dict(options))
    if operation_id == "nonparametric.robust_summary":
        return run_robust_summary(_values(source, _binding(bindings, "values")), **dict(options))
    x = _values(source, _binding(bindings, "x"))
    y = _values(source, _binding(bindings, "y"))
    if operation_id == "nonparametric.mann_whitney":
        return run_mann_whitney(x, y, **dict(options))
    if operation_id == "nonparametric.wilcoxon_signed_rank":
        return run_wilcoxon_signed_rank(x, y, **dict(options))
    if operation_id == "nonparametric.spearman":
        return run_spearman(x, y, **dict(options))
    if operation_id == "nonparametric.kendall":
        return run_kendall(x, y, **dict(options))
    raise P7PackAdapterError(f"nonparametric adapter received unsupported operation: {operation_id}")


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
    operation_id, _bindings, _options = _request_parts(request)
    if operation_id not in {"resampling.bootstrap", "resampling.permutation"}:
        raise P7PackAdapterError(f"resampling adapter received unsupported operation: {operation_id}")
    return _validate_declared_bindings(request)


def execute_resampling(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    _require_columns(source, bindings)
    from workbench.engine.packs.resampling import run_bootstrap, run_permutation

    if operation_id == "resampling.bootstrap":
        return run_bootstrap(_values(source, _binding(bindings, "values")), **dict(options))
    if operation_id == "resampling.permutation":
        return run_permutation(
            _values(source, _binding(bindings, "left")),
            _values(source, _binding(bindings, "right")),
            **dict(options),
        )
    raise P7PackAdapterError(f"resampling adapter received unsupported operation: {operation_id}")


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
    from workbench.engine.packs.spatial_statistics import (
        run_geary_c,
        run_getis_ord_g,
        run_moran_i,
    )

    kwargs = {
        "weight_policy": weight_policy,
        "permutation_policy": permutation_policy,
    }
    if operation_id == "spatial.moran_i":
        return run_moran_i(values, weights, **kwargs)
    if operation_id == "spatial.geary_c":
        return run_geary_c(values, weights, **kwargs)
    if operation_id == "spatial.getis_ord_g":
        return run_getis_ord_g(values, weights, **kwargs)
    raise P7PackAdapterError(f"spatial adapter received unsupported operation: {operation_id}")


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
    operation_id, _bindings, options = _request_parts(request)
    _validate_declared_bindings(request)
    for name in ("treated_unit", "donor_pool", "periods", "pre_periods", "post_periods"):
        _option(options, name)
    if operation_id == "synthetic_control.placebo":
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
    elif operation_id != "synthetic_control.fit":
        raise P7PackAdapterError(f"synthetic-control adapter received unsupported operation: {operation_id}")
    return request


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
    from workbench.engine.packs.synthetic_control import fit_synthetic_control, run_placebo

    if operation_id == "synthetic_control.fit":
        return fit_synthetic_control(**common)
    return run_placebo(
        **common,
        placebo_policy=cast(Mapping[str, object], _mapping_options(options, "placebo_policy")),
    )


# ── power analysis ───────────────────────────────────────────────────────


def validate_power_request(request: Request) -> Request:
    operation_id, _bindings, options = _request_parts(request)
    if operation_id not in {"power_analysis.solve", "power_analysis.sensitivity_grid"}:
        raise P7PackAdapterError(f"power adapter received unsupported operation: {operation_id}")
    for name in ("design", "solve_for"):
        _option(options, name)
    if operation_id == "power_analysis.sensitivity_grid":
        _option(options, "axes")
    return _validate_declared_bindings(request)


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
    from workbench.engine.packs.power_analysis import solve_power, solve_power_grid

    if operation_id == "power_analysis.solve":
        sensitivity_grid = options.get("sensitivity_grid")
        payload = solve_power(
            **params,
            sensitivity_grid=cast(Mapping[str, Sequence[object]] | None, sensitivity_grid),
        )
    else:
        axes = _option(options, "axes")
        if not isinstance(axes, Mapping):
            raise P7PackAdapterError("power sensitivity-grid axes must be an object")
        payload = solve_power_grid(
            axes=cast(Mapping[str, Sequence[object]], axes),
            **params,
        )
    # The frozen power contract predates the workflow operation envelope and
    # therefore has no operation_id field.  Keep that contract byte-for-byte
    # intact and add a small adapter envelope so the generic registry can
    # still validate identity without inventing a field inside the result.
    return {"operation_id": operation_id, "payload": payload}


# ── time-series pack ─────────────────────────────────────────────────────


def validate_time_series_request(request: Request) -> Request:
    operation_id, _bindings, options = _request_parts(request)
    if operation_id not in {
        "time_series.acf",
        "time_series.pacf",
        "time_series.adf",
        "time_series.kpss",
        "time_series.arima",
        "time_series.var",
        "time_series.irf",
        "time_series.cointegration",
        "time_series.vecm",
        "time_series.granger",
    }:
        raise P7PackAdapterError(f"time-series adapter received unsupported operation: {operation_id}")
    _validate_declared_bindings(request)
    _option(options, "time_order")
    return request


def execute_time_series(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    _require_columns(source, bindings)
    time_column = _binding(bindings, "time")
    time_order = str(_option(options, "time_order"))
    from workbench.engine.packs.time_series import (
        fit_arima,
        fit_var,
        fit_vecm,
        run_acf,
        run_adf,
        run_cointegration,
        run_granger,
        run_irf,
        run_kpss,
        run_pacf,
    )
    if operation_id in {"time_series.acf", "time_series.pacf"}:
        kwargs = {
            "time_column": time_column,
            "value_column": _binding(bindings, "value"),
            "time_order": time_order,
            "nlags": int(_option(options, "nlags")),
            "confidence_level": float(_option(options, "confidence_level", 0.95)),
        }
        if operation_id == "time_series.acf":
            return run_acf(adjusted=bool(_option(options, "adjusted", False)), frame=source, **kwargs)
        return run_pacf(method=str(_option(options, "method", "ywm")), frame=source, **kwargs)
    if operation_id == "time_series.adf":
        return run_adf(
            source,
            time_column=time_column,
            value_column=_binding(bindings, "value"),
            time_order=time_order,
            regression=str(_option(options, "regression", "c")),
            autolag=str(_option(options, "autolag", "aic")),
            max_lag=int(_option(options, "max_lag", 12)),
        )
    if operation_id == "time_series.kpss":
        return run_kpss(
            source,
            time_column=time_column,
            value_column=_binding(bindings, "value"),
            time_order=time_order,
            regression=str(_option(options, "regression", "c")),
            nlags=cast(str | int, _option(options, "nlags", "auto")),
        )
    if operation_id == "time_series.arima":
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
    if operation_id in {"time_series.var", "time_series.irf", "time_series.cointegration", "time_series.vecm"}:
        value_columns = _binding_columns(bindings, "values")
    if operation_id == "time_series.var":
        return fit_var(
            source,
            time_column=time_column,
            value_columns=value_columns,
            time_order=time_order,
            lags=int(_option(options, "lags")),
            trend=str(_option(options, "trend", "c")),
            forecast_horizon=int(_option(options, "forecast_horizon", 1)),
            confidence_level=float(_option(options, "confidence_level", 0.95)),
            stability_policy=str(_option(options, "stability_policy", "reject_unstable")),
        )
    if operation_id == "time_series.irf":
        return run_irf(
            source,
            time_column=time_column,
            value_columns=value_columns,
            time_order=time_order,
            lags=int(_option(options, "lags")),
            trend=str(_option(options, "trend", "c")),
            horizon=int(_option(options, "horizon", 10)),
            orthogonalized=bool(_option(options, "orthogonalized", True)),
            confidence_level=float(_option(options, "confidence_level", 0.95)),
            ci_method=str(_option(options, "ci_method", "asymptotic_normal")),
            stability_policy=str(_option(options, "stability_policy", "reject_unstable")),
        )
    if operation_id == "time_series.cointegration":
        return run_cointegration(
            source,
            time_column=time_column,
            value_columns=value_columns,
            time_order=time_order,
            method=str(_option(options, "method")),
            confidence_level=float(_option(options, "confidence_level", 0.95)),
            max_lag=int(_option(options, "max_lag", 1)),
            trend=str(_option(options, "trend", "c")),
            det_order=int(_option(options, "det_order", 0)),
            k_ar_diff=int(_option(options, "k_ar_diff", 1)),
        )
    if operation_id == "time_series.vecm":
        return fit_vecm(
            source,
            time_column=time_column,
            value_columns=value_columns,
            time_order=time_order,
            det_order=int(_option(options, "det_order", 0)),
            k_ar_diff=int(_option(options, "k_ar_diff", 1)),
            deterministic=str(_option(options, "deterministic")),
            forecast_horizon=int(_option(options, "forecast_horizon", 1)),
            confidence_level=float(_option(options, "confidence_level", 0.95)),
        )
    if operation_id == "time_series.granger":
        return run_granger(
            source,
            time_column=time_column,
            cause=_binding(bindings, "cause"),
            effect=_binding(bindings, "effect"),
            time_order=time_order,
            max_lag=int(_option(options, "max_lag")),
            test=str(_option(options, "test", "ssr_ftest")),
        )
    raise P7PackAdapterError(f"time-series adapter received unsupported operation: {operation_id}")


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
class P7FamilyAdapter:
    """Family-level typed functions projected into every declared operation."""

    validate_request: RequestValidator
    extract_columns: ColumnExtractor
    execute: Executor
    validate_result: ResultValidator
    validate_frame_request: FrameRequestValidator = validate_frame_request_passthrough


P7_FAMILY_ADAPTERS: Mapping[str, P7FamilyAdapter] = {
    "categorical": P7FamilyAdapter(validate_categorical_request, _generic_columns, execute_categorical, _validate_categorical_result),
    "glm_extensions": P7FamilyAdapter(validate_glm_request, _generic_columns, execute_glm, _validate_glm_result),
    "iv_gmm": P7FamilyAdapter(validate_iv_request, _generic_columns, execute_iv, _validate_iv_result),
    "matching": P7FamilyAdapter(validate_matching_request, _generic_columns, execute_matching, _validate_matching_result),
    "meta_analysis": P7FamilyAdapter(validate_meta_request, _generic_columns, execute_meta, _validate_meta_result),
    "missing_data": P7FamilyAdapter(validate_missing_request, _generic_columns, execute_missing, _validate_missing_result),
    "model_diagnostics": P7FamilyAdapter(validate_diagnostics_request, _generic_columns, execute_diagnostics, _validate_diagnostics_result),
    "multiple_comparisons": P7FamilyAdapter(validate_multiple_comparisons_request, _generic_columns, execute_multiple_comparisons, _validate_multiple_comparisons_result),
    "multivariate": P7FamilyAdapter(validate_multivariate_request, _generic_columns, execute_multivariate, _validate_multivariate_result),
    "nonparametric": P7FamilyAdapter(validate_nonparametric_request, _generic_columns, execute_nonparametric, _validate_nonparametric_result),
    "power_analysis": P7FamilyAdapter(validate_power_request, _no_columns, execute_power, _validate_power_result),
    "repeated_measures_anova": P7FamilyAdapter(validate_repeated_measures_request, _generic_columns, execute_repeated_measures, _validate_repeated_result),
    "resampling": P7FamilyAdapter(validate_resampling_request, _generic_columns, execute_resampling, _validate_resampling_result),
    "roc_diagnostics": P7FamilyAdapter(validate_roc_request, _generic_columns, execute_roc, _validate_roc_result),
    "spatial_statistics": P7FamilyAdapter(validate_spatial_request, _generic_columns, execute_spatial, _validate_spatial_result),
    "survival_analysis": P7FamilyAdapter(validate_survival_request, _generic_columns, execute_survival, _validate_survival_result),
    "synthetic_control": P7FamilyAdapter(
        validate_synthetic_request,
        _generic_columns,
        execute_synthetic,
        _validate_synthetic_result,
        validate_synthetic_frame_request,
    ),
    "time_series": P7FamilyAdapter(validate_time_series_request, _generic_columns, execute_time_series, _validate_time_series_result),
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
    "P7PackAdapterError",
    "P7_FAMILY_ADAPTERS",
    "p7_family_adapter",
]
