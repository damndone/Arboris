"""Joint normal ARMA--ARCH/GARCH maximum likelihood matching Stata 18.

Stata [TS] arch (https://www.stata.com/manuals18/tsarch.pdf) parameterizes
``y = mu + u; u = sum(phi*u_lag) + sum(theta*epsilon_lag) + epsilon``.
Thus mu is the unconditional mean. With arma0(zero), both presample u and
innovations are zero; every observation enters the likelihood (hold_back=0).
arch0(xb) primes *both* squared innovations and conditional variances with
``mean(epsilon**2)`` from the current mean/ARMA parameters, recomputed on each
likelihood evaluation. It is not omega/(1-sum(alpha)-sum(beta)). Local Stata
help arch and full-series prediction oracles verify these conventions.

OPG is inverse(sum(score_t score_t')). OIM is inverse(-sum(Hessian_t)).
Robust is n/(n-1) * OIM @ sum(score_t score_t') @ OIM, the full
Huber/White sandwich. Stata [P] _robust uses minus(1) for ML, rather than
the regression n/(n-k) adjustment. Differentiation
includes the parameter-dependent arch0(xb) priming value. Scores are analytic;
observed information is a centered numerical derivative of the analytic
summed score. The covariance and reported parameters use the natural scale.

SLSQP optimizes all mean and variance parameters together, with explicit
positivity, variance-persistence, AR-stationarity and MA-invertibility
constraints. Data are rescaled internally for conditioning; there is no
change to the model, likelihood sample, or external units. scipy.signal
filters evaluate recursions in compiled code without optional JIT tooling.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.optimize import minimize
from scipy.signal import lfilter, lfiltic

from workbench.contracts.common.envelope import freeze_json, thaw_json
from workbench.engine.packs.arma_garch.errors import ArmaGarchInputError, diagnostic
from workbench.engine.packs.arma_garch.volatility import (
    VarianceCandidateSpec, calculate_persistence, validate_variance_parameters,
)


@dataclass(frozen=True)
class JointArmaGarchResult:
    mean_order: tuple[int, int]
    variance_order: tuple[int, int]
    nobs: int
    convergence_details: Mapping[str, object]
    parameter_names: tuple[str, ...]
    parameters: Mapping[str, float]
    standard_errors: Mapping[str, float]
    covariance: Mapping[str, object]
    vce: str
    presample: Mapping[str, object]
    parameter_constraints: tuple[Mapping[str, object], ...]
    log_likelihood: float
    aic: float
    bic: float
    conditional_series: Mapping[str, object]
    persistence: Mapping[str, object]
    warnings: tuple[str, ...]
    converged: bool = True
    hold_back: int = 0
    model_family: str = "arma_garch"
    estimation_strategy: str = "joint"
    resolved_strategy: str = "joint_arma_garch"
    backend: str = "workbench_joint_mle"
    innovation_distribution: str = "normal"
    joint_likelihood: bool = True

    def __post_init__(self) -> None:
        for name in ("convergence_details", "parameters", "standard_errors", "covariance",
                     "presample", "parameter_constraints", "conditional_series", "persistence"):
            object.__setattr__(self, name, freeze_json(getattr(self, name), f"joint_arma_garch.{name}"))

    def to_dict(self) -> dict[str, object]:
        payload = {name: thaw_json(getattr(self, name)) for name in self.__dataclass_fields__}
        payload["display_name"] = f"Joint ARMA({self.mean_order[0]},{self.mean_order[1]})-variance({self.variance_order[0]},{self.variance_order[1]})"
        return payload


def _error(code: str, message: str, **evidence: object) -> ArmaGarchInputError:
    return ArmaGarchInputError(diagnostic(code, message, evidence=evidence,
        impact="The requested joint model cannot produce an accepted estimate."))


def _lag_sum(values: np.ndarray, coefficients: np.ndarray, initial: float) -> np.ndarray:
    if not len(coefficients):
        return np.zeros_like(values)
    numerator = np.r_[0., coefficients]
    return lfilter(numerator, [1.], values,
        zi=lfiltic(numerator, [1.], [], np.full(len(coefficients), initial)))[0]


def _roots_radius(coefficients: np.ndarray, sign: float) -> float:
    # Roots here are reciprocal lag-polynomial roots (companion eigenvalues).
    return float(np.max(np.abs(np.roots(np.r_[1., sign*coefficients])))) if len(coefficients) else 0.


def filter_joint_arma_garch(
    values: np.ndarray, *, mean_p: int, mean_q: int, include_constant: bool,
    variance_spec: VarianceCandidateSpec, parameters: Mapping[str, float],
    presample_variance: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Replay fitted innovations and variance with the original arch0(xb).

    Stata prediction keeps the fitted e(archi) when new observations arrive;
    changing the priming variance would change a fixed-parameter forecast.
    """
    if (type(mean_p) is not int or mean_p < 0 or type(mean_q) is not int or mean_q < 1
        or type(include_constant) is not bool):
        raise _error("JOINT_ARMA_GARCH_INVALID_PARAMETERS", "Prediction orders and constant setting are invalid.")
    try:
        if type(variance_spec.p) is not int or type(variance_spec.q) is not int:
            raise ValueError("Variance orders must be integers.")
        VarianceCandidateSpec.create(model=variance_spec.model, p=variance_spec.p,
            q=variance_spec.q, distribution=variance_spec.distribution)
    except ValueError as exc:
        raise _error("JOINT_ARMA_GARCH_INVALID_PARAMETERS", str(exc)) from exc
    names = (["mu"] if include_constant else []) + [f"ar{i}" for i in range(1, mean_p+1)]
    names += [f"ma{i}" for i in range(1, mean_q+1)] + ["omega"]
    names += [f"arch{i}" for i in range(1, variance_spec.p+1)] + [f"garch{i}" for i in range(1, variance_spec.q+1)]
    try:
        raw = np.asarray(values)
        if (raw.ndim != 1 or not len(raw) or np.iscomplexobj(raw)
            or (raw.dtype.kind == "O" and any(np.iscomplexobj(value) for value in raw.flat))):
            raise ValueError("Prediction requires a real one-dimensional history.")
        y = np.asarray(raw, dtype=float)
        if not np.isfinite(y).all():
            raise ValueError("Prediction history must be finite.")
    except (TypeError, ValueError) as exc:
        raise _error("JOINT_ARMA_GARCH_INVALID_INPUT", str(exc)) from exc
    try:
        if not isinstance(parameters, Mapping) or set(parameters) != set(names):
            raise ValueError("Prediction named parameters do not match the specification.")
        if any(np.iscomplexobj(parameters[name]) for name in names) or np.iscomplexobj(presample_variance):
            raise ValueError("Prediction parameters must be real.")
        x = np.array([parameters[name] for name in names], dtype=float)
        h0 = float(presample_variance)
    except (TypeError, ValueError) as exc:
        raise _error("JOINT_ARMA_GARCH_INVALID_PARAMETERS", str(exc)) from exc
    likelihood = _Likelihood(y, mean_p, mean_q, include_constant, variance_spec.p, variance_spec.q)
    if (variance_spec.distribution != "normal" or not np.isfinite(x).all()
        or not np.isfinite(h0) or h0 <= 0 or x[likelihood.m] <= 0
        or np.any(x[likelihood.m+1:] < 0) or np.any(likelihood.constraints(x) < 0)):
        raise _error("JOINT_ARMA_GARCH_INVALID_PARAMETERS", "Prediction parameters or presample variance are invalid.")
    mu = x[0] if include_constant else 0.
    ar, ma = x[likelihood.c:likelihood.c+mean_p], x[likelihood.c+mean_p:likelihood.m]
    alpha, beta = x[likelihood.m+1:likelihood.m+1+variance_spec.p], x[likelihood.m+1+variance_spec.p:]
    e = lfilter(np.r_[1., -ar], np.r_[1., ma], y-mu)
    denominator = np.r_[1., -beta]
    h = lfilter([1.], denominator, x[likelihood.m] + _lag_sum(e*e, alpha, h0),
        zi=lfiltic([1.], denominator, np.full(variance_spec.q, h0)))[0]
    if not np.isfinite(e).all() or not np.isfinite(h).all() or np.any(h <= 0):
        raise _error("JOINT_ARMA_GARCH_INVALID_PARAMETERS", "Prediction recursions are non-finite or non-positive.")
    return e, h


