"""Explicit power-analysis solvers backed by statsmodels."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import product
import math
import warnings
from typing import Any

import statsmodels
from statsmodels.stats.power import FTestAnovaPower, NormalIndPower, TTestIndPower

from workbench.contracts.model.power_analysis import (
    POWER_ANALYSIS_ALTERNATIVES,
    POWER_ANALYSIS_COMPLETED,
    POWER_ANALYSIS_CONTRACT,
    POWER_ANALYSIS_CONTRACT_VERSION,
    POWER_ANALYSIS_DESIGNS,
    POWER_ANALYSIS_DESIGN_EFFECT_SIZE_TYPES,
    POWER_ANALYSIS_EFFECT_SIZE_TYPES,
    POWER_ANALYSIS_MAX_GROUPS,
    POWER_ANALYSIS_MAX_GRID_AXES,
    POWER_ANALYSIS_MAX_GRID_SCENARIOS,
    POWER_ANALYSIS_MAX_GRID_VALUES_PER_AXIS,
    POWER_ANALYSIS_MAX_NUMERIC_INPUT,
    POWER_ANALYSIS_STATUS_COMPLETED,
    POWER_ANALYSIS_SOLVE_TARGETS,
    PowerAnalysisInput,
    PowerAnalysisResult,
    compute_power_analysis_evidence_digest,
)


class PowerAnalysisError(ValueError):
    """Stable, machine-readable failure from the power-analysis boundary."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


_CORE_FIELDS = ("alpha", "power", "sample_size", "effect_size")
_GRID_CORE_FIELDS = frozenset(_CORE_FIELDS) | {"ratio", "k_groups"}


def _fail(reason_code: str, message: str) -> None:
    raise PowerAnalysisError(reason_code, message)


