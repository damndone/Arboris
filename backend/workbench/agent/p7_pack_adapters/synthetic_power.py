"""Synthetic-control and power-analysis pack adapters."""

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
from .base import P7PackAdapterError, Request, RequestValidator, Result, _binding_columns, _frame, _mapping_options, _option, _options, _request_parts, _require_columns, _validate_declared_bindings


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
    required = ("treated_unit", "pre_periods", "post_periods")
    for name in (*required, *(() if options.get("unit_column") is not None else ("donor_pool", "periods"))):
        _option(options, name)
    _refuse_unlisted_periods(options)
    return options, request


def _refuse_unlisted_periods(options: Mapping[str, object]) -> None:
    """Refuse before approval what the engine refuses after it.

    QRData 374 (6af0a0da round): pre_periods [{"low": 1970, "high": 1988}] passed the
    proposal, was approved, and failed in the engine three times, once as a TypeError.
    Only the engine's own conditions are checked here: a period is one scalar label,
    there are at least two pre periods, and pre and post periods do not overlap.
    """
    lists: dict[str, list[object]] = {}
    for name in ("periods", "pre_periods", "post_periods"):
        value = options.get(name)
        if value is None:
            continue
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise P7PackAdapterError(f"SYNTHETIC_CONTROL_INVALID_PERIODS: {name} must be an array of periods")
        if any(isinstance(item, Mapping) for item in value):
            raise P7PackAdapterError(
                f"SYNTHETIC_CONTROL_INVALID_PERIODS: {name} lists each period, not a range object; "
                "write every period, e.g. [1970, 1971, ..., 1988]")
        if any(isinstance(item, (bool, Sequence)) and not isinstance(item, str) for item in value):
            raise P7PackAdapterError(f"SYNTHETIC_CONTROL_INVALID_PERIODS: each {name} entry is one period label")
        lists[name] = list(value)
    pre, post = lists.get("pre_periods", []), lists.get("post_periods", [])
    if len(pre) < 2:
        raise P7PackAdapterError(
            "SYNTHETIC_CONTROL_INSUFFICIENT_PRE_PERIODS: at least two pre-treatment periods are required")
    if set(pre) & set(post):
        raise P7PackAdapterError("SYNTHETIC_CONTROL_INVALID_PERIODS: pre_periods and post_periods must be disjoint")


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
    """Reject a period vector that cannot index the source rows, or period lists written as ranges."""

    source = _frame(frame)
    _operation_id, _bindings, options = _request_parts(request)
    if options.get("unit_column") is not None:
        time_column = options.get("time_column")
        if isinstance(time_column, str) and time_column in source.columns:
            periods = sorted(value.item() if hasattr(value, "item") else value for value in source[time_column].dropna().unique())
            _refuse_period_ranges({**options, "periods": periods})
        return
    periods = _option(options, "periods")
    if not isinstance(periods, Sequence) or isinstance(periods, (str, bytes)):
        raise P7PackAdapterError(
            "SYNTHETIC_CONTROL_INVALID_PERIODS: periods must be an array"
        )
    if len(periods) != len(source):
        raise P7PackAdapterError(
            "SYNTHETIC_CONTROL_PERIOD_COUNT_MISMATCH: "
            f"periods has {len(periods)} values but the source has {len(source)} rows. "
            "For long data with one row per unit and period, set unit_column and time_column and bind outcomes to "
            "the one outcome column."
        )
    _refuse_period_ranges(options)


def _wide_from_long(
    source: pd.DataFrame, outcome_columns: Sequence[str], options: Mapping[str, object]
) -> tuple[pd.DataFrame, list[str], dict[str, object]]:
    """One row per unit and period, as most panels arrive: the engine still sees a balanced unit-by-period matrix."""
    unit, time = options.get("unit_column"), options.get("time_column")
    if type(unit) is not str or type(time) is not str or len(outcome_columns) != 1 or "predictors" in options:
        raise P7PackAdapterError(
            "SYNTHETIC_CONTROL_LONG_SHAPE: long data needs unit_column, time_column and one outcome column"
        )
    missing = [column for column in (unit, time) if column not in source.columns]
    if missing:
        raise P7PackAdapterError(f"P7 pack source is missing column(s): {', '.join(missing)}")
    if source.duplicated([unit, time]).any():
        raise P7PackAdapterError(f"SYNTHETIC_CONTROL_LONG_SHAPE: {unit} and {time} do not identify one row each")
    wide = source.pivot(index=time, columns=unit, values=outcome_columns[0]).sort_index()
    wide.columns = [_unit_label(label) for label in wide.columns]
    gaps = wide.columns[wide.isna().any()].tolist()
    if gaps:
        raise P7PackAdapterError(
            "SYNTHETIC_CONTROL_LONG_SHAPE: the panel is not balanced; these units miss periods or values: "
            + ", ".join(gaps[:20])
        )
    labels = [str(label) for label in wide.columns]
    treated = _unit_label(_option(options, "treated_unit"))
    if treated not in labels:
        raise P7PackAdapterError(f"SYNTHETIC_CONTROL_LONG_SHAPE: treated_unit {treated} is not a value of {unit}")
    donors = options.get("donor_pool")
    return wide, labels, {
        **options,
        "treated_unit": treated,
        "periods": [value.item() if hasattr(value, "item") else value for value in wide.index],
        "donor_pool": [label for label in labels if label != treated] if donors is None
                      else [_unit_label(label) for label in cast(Sequence[object], donors)],
    }


def _refuse_period_ranges(options: Mapping[str, object]) -> None:
    """pre_periods and post_periods list periods; [1970, 1987] is two periods, not a range.

    QRData 374 (2026-11-02): read as two periods each, the fit averaged two post years and was wrong.
    """
    periods = options.get("periods")
    declared = [*cast(Sequence[object], options.get("pre_periods") or ()), *cast(Sequence[object], options.get("post_periods") or ())]
    if not isinstance(periods, Sequence) or not declared:
        return
    try:
        low, high = min(declared), max(declared)  # type: ignore[type-var]
        skipped = [period for period in periods if low < period < high and period not in declared]  # type: ignore[operator]
    except TypeError:
        return
    if skipped:
        raise P7PackAdapterError(
            "SYNTHETIC_CONTROL_PERIOD_GAPS: pre_periods and post_periods list every period, not a range; "
            f"{len(skipped)} period(s) lie between them in neither list: {', '.join(map(str, skipped[:12]))}"
            f"{' ...' if len(skipped) > 12 else ''}. List each period, e.g. pre_periods {low} through the last pre period."
        )


def _unit_label(value: object) -> str:
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)


def execute_synthetic(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    outcome_columns = _binding_columns(bindings, "outcomes")
    if options.get("unit_column") is not None:
        _require_columns(source, {"outcomes": outcome_columns})
        source, outcome_columns, options = _wide_from_long(source, outcome_columns, options)
    else:
        _require_columns(source, bindings)
    _refuse_period_ranges(options)
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
    if solve_for not in POWER_ANALYSIS_SOLVE_TARGETS:
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