class _Likelihood:
    def __init__(self, y: np.ndarray, p: int, q: int, constant: bool, r: int, s: int):
        self.y, self.p, self.q, self.c, self.r, self.s = y, p, q, int(constant), r, s
        self.m = self.c+p+q
        self.k = self.m+1+r+s

    def evaluate(self, x: np.ndarray):
        mu = x[0] if self.c else 0.
        ar = x[self.c:self.c+self.p]
        ma = x[self.c+self.p:self.m]
        omega = x[self.m]
        alpha, beta = x[self.m+1:self.m+1+self.r], x[self.m+1+self.r:]
        numerator, denominator = np.r_[1., -ar], np.r_[1., ma]
        u = self.y-mu
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            e = lfilter(numerator, denominator, u)
            de = np.zeros((len(e), self.k))
            if self.c:
                de[:, 0] = -lfilter(numerator, denominator, np.ones(len(e)))
            for i in range(self.p):
                de[:, self.c+i] = -lfilter([1.], denominator, np.r_[np.zeros(i+1), u[:len(u)-i-1]])
            for i in range(self.q):
                de[:, self.c+self.p+i] = -lfilter([1.], denominator, np.r_[np.zeros(i+1), e[:len(e)-i-1]])
            e2 = e*e
            h0 = float(np.mean(e2))
            dh0 = np.mean(2*e[:, None]*de, axis=0)
            forcing = omega + _lag_sum(e2, alpha, h0)
            hden = np.r_[1., -beta]
            h = lfilter([1.], hden, forcing, zi=lfiltic([1.], hden, np.full(self.s, h0)))[0]
            dh = np.empty_like(de)
            for j in range(self.k):
                df = _lag_sum(2*e*de[:, j], alpha, float(dh0[j]))
                if j == self.m:
                    df += 1.
                elif self.m < j <= self.m+self.r:
                    lag = j-self.m
                    df += np.r_[np.full(lag, h0), e2[:-lag]]
                elif j > self.m+self.r:
                    lag = j-self.m-self.r
                    df += np.r_[np.full(lag, h0), h[:-lag]]
                dh[:, j] = lfilter([1.], hden, df,
                    zi=lfiltic([1.], hden, np.full(self.s, dh0[j])))[0]
            ll = -.5*(np.log(2*np.pi)+np.log(h)+e2/h)
            score = -e[:, None]*de/h[:, None] + .5*(e2/h-1)[:, None]*dh/h[:, None]
        if np.any(h <= 0) or not np.isfinite(ll).all() or not np.isfinite(score).all():
            return None
        return ll, score, e, h, h0

    def objective(self, x):
        evaluated = self.evaluate(x)
        if evaluated is None:
            return 1e100, np.zeros(self.k)
        ll, score, *_ = evaluated
        return -float(np.mean(ll)), -np.mean(score, axis=0)

    def constraints(self, x):
        return np.array([1.-1e-8-np.sum(x[self.m+1:]),
            1.-1e-8-_roots_radius(x[self.c:self.c+self.p], -1.),
            1.-1e-8-_roots_radius(x[self.c+self.p:self.m], 1.)])