def _number(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if type(value) not in {int, float} or isinstance(value, bool):
        _fail("POWER_ANALYSIS_INVALID_PARAMETER", f"{field_name} must be a number or null")
    if type(value) is int and abs(value) > POWER_ANALYSIS_MAX_NUMERIC_INPUT:
        _fail("POWER_ANALYSIS_INVALID_PARAMETER", f"{field_name} is outside the supported bound")
    try:
        normalized = float(value)
    except OverflowError:
        _fail("POWER_ANALYSIS_NON_FINITE_INPUT", f"{field_name} must be finite")
    if not math.isfinite(normalized):
        _fail("POWER_ANALYSIS_NON_FINITE_INPUT", f"{field_name} must be finite")
    if abs(normalized) > POWER_ANALYSIS_MAX_NUMERIC_INPUT:
        _fail("POWER_ANALYSIS_INVALID_PARAMETER", f"{field_name} is outside the supported bound")
    return normalized


def _validate_probability(value: float | None, field_name: str) -> None:
    if value is not None and not 0.0 < value < 1.0:
        _fail("POWER_ANALYSIS_INVALID_PARAMETER", f"{field_name} must be strictly between 0 and 1")


def _validate_request(
    *,
    design: str,
    solve_for: str,
    effect_size_type: str,
    alpha: Any,
    power: Any,
    sample_size: Any,
    effect_size: Any,
    ratio: Any,
    alternative: Any,
    k_groups: Any,
) -> PowerAnalysisInput:
    if type(design) is not str or design not in POWER_ANALYSIS_DESIGNS:
        _fail("POWER_ANALYSIS_UNSUPPORTED_DESIGN", "design is not declared")
    if type(solve_for) is not str or solve_for not in POWER_ANALYSIS_SOLVE_TARGETS:
        _fail("POWER_ANALYSIS_INVALID_SOLVE_TARGET", "solve_for is not declared")
    if type(effect_size_type) is not str or effect_size_type not in POWER_ANALYSIS_EFFECT_SIZE_TYPES:
        _fail("POWER_ANALYSIS_EFFECT_SIZE_LABEL", "effect_size_type is not declared")
    if effect_size_type != POWER_ANALYSIS_DESIGN_EFFECT_SIZE_TYPES[design]:
        _fail(
            "POWER_ANALYSIS_EFFECT_SIZE_LABEL",
            f"{design} requires {POWER_ANALYSIS_DESIGN_EFFECT_SIZE_TYPES[design]}",
        )

    normalized = {
        "alpha": _number(alpha, "alpha"),
        "power": _number(power, "power"),
        "sample_size": _number(sample_size, "sample_size"),
        "effect_size": _number(effect_size, "effect_size"),
        "ratio": _number(ratio, "ratio") if ratio is not None else None,
    }
    _validate_probability(normalized["alpha"], "alpha")
    _validate_probability(normalized["power"], "power")
    if normalized["sample_size"] is not None and normalized["sample_size"] <= 0.0:
        _fail("POWER_ANALYSIS_INVALID_PARAMETER", "sample_size must be positive")
    if normalized["effect_size"] is not None:
        if normalized["effect_size"] == 0.0:
            _fail("POWER_ANALYSIS_INVALID_PARAMETER", "effect_size must be non-zero")
        if design == "one_way_anova" and normalized["effect_size"] < 0.0:
            _fail("POWER_ANALYSIS_INVALID_PARAMETER", "cohens_f must be positive")

    unknowns = [field for field in _CORE_FIELDS if normalized[field] is None]
    if len(unknowns) != 1 or unknowns[0] != solve_for:
        _fail(
            "POWER_ANALYSIS_UNKNOWN_COUNT",
            "exactly one of alpha, power, sample_size, and effect_size must be omitted as solve_for",
        )

    if design in {"independent_t", "two_proportion_z"}:
        if ratio is None or alternative is None:
            _fail(
                "POWER_ANALYSIS_REQUIRED_PARAMETER",
                "ratio and alternative must be supplied explicitly",
            )
        if type(alternative) is not str or alternative not in POWER_ANALYSIS_ALTERNATIVES:
            _fail("POWER_ANALYSIS_UNSUPPORTED_ALTERNATIVE", "alternative is not declared")
        if normalized["ratio"] is None or normalized["ratio"] <= 0.0:
            _fail("POWER_ANALYSIS_INVALID_PARAMETER", "ratio must be positive")
        if k_groups is not None:
            _fail("POWER_ANALYSIS_UNSUPPORTED_COMBINATION", "k_groups is only valid for one_way_anova")
    else:
        if ratio is not None or alternative is not None:
            _fail(
                "POWER_ANALYSIS_UNSUPPORTED_COMBINATION",
                "ratio and alternative are only valid for two-sample designs",
            )
        if type(k_groups) is not int or isinstance(k_groups, bool) or k_groups < 2:
            _fail("POWER_ANALYSIS_REQUIRED_PARAMETER", "k_groups must be an explicit integer of at least 2")
        if k_groups > POWER_ANALYSIS_MAX_GROUPS:
            _fail("POWER_ANALYSIS_INVALID_PARAMETER", "k_groups is outside the supported bound")

    if normalized["sample_size"] is not None:
        minimum = 2.0 if design in {"independent_t", "two_proportion_z"} else float(k_groups + 1)
        if normalized["sample_size"] < minimum:
            _fail(
                "POWER_ANALYSIS_INVALID_PARAMETER",
                f"sample_size must be at least {minimum:g} for {design}",
            )

    return PowerAnalysisInput(
        design=design,
        solve_for=solve_for,
        effect_size_type=effect_size_type,
        alpha=normalized["alpha"],
        power=normalized["power"],
        sample_size=normalized["sample_size"],
        effect_size=normalized["effect_size"],
        ratio=normalized["ratio"],
        alternative=alternative,
        k_groups=k_groups,
    )


def _solver_for(design: str) -> tuple[Any, str]:
    if design == "independent_t":
        return TTestIndPower(), "TTestIndPower"
    if design == "one_way_anova":
        return FTestAnovaPower(), "FTestAnovaPower"
    if design == "two_proportion_z":
        return NormalIndPower(), "NormalIndPower"
    _fail("POWER_ANALYSIS_UNSUPPORTED_DESIGN", "design is not declared")


def _solve_one(request: PowerAnalysisInput) -> tuple[float, str]:
    solver, solver_class = _solver_for(request.design)
    params: dict[str, Any] = {
        "effect_size": request.effect_size,
        "alpha": request.alpha,
        "power": request.power,
    }
    if request.design == "one_way_anova":
        params.update(nobs=request.sample_size, k_groups=request.k_groups)
    else:
        params.update(
            nobs1=request.sample_size,
            ratio=request.ratio,
            alternative=request.alternative,
        )

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            solved = solver.solve_power(**params)
    except Exception:
        _fail("POWER_ANALYSIS_NON_CONVERGENCE", "statsmodels could not solve the declared target")
    if caught:
        _fail("POWER_ANALYSIS_NON_CONVERGENCE", "statsmodels emitted a numerical convergence warning")
    try:
        solved_float = float(solved)
    except (OverflowError, TypeError, ValueError):
        _fail("POWER_ANALYSIS_NON_FINITE_RESULT", "statsmodels returned a non-numeric result")
    if not math.isfinite(solved_float):
        _fail("POWER_ANALYSIS_NON_FINITE_RESULT", "statsmodels returned a non-finite result")
    if request.solve_for in {"alpha", "power"} and not 0.0 < solved_float < 1.0:
        _fail("POWER_ANALYSIS_NON_FINITE_RESULT", "solved probability is outside (0, 1)")
    if request.solve_for == "sample_size":
        minimum = 2.0 if request.design in {"independent_t", "two_proportion_z"} else float(request.k_groups + 1)
        if solved_float < minimum:
            _fail("POWER_ANALYSIS_NON_FINITE_RESULT", "solved sample size is below the declared design bound")
    if request.solve_for == "effect_size":
        if solved_float == 0.0 or (
            request.design == "one_way_anova" and solved_float < 0.0
        ):
            _fail("POWER_ANALYSIS_NON_FINITE_RESULT", "solved effect size is outside the declared convention")
    return solved_float, solver_class


def _semantics(request: PowerAnalysisInput) -> dict[str, Any]:
    if request.design == "one_way_anova":
        return {
            "family": request.design,
            "effect_size": request.effect_size_type,
            "sample_size": "total_nobs",
            "k_groups": request.k_groups,
            "rounding_policy": "none",
        }
    return {
        "family": request.design,
        "effect_size": request.effect_size_type,
        "sample_size": "nobs1_per_group",
        "ratio": "nobs2_over_nobs1",
        "alternative": request.alternative,
        "rounding_policy": "none",
    }


def _validate_grid(
    axes: Mapping[str, Sequence[Any]], solve_for: str, design: str
) -> dict[str, list[float | int]]:
    if not isinstance(axes, Mapping):
        _fail("POWER_ANALYSIS_GRID_BOUNDS", "sensitivity_grid axes must be a mapping")
    if not axes or len(axes) > POWER_ANALYSIS_MAX_GRID_AXES:
        _fail("POWER_ANALYSIS_GRID_BOUNDS", "sensitivity_grid must have between 1 and 6 axes")
    allowed = set(_GRID_CORE_FIELDS)
    if design != "one_way_anova":
        allowed.discard("k_groups")
    else:
        allowed.discard("ratio")
    if any(type(field_name) is not str for field_name in axes):
        _fail("POWER_ANALYSIS_GRID_AXIS", "sensitivity axis names must be strings")
    normalized: dict[str, list[float | int]] = {}
    for field_name in sorted(axes):
        if type(field_name) is not str or field_name not in allowed:
            _fail("POWER_ANALYSIS_GRID_AXIS", f"unsupported sensitivity axis {field_name!r}")
        if field_name == solve_for:
            _fail("POWER_ANALYSIS_GRID_TARGET", "the declared solve target cannot also be a grid axis")
        values = axes[field_name]
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            _fail("POWER_ANALYSIS_GRID_BOUNDS", f"axis {field_name} must be a finite sequence")
        if not values or len(values) > POWER_ANALYSIS_MAX_GRID_VALUES_PER_AXIS:
            _fail("POWER_ANALYSIS_GRID_BOUNDS", f"axis {field_name} exceeds the bounded grid size")
        converted: list[float | int] = []
        for value in values:
            if type(value) not in {int, float} or isinstance(value, bool):
                _fail("POWER_ANALYSIS_GRID_FINITE", f"axis {field_name} contains a non-numeric value")
            if type(value) is int and abs(value) > POWER_ANALYSIS_MAX_NUMERIC_INPUT:
                _fail("POWER_ANALYSIS_GRID_FINITE", f"axis {field_name} exceeds the numeric bound")
            try:
                normalized_value = float(value)
            except OverflowError:
                _fail("POWER_ANALYSIS_GRID_FINITE", f"axis {field_name} contains a non-finite value")
            if not math.isfinite(normalized_value):
                _fail("POWER_ANALYSIS_GRID_FINITE", f"axis {field_name} contains a non-finite value")
            if field_name == "k_groups":
                if type(value) is not int or value < 2:
                    _fail("POWER_ANALYSIS_GRID_AXIS", "k_groups grid values must be integers of at least 2")
                converted.append(value)
            else:
                converted.append(float(value))
        if len(set(converted)) != len(converted):
            _fail("POWER_ANALYSIS_GRID_BOUNDS", f"axis {field_name} contains duplicate values")
        normalized[field_name] = converted
    scenario_count = math.prod(len(values) for values in normalized.values())
    if scenario_count > POWER_ANALYSIS_MAX_GRID_SCENARIOS:
        _fail("POWER_ANALYSIS_GRID_BOUNDS", "sensitivity_grid exceeds the scenario bound")
    return normalized


def _grid_results(
    request: PowerAnalysisInput,
    axes: Mapping[str, Sequence[Any]],
) -> dict[str, Any]:
    normalized_axes = _validate_grid(axes, request.solve_for, request.design)
    axis_names = tuple(normalized_axes)
    scenarios: list[dict[str, Any]] = []
    for values in product(*(normalized_axes[name] for name in axis_names)):
        overrides = dict(zip(axis_names, values, strict=True))
        scenario_values = request.to_dict()
        scenario_values.update(overrides)
        scenario = _validate_request(**scenario_values)
        solved_value, _ = _solve_one(scenario)
        scenarios.append(
            {
                "inputs": scenario.to_dict(),
                "solved_value": solved_value,
            }
        )
    return {"axes": normalized_axes, "scenarios": scenarios}


def solve_power(
    *,
    design: str,
    solve_for: str,
    effect_size_type: str,
    alpha: float | int | None = None,
    power: float | int | None = None,
    sample_size: float | int | None = None,
    effect_size: float | int | None = None,
    ratio: float | int | None = None,
    alternative: str | None = None,
    k_groups: int | None = None,
    sensitivity_grid: Mapping[str, Sequence[Any]] | None = None,
) -> dict[str, Any]:
    """Solve one explicitly declared power-analysis target.

    ``sample_size`` means nobs1 per group for the two-sample designs and total
    nobs for one-way ANOVA.  No sample-size rounding is performed.
    """

    request = _validate_request(
        design=design,
        solve_for=solve_for,
        effect_size_type=effect_size_type,
        alpha=alpha,
        power=power,
        sample_size=sample_size,
        effect_size=effect_size,
        ratio=ratio,
        alternative=alternative,
        k_groups=k_groups,
    )
    solved_value, solver_class = _solve_one(request)
    grid = None if sensitivity_grid is None else _grid_results(request, sensitivity_grid)
    result_payload = {
        "contract": POWER_ANALYSIS_CONTRACT,
        "contract_version": POWER_ANALYSIS_CONTRACT_VERSION,
        "status": POWER_ANALYSIS_STATUS_COMPLETED,
        "reason_code": POWER_ANALYSIS_COMPLETED,
        "design": request.design,
        "solve_for": request.solve_for,
        "effect_size_type": request.effect_size_type,
        "design_semantics": _semantics(request),
        "inputs": request.to_dict(),
        "solved_value": solved_value,
        "provenance": {
            "library": "statsmodels",
            "version": str(statsmodels.__version__),
            "solver_class": solver_class,
        },
    }
    if grid is not None:
        result_payload["sensitivity_grid"] = grid
    result = PowerAnalysisResult(
        design=result_payload["design"],
        solve_for=result_payload["solve_for"],
        effect_size_type=result_payload["effect_size_type"],
        design_semantics=result_payload["design_semantics"],
        inputs=result_payload["inputs"],
        solved_value=result_payload["solved_value"],
        provenance=result_payload["provenance"],
        evidence_digest=compute_power_analysis_evidence_digest(result_payload),
        sensitivity_grid=result_payload.get("sensitivity_grid"),
        status=result_payload["status"],
        reason_code=result_payload["reason_code"],
    )
    return result.to_dict()


def solve_power_grid(
    *,
    axes: Mapping[str, Sequence[Any]],
    design: str,
    solve_for: str,
    effect_size_type: str,
    alpha: float | int | None = None,
    power: float | int | None = None,
    sample_size: float | int | None = None,
    effect_size: float | int | None = None,
    ratio: float | int | None = None,
    alternative: str | None = None,
    k_groups: int | None = None,
    **unknown_parameters: Any,
) -> dict[str, Any]:
    """Evaluate every explicitly supplied sensitivity-grid scenario."""

    if unknown_parameters:
        names = ", ".join(sorted(unknown_parameters))
        _fail("POWER_ANALYSIS_UNKNOWN_PARAMETER", f"unknown parameter(s): {names}")
    return solve_power(
        design=design,
        solve_for=solve_for,
        effect_size_type=effect_size_type,
        alpha=alpha,
        power=power,
        sample_size=sample_size,
        effect_size=effect_size,
        ratio=ratio,
        alternative=alternative,
        k_groups=k_groups,
        sensitivity_grid=axes,
    )


evaluate_sensitivity_grid = solve_power_grid


__all__ = [
    "PowerAnalysisError",
    "evaluate_sensitivity_grid",
    "solve_power",
    "solve_power_grid",
]
