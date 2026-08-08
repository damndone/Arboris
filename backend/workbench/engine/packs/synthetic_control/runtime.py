"""Bounded synthetic-control kernels with explicit donor and placebo policies."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

import numpy as np
from scipy.optimize import minimize

from workbench.contracts.model.synthetic_control import SyntheticControlInput, make_synthetic_control_result
from workbench.engine.packs.p7_common import make_p7_scope


class SyntheticControlPackError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _fail(reason_code: str, message: str) -> None:
    raise SyntheticControlPackError(reason_code, message)


def _scope(estimand: str) -> dict[str, Any]:
    return make_p7_scope(
        estimand=estimand,
        input_semantics="one treated unit, explicit donor pool, ordered periods, and nonnegative simplex weights",
        assumptions=[
            "the donor pool spans the treated unit's untreated path",
            "the pre-treatment outcome path is an informative predictor under the declared policy",
        ],
        limitations=[
            "pre-fit quality does not prove causal identification or rule out anticipation",
            "interference, donor contamination, time-varying confounding, and weight instability are not automatically tested",
        ],
        not_claimed=["post-treatment gaps are not automatically a causal effect", "placebo gaps are diagnostic summaries, not a calibrated p-value"],
        unsupported_extensions=["augmented SCM, ridge/elastic-net weights, automatic donor selection, and probabilistic significance tests"],
    )


def _prepare(outcome_matrix: Any, treated_unit: str, donor_pool: Sequence[str], unit_labels: Sequence[str], periods: Sequence[int | float], pre_periods: Sequence[int | float], post_periods: Sequence[int | float]) -> tuple[np.ndarray, list[str], list[int | float], np.ndarray, np.ndarray, np.ndarray]:
    if isinstance(outcome_matrix, (str, bytes)):
        _fail("SYNTHETIC_CONTROL_INVALID_INPUT", "outcome_matrix must be numeric")
    try:
        outcomes = np.asarray(outcome_matrix, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SyntheticControlPackError("SYNTHETIC_CONTROL_INVALID_INPUT", "outcome_matrix must be numeric") from exc
    if outcomes.ndim != 2 or outcomes.shape[0] < 2 or outcomes.shape[1] < 3:
        _fail("SYNTHETIC_CONTROL_INVALID_INPUT", "outcome_matrix must have at least two units and three periods")
    if not np.isfinite(outcomes).all():
        _fail("SYNTHETIC_CONTROL_NONFINITE_INPUT", "outcome_matrix must be finite")
    labels = list(unit_labels)
    if len(labels) != outcomes.shape[0] or len(set(labels)) != len(labels) or any(type(label) is not str or not label for label in labels):
        _fail("SYNTHETIC_CONTROL_INVALID_UNITS", "unit_labels must be unique and match outcome rows")
    if treated_unit not in labels or any(unit not in labels for unit in donor_pool):
        _fail("SYNTHETIC_CONTROL_INVALID_UNITS", "treated and donor labels must be present")
    if treated_unit in donor_pool or len(set(donor_pool)) != len(donor_pool):
        _fail("SYNTHETIC_CONTROL_DONOR_INFEASIBLE", "donor_pool must be unique and exclude treated_unit")
    if len(donor_pool) < 2:
        _fail("SYNTHETIC_CONTROL_DONOR_INFEASIBLE", "at least two donors are required for a bounded simplex fit")
    ordered = list(periods)
    if len(ordered) != outcomes.shape[1] or ordered != sorted(ordered) or len(set(ordered)) != len(ordered):
        _fail("SYNTHETIC_CONTROL_UNSORTED_PERIODS", "periods must be sorted and match outcome columns")
    if len(pre_periods) < 2:
        _fail("SYNTHETIC_CONTROL_INSUFFICIENT_PRE_PERIODS", "at least two pre-treatment periods are required")
    if not set(pre_periods).issubset(ordered) or not set(post_periods).issubset(ordered) or set(pre_periods) & set(post_periods):
        _fail("SYNTHETIC_CONTROL_INVALID_PERIODS", "pre and post periods must be disjoint members of periods")
    pre_idx = np.asarray([ordered.index(period) for period in pre_periods], dtype=int)
    post_idx = np.asarray([ordered.index(period) for period in post_periods], dtype=int)
    treated_idx = labels.index(treated_unit)
    donor_idx = np.asarray([labels.index(unit) for unit in donor_pool], dtype=int)
    return outcomes, labels, ordered, pre_idx, post_idx, np.concatenate(([treated_idx], donor_idx))


def _solver(solver_policy: Mapping[str, Any] | None) -> dict[str, Any]:
    value = solver_policy or {"solver": "scipy_slsqp", "max_iter": 500, "tolerance": 1e-10, "constraint_tolerance": 1e-8}
    try:
        request = SyntheticControlInput.from_dict({
            "operation_id": "synthetic_control.fit", "treated_unit": "treated", "donor_pool": ["d1", "d2"],
            "periods": [0, 1, 2], "pre_periods": [0, 1], "post_periods": [2],
            "predictor_policy": "pre_outcome_v1", "weight_policy": "simplex_nonnegative_v1",
            "solver_policy": value, "tolerance_policy": {"weight_sum": 1e-8, "constraint": 1e-8, "finite": 0.0}, "placebo_policy": None,
        })
    except Exception as exc:
        _fail("SYNTHETIC_CONTROL_INVALID_POLICY", str(exc))
    return dict(request.solver_policy)


def _tolerances(value: Mapping[str, Any] | None) -> dict[str, float]:
    raw = value or {"weight_sum": 1e-8, "constraint": 1e-8, "finite": 0.0}
    expected = {"weight_sum", "constraint", "finite"}
    if not isinstance(raw, Mapping) or set(raw) != expected:
        _fail("SYNTHETIC_CONTROL_INVALID_POLICY", "tolerance_policy must be closed")
    normalized = {}
    for field in expected:
        number = raw[field]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(float(number)) or float(number) < 0.0:
            _fail("SYNTHETIC_CONTROL_INVALID_POLICY", f"tolerance {field} is invalid")
        normalized[field] = float(number)
    return normalized


def _fit_weights(target: np.ndarray, donor_matrix: np.ndarray, policy: Mapping[str, Any], tolerances: Mapping[str, float]) -> tuple[np.ndarray, dict[str, Any]]:
    if np.std(target) <= tolerances["finite"] and np.all(np.std(donor_matrix, axis=1) <= tolerances["finite"]):
        _fail("SYNTHETIC_CONTROL_DEGENERATE", "pre-treatment outcomes do not identify a useful fit")
    donor_count = donor_matrix.shape[0]
    start = np.full(donor_count, 1.0 / donor_count)
    objective = lambda weights: float(np.sum((target - weights @ donor_matrix) ** 2))
    try:
        fit = minimize(
            objective,
            start,
            method="SLSQP",
            bounds=[(0.0, 1.0)] * donor_count,
            constraints={"type": "eq", "fun": lambda weights: float(np.sum(weights) - 1.0)},
            options={"ftol": float(policy["tolerance"]), "maxiter": int(policy["max_iter"])},
        )
    except (ArithmeticError, FloatingPointError, ValueError, np.linalg.LinAlgError) as exc:
        raise SyntheticControlPackError("SYNTHETIC_CONTROL_NUMERICAL_FAILURE", f"simplex solver failed: {exc}") from exc
    weights = np.asarray(fit.x, dtype=float)
    if not fit.success or not np.isfinite(weights).all():
        _fail("SYNTHETIC_CONTROL_CONSTRAINT_FAILURE", "simplex solver did not satisfy the declared constraints")
    if abs(float(weights.sum()) - 1.0) > tolerances["weight_sum"] or np.min(weights) < -tolerances["constraint"] or np.max(weights) > 1.0 + tolerances["constraint"]:
        _fail("SYNTHETIC_CONTROL_CONSTRAINT_FAILURE", "simplex weights violate declared bounds")
    weights = np.clip(weights, 0.0, 1.0)
    weights /= weights.sum()
    return weights, {"success": True, "iterations": int(getattr(fit, "nit", 0) or 0), "objective": objective(weights)}


def _fit_core(outcomes: np.ndarray, labels: list[str], periods: list[int | float], treated_unit: str, donor_pool: Sequence[str], pre_periods: Sequence[int | float], post_periods: Sequence[int | float], solver_policy: Mapping[str, Any], tolerance_policy: Mapping[str, Any]) -> dict[str, Any]:
    _, _, _, pre_idx, post_idx, unit_indices = _prepare(outcomes, treated_unit, donor_pool, labels, periods, pre_periods, post_periods)
    treated_idx, *donor_indices = unit_indices.tolist()
    target_pre = outcomes[treated_idx, pre_idx]
    donor_pre = outcomes[np.asarray(donor_indices), :][:, pre_idx]
    weights, solver = _fit_weights(target_pre, donor_pre, solver_policy, tolerance_policy)
    synthetic_pre = weights @ donor_pre
    synthetic_post = weights @ outcomes[np.asarray(donor_indices), :][:, post_idx]
    treated_post = outcomes[treated_idx, post_idx]
    gaps = treated_post - synthetic_post
    result = {
        "treated_unit": treated_unit,
        "weight_sum": float(weights.sum()),
        "weights": [{"unit": unit, "weight": float(weight)} for unit, weight in zip(donor_pool, weights)],
        "nonzero_donor_count": int(np.count_nonzero(weights > tolerance_policy["constraint"])),
        "pre_fit": {"rmse": float(np.sqrt(np.mean((target_pre - synthetic_pre) ** 2))), "max_abs_gap": float(np.max(np.abs(target_pre - synthetic_pre)))},
        "post_treatment": {"gap_mean": float(np.mean(gaps)), "gap_cumulative": float(np.sum(gaps))},
        "solver": solver,
        "scope": _scope("post-treatment treated-minus-synthetic outcome gap"),
    }
    return result


def fit_synthetic_control(*, outcome_matrix: Any, treated_unit: str, donor_pool: Sequence[str], unit_labels: Sequence[str], periods: Sequence[int | float], pre_periods: Sequence[int | float], post_periods: Sequence[int | float], predictor_matrix: Any = None, solver_policy: Mapping[str, Any] | None = None, tolerance_policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    # Predictor matrices are accepted only as a future typed extension point;
    # v1's declared predictor_policy is pre-treatment outcomes, so a supplied
    # untyped matrix is rejected rather than silently substituted.
    if predictor_matrix is not None:
        _fail("SYNTHETIC_CONTROL_UNSUPPORTED_PREDICTOR", "predictor_matrix is not part of the v1 pre_outcome policy")
    try:
        outcomes, labels, ordered, _, _, _ = _prepare(outcome_matrix, treated_unit, donor_pool, unit_labels, periods, pre_periods, post_periods)
    except SyntheticControlPackError:
        raise
    policy = _solver(solver_policy)
    tolerances = _tolerances(tolerance_policy)
    result = _fit_core(outcomes, labels, ordered, treated_unit, donor_pool, pre_periods, post_periods, policy, tolerances)
    return make_synthetic_control_result(operation_id="synthetic_control.fit", status="completed", reason_code="SYNTHETIC_CONTROL_COMPLETED", n_units=len(labels), n_periods=len(ordered), result=result)


def run_placebo(*, outcome_matrix: Any, treated_unit: str, donor_pool: Sequence[str], unit_labels: Sequence[str], periods: Sequence[int | float], pre_periods: Sequence[int | float], post_periods: Sequence[int | float], placebo_policy: Mapping[str, Any], predictor_matrix: Any = None, solver_policy: Mapping[str, Any] | None = None, tolerance_policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if predictor_matrix is not None:
        _fail("SYNTHETIC_CONTROL_UNSUPPORTED_PREDICTOR", "predictor_matrix is not part of the v1 pre_outcome policy")
    outcomes, labels, ordered, _, _, _ = _prepare(outcome_matrix, treated_unit, donor_pool, unit_labels, periods, pre_periods, post_periods)
    if not isinstance(placebo_policy, Mapping) or set(placebo_policy) != {"unit_policy", "placebo_units", "max_placebos", "donor_policy", "failure_policy"}:
        _fail("SYNTHETIC_CONTROL_INVALID_PLACEBO_POLICY", "placebo_policy must be explicit and closed")
    placebo_units = list(placebo_policy["placebo_units"])
    if placebo_policy["unit_policy"] != "explicit" or placebo_policy["donor_policy"] != "exclude_original_treated" or placebo_policy["failure_policy"] != "reject" or treated_unit in placebo_units or len(placebo_units) > int(placebo_policy["max_placebos"]):
        _fail("SYNTHETIC_CONTROL_INVALID_PLACEBO_POLICY", "placebo policy violates explicit unit bounds")
    if any(unit not in donor_pool for unit in placebo_units) or len(set(placebo_units)) != len(placebo_units):
        _fail("SYNTHETIC_CONTROL_INVALID_PLACEBO_POLICY", "placebo units must be unique donors")
    policy = _solver(solver_policy)
    tolerances = _tolerances(tolerance_policy)
    summaries: list[dict[str, Any]] = []
    for placebo in placebo_units:
        placebo_donors = [unit for unit in donor_pool if unit != placebo and unit != treated_unit]
        summary = _fit_core(outcomes, labels, ordered, placebo, placebo_donors, pre_periods, post_periods, policy, tolerances)
        summaries.append({"unit": placebo, "pre_fit_rmse": summary["pre_fit"]["rmse"], "post_gap_mean": summary["post_treatment"]["gap_mean"], "post_gap_cumulative": summary["post_treatment"]["gap_cumulative"]})
    result = {
        "estimands": {"pre_fit": "pre_treatment_fit_rmse", "post_gap": "post_treatment_placebo_gap"},
        "placebo_count": len(summaries),
        "placebo_summaries": summaries,
        "scope": _scope("placebo pre-fit and post-treatment gap summaries under the declared donor policy"),
    }
    return make_synthetic_control_result(operation_id="synthetic_control.placebo", status="completed", reason_code="SYNTHETIC_CONTROL_COMPLETED", n_units=len(labels), n_periods=len(ordered), result=result)


__all__ = ["SyntheticControlPackError", "fit_synthetic_control", "run_placebo"]