def _initial_parameters(likelihood: _Likelihood) -> np.ndarray:
    """Cheap Hannan--Rissanen starting values; these are not final estimates."""
    y = likelihood.y
    mu = float(np.mean(y)) if likelihood.c else 0.
    u = y-mu
    p, q = likelihood.p, likelihood.q
    high = min(max(12, p+q+4), len(y)//4)
    design = np.column_stack([u[high-i:len(u)-i] for i in range(1, high+1)])
    initial_ar = np.linalg.lstsq(design, u[high:], rcond=None)[0]
    e = lfilter(np.r_[1., -initial_ar], [1.], u)
    lag = max(high, p, q)
    columns = [u[lag-i:len(u)-i] for i in range(1, p+1)]
    columns += [e[lag-i:len(u)-i] for i in range(1, q+1)]
    arma = np.linalg.lstsq(np.column_stack(columns), u[lag:], rcond=None)[0]
    if _roots_radius(arma[:p], -1.) >= .98 or _roots_radius(arma[p:], 1.) >= .98:
        arma = np.zeros(p+q)
    alpha = np.full(likelihood.r, .15/max(1, likelihood.r))
    beta = np.full(likelihood.s, .65/max(1, likelihood.s))
    variance = float(np.mean(lfilter(np.r_[1., -arma[:p]], np.r_[1., arma[p:]], u)**2))
    omega = max(variance*(1-alpha.sum()-beta.sum()), 1e-6)
    return np.r_[([mu] if likelihood.c else []), arma, omega, alpha, beta]


def fit_joint_arma_garch(
    values: np.ndarray, *, mean_p: int, mean_q: int, include_constant: bool,
    variance_spec: VarianceCandidateSpec, time_index_semantics: str,
    presample: Literal["stata"] = "stata", vce: Literal["opg", "oim", "robust"] = "opg",
    start: Mapping[str, float] | None = None, max_iterations: int = 500,
) -> JointArmaGarchResult:
    """Estimate one specified joint model; raise structured errors on failure."""
    if variance_spec.distribution != "normal":
        raise _error("UNSUPPORTED_JOINT_DISTRIBUTION", "Joint ARMA-GARCH supports normal innovations only.", distribution=variance_spec.distribution)
    if type(mean_p) is not int or mean_p < 0 or type(mean_q) is not int or mean_q < 1:
        raise _error("JOINT_ARMA_GARCH_INVALID_PARAMETERS", "Orders require integer p>=0 and q>=1.")
    if type(include_constant) is not bool or presample != "stata" or vce not in {"opg", "oim", "robust"}:
        raise _error("JOINT_ARMA_GARCH_INVALID_PARAMETERS", "Unsupported constant, presample, or VCE setting.")
    try:
        if type(variance_spec.p) is not int or type(variance_spec.q) is not int:
            raise ValueError("Variance orders must be integers.")
        VarianceCandidateSpec.create(
            model=variance_spec.model, p=variance_spec.p, q=variance_spec.q,
            distribution=variance_spec.distribution,
        )
    except ValueError as exc:
        raise _error("JOINT_ARMA_GARCH_INVALID_PARAMETERS", str(exc)) from exc
    try:
        raw_values = np.asarray(values)
        contains_complex = np.iscomplexobj(raw_values) or (
            raw_values.dtype.kind == "O"
            and any(np.iscomplexobj(value) for value in raw_values.flat)
        )
        if contains_complex:
            raise ValueError("Complex observations are unsupported.")
        y = np.asarray(raw_values, dtype=float)
    except (ValueError, TypeError) as exc:
        raise _error("JOINT_ARMA_GARCH_INVALID_INPUT", "Input values must be real numeric values.") from exc
    if y.ndim != 1 or len(y) <= max(mean_p, mean_q, variance_spec.p, variance_spec.q, 12)+2 or not np.isfinite(y).all():
        raise _error("JOINT_ARMA_GARCH_INVALID_INPUT", "Input must be a sufficiently long finite one-dimensional series.")
    if type(max_iterations) is not int or max_iterations < 1:
        raise _error("JOINT_ARMA_GARCH_INVALID_PARAMETERS", "max_iterations must be a positive integer.")
    # Validate the semantic period unit even for ARCH, where persistence is absent.
    if time_index_semantics not in {"observation_order", "regular_calendar", "business_or_trading_observations"}:
        raise _error("JOINT_ARMA_GARCH_INVALID_PARAMETERS", "Unsupported time index semantics.")
    scale = float(np.std(y))
    if not np.isfinite(scale) or scale <= np.finfo(float).eps:
        raise _error("JOINT_ARMA_GARCH_INVALID_INPUT", "The input variance must be positive.")
    likelihood = _Likelihood(y/scale, mean_p, mean_q, include_constant, variance_spec.p, variance_spec.q)
    names = (["mu"] if include_constant else []) + [f"ar{i}" for i in range(1, mean_p+1)] + [f"ma{i}" for i in range(1, mean_q+1)]
    names += ["omega"] + [f"arch{i}" for i in range(1, variance_spec.p+1)] + [f"garch{i}" for i in range(1, variance_spec.q+1)]
    units = np.ones(likelihood.k)
    if include_constant: units[0] = scale
    units[likelihood.m] = scale**2
    initial = _initial_parameters(likelihood)
    if start is not None:
        if set(start)-set(names):
            raise _error("JOINT_ARMA_GARCH_INVALID_PARAMETERS", "Unknown starting parameter names.")
        for i, name in enumerate(names):
            if name in start:
                try:
                    initial[i] = float(start[name])/units[i]
                except (ValueError, TypeError, OverflowError) as exc:
                    raise _error("JOINT_ARMA_GARCH_INVALID_PARAMETERS", "Starting parameters must be finite numbers.") from exc
    if not np.isfinite(initial).all() or initial[likelihood.m] <= 0 or np.any(initial[likelihood.m+1:] < 0) or np.any(likelihood.constraints(initial) <= 0):
        raise _error("JOINT_ARMA_GARCH_INVALID_PARAMETERS", "Starting parameters violate positivity, stationarity, or invertibility.")
    bounds = [(None, None)]*likelihood.m + [(1e-10, None)] + [(0., None)]*(variance_spec.p+variance_spec.q)
    optimized = minimize(likelihood.objective, initial, jac=True, method="SLSQP", bounds=bounds,
        constraints={"type": "ineq", "fun": likelihood.constraints}, options={"maxiter": max_iterations, "ftol": 1e-13})
    x = optimized.x
    evaluated = likelihood.evaluate(x)
    if not optimized.success:
        raise _error("JOINT_ARMA_GARCH_NOT_CONVERGED", str(optimized.message), iterations=int(optimized.nit), optimizer="SLSQP")
    if evaluated is None:
        raise _error("JOINT_ARMA_GARCH_NONFINITE_LIKELIHOOD", "The final likelihood or conditional series is non-finite.")
    ll, score, e, h, h0 = evaluated
    if np.any(likelihood.constraints(x) < 0):
        raise _error("JOINT_ARMA_GARCH_INVALID_PARAMETERS", "Final ARMA or variance parameters violate stationarity.")
    parameters = dict(zip(names, (x*units).tolist()))
    variance_parameters = {"sigma2": parameters["omega"], "omega": parameters["omega"]}
    variance_parameters.update({f"alpha[{i}]": parameters[f"arch{i}"] for i in range(1, variance_spec.p+1)})
    variance_parameters.update({f"beta[{i}]": parameters[f"garch{i}"] for i in range(1, variance_spec.q+1)})
    validation = validate_variance_parameters(model=variance_spec.model, p=variance_spec.p, q=variance_spec.q,
        distribution="normal", parameters=variance_parameters)
    if not validation.valid:
        raise _error("JOINT_ARMA_GARCH_INVALID_PARAMETERS", "Final variance parameters violate constraints.")
    meat = score.T @ score
    try:
        if vce == "opg":
            covariance = np.linalg.inv(meat)
        else:
            info = np.empty((likelihood.k, likelihood.k))
            for j in range(likelihood.k):
                step = 1e-5*max(1., abs(x[j]))
                delta = np.zeros(likelihood.k)
                delta[j] = step
                upper, lower = likelihood.evaluate(x+delta), likelihood.evaluate(x-delta)
                if upper is None or lower is None:
                    raise np.linalg.LinAlgError("Observed information cannot be evaluated.")
                info[:, j] = -(upper[1].sum(axis=0)-lower[1].sum(axis=0))/(2*step)
            info = (info+info.T)/2
            bread = np.linalg.inv(info)
            covariance = bread if vce == "oim" else (len(y)/(len(y)-1))*(bread @ meat @ bread)
        covariance = covariance * units[:, None]*units[None, :]
        covariance = (covariance+covariance.T)/2
        if not np.isfinite(covariance).all() or np.min(np.linalg.eigvalsh(covariance)) <= 0:
            raise np.linalg.LinAlgError("Covariance is not positive definite.")
    except np.linalg.LinAlgError as exc:
        raise _error("JOINT_ARMA_GARCH_INVALID_COVARIANCE", str(exc)) from exc
    e, h = e*scale, h*scale**2
    volatility = np.sqrt(h)
    standardized = e/volatility
    log_likelihood = float(ll.sum()-len(y)*np.log(scale))
    persistence = calculate_persistence(model=variance_spec.model, p=variance_spec.p, q=variance_spec.q,
        parameters=variance_parameters, time_index_semantics=time_index_semantics)
    conditional = {"alignment": {"total_observations": len(y), "hold_back": 0, "effective_sample": len(y)},
        "mean": (y-e).tolist(), "residual": e.tolist(), "variance": h.tolist(), "volatility": volatility.tolist(),
        "standardized_residual": standardized.tolist(), "squared_standardized_residual": (standardized**2).tolist()}
    return JointArmaGarchResult(mean_order=(mean_p, mean_q), variance_order=(variance_spec.p, variance_spec.q), nobs=len(y),
        convergence_details={"optimizer": "SLSQP", "iterations": int(optimized.nit), "gradient_norm": float(np.linalg.norm(score.sum(axis=0)/units, ord=np.inf)), "success": True, "message": str(optimized.message)},
        parameter_names=tuple(names), parameters=parameters, standard_errors=dict(zip(names, np.sqrt(np.diag(covariance)).tolist())),
        covariance={"names": names, "matrix": covariance.tolist()}, vce=vce,
        presample={"method": "stata", "arch0": "xb", "arma0": "zero", "innovation": 0., "disturbance": 0., "squared_innovation": h0*scale**2, "variance": h0*scale**2},
        parameter_constraints=validation.constraints, log_likelihood=log_likelihood,
        aic=-2*log_likelihood+2*likelihood.k, bic=float(-2*log_likelihood+likelihood.k*np.log(len(y))), conditional_series=conditional,
        persistence={"persistence": persistence.persistence, "half_life": persistence.half_life, "half_life_unit": persistence.half_life_unit, "warnings": list(persistence.warnings)}, warnings=persistence.warnings)
