"""Negative binomial ML and tightly converged count GLMs.

NB2 has variance mu + alpha * mu**2; NB1 has variance (1 + delta) * mu.
Joint fits retain statsmodels' natural-scale ancillary parameter in the fitted
object, while the presentation separates it from regression coefficients.
"""
from __future__ import annotations

import math
import json

import numpy as np
import statsmodels.formula.api as smf
from scipy.special import gammaln
from scipy.stats import chi2, norm
from statsmodels.genmod import families

from .normalize import normalize_statsmodels_result

GLM_TOLERANCE = 1e-12
ML_TOLERANCE = 1e-8

# Response support belongs to the family, independently of its link or alpha.
# Poisson and fixed-NB likelihoods allow nonnegative fractional responses.
GLM_RESPONSE_SUPPORT = {families.Poisson: (0., None),
                        families.NegativeBinomial: (0., None),
                        families.Binomial: (0., 1.)}


def _validate_alpha(alpha: float) -> float:
    try:
        value = float(alpha)
    except (TypeError, ValueError) as exc:
        raise ValueError("NB_ALPHA_INVALID: fixed alpha must be a finite positive number.") from exc
    if not np.isfinite(value) or value <= 0:
        raise ValueError("NB_ALPHA_INVALID: fixed alpha must be finite and strictly positive.")
    return value


def _validate_counts(endog):
    if not np.all(np.isfinite(endog)) or np.any(endog < 0) or np.any(endog != np.floor(endog)):
        raise ValueError("NB_COUNTS_INVALID: response must contain finite nonnegative integer counts.")


def _validate_glm_response(frame, formula, family, error_code):
    from patsy import dmatrices

    bounds = next((support for family_type, support in GLM_RESPONSE_SUPPORT.items()
                   if isinstance(family, family_type)), None)
    if bounds is None:
        return
    # Match Patsy's complete-case estimation sample without discarding illegal
    # finite or infinite values. Validate before constructing/fitting the GLM.
    endog, _ = dmatrices(formula, frame, return_type="dataframe")
    response = np.asarray(endog)
    lower, upper = bounds
    if (not np.all(np.isfinite(response)) or np.any(response < lower)
            or (upper is not None and np.any(response > upper))):
        raise ValueError(f"{error_code}: estimation response is outside the family's finite support.")


def _require_finite(value, code, description):
    if not np.all(np.isfinite(np.asarray(value))):
        raise ValueError(f"{code}: {description} contains nonfinite values.")


def _information_covariance(information, code):
    _require_finite(information, code, "Information matrix")
    try:
        np.linalg.cholesky(information)
        covariance = np.linalg.inv(information)
    except np.linalg.LinAlgError as exc:
        raise ValueError(f"{code}: regular positive-definite information is unavailable.") from exc
    _require_finite(covariance, code, "Covariance matrix")
    try:
        np.linalg.cholesky(covariance)
    except np.linalg.LinAlgError as exc:
        raise ValueError(f"{code}: positive-definite covariance is unavailable.") from exc
    return covariance


def _validate_glm_result(fitted):
    _require_finite(fitted.params, "GLM_RESULT_NONFINITE", "Regression parameters")
    _require_finite(fitted.llf, "GLM_RESULT_NONFINITE", "Log likelihood")
    _require_finite(fitted.cov_params(), "GLM_RESULT_NONFINITE", "Covariance matrix")


def _glm_fitted(frame, formula, family, *, response_error_code="GLM_RESPONSE_INVALID"):
    _validate_glm_response(frame, formula, family, response_error_code)
    model = smf.glm(formula=formula, data=frame, family=family)
    fitted = model.fit(maxiter=1000, tol=GLM_TOLERANCE, tol_criterion="params")
    if not fitted.converged:
        raise ValueError("GLM_NOT_CONVERGED: IRLS failed to converge.")
    _validate_glm_result(fitted)
    # IRLS stores the information from its previous step; evaluate at the final
    # optimum so fitted covariance and exported inference use the same point.
    fitted._results.normalized_cov_params = _information_covariance(
        -model.hessian(fitted.params, observed=False), "GLM_RESULT_NONFINITE")
    fitted._results._cache.clear()
    _validate_glm_result(fitted)
    return fitted


def _glm_convergence(fitted):
    return {"converged": bool(fitted.converged), "iterations": int(fitted.fit_history["iteration"]),
            "tolerance": GLM_TOLERANCE, "criterion": "absolute parameter change"}


