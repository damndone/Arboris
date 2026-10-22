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
