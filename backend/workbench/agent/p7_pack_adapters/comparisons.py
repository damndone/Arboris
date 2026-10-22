"""Multiple comparisons, nonparametric, repeated-measures, resampling and ROC pack adapters."""

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
from .base import P7PackAdapterError, Request, Result, _binding, _binding_columns, _frame, _option, _request_parts, _require_columns, _validate_declared_bindings, _values


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