def _metadata(*, dispersion, estimated, fixed, ancillary, test, information, convergence):
    return {"dispersion": dispersion, "alpha_estimated": estimated, "alpha_fixed_value": fixed,
            "ancillary_parameters": ancillary, "overdispersion_test": test,
            "information_matrix": information, "convergence": convergence}


def _validate_packet(result, code):
    try:
        json.dumps(result, allow_nan=False)
    except ValueError as exc:
        raise ValueError(f"{code}: normalized inference packet contains nonfinite values.") from exc


def fit_glm(frame, formula: str, model_id: str, family_name: str, *, alpha=None):
    family_map = {"binomial": families.Binomial, "poisson": families.Poisson,
                  "negative_binomial": families.NegativeBinomial}
    family_cls = family_map.get(family_name)
    if family_cls is None:
        raise ValueError(f"Unsupported GLM family: {family_name}")
    if family_name == "negative_binomial":
        if alpha is None:
            raise ValueError("GLM_NB_ALPHA_REQUIRED: supply a fixed positive alpha for the negative binomial GLM.")
        alpha = _validate_alpha(alpha)
        family = family_cls(alpha=alpha)
    else:
        if alpha is not None:
            raise ValueError("GLM_ALPHA_NOT_APPLICABLE: alpha is only defined for the negative binomial family.")
        family = family_cls()
    fitted = _glm_fitted(frame, formula, family)
    result = normalize_statsmodels_result(fitted, model_id)
    result.update(model_type="glm", glm_family=family_name, engine="statsmodels")
    result.update(_metadata(dispersion="mean" if alpha is not None else None, estimated=False,
                           fixed=alpha, ancillary=[], test=None, information="expected",
                           convergence=_glm_convergence(fitted)))
    _validate_packet(result, "GLM_RESULT_NONFINITE")
    return result, fitted


def overdispersion_test(log_likelihood: float, restricted_log_likelihood: float):
    lr = float(2 * (log_likelihood-restricted_log_likelihood))
    return {"statistic": lr, "df": 1,
            "p_value": float(.5 * chi2.sf(lr, 1)) if lr > 0 else 1.,
            "distribution": "chibar2(01)", "restricted_model": "poisson",
            "log_likelihood_restricted": float(restricted_log_likelihood)}


def _exp_confidence_limit(log_limit):
    # JSON has no infinity. Report numeric unavailability instead of clipping.
    if log_limit < np.log(np.nextafter(0., 1.)) or log_limit > np.log(np.finfo(float).max):
        return None
    return math.exp(log_limit)


def _log1p_derivatives(t):
    """Stable A(t)=(log(1+t)-t/(1+t))/t**2 and its derivative.

    The Taylor polynomial is only a floating-point evaluation strategy for this
    analytic function: 16 terms below .01 have error below double precision.
    """
    t = np.asarray(t)
    small = np.abs(t) < .01
    a = np.empty_like(t, dtype=float)
    da = np.empty_like(t, dtype=float)
    coefficients = [(-1.)**n*(n+1)/(n+2) for n in range(16)]
    a[small] = np.polynomial.polynomial.polyval(t[small], coefficients)
    da[small] = np.polynomial.polynomial.polyval(t[small], [n*coefficients[n] for n in range(1,16)])
    large = t[~small]
    numerator = np.log1p(large)-large/(1+large)
    a[~small] = numerator/large**2
    da[~small] = (large**2/(1+large)**2-2*numerator)/large**3
    return a, da


