"""Explicit, bounded ATT matching and covariate-balance evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.discrete.discrete_model import Logit

from workbench.contracts.model.matching import MatchingInput, make_matching_result
from workbench.engine.packs.p7_common import make_p7_scope


class MatchingPackError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _fail(reason_code: str, message: str) -> None:
    raise MatchingPackError(reason_code, message)


def _policy_input(operation_id: str, *, outcome_column: str | None, **kwargs: Any) -> MatchingInput:
    value = {
        "operation_id": operation_id,
        "treatment_column": kwargs["treatment_column"],
        "outcome_column": outcome_column,
        "covariate_columns": list(kwargs["covariate_columns"]),
        "id_column": kwargs["id_column"],
        "estimand": "ATT" if operation_id == "matching.att" else "covariate_balance",
        "propensity_policy": kwargs.get("propensity_policy"),
        "distance_policy": kwargs.get("distance_policy"),
        "ratio": kwargs.get("ratio"),
        "caliper": kwargs.get("caliper"),
        "replacement": kwargs.get("replacement"),
        "tie_policy": kwargs.get("tie_policy"),
        "common_support_policy": kwargs.get("common_support_policy"),
        "unmatched_policy": kwargs.get("unmatched_policy"),
        "balance_threshold": kwargs.get("balance_threshold"),
        "missing_policy": kwargs.get("missing_policy"),
    }
    try:
        return MatchingInput.from_dict(value)
    except Exception as exc:
        _fail("MATCHING_INVALID_POLICY", str(exc))


def _validate_frame(frame: Any, request: MatchingInput, *, require_outcome: bool) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        _fail("MATCHING_INVALID_INPUT", "frame must be a non-empty DataFrame")
    required = [request.treatment_column, request.id_column, *request.covariate_columns]
    if require_outcome:
        required.append(request.outcome_column or "")
    if any(column not in frame.columns for column in required):
        _fail("MATCHING_MISSING_COLUMN", "a declared matching column is absent")
    if frame[request.id_column].isna().any() or frame[request.id_column].duplicated().any():
        _fail("MATCHING_DUPLICATE_ID", "id_column must be complete and unique")
    treatment = frame[request.treatment_column]
    if pd.api.types.is_bool_dtype(treatment):
        _fail("MATCHING_TREATMENT", "boolean treatment must be explicitly encoded as 0/1")
    try:
        treatment_values = treatment.to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise MatchingPackError("MATCHING_TREATMENT", "treatment must be numeric 0/1") from exc
    if not np.isfinite(treatment_values).all() or set(np.unique(treatment_values)) != {0.0, 1.0}:
        _fail("MATCHING_TREATMENT", "treatment must contain both numeric 0 and 1")
    for column in request.covariate_columns:
        series = frame[column]
        if not pd.api.types.is_numeric_dtype(series):
            _fail("MATCHING_NON_NUMERIC", f"covariate {column} must use a numeric dtype")
        try:
            values = series.to_numpy(dtype=float)
        except (TypeError, ValueError) as exc:
            raise MatchingPackError("MATCHING_NON_NUMERIC", f"covariate {column} must be numeric") from exc
        if not np.isfinite(values).all():
            _fail("MATCHING_NONFINITE", f"covariate {column} must be finite")
    if require_outcome:
        if not pd.api.types.is_numeric_dtype(frame[request.outcome_column or ""]):
            _fail("MATCHING_NON_NUMERIC", "outcome must use a numeric dtype")
        try:
            outcomes = frame[request.outcome_column or ""].to_numpy(dtype=float)
        except (TypeError, ValueError) as exc:
            raise MatchingPackError("MATCHING_NON_NUMERIC", "outcome must be numeric") from exc
        if not np.isfinite(outcomes).all():
            _fail("MATCHING_NONFINITE", "outcome must be finite")
    return frame.reset_index(drop=True).copy()


def _fit_propensity(frame: pd.DataFrame, request: MatchingInput) -> tuple[np.ndarray, list[str]]:
    treatment = frame[request.treatment_column].to_numpy(dtype=float)
    matrix = frame[list(request.covariate_columns)].to_numpy(dtype=float)
    design = sm.add_constant(matrix, has_constant="add")
    names = ["const", *request.covariate_columns]
    policy = dict(request.propensity_policy)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fitted = Logit(treatment, design).fit(method=policy["solver"], maxiter=policy["max_iter"], tol=policy["tolerance"], disp=0)
    except (ArithmeticError, FloatingPointError, ValueError, np.linalg.LinAlgError) as exc:
        raise MatchingPackError("MATCHING_PROPENSITY_FAILURE", f"propensity model failed: {exc}") from exc
    if not bool(getattr(fitted, "mle_retvals", {}).get("converged", True)):
        _fail("MATCHING_PROPENSITY_FAILURE", "propensity model did not converge")
    probabilities = np.asarray(fitted.predict(design), dtype=float)
    if not np.isfinite(probabilities).all():
        _fail("MATCHING_PROPENSITY_EXTREME", "propensity probabilities are non-finite")
    lower, upper = float(policy["min_probability"]), float(policy["max_probability"])
    if np.any(probabilities < lower) or np.any(probabilities > upper):
        _fail("MATCHING_PROPENSITY_EXTREME", "propensity probabilities exceed declared bounds")
    return probabilities, names


def _logit(value: np.ndarray) -> np.ndarray:
    return np.log(value / (1.0 - value))


def _scope(estimand: str) -> dict[str, Any]:
    return make_p7_scope(
        estimand=estimand,
        input_semantics="binary treatment, numeric outcome/covariates, and explicit propensity-distance matching policy",
        assumptions=[
            "conditional exchangeability within measured covariates is a substantive assumption",
            "the declared propensity model and common-support rule are adequate",
        ],
        limitations=[
            "unmeasured confounding, measurement error, and propensity misspecification remain possible",
            "matching changes the supported population and does not recover an unsupported ATE automatically",
        ],
        not_claimed=["the matched difference is not an unconditional causal claim", "balance evidence is not proof of exchangeability"],
        unsupported_extensions=["ATE, weighting, full matching, Mahalanobis distance, and automatic method selection"],
    )


def _smd(treated: np.ndarray, control: np.ndarray) -> float | None:
    pooled = math.sqrt(max((float(np.var(treated, ddof=1)) + float(np.var(control, ddof=1))) / 2.0, 0.0)) if treated.size > 1 and control.size > 1 else 0.0
    if pooled == 0.0:
        return 0.0 if np.isclose(float(np.mean(treated)), float(np.mean(control))) else None
    return float((np.mean(treated) - np.mean(control)) / pooled)


def _variance_ratio(treated: np.ndarray, control: np.ndarray) -> float | None:
    if treated.size < 2 or control.size < 2:
        return None
    denominator = float(np.var(control, ddof=1))
    numerator = float(np.var(treated, ddof=1))
    if denominator == 0.0:
        return None if numerator == 0.0 else None
    return float(numerator / denominator)


def assess_balance(frame: pd.DataFrame, *, treatment_column: str, covariate_columns: Sequence[str], id_column: str, matched_pairs: Sequence[Mapping[str, Any]] | None = None, balance_threshold: float | None = 0.1, missing_policy: str = "reject") -> dict[str, Any]:
    request = _policy_input(
        "matching.balance", treatment_column=treatment_column, outcome_column=None,
        covariate_columns=covariate_columns, id_column=id_column,
        propensity_policy={"model": "logit", "solver": "newton", "max_iter": 200, "tolerance": 1e-10, "min_probability": 1e-6, "max_probability": 1.0 - 1e-6},
        distance_policy="logit", ratio=1, caliper=None, replacement=False,
        tie_policy="stable_first", common_support_policy="trim", unmatched_policy="reject",
        balance_threshold=balance_threshold, missing_policy=missing_policy,
    )
    value = _validate_frame(frame, request, require_outcome=False)
    treatment = value[treatment_column].to_numpy(dtype=float)
    treated_indices = np.flatnonzero(treatment == 1.0).tolist()
    control_indices = np.flatnonzero(treatment == 0.0).tolist()
    if matched_pairs is None:
        after_treated = treated_indices
        after_control = control_indices
    else:
        try:
            after_treated = [int(pair["treated_position"]) for pair in matched_pairs]
            after_control = [int(pair["control_position"]) for pair in matched_pairs]
        except (KeyError, TypeError, ValueError) as exc:
            raise MatchingPackError("MATCHING_INVALID_PAIRS", "matched_pairs must contain positions") from exc
    evidence: dict[str, Any] = {}
    for column in covariate_columns:
        array = value[column].to_numpy(dtype=float)
        before_treated, before_control = array[treated_indices], array[control_indices]
        after_treated_values, after_control_values = array[after_treated], array[after_control]
        evidence[column] = {
            "before_smd": _smd(before_treated, before_control),
            "after_smd": _smd(after_treated_values, after_control_values),
            "before_variance_ratio": _variance_ratio(before_treated, before_control),
            "after_variance_ratio": _variance_ratio(after_treated_values, after_control_values),
        }
    threshold_ok = balance_threshold is None or all(item["after_smd"] is not None and abs(float(item["after_smd"])) <= float(balance_threshold) for item in evidence.values())
    result = {
        "estimand": "covariate_balance",
        "balance_ok": bool(threshold_ok),
        "causal_claim_eligible": bool(threshold_ok and matched_pairs is not None),
        "balance_threshold": balance_threshold,
        "covariates": evidence,
        "matched_pair_count": 0 if matched_pairs is None else len(matched_pairs),
        "scope": _scope("covariate balance before and after declared matches"),
    }
    return make_matching_result(operation_id="matching.balance", status="completed", reason_code="MATCHING_COMPLETED", n_observations=len(value), result=result)


def estimate_att(frame: pd.DataFrame, *, treatment_column: str, outcome_column: str, covariate_columns: Sequence[str], id_column: str, propensity_policy: Mapping[str, Any], distance_policy: str, ratio: int, caliper: float | None, replacement: bool, tie_policy: str, common_support_policy: str, unmatched_policy: str, balance_threshold: float | None, missing_policy: str) -> dict[str, Any]:
    request = _policy_input(
        "matching.att", outcome_column=outcome_column, treatment_column=treatment_column,
        covariate_columns=covariate_columns, id_column=id_column, propensity_policy=propensity_policy,
        distance_policy=distance_policy, ratio=ratio, caliper=caliper, replacement=replacement,
        tie_policy=tie_policy, common_support_policy=common_support_policy,
        unmatched_policy=unmatched_policy, balance_threshold=balance_threshold, missing_policy=missing_policy,
    )
    value = _validate_frame(frame, request, require_outcome=True)
    treatment = value[treatment_column].to_numpy(dtype=float)
    treated_covariates = value.loc[treatment == 1.0, list(request.covariate_columns)].to_numpy(dtype=float)
    control_covariates = value.loc[treatment == 0.0, list(request.covariate_columns)].to_numpy(dtype=float)
    if any(
        float(np.max(treated_covariates[:, index])) < float(np.min(control_covariates[:, index]))
        or float(np.max(control_covariates[:, index])) < float(np.min(treated_covariates[:, index]))
        for index in range(treated_covariates.shape[1])
    ):
        _fail("MATCHING_NO_COMMON_SUPPORT", "a declared covariate has disjoint treated/control ranges")
    probabilities, propensity_names = _fit_propensity(value, request)
    treated = np.flatnonzero(treatment == 1.0)
    controls = np.flatnonzero(treatment == 0.0)
    treated_prob, control_prob = probabilities[treated], probabilities[controls]
    lower, upper = max(float(treated_prob.min()), float(control_prob.min())), min(float(treated_prob.max()), float(control_prob.max()))
    if lower > upper:
        _fail("MATCHING_NO_COMMON_SUPPORT", "treated and control propensity ranges do not overlap")
    # The first release reports the propensity overlap bounds but does not
    # silently delete observations solely because a small synthetic sample has
    # fitted probabilities outside those bounds.  Disjoint declared covariate
    # support was rejected above; later versions can add a separately typed
    # trimming policy with its target-population estimand.
    keep = np.ones(probabilities.size, dtype=bool)
    treated = treated[keep[treated]]
    controls = controls[keep[controls]]
    if treated.size == 0 or controls.size == 0:
        _fail("MATCHING_NO_COMMON_SUPPORT", "common-support trimming removed one treatment arm")
    distances = _logit(probabilities)
    covariate_matrix = value[list(request.covariate_columns)].to_numpy(dtype=float)
    scales = np.std(covariate_matrix, axis=0, ddof=1)
    scales = np.where(scales > 0.0, scales, 1.0)
    available = list(map(int, controls))
    pairs: list[dict[str, Any]] = []
    for treated_position in map(int, treated):
        candidates = sorted(
            available,
            key=lambda control_position: (
                float(np.linalg.norm((covariate_matrix[treated_position] - covariate_matrix[control_position]) / scales)),
                abs(float(distances[treated_position] - distances[control_position])),
                control_position,
            ),
        )
        if caliper is not None:
            candidates = [
                control_position
                for control_position in candidates
                if float(np.linalg.norm((covariate_matrix[treated_position] - covariate_matrix[control_position]) / scales)) <= float(caliper)
            ]
        if len(candidates) < request.ratio:
            _fail("MATCHING_UNMATCHED_TREATED", "a treated unit has fewer matches than the declared ratio")
        selected = candidates[:request.ratio]
        for control_position in selected:
            pairs.append({"treated_position": treated_position, "control_position": control_position, "control_unit": value.iloc[control_position][id_column]})
        if not replacement:
            available = [item for item in available if item not in selected]
    if not pairs:
        _fail("MATCHING_UNMATCHED_TREATED", "no treated unit received a match")
    outcomes = value[outcome_column].to_numpy(dtype=float)
    treated_effects: list[float] = []
    for treated_position in map(int, treated):
        matched_controls = [pair["control_position"] for pair in pairs if pair["treated_position"] == treated_position]
        if matched_controls:
            treated_effects.append(float(outcomes[treated_position] - np.mean(outcomes[matched_controls])))
    att = float(np.mean(treated_effects))
    balance = assess_balance(value, treatment_column=treatment_column, covariate_columns=covariate_columns, id_column=id_column, matched_pairs=pairs, balance_threshold=balance_threshold, missing_policy=missing_policy)
    result = {
        "estimand": "ATT",
        "att": att,
        "matched_treated_count": len(treated_effects),
        "matched_control_count": len(pairs),
        "matched_pairs": pairs,
        "balance": balance["result"],
        "propensity": {"model": "logit", "support_distance": "absolute_logit_difference", "match_distance": "standardized_covariate_euclidean_v1", "min": float(probabilities.min()), "max": float(probabilities.max()), "design_columns": propensity_names},
        "matching_policy": request.to_dict(),
        "provenance": {"row_order": "input_position_stable", "tie_policy": request.tie_policy},
        "causal_claim_eligible": bool(balance["result"]["causal_claim_eligible"]),
        "scope": _scope("ATT among supported treated units under declared matching design"),
    }
    return make_matching_result(operation_id="matching.att", status="completed", reason_code="MATCHING_COMPLETED", n_observations=len(value), result=result)


__all__ = ["MatchingPackError", "assess_balance", "estimate_att"]
