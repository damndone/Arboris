"""Statsmodels-backed GLM extension kernels with explicit estimand layers.

The public functions accept arrays/data frames, but every normal result is
wrapped in the closed request/result contract.  The pack never infers a zero
process, link, missing-data policy, or formula from the data.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any
import warnings

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import norm
import statsmodels.api as sm
from statsmodels.discrete.count_model import ZeroInflatedNegativeBinomialP, ZeroInflatedPoisson
from statsmodels.othermod.betareg import BetaModel

from workbench.contracts.model.glm_extensions import GLMExtensionRequest, GLMExtensionResultEnvelope
from workbench.engine.packs.p7_common import make_p7_scope


class GLMExtensionPackError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _fail(reason_code: str, message: str) -> None:
    raise GLMExtensionPackError(reason_code, message)


def _defaults(operation_id: str, predictor_columns: Sequence[str], **overrides: Any) -> GLMExtensionRequest:
    if operation_id == "glm.beta":
        response = "strict_unit_interval_v1"
        zero_process = "not_applicable_v1"
        count_link = zero_link = positive_link = "not_applicable"
        mean_link, precision_link = "logit", "log"
    elif operation_id.startswith("glm.zero_inflated"):
        response = "nonnegative_integer_count_v1"
        zero_process = "mixture_structural_zero_v1"
        count_link, zero_link = "log", "logit"
        positive_link = mean_link = precision_link = "not_applicable"
    else:
        response = "nonnegative_integer_count_v1"
        zero_process = "separate_zero_gate_truncated_count_v1"
        count_link, positive_link, mean_link, precision_link = "not_applicable", "log", "not_applicable", "not_applicable"
        zero_link = "logit"
    value: dict[str, Any] = {
        "operation_id": operation_id,
        "predictor_columns": list(predictor_columns),
        "zero_predictor_columns": None,
        "positive_predictor_columns": None,
        "precision_predictor_columns": None,
        "matrix_semantics": "rows_are_observations_columns_are_predictors_v1",
        "response_semantics": response,
        "zero_process_semantics": zero_process,
        "count_link": count_link,
        "zero_link": zero_link,
        "positive_count_link": positive_link,
        "mean_link": mean_link,
        "precision_link": precision_link,
        "intercept": True,
        "missing_policy": "reject_nonfinite_v1",
        "offset_policy": "none_v1",
        "optimizer": "bfgs",
        "maxiter": 300,
        "tolerance": 1e-8,
        "max_abs_linear_predictor": 30.0,
    }
    value.update(overrides)
    try:
        return GLMExtensionRequest.from_dict(value)
    except Exception as exc:
        if isinstance(exc, GLMExtensionPackError):
            raise
        _fail("GLM_BAD_INPUT", str(exc))


def _numeric_response(value: Any, *, kind: str) -> np.ndarray:
    if isinstance(value, (str, bytes)):
        _fail("GLM_BAD_INPUT", "response must be a one-dimensional numeric sequence")
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise GLMExtensionPackError("GLM_BAD_INPUT", "response must be numeric") from exc
    if array.ndim != 1 or array.size < 2:
        _fail("GLM_BAD_INPUT", "response must contain at least two observations")
    if not np.isfinite(array).all():
        _fail("GLM_NONFINITE_INPUT", "response must be finite")
    if kind == "count":
        if np.any(array < 0.0) or np.any(array != np.floor(array)):
            _fail("GLM_INVALID_COUNT", "count responses must be nonnegative integers")
    else:
        if np.any(array <= 0.0) or np.any(array >= 1.0):
            _fail("GLM_BETA_BOUNDARY_RESPONSE", "Beta responses must be strictly inside (0, 1)")
    if array.size > 100_000:
        _fail("GLM_OUTPUT_TOO_LARGE", "response exceeds the supported observation bound")
    return array


def _frame_and_design(X: Any, request: GLMExtensionRequest, columns: Sequence[str] | None = None) -> tuple[pd.DataFrame, np.ndarray, list[str]]:
    if not isinstance(X, pd.DataFrame):
        _fail("GLM_BAD_INPUT", "predictors must be a pandas DataFrame with named columns")
    selected = list(columns or request.predictor_columns)
    if not selected or any(column not in X.columns for column in selected):
        _fail("GLM_MISSING_PREDICTOR", "every declared predictor column must exist")
    if X[selected].isna().any().any():
        _fail("GLM_NONFINITE_INPUT", "predictors must be finite")
    try:
        matrix = X[selected].to_numpy(dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise GLMExtensionPackError("GLM_NON_NUMERIC_PREDICTOR", "predictors must be numeric") from exc
    if not np.isfinite(matrix).all():
        _fail("GLM_NONFINITE_INPUT", "predictors must be finite")
    if request.intercept:
        matrix = sm.add_constant(matrix, has_constant="add")
        names = ["const", *selected]
    else:
        names = selected
    if np.linalg.matrix_rank(matrix) < matrix.shape[1]:
        _fail("GLM_SINGULAR_DESIGN", "declared predictor design is rank deficient")
    return X, matrix, names


def _process_columns(request: GLMExtensionRequest, field: str) -> tuple[str, ...]:
    value = getattr(request, field)
    return tuple(value or request.predictor_columns)


def _fit_kwargs(request: GLMExtensionRequest) -> dict[str, Any]:
    return {"method": request.optimizer, "maxiter": request.maxiter, "disp": False}


def _check_linear_predictor(value: np.ndarray, request: GLMExtensionRequest, label: str) -> None:
    if not np.isfinite(value).all() or np.max(np.abs(value)) > request.max_abs_linear_predictor:
        _fail("GLM_LINEAR_PREDICTOR_BOUND", f"{label} exceeds max_abs_linear_predictor")


def _coefficient_map(params: Any, bse: Any, pvalues: Any, cov: Any, names: Sequence[str]) -> dict[str, dict[str, Any]]:
    values = np.asarray(params, dtype=float)
    errors = np.asarray(bse, dtype=float)
    probabilities = np.asarray(pvalues, dtype=float)
    covariance = np.asarray(cov, dtype=float)
    output: dict[str, dict[str, Any]] = {}
    for index, name in enumerate(names):
        estimate = float(values[index])
        se = float(errors[index])
        p_value = float(probabilities[index])
        if not all(math.isfinite(value) for value in (estimate, se, p_value)):
            _fail("GLM_NUMERICAL_FAILURE", "coefficient evidence is non-finite")
        output[str(name)] = {
            "estimate": estimate,
            "standard_error": se,
            "p_value": p_value,
            "ci_lower": estimate - 1.959963984540054 * se,
            "ci_upper": estimate + 1.959963984540054 * se,
        }
    return output


def _scope(
    model_family: str,
    *,
    count: bool,
    approximate_positive_count_inference: bool = False,
) -> dict[str, Any]:
    if count:
        assumptions = [
            "the declared count and zero-process semantics match the scientific data-generating question",
            "the supplied predictor design and maximum linear-predictor policy are adequate",
        ]
        limitations = [
            "zero-process and count-process parameters are conditional model quantities, not causal effects",
            "finite-sample convergence, separation, and overdispersion diagnostics remain model-dependent",
        ]
        if approximate_positive_count_inference:
            limitations.append(
                "positive-count standard errors use a BFGS inverse-Hessian approximation and p-values use an approximate normal Wald reference"
            )
        unsupported = ["automatic model selection, offsets, exposure, formula parsing, and random effects"]
    else:
        assumptions = [
            "the response is a continuous proportion strictly inside (0, 1)",
            "the logit mean and log precision links are appropriate for the declared design",
        ]
        limitations = [
            "Beta regression does not represent exact zero/one mass or causal identification",
            "precision is a separate distributional parameter and is not a second mean effect",
        ]
        unsupported = ["zero/one-inflated Beta models, formula parsing, and automatic model selection"]
    return make_p7_scope(
        estimand=f"{model_family} parameter layers and predicted response summaries",
        input_semantics="finite named predictor matrix with explicit response, link, and optimizer policies",
        assumptions=assumptions,
        limitations=limitations,
        not_claimed=["a fitted coefficient is not an unconditional causal effect", "successful optimization does not prove model adequacy"],
        unsupported_extensions=unsupported,
    )


def _base_result(request: GLMExtensionRequest, *, family: str, y: np.ndarray, fit: Mapping[str, Any], coefficients: Mapping[str, Any], mean: Mapping[str, Any], zero: Mapping[str, Any], diagnostics: Mapping[str, Any], inference: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result = {
        "status": "completed",
        "reason_code": "ANALYSIS_COMPLETED",
        "model_family": family,
        "n_observations": int(y.size),
        "predictor_columns": list(request.predictor_columns),
        "policy": request.to_dict(),
        "fit": dict(fit),
        "coefficient_estimands": dict(coefficients),
        "mean_estimands": dict(mean),
        "zero_probability_estimands": dict(zero),
        "scope": _scope(
            family,
            count=request.operation_id != "glm.beta",
            approximate_positive_count_inference=inference is not None,
        ),
        "diagnostics": dict(diagnostics),
    }
    if inference is not None:
        result["inference"] = dict(inference)
    return result


def _packet(operation_id: str, result: Mapping[str, Any]) -> dict[str, Any]:
    return GLMExtensionResultEnvelope(operation_id=operation_id, result=result).to_dict()


def _fit_zero_inflated(y: Any, X: Any, *, operation_id: str, predictor_columns: Sequence[str], **options: Any) -> dict[str, Any]:
    request = _defaults(operation_id, predictor_columns, **options)
    response = _numeric_response(y, kind="count")
    _, main_design, main_names = _frame_and_design(X, request)
    zero_columns = _process_columns(request, "zero_predictor_columns")
    _, zero_design, zero_names = _frame_and_design(X, request, zero_columns)
    if operation_id == "glm.zero_inflated_poisson":
        model = ZeroInflatedPoisson(response, main_design, exog_infl=zero_design, inflation="logit")
    else:
        model = ZeroInflatedNegativeBinomialP(response, main_design, exog_infl=zero_design, inflation="logit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fitted = model.fit(**_fit_kwargs(request))
    except (ArithmeticError, FloatingPointError, ValueError, np.linalg.LinAlgError) as exc:
        _fail("GLM_NUMERICAL_FAILURE", f"zero-inflated fit failed: {exc}")
    converged = bool(getattr(fitted, "mle_retvals", {}).get("converged", True))
    covariance = np.asarray(fitted.cov_params(), dtype=float)
    covariance_finite = bool(np.isfinite(covariance).all())
    if not converged:
        _fail("GLM_NONCONVERGENCE", "zero-inflated optimizer did not converge")
    if not covariance_finite:
        _fail("GLM_NUMERICAL_FAILURE", "zero-inflated covariance is non-finite")
    p = len(main_names)
    _check_linear_predictor(zero_design @ np.asarray(fitted.params[:len(zero_names)], dtype=float), request, "zero process")
    _check_linear_predictor(main_design @ np.asarray(fitted.params[len(zero_names):len(zero_names) + p], dtype=float), request, "count process")
    zero_coefficients = _coefficient_map(fitted.params[:len(zero_names)], fitted.bse[:len(zero_names)], fitted.pvalues[:len(zero_names)], covariance[:len(zero_names), :len(zero_names)], zero_names)
    count_coefficients = _coefficient_map(fitted.params[len(zero_names):len(zero_names) + p], fitted.bse[len(zero_names):len(zero_names) + p], fitted.pvalues[len(zero_names):len(zero_names) + p], covariance[len(zero_names):len(zero_names) + p, len(zero_names):len(zero_names) + p], main_names)
    coefficients: dict[str, Any] = {"zero": zero_coefficients, "count": count_coefficients}
    if operation_id.endswith("negative_binomial"):
        alpha = float(fitted.params[-1])
        if not math.isfinite(alpha):
            _fail("GLM_NUMERICAL_FAILURE", "negative-binomial dispersion is non-finite")
        coefficients["dispersion"] = {"alpha": {"estimate": alpha}}
    predicted_mean = np.asarray(fitted.predict(which="mean"), dtype=float)
    predicted_zero = np.asarray(fitted.predict(which="prob-zero"), dtype=float)
    if not np.isfinite(predicted_mean).all() or not np.isfinite(predicted_zero).all():
        _fail("GLM_NUMERICAL_FAILURE", "predicted GLM summaries are non-finite")
    result = _base_result(
        request,
        family=operation_id.removeprefix("glm."),
        y=response,
        fit={"converged": converged, "optimizer": request.optimizer, "iterations": int(getattr(fitted, "mle_retvals", {}).get("iterations", 0) or 0)},
        coefficients=coefficients,
        mean={
            "conditional_count_mean": {"sample_mean": float(np.mean(np.asarray(fitted.predict(which="mean-main"), dtype=float)))},
            "unconditional_mean": {"sample_mean": float(predicted_mean.mean())},
        },
        zero={"observed_zero_probability": {"sample_mean": float(predicted_zero.mean())}},
        diagnostics={"covariance_finite": covariance_finite, "zero_design_columns": zero_names, "count_design_columns": main_names},
    )
    return _packet(operation_id, result)


def _gate_fit(response: np.ndarray, design: np.ndarray, names: Sequence[str], request: GLMExtensionRequest) -> Any:
    positive = (response > 0).astype(float)
    if positive.min() == positive.max():
        _fail("GLM_DEGENERATE_ZERO_PROCESS", "both zero and positive observations are required")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fitted = sm.GLM(positive, design, family=sm.families.Binomial()).fit(maxiter=request.maxiter, tol=request.tolerance, disp=0)
    except (ArithmeticError, FloatingPointError, ValueError, np.linalg.LinAlgError) as exc:
        _fail("GLM_NUMERICAL_FAILURE", f"zero gate fit failed: {exc}")
    if not bool(getattr(fitted, "converged", True)):
        _fail("GLM_NONCONVERGENCE", "zero gate optimizer did not converge")
    if not np.isfinite(np.asarray(fitted.cov_params(), dtype=float)).all():
        _fail("GLM_NUMERICAL_FAILURE", "zero gate covariance is non-finite")
    return fitted


def _truncated_nll(parameters: np.ndarray, positive_y: np.ndarray, design: np.ndarray, *, family: str, alpha: float | None) -> float:
    eta = np.clip(design @ parameters, -30.0, 30.0)
    mu = np.exp(eta)
    if family == "poisson":
        log_pmf = positive_y * eta - mu - gammaln(positive_y + 1.0)
        log_positive = np.log(-np.expm1(-mu))
    else:
        assert alpha is not None
        r = 1.0 / alpha
        p = 1.0 / (1.0 + alpha * mu)
        log_pmf = gammaln(positive_y + r) - gammaln(r) - gammaln(positive_y + 1.0) + r * np.log(p) + positive_y * np.log1p(-p)
        log_positive = np.log1p(-np.exp(-r * np.log1p(alpha * mu)))
    value = -float(np.sum(log_pmf - log_positive))
    return value if math.isfinite(value) else 1e300


def _fit_truncated(response: np.ndarray, design: np.ndarray, names: Sequence[str], *, family: str, request: GLMExtensionRequest) -> tuple[np.ndarray, np.ndarray, float | None, bool]:
    positive = response > 0
    y_positive = response[positive]
    X_positive = design[positive]
    if y_positive.size < max(5, design.shape[1] + 2):
        _fail("GLM_TOO_FEW_POSITIVE", "the positive truncated process needs more observations than parameters")
    initial_fit = sm.GLM(y_positive, X_positive, family=sm.families.Poisson()).fit(maxiter=request.maxiter, tol=request.tolerance, disp=0)
    initial = np.asarray(initial_fit.params, dtype=float)
    alpha = None
    if family == "negative_binomial":
        start = np.r_[initial, math.log(0.5)]
        fit = minimize(
            lambda theta: _truncated_nll(theta[:-1], y_positive, X_positive, family=family, alpha=float(np.clip(np.exp(theta[-1]), 1e-8, 1e6))),
            start,
            method="BFGS",
            options={"maxiter": request.maxiter, "gtol": request.tolerance},
        )
        alpha = float(np.clip(np.exp(fit.x[-1]), 1e-8, 1e6)) if np.isfinite(fit.x).all() else None
        parameters = np.asarray(fit.x[:-1], dtype=float) if np.isfinite(fit.x).all() else np.asarray(initial, dtype=float)
    else:
        fit = minimize(
            lambda params: _truncated_nll(params, y_positive, X_positive, family=family, alpha=None),
            initial,
            method="BFGS",
            options={"maxiter": request.maxiter, "gtol": request.tolerance},
        )
        parameters = np.asarray(fit.x, dtype=float)
    if not fit.success or not np.isfinite(fit.x).all():
        _fail("GLM_NONCONVERGENCE", "truncated count optimizer did not converge")
    # Numerical Hessian inversion is reported only when finite.  The response
    # coefficients are still returned; no fictitious standard errors are made.
    hessian_inverse = np.asarray(getattr(fit, "hess_inv", np.zeros((len(fit.x), len(fit.x)))), dtype=float)
    if hessian_inverse.ndim == 0:
        hessian_inverse = np.eye(len(fit.x))
    se = np.sqrt(np.maximum(np.diag(hessian_inverse)[:len(parameters)], 0.0))
    return parameters, se, alpha, True


def _fit_hurdle(y: Any, X: Any, *, operation_id: str, predictor_columns: Sequence[str], **options: Any) -> dict[str, Any]:
    request = _defaults(operation_id, predictor_columns, **options)
    response = _numeric_response(y, kind="count")
    _, gate_design, gate_names = _frame_and_design(X, request, _process_columns(request, "zero_predictor_columns"))
    _, positive_design, positive_names = _frame_and_design(X, request, _process_columns(request, "positive_predictor_columns"))
    gate_fit = _gate_fit(response, gate_design, gate_names, request)
    _check_linear_predictor(gate_design @ np.asarray(gate_fit.params, dtype=float), request, "zero gate")
    positive_probability = np.asarray(gate_fit.predict(gate_design), dtype=float)
    zero_probability = 1.0 - positive_probability
    coefficients: dict[str, Any] = {
        "zero": _coefficient_map(gate_fit.params, gate_fit.bse, gate_fit.pvalues, gate_fit.cov_params(), gate_names),
    }
    family = "poisson" if operation_id.endswith("poisson") else "negative_binomial"
    count_params, count_se, alpha, _ = _fit_truncated(response, positive_design, positive_names, family=family, request=request)
    _check_linear_predictor(positive_design @ count_params, request, "positive count process")
    count_p = 2.0 * norm.sf(np.abs(np.divide(count_params, count_se, out=np.zeros_like(count_params), where=count_se > 0.0)))
    coefficient_count: dict[str, dict[str, Any]] = {}
    for index, name in enumerate(positive_names):
        estimate = float(count_params[index])
        standard_error = float(count_se[index])
        coefficient_count[name] = {"estimate": estimate, "standard_error": standard_error, "p_value": float(count_p[index]) if math.isfinite(float(count_p[index])) else None}
    coefficients["positive_count"] = coefficient_count
    if alpha is not None:
        coefficients["dispersion"] = {"alpha": {"estimate": alpha}}
    mu = np.exp(np.clip(positive_design @ count_params, -30.0, 30.0))
    if family == "poisson":
        positive_mean = mu / (-np.expm1(-mu))
    else:
        positive_mean = mu / (1.0 - np.exp(-(1.0 / alpha) * np.log1p(alpha * mu)))
    unconditional = positive_probability * positive_mean
    if not np.isfinite(unconditional).all() or not np.isfinite(zero_probability).all():
        _fail("GLM_NUMERICAL_FAILURE", "hurdle predicted summaries are non-finite")
    result = _base_result(
        request,
        family=operation_id.removeprefix("glm."),
        y=response,
        fit={"converged": True, "optimizer": request.optimizer},
        coefficients=coefficients,
        mean={
            "positive_truncated_count_mean": {"sample_mean": float(positive_mean.mean())},
            "unconditional_mean": {
                "sample_mean": float(unconditional.mean()),
                "factorized_marginal_product": float((1.0 - zero_probability.mean()) * positive_mean.mean()),
            },
        },
        zero={
            "zero_gate_probability": {"sample_mean": float(zero_probability.mean())},
            "observed_zero_probability": {"sample_mean": float(zero_probability.mean())},
        },
        diagnostics={"covariance_finite": bool(np.isfinite(np.asarray(gate_fit.cov_params(), dtype=float)).all()), "zero_design_columns": gate_names, "positive_count_design_columns": positive_names},
        inference={
            "positive_count": {
                "standard_error_method": "bfgs_inverse_hessian_approximation",
                "p_value_method": "normal_wald_approximation",
                "p_value_status": "approximate",
            }
        },
    )
    return _packet(operation_id, result)


def _fit_beta(y: Any, X: Any, *, predictor_columns: Sequence[str], **options: Any) -> dict[str, Any]:
    request = _defaults("glm.beta", predictor_columns, **options)
    response = _numeric_response(y, kind="beta")
    _, design, names = _frame_and_design(X, request)
    model = BetaModel(response, design)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fitted = model.fit(method=request.optimizer, maxiter=request.maxiter, disp=False, tol=request.tolerance)
    except (ArithmeticError, FloatingPointError, ValueError, np.linalg.LinAlgError) as exc:
        raise GLMExtensionPackError("GLM_NUMERICAL_FAILURE", f"Beta fit failed: {exc}") from exc
    if not bool(getattr(fitted, "mle_retvals", {}).get("converged", True)):
        _fail("GLM_NONCONVERGENCE", "Beta optimizer did not converge")
    covariance = np.asarray(fitted.cov_params(), dtype=float)
    if not np.isfinite(covariance).all() or not np.isfinite(np.asarray(fitted.params, dtype=float)).all():
        _fail("GLM_NUMERICAL_FAILURE", "Beta covariance or coefficients are non-finite")
    _check_linear_predictor(design @ np.asarray(fitted.params[:len(names)], dtype=float), request, "Beta mean process")
    coefficients = {"mean": _coefficient_map(fitted.params[:len(names)], fitted.bse[:len(names)], fitted.pvalues[:len(names)], covariance[:len(names), :len(names)], names), "precision": {"precision": {"estimate": float(fitted.params[-1]), "standard_error": float(fitted.bse[-1]), "p_value": float(fitted.pvalues[-1])}}}
    predicted = np.asarray(fitted.predict(design), dtype=float)
    result = _base_result(
        request,
        family="beta",
        y=response,
        fit={"converged": True, "optimizer": request.optimizer},
        coefficients=coefficients,
        mean={"expected_response": {"sample_mean": float(predicted.mean())}},
        zero={"not_applicable": {"applicable": False}},
        diagnostics={"covariance_finite": True, "design_columns": names},
    )
    return _packet("glm.beta", result)


def fit_zero_inflated_poisson(y: Any, X: Any, *, predictor_columns: Sequence[str], **options: Any) -> dict[str, Any]:
    if "callback" in options:
        _fail("GLM_BAD_INPUT", "callbacks are not accepted by the typed GLM pack")
    return _fit_zero_inflated(y, X, operation_id="glm.zero_inflated_poisson", predictor_columns=predictor_columns, **options)


def fit_zero_inflated_negative_binomial(y: Any, X: Any, *, predictor_columns: Sequence[str], **options: Any) -> dict[str, Any]:
    if "callback" in options:
        _fail("GLM_BAD_INPUT", "callbacks are not accepted by the typed GLM pack")
    return _fit_zero_inflated(y, X, operation_id="glm.zero_inflated_negative_binomial", predictor_columns=predictor_columns, **options)


def fit_hurdle_poisson(y: Any, X: Any, *, predictor_columns: Sequence[str], **options: Any) -> dict[str, Any]:
    if options.get("zero_process_semantics") == "auto":
        _fail("GLM_ZERO_PROCESS_POLICY", "zero_process_semantics must be explicit")
    return _fit_hurdle(y, X, operation_id="glm.hurdle_poisson", predictor_columns=predictor_columns, **options)


def fit_hurdle_negative_binomial(y: Any, X: Any, *, predictor_columns: Sequence[str], **options: Any) -> dict[str, Any]:
    if options.get("zero_process_semantics") == "auto":
        _fail("GLM_ZERO_PROCESS_POLICY", "zero_process_semantics must be explicit")
    return _fit_hurdle(y, X, operation_id="glm.hurdle_negative_binomial", predictor_columns=predictor_columns, **options)


def fit_beta(y: Any, X: Any, *, predictor_columns: Sequence[str], **options: Any) -> dict[str, Any]:
    if "callback" in options:
        _fail("GLM_BAD_INPUT", "callbacks are not accepted by the typed GLM pack")
    return _fit_beta(y, X, predictor_columns=predictor_columns, **options)


def _error_packet(operation_id: str, reason_code: str, message: str, *, status: str = "rejected") -> dict[str, Any]:
    return _packet(operation_id if operation_id in {"glm.zero_inflated_poisson", "glm.zero_inflated_negative_binomial", "glm.hurdle_poisson", "glm.hurdle_negative_binomial", "glm.beta"} else "glm.beta", {"status": status, "reason_code": reason_code, "error_code": reason_code, "message": message})


def run_glm_extension(operation_id: str, y: Any, X: Any, *, predictor_columns: Sequence[str], **options: Any) -> dict[str, Any]:
    dispatch = {
        "glm.zero_inflated_poisson": fit_zero_inflated_poisson,
        "glm.zero_inflated_negative_binomial": fit_zero_inflated_negative_binomial,
        "glm.hurdle_poisson": fit_hurdle_poisson,
        "glm.hurdle_negative_binomial": fit_hurdle_negative_binomial,
        "glm.beta": fit_beta,
    }
    if operation_id not in dispatch:
        return _error_packet("glm.beta", "GLM_BAD_INPUT", "operation_id is not declared")
    if isinstance(X, str) or "~" in str(X):
        return _error_packet(operation_id, "GLM_BAD_INPUT", "formula strings are not accepted; pass a named design matrix")
    try:
        return dispatch[operation_id](y, X, predictor_columns=predictor_columns, **options)
    except GLMExtensionPackError as exc:
        status = "failed" if exc.reason_code in {"GLM_NONCONVERGENCE", "GLM_NUMERICAL_FAILURE"} else "rejected"
        return _error_packet(operation_id, exc.reason_code, str(exc), status=status)


__all__ = ["GLMExtensionPackError", "fit_beta", "fit_hurdle_negative_binomial", "fit_hurdle_poisson", "fit_zero_inflated_negative_binomial", "fit_zero_inflated_poisson", "run_glm_extension"]