def _small_dispersion_likelihood(y, x, mu, alpha, dispersion):
    """Exact integer-count log1p sums avoid cancellation of large log-gammas.

    Return log likelihood and natural-scale score/Hessian for beta and alpha
    (delta for NB1). This includes the continuous Poisson limit at alpha=0;
    it does not declare that a finite optimizer iterate is the exact boundary.
    """
    y = np.asarray(y)
    mean_dispersion = dispersion == "mean"
    effective = np.full(len(y), alpha) if mean_dispersion else alpha/mu
    log_product = np.zeros(len(y))
    first = np.zeros(len(y))
    second = np.zeros(len(y))
    eta_sum = np.zeros(len(y))
    eta_hessian = np.zeros(len(y))
    cross_sum = np.zeros(len(y))
    for j in range(1, int(np.max(y))):
        selected = y > j
        t = effective[selected]*j
        jscale = j if mean_dispersion else j/mu[selected]
        log_product[selected] += np.log1p(t)
        first[selected] += jscale/(1+t)
        second[selected] += (jscale/(1+t))**2
        if not mean_dispersion:
            eta_sum[selected] += t/(1+t)
            eta_hessian[selected] += t/(1+t)**2
            cross_sum[selected] += jscale/(1+t)**2
    t = alpha*mu if mean_dispersion else np.full(len(y), alpha)
    ratio = np.ones(len(y))
    np.divide(np.log1p(t), t, out=ratio, where=t != 0)
    ll = float(np.sum(log_product+y*np.log(mu)-gammaln(y+1)-y*np.log1p(t)-mu*ratio))
    a, da = _log1p_derivatives(t)
    if mean_dispersion:
        sb = (y-mu)/(1+t)
        hb = -mu*(1+alpha*y)/(1+t)**2
        cross = -mu*(y-mu)/(1+t)**2
        sa = first+mu**2*a-y*mu/(1+t)
        ha = -second+mu**3*da+y*mu**2/(1+t)**2
    else:
        sb = y-mu*ratio-eta_sum
        hb = -mu*ratio+eta_hessian
        cross = mu*a-cross_sum
        sa = first+mu*a-y/(1+t)
        ha = -second+mu*da+y/(1+t)**2
    score = np.r_[x.T@sb, np.sum(sa)]
    hessian = np.empty((x.shape[1]+1,x.shape[1]+1))
    hessian[:-1,:-1] = x.T@(hb[:,None]*x)
    hessian[:-1,-1] = hessian[-1,:-1] = x.T@cross
    hessian[-1,-1] = np.sum(ha)
    return ll, score, hessian


def _install_stable_likelihood(model, dispersion):
    original = {name: getattr(model,name) for name in ("loglike","score","hessian")}
    cache = {}

    def evaluate(params):
        params = np.asarray(params)
        alpha = np.exp(params[-1]) if model._transparams else params[-1]
        if alpha >= .001:
            return None
        natural = np.r_[params[:-1],alpha]
        if "params" not in cache or not np.array_equal(natural,cache["params"]):
            mu = np.exp(model.exog@params[:-1])
            cache["params"] = natural
            cache["result"] = _small_dispersion_likelihood(model.endog,model.exog,mu,alpha,dispersion)
        ll, score, hessian = cache["result"]
        if model._transparams:
            score = score.copy()
            hessian = hessian.copy()
            hessian[-1,:-1] *= alpha
            hessian[:-1,-1] *= alpha
            hessian[-1,-1] = alpha**2*hessian[-1,-1]+alpha*score[-1]
            score[-1] *= alpha
        return ll, score, hessian

    def loglike(params):
        stable = evaluate(params)
        return original["loglike"](params) if stable is None else stable[0]

    def score(params):
        stable = evaluate(params)
        return original["score"](params) if stable is None else stable[1]

    def hessian(params):
        stable = evaluate(params)
        return original["hessian"](params) if stable is None else stable[2]

    model.loglike, model.score, model.hessian = loglike, score, hessian


class _RegressionProjection:
    """Present beta only without mutating the joint statsmodels fitted result."""

    def __init__(self, fitted):
        self.fitted = fitted

    def __getattr__(self, name):
        value = getattr(self.fitted, name)
        if name in {"params", "bse", "pvalues"}:
            return value.iloc[:-1]
        return value

    def conf_int(self):
        return self.fitted.conf_int().iloc[:-1]


