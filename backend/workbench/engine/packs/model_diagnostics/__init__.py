"""Standalone diagnostics for explicit OLS-shaped inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

import numpy as np
import statsmodels.api as sm
from statsmodels.stats.diagnostic import acorr_breusch_godfrey, het_breuschpagan, het_white, linear_reset
from statsmodels.stats.outliers_influence import OLSInfluence, variance_inflation_factor

from workbench.contracts.model.model_diagnostics import ModelDiagnosticsInput, make_model_diagnostics_result
from workbench.engine.packs.p7_common import make_p7_scope


class ModelDiagnosticsPackError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _fail(code: str, message: str) -> None:
    raise ModelDiagnosticsPackError(code, message)


def _request(
    operation_id: str,
    *,
    response: Sequence[float],
    design: Sequence[Sequence[float]],
    residuals: Sequence[float],
    fitted_values: Sequence[float] | None,
    design_columns: Sequence[str],
    intercept: bool,
    intercept_column: str | None,
    model_metadata: Mapping[str, Any],
    time_order: str | None = None,
    time_values: Sequence[float] | None = None,
    lag: int | None = None,
    reset_powers: Sequence[int] | None = None,
    max_output_rows: int | None = None,
) -> ModelDiagnosticsInput:
    try:
        request = ModelDiagnosticsInput(
            operation_id=operation_id,
            response=tuple(response),
            design=tuple(tuple(row) for row in design),
            design_columns=tuple(design_columns),
            residuals=tuple(residuals),
            fitted_values=None if fitted_values is None else tuple(fitted_values),
            intercept=intercept,
            intercept_column=intercept_column,
            model_metadata=model_metadata,
            time_order=time_order,
            time_values=None if time_values is None else tuple(time_values),
            lag=lag,
            reset_powers=None if reset_powers is None else tuple(reset_powers),
            max_output_rows=max_output_rows,
        )
    except Exception as exc:
        if isinstance(exc, ModelDiagnosticsPackError):
            raise
        _fail("DIAGNOSTICS_INVALID_INPUT", str(exc))
    return request


def _arrays(request: ModelDiagnosticsInput) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray | None]:
    y = np.asarray(request.response, dtype=float)
    X = np.asarray(request.design, dtype=float)
    resid = np.asarray(request.residuals, dtype=float)
    fitted = None if request.fitted_values is None else np.asarray(request.fitted_values, dtype=float)
    if not np.isfinite(X).all() or not np.isfinite(y).all() or not np.isfinite(resid).all() or (fitted is not None and not np.isfinite(fitted).all()):
        _fail("DIAGNOSTICS_NON_FINITE_INPUT", "diagnostic inputs must be finite")
    if np.linalg.matrix_rank(X) < X.shape[1]:
        _fail("DIAGNOSTICS_SINGULAR_DESIGN", "design matrix is singular")
    if fitted is not None and not np.allclose(y - fitted, resid, rtol=1e-7, atol=1e-8):
        _fail("DIAGNOSTICS_FITTED_RESIDUAL_MISMATCH", "residuals do not equal response minus fitted values")
    return y, X, resid, fitted


def _scope(estimand: str, input_semantics: str, assumptions: list[str], limitations: list[str]) -> dict[str, Any]:
    return make_p7_scope(
        estimand=estimand,
        input_semantics=input_semantics,
        assumptions=assumptions,
        limitations=limitations,
        not_claimed=["the diagnostic does not classify the model as valid or invalid"],
        unsupported_extensions=["survey, clustered covariance, and non-OLS semantics are not included"],
    )


def _packet(operation_id: str, request: ModelDiagnosticsInput, result: dict[str, Any]) -> dict[str, Any]:
    return make_model_diagnostics_result(
        operation_id=operation_id,
        status="completed",
        reason_code="DIAGNOSTICS_COMPLETED",
        n_observations=len(request.response),
        design_columns=request.design_columns,
        result=result,
    )


def run_vif(
    design: Sequence[Sequence[float]], *, design_columns: Sequence[str], intercept: bool,
    intercept_column: str | None, model_metadata: Mapping[str, Any], max_output_rows: int | None = None,
) -> dict[str, Any]:
    n = len(design)
    request = _request(
        "diagnostics.vif", response=[0.0] * n, design=design, residuals=[0.0] * n,
        fitted_values=None, design_columns=design_columns, intercept=intercept,
        intercept_column=intercept_column, model_metadata=model_metadata, max_output_rows=max_output_rows,
    )
    _, X, _, _ = _arrays(request)
    variables = [name for name in request.design_columns if not (request.intercept and name == request.intercept_column)]
    vif = {}
    for name in variables:
        index = request.design_columns.index(name)
        try:
            value = float(variance_inflation_factor(X, index))
        except Exception as exc:
            _fail("DIAGNOSTICS_NUMERIC_FAILURE", f"VIF failed for {name}: {exc}")
        if not math.isfinite(value):
            _fail("DIAGNOSTICS_NUMERIC_FAILURE", f"VIF is non-finite for {name}")
        vif[name] = value
    condition_number = float(np.linalg.cond(X))
    return _packet("diagnostics.vif", request, {
        "intercept": {"included": request.intercept, "column": request.intercept_column, "excluded_from_vif": request.intercept},
        "variables": variables, "vif": vif,
        "condition": {"rank": int(np.linalg.matrix_rank(X)), "columns": int(X.shape[1]), "full_rank": True, "condition_number": condition_number},
        "scope": _scope("design-matrix collinearity evidence", "finite numeric OLS design matrix with explicit intercept metadata", ["the supplied design is the intended estimation design"], ["VIF is a collinearity diagnostic, not a model-validity decision"]),
    })


def _fit_request(operation_id: str, response: Sequence[float], design: Sequence[Sequence[float]], residuals: Sequence[float], fitted_values: Sequence[float] | None, **kwargs: Any) -> tuple[ModelDiagnosticsInput, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    request = _request(operation_id, response=response, design=design, residuals=residuals, fitted_values=fitted_values, **kwargs)
    y, X, resid, fitted = _arrays(request)
    if fitted is None:
        _fail("DIAGNOSTICS_INVALID_INPUT", "this diagnostic requires fitted_values")
    return request, y, X, resid, fitted


def run_breusch_pagan(response: Sequence[float], design: Sequence[Sequence[float]], residuals: Sequence[float], *, fitted_values: Sequence[float], **kwargs: Any) -> dict[str, Any]:
    request, y, X, resid, fitted = _fit_request("diagnostics.breusch_pagan", response, design, residuals, fitted_values, **kwargs)
    lm, lm_p, f_stat, f_p = het_breuschpagan(resid, X)
    df = int(X.shape[1] - (1 if request.intercept else 0))
    auxiliary_df = max(int(len(y) - X.shape[1]), 1)
    auxiliary = sm.OLS(resid**2, X).fit()
    return _packet("diagnostics.breusch_pagan", request, {
        "statistic": float(lm), "p_value": float(lm_p), "f_statistic": float(f_stat), "f_p_value": float(f_p), "df": df,
        "auxiliary_regression": {"df_residual": auxiliary_df, "r_squared": float(auxiliary.rsquared), "terms": list(request.design_columns)},
        "scope": _scope("heteroskedasticity evidence from a Breusch-Pagan auxiliary regression", "OLS response, design, fitted values, and residuals in matching row order", ["the supplied OLS residuals are the intended residuals", "the auxiliary variance model is linear in the declared design"], ["finite-sample power and omitted variance structure remain limitations"]),
    })


def run_white(response: Sequence[float], design: Sequence[Sequence[float]], residuals: Sequence[float], *, fitted_values: Sequence[float], **kwargs: Any) -> dict[str, Any]:
    request, y, X, resid, fitted = _fit_request("diagnostics.white", response, design, residuals, fitted_values, **kwargs)
    lm, lm_p, f_stat, f_p = het_white(resid, X)
    terms = [request.intercept_column] if request.intercept else []
    variable_indices = [i for i, name in enumerate(request.design_columns) if not (request.intercept and name == request.intercept_column)]
    terms.extend(request.design_columns[i] for i in variable_indices)
    for left, i in enumerate(variable_indices):
        terms.append(f"{request.design_columns[i]}^2")
        terms.extend(
            f"{request.design_columns[i]}:{request.design_columns[j]}"
            for j in variable_indices[left + 1 :]
        )
    auxiliary = sm.OLS(resid**2, X).fit()
    white_aux_df = max(int(len(y) - len(terms) + (1 if request.intercept else 0)), 1)
    return _packet("diagnostics.white", request, {
        "statistic": float(lm), "p_value": float(lm_p), "f_statistic": float(f_stat), "f_p_value": float(f_p), "df": int(lm if False else len(terms) - (1 if request.intercept else 0)),
        "auxiliary_regression": {"df_residual": white_aux_df, "r_squared": float(lm / len(y)), "terms": terms},
        "scope": _scope("heteroskedasticity evidence from a White auxiliary expansion", "OLS response, design, fitted values, and residuals in matching row order", ["the supplied OLS residuals are the intended residuals", "squared and cross terms are the declared White expansion"], ["the expansion can be high-dimensional and is not a model-validity decision"]),
    })


def run_breusch_godfrey(response: Sequence[float], design: Sequence[Sequence[float]], residuals: Sequence[float], *, fitted_values: Sequence[float], lag: int, time_order: str, **kwargs: Any) -> dict[str, Any]:
    request, y, X, resid, fitted = _fit_request("diagnostics.breusch_godfrey", response, design, residuals, fitted_values, lag=lag, time_order=time_order, **kwargs)
    fit = sm.OLS(y, X).fit()
    lm, lm_p, f_stat, f_p = acorr_breusch_godfrey(fit, nlags=lag)
    return _packet("diagnostics.breusch_godfrey", request, {
        "statistic": float(lm), "p_value": float(lm_p), "f_statistic": float(f_stat), "f_p_value": float(f_p), "df": int(lag),
        "lag": int(lag), "time_order": time_order,
        "scope": _scope("residual serial-correlation evidence at declared lags", "OLS residual sequence with explicit time order and lag", ["the row order is the declared time order", "the OLS specification is the intended base model"], ["the test does not diagnose all forms of dependence"]),
    })


def run_reset(response: Sequence[float], design: Sequence[Sequence[float]], residuals: Sequence[float], *, fitted_values: Sequence[float], reset_powers: Sequence[int], **kwargs: Any) -> dict[str, Any]:
    request, y, X, resid, fitted = _fit_request("diagnostics.reset", response, design, residuals, fitted_values, reset_powers=reset_powers, **kwargs)
    fit = sm.OLS(y, X).fit()
    outcome = linear_reset(fit, power=tuple(reset_powers), use_f=True)
    return _packet("diagnostics.reset", request, {
        "f_statistic": float(outcome.fvalue), "p_value": float(outcome.pvalue), "powers": list(reset_powers), "df_num": len(reset_powers), "df_denom": int(fit.df_resid - len(reset_powers)),
        "scope": _scope("functional-form evidence from a RESET augmentation", "OLS response, design, fitted values, residuals, and explicit fitted-power set", ["the base OLS design is correctly specified for the declared diagnostic", "the supplied powers are predeclared"], ["a non-significant result does not prove functional-form correctness"]),
    })


def run_influence(response: Sequence[float], design: Sequence[Sequence[float]], residuals: Sequence[float], *, fitted_values: Sequence[float], max_output_rows: int | None = None, **kwargs: Any) -> dict[str, Any]:
    request, y, X, resid, fitted = _fit_request("diagnostics.influence", response, design, residuals, fitted_values, max_output_rows=max_output_rows, **kwargs)
    fit = sm.OLS(y, X).fit()
    influence = OLSInfluence(fit)
    cooks = np.asarray(influence.cooks_distance[0], dtype=float)
    selected = list(range(len(y)))
    truncated = False
    if max_output_rows is not None and max_output_rows < len(y):
        selected = sorted(selected, key=lambda i: (-cooks[i], i))[:max_output_rows]
        selected = sorted(selected)
        truncated = True
    rows = []
    for i in selected:
        rows.append({
            "observation_index": i,
            "leverage": float(influence.hat_matrix_diag[i]),
            "cooks_distance": float(cooks[i]),
            "studentized_residual_internal": float(influence.resid_studentized_internal[i]),
            "studentized_residual_external": float(influence.resid_studentized_external[i]),
            "dfbetas": {name: float(value) for name, value in zip(request.design_columns, influence.dfbetas[i])},
        })
    return _packet("diagnostics.influence", request, {
        "observations": rows, "rows_returned": len(rows), "rows_truncated": truncated,
        "scope": _scope("observation-level OLS influence evidence", "OLS response, design, fitted values, and residuals in matching row order", ["the supplied OLS fit is the intended base model"], ["influence evidence is not an automatic outlier deletion rule"]),
    })


def _run_typed_request(request: ModelDiagnosticsInput) -> dict[str, Any]:
    """Execute one already-validated request at the Agent seam."""

    common = {
        "design_columns": request.design_columns,
        "intercept": request.intercept,
        "intercept_column": request.intercept_column,
        "model_metadata": request.model_metadata,
    }
    if request.operation_id == "diagnostics.vif":
        return run_vif(request.design, max_output_rows=request.max_output_rows, **common)
    if request.operation_id == "diagnostics.breusch_pagan":
        return run_breusch_pagan(request.response, request.design, request.residuals, fitted_values=request.fitted_values or (), **common)
    if request.operation_id == "diagnostics.white":
        return run_white(request.response, request.design, request.residuals, fitted_values=request.fitted_values or (), **common)
    if request.operation_id == "diagnostics.breusch_godfrey":
        return run_breusch_godfrey(request.response, request.design, request.residuals, fitted_values=request.fitted_values or (), lag=request.lag or 1, time_order=request.time_order or "declared_order", **common)
    if request.operation_id == "diagnostics.reset":
        return run_reset(request.response, request.design, request.residuals, fitted_values=request.fitted_values or (), reset_powers=request.reset_powers or (2,), **common)
    return run_influence(request.response, request.design, request.residuals, fitted_values=request.fitted_values or (), max_output_rows=request.max_output_rows, **common)


def run_model_diagnostics(operation_id: str | ModelDiagnosticsInput, **kwargs: Any) -> dict[str, Any]:
    if isinstance(operation_id, ModelDiagnosticsInput):
        if kwargs:
            _fail("DIAGNOSTICS_INVALID_INPUT", "a typed diagnostics request cannot be combined with raw kwargs")
        return _run_typed_request(operation_id)
    dispatch = {
        "diagnostics.vif": run_vif,
        "diagnostics.breusch_pagan": run_breusch_pagan,
        "diagnostics.white": run_white,
        "diagnostics.breusch_godfrey": run_breusch_godfrey,
        "diagnostics.reset": run_reset,
        "diagnostics.influence": run_influence,
    }
    if operation_id not in dispatch:
        _fail("DIAGNOSTICS_INVALID_INPUT", "operation_id is not declared")
    # The future Agent seam must pass a typed request; this convenience dispatcher
    # deliberately does not accept an untyped bag of raw fitted arrays.
    if kwargs:
        _fail("DIAGNOSTICS_NUMERIC_FAILURE", "run_model_diagnostics requires a typed request boundary")
    return dispatch[operation_id](**kwargs)


__all__ = [
    "ModelDiagnosticsPackError", "run_breusch_godfrey", "run_breusch_pagan", "run_influence",
    "run_model_diagnostics", "run_reset", "run_vif", "run_white",
]
