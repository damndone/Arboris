"""Categorical, GLM, IV, matching and meta-analysis pack adapters."""

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
from .base import P7PackAdapterError, Request, Result, _binding, _binding_columns, _bool_option, _frame, _option, _request_parts, _require_columns, _row_matrix, _validate_declared_bindings, _values


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
    exog, exog_columns = _iv_exog_with_intercept(
        exog,
        list(exog_columns),
        intercept=_bool_option(names, "intercept", True),
        intercept_column=names.pop("intercept_column", "const"),
    )
    names.pop("intercept", None)
    names.setdefault("exog_names", list(exog_columns))
    names.setdefault("endog_names", list(endog_columns))
    names.setdefault("instrument_names", list(instrument_columns))
    try:
        return _IV_EXECUTORS[operation_id](y, exog, endog, instruments, names)
    except KeyError as exc:
        raise P7PackAdapterError(
            f"IV adapter received unsupported operation: {operation_id}"
        ) from exc


def _iv_exog_with_intercept(
    exog: np.ndarray,
    columns: list[str],
    *,
    intercept: bool,
    intercept_column: object,
) -> tuple[np.ndarray, list[str]]:
    """Add the intercept a workflow request implies, unless the design has one.

    The pack estimates exactly the design it is given. A workflow request
    binds data columns, and data rarely carry a column of ones, so without
    this the first stage and the GMM fit run through the origin (v1.9.1 M0:
    partial F 6223.5 instead of 170.6). As with the diagnostics adapter the
    intercept is on unless ``intercept`` is false; a bound column that is
    already constant serves as the intercept and none is added.
    """

    if not intercept:
        return exog, columns
    if type(intercept_column) is not str or not intercept_column:
        raise P7PackAdapterError("IV intercept_column must be a non-empty string")
    if exog.size and any(
        np.all(np.isfinite(exog[:, index])) and np.ptp(exog[:, index]) == 0 and exog[0, index] != 0
        for index in range(exog.shape[1])
    ):
        return exog, columns
    if intercept_column in columns:
        raise P7PackAdapterError(
            f"IV exog column {intercept_column!r} is not constant; name the intercept column differently"
        )
    ones = np.ones((exog.shape[0], 1))
    return np.column_stack((ones, exog)) if exog.size else ones, [intercept_column, *columns]


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