def fit_negative_binomial(frame, formula: str, model_id: str, *, dispersion="mean", alpha=None, y_column=None):
    if y_column is not None and alpha is None:
        _validate_counts(np.asarray(frame[y_column].dropna()))
    if dispersion not in {"mean", "constant"}:
        raise ValueError("NB_DISPERSION_INVALID: dispersion must be 'mean' or 'constant'.")
    if alpha is not None:
        alpha = _validate_alpha(alpha)
        if dispersion != "mean":
            raise ValueError("NB_FIXED_DISPERSION_UNSUPPORTED: fixed alpha currently requires NB2 dispersion='mean'.")
        fitted = _glm_fitted(frame, formula, families.NegativeBinomial(alpha=alpha),
                             response_error_code="NB_COUNTS_INVALID")
        fitted._results.normalized_cov_params = _information_covariance(
            -fitted.model.hessian(fitted.params, observed=True), "GLM_RESULT_NONFINITE")
        fitted._results._cache.clear()
        _validate_glm_result(fitted)
        result = normalize_statsmodels_result(fitted, model_id)
        result.update(_metadata(dispersion=dispersion, estimated=False, fixed=alpha, ancillary=[],
                                test=None, information="observed", convergence=_glm_convergence(fitted)))
    else:
        model = smf.negativebinomial(formula=formula, data=frame, loglike_method="nb2" if dispersion == "mean" else "nb1")
        iterations = 0

        def record_iteration(params):
            nonlocal iterations
            iterations += 1

        fitted = model.fit(method="bfgs", gtol=ML_TOLERANCE, maxiter=1000, disp=False,
                           callback=record_iteration)
        if float(fitted.params.iloc[-1]) < .001:
            _install_stable_likelihood(model, dispersion)
            fitted = model.fit(start_params=np.asarray(fitted.params), method="bfgs",
                               gtol=ML_TOLERANCE, maxiter=1000, disp=False, callback=record_iteration)
        endog = model.endog
        _validate_counts(endog)
        retvals = fitted.mle_retvals
        if not retvals["converged"]:
            raise ValueError("NB_NOT_CONVERGED: joint ML failed to converge.")
        params = np.asarray(fitted.params)
        _require_finite(params, "NB_INFERENCE_UNCERTIFIED", "Joint parameters")
        _require_finite(fitted.llf, "NB_INFERENCE_UNCERTIFIED", "Log likelihood")
        if params[-1] <= 0:
            raise ValueError("NB_INFERENCE_UNCERTIFIED: a regular natural-parameter interior point is unavailable.")
        natural_score = model.score(params)
        _require_finite(natural_score, "NB_INFERENCE_UNCERTIFIED", "Natural-parameter score")
        natural_mean_score = float(np.max(np.abs(natural_score)) / len(endog))
        if natural_mean_score > ML_TOLERANCE:
            raise ValueError("NB_INFERENCE_UNCERTIFIED: regular interior inference is unavailable; "
                             f"maximum absolute natural-parameter score per observation={natural_mean_score:.17g} "
                             f"exceeds tolerance={ML_TOLERANCE:.17g}. Optimizer log-coordinate stopping does not certify this point.")
        # Re-evaluate OIM on the natural ancillary scale after the optimizer's
        # log transformation. Do not use its inverse-BFGS approximation.
        fitted._results.normalized_cov_params = _information_covariance(
            -model.hessian(params), "NB_INFERENCE_UNCERTIFIED")
        fitted._results._cache.clear()
        result = normalize_statsmodels_result(_RegressionProjection(fitted), model_id)
        a = float(fitted.params.iloc[-1])
        se = float(fitted.bse.iloc[-1])
        loga = float(np.log(a))
        logse = se / a
        _require_finite(logse, "NB_INFERENCE_UNCERTIFIED", "Log ancillary standard error")
        z = norm.ppf(.975)
        logname, name = ("lnalpha", "alpha") if dispersion == "mean" else ("lndelta", "delta")
        ancillary = [
            {"name": logname, "estimate": loga, "std_error": logse,
             "conf_low": loga-z*logse, "conf_high": loga+z*logse, "scale": "log"},
            {"name": name, "estimate": a, "std_error": se,
             "conf_low": _exp_confidence_limit(loga-z*logse), "conf_high": _exp_confidence_limit(loga+z*logse), "scale": "natural"},
        ]
        if ancillary[1]["conf_low"] is None or ancillary[1]["conf_high"] is None:
            result.setdefault("warnings", []).append({"code": "NB_ANCILLARY_CI_NUMERIC_RANGE",
                "message": "Natural-scale ancillary confidence limit is unavailable: exponent exceeds the finite numeric range. The log-scale interval is retained."})
        # Reuse the exact design and complete-case sample selected by Patsy.
        from statsmodels.genmod.generalized_linear_model import GLM
        poisson = GLM(endog, model.exog, family=families.Poisson()).fit(tol=GLM_TOLERANCE, maxiter=1000, tol_criterion="params")
        if not poisson.converged:
            raise ValueError("NB_POISSON_NOT_CONVERGED: restricted model failed to converge.")
        _require_finite(poisson.params, "NB_POISSON_NOT_CONVERGED", "Restricted parameters")
        _require_finite(poisson.llf, "NB_POISSON_NOT_CONVERGED", "Restricted log likelihood")
        test = overdispersion_test(fitted.llf, poisson.llf)
        result.update(_metadata(dispersion=dispersion, estimated=True, fixed=None, ancillary=ancillary,
                                test=test, information="observed",
                                convergence={"converged": True, "iterations": iterations,
                                             "tolerance": ML_TOLERANCE,
                                             "criterion": "maximum absolute natural-parameter score per observation (beta and ancillary)"}))
    result.update(model_type="negative_binomial", engine="statsmodels")
    _validate_packet(result, "NB_INFERENCE_UNCERTIFIED")
    return result, fitted
