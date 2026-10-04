"""Checks on the outcome and on the fitted relationship.

`outcome_distribution` checks read the outcome on its own; `post_fit` checks
read the fitted model and may only inform inference choices (standard errors,
penalisation), never the substantive specification (design §4.3).
"""

from __future__ import annotations

import math

import numpy as np
from scipy import optimize, stats

from .context import CheckContext, public_column
from .contracts import CheckOutcome, CheckSpec, Threshold

_SEPARATION_TOLERANCE = 1e-7


def perfect_fit(context: CheckContext, spec: CheckSpec) -> CheckOutcome:
    fitted = context.fitted
    resid = getattr(fitted, "resid", None)
    y = context.outcome
    if resid is None or y is None:
        return CheckOutcome("not_checked", "The fit does not expose its residuals.")
    resid = np.asarray(resid, dtype=float)
    total = float(np.sum((y - y.mean()) ** 2))
    ssr = float(np.sum(resid**2))
    ratio = ssr / total if total > 0 else 0.0
    evidence = {"residual_sum_of_squares": ssr, "total_sum_of_squares": total, "ssr_over_tss": ratio}
    if ratio < spec.threshold("fails_below"):
        return CheckOutcome(
            "fails",
            "The model fits the data exactly: the outcome is an exact linear combination of the "
            "regressors, so there is no residual variation and standard errors, tests and "
            "intervals are not meaningful. They are not shown.",
            evidence,
            "Check whether the outcome was constructed from the regressors.",
        )
    return CheckOutcome("holds", "The residual variance is not zero.", evidence)


def _separating_direction(matrix: np.ndarray, sign: np.ndarray) -> np.ndarray | None:
    """Konis (2007): maximise sum_i s_i x_i'b subject to s_i x_i'b >= 0 and a box
    on b. A positive optimum means a separating direction exists and the MLE
    does not; the coefficients that are non-zero in it diverge. This is the
    linear program detectseparation solves, and the same reading of it."""
    signed = matrix * sign[:, None]
    rows, k = signed.shape
    solved = optimize.linprog(
        -signed.sum(axis=0), A_ub=-signed, b_ub=np.zeros(rows), bounds=[(-1.0, 1.0)] * k, method="highs",
    )
    if solved.status != 0:
        raise RuntimeError(f"linear program failed: {solved.message}")
    if -solved.fun <= _SEPARATION_TOLERANCE * rows:
        return None
    return solved.x


def separation_reason(model) -> str | None:
    """Why a binary maximum-likelihood fit failed, if the data are separated.

    Called when a logit or probit does not converge: separated data are the
    usual cause, and naming the separating regressors is the useful answer.
    """
    from types import SimpleNamespace

    from .context import design_from_fitted

    design = design_from_fitted(SimpleNamespace(model=model))
    y = np.asarray(getattr(model, "endog", []), dtype=float)
    if design is None or not len(y) or not set(np.unique(y).tolist()) <= {0.0, 1.0}:
        return None
    direction = _separating_direction(design.matrix, np.where(y > 0.5, 1.0, -1.0))
    if direction is None:
        return None
    involved = [public_column(name) for name, value in zip(design.column_names, direction) if abs(value) > 1e-6]
    return (
        f"the outcome is separated by {', '.join(involved)}, so maximum-likelihood estimates do not "
        "exist. Use Firth's penalised likelihood, or remove or combine the separating regressors"
    )


def separation(context: CheckContext, spec: CheckSpec) -> CheckOutcome:
    design = context.design
    y = context.outcome
    if design is None or y is None:
        return CheckOutcome("not_checked", "The fit does not expose its design matrix and outcome.")
    values = set(np.unique(y).tolist())
    if not values <= {0.0, 1.0}:
        return CheckOutcome("not_checked", "Separation is checked for 0/1 outcomes.")
    sign = np.where(y > 0.5, 1.0, -1.0)
    direction = _separating_direction(design.matrix, sign)
    names = [public_column(name) for name in design.column_names]
    infinite_terms = (
        sorted(f"{names[j]} ({'+' if value > 0 else '-'}inf)" for j, value in enumerate(direction)
               if abs(value) > 1e-6)
        if direction is not None else []
    )
    evidence = {"separated": direction is not None, "infinite_estimates": infinite_terms}
    if direction is not None:
        return CheckOutcome(
            "fails",
            "The outcome is (quasi-)completely separated by the regressors, so maximum-likelihood "
            f"estimates do not exist: {', '.join(infinite_terms) or 'some coefficients'} diverge. "
            "The reported coefficients and standard errors are artefacts of where the optimiser stopped.",
            evidence,
            "Use Firth's penalised likelihood, or remove or combine the separating regressors.",
        )
    return CheckOutcome("holds", "No separation: the maximum-likelihood estimates exist.", evidence)


def events_per_variable(context: CheckContext, spec: CheckSpec) -> CheckOutcome:
    y = context.outcome
    design = context.design
    if y is None or design is None:
        return CheckOutcome("not_checked", "The fit does not expose its outcome and design.")
    events = int(np.sum(y > 0.5))
    minority = min(events, len(y) - events)
    parameters = len(design.regressor_columns)
    if parameters == 0:
        return CheckOutcome("not_applicable", "The model has no regressors.")
    epv = minority / parameters
    evidence = {"events_in_smaller_class": minority, "regressor_parameters": parameters, "events_per_variable": round(epv, 2)}
    if epv < spec.threshold("caution_below"):
        return CheckOutcome(
            "caution",
            f"{minority} events in the smaller outcome class for {parameters} regressor parameters "
            f"({epv:.1f} per parameter); estimates may be biased and unstable. The rule of ten is a "
            "rough guide, not a guarantee.",
            evidence,
            "Reduce the number of parameters, or use penalised estimation.",
        )
    return CheckOutcome("holds", f"{epv:.1f} events per regressor parameter.", evidence)


def cluster_count(context: CheckContext, spec: CheckSpec) -> CheckOutcome:
    clusters = (context.kernel or {}).get("n_clusters")
    if not isinstance(clusters, int):
        return CheckOutcome("not_checked", "The fit does not record its number of clusters.")
    evidence = {"clusters": clusters}
    if clusters < spec.threshold("caution_below"):
        return CheckOutcome(
            "caution",
            f"Only {clusters} clusters: cluster-robust standard errors rely on many clusters and tend "
            "to be too small with few, even with the t(G - 1) reference distribution.",
            evidence,
            "Consider the wild cluster bootstrap for inference.",
        )
    return CheckOutcome("holds", f"{clusters} clusters.", evidence)


def heteroskedasticity(context: CheckContext, spec: CheckSpec) -> CheckOutcome:
    fitted = context.fitted
    resid = getattr(fitted, "resid", None)
    design = context.design
    if resid is None or design is None:
        return CheckOutcome("not_checked", "The fit does not expose its residuals and design.")
    from statsmodels.stats.diagnostic import het_breuschpagan

    statistic, p_value, _, _ = het_breuschpagan(np.asarray(resid, dtype=float), design.matrix)
    estimator = (context.kernel or {}).get("covariance_estimator")
    evidence = {"breusch_pagan_lm": float(statistic), "p_value": float(p_value), "covariance_estimator": estimator}
    if p_value < spec.threshold("alpha"):
        if estimator in {"HC1", "cluster"}:
            return CheckOutcome(
                "holds",
                f"The residual variance depends on the regressors (Breusch-Pagan p = {p_value:.3g}); "
                "the robust standard errors in use account for it.",
                evidence,
            )
        return CheckOutcome(
            "caution",
            f"The residual variance depends on the regressors (Breusch-Pagan p = {p_value:.3g}); "
            "conventional standard errors are not reliable.",
            evidence,
            "Use robust (HC1) standard errors.",
        )
    return CheckOutcome("holds", f"No evidence of heteroskedasticity (Breusch-Pagan p = {p_value:.3g}).", evidence)


def overdispersion(context: CheckContext, spec: CheckSpec) -> CheckOutcome:
    """Cameron & Trivedi (1990): regress ((y - mu)^2 - y) / mu on mu without an
    intercept; a positive slope means variance above the mean."""
    fitted = context.fitted
    y = context.outcome
    if fitted is None or y is None or not hasattr(fitted, "predict"):
        return CheckOutcome("not_checked", "The fit does not expose its predicted means.")
    mu = np.asarray(fitted.predict(), dtype=float)
    response = ((y - mu) ** 2 - y) / mu
    slope = float(np.sum(response * mu) / np.sum(mu**2))
    residual = response - slope * mu
    df = len(y) - 1
    se = math.sqrt(float(np.sum(residual**2)) / df / float(np.sum(mu**2)))
    t = slope / se
    p_value = float(stats.t.sf(t, df))
    pearson = float(np.sum((y - mu) ** 2 / mu) / max(len(y) - design_size(context), 1))
    evidence = {"alpha": slope, "t": t, "p_value": p_value, "pearson_ratio": pearson}
    if p_value < spec.threshold("alpha") and slope > 0:
        return CheckOutcome(
            "caution",
            f"The outcome varies more than the model allows (overdispersion, Cameron-Trivedi p = {p_value:.3g}); "
            "its standard errors are too small.",
            evidence,
            "Use a negative binomial model, or robust standard errors.",
        )
    return CheckOutcome("holds", f"No evidence of overdispersion (Cameron-Trivedi p = {p_value:.3g}).", evidence)


def design_size(context: CheckContext) -> int:
    return context.design.matrix.shape[1] if context.design is not None else 0


PERFECT_FIT = CheckSpec(
    check_id="fit.perfect",
    title="Perfect fit",
    requires=frozenset({"method.least_squares", "design.linear_predictor"}),
    blinding="post_fit",
    thresholds=(
        Threshold("fails_below", 1e-10, "residual sum of squares below 1e-10 of the total sum of squares",
                  "numerical criterion; cf. R summary.lm's 'essentially perfect fit' warning"),
    ),
    run=perfect_fit,
    suppresses_inference=True,
)

SEPARATION = CheckSpec(
    check_id="fit.separation",
    title="Separation",
    requires=frozenset({"outcome.binary", "method.maximum_likelihood", "design.linear_predictor"}),
    blinding="post_fit",
    thresholds=(
        Threshold("exists", 1.0, "any separating direction found by the linear program",
                  "Konis (2007), Linear programming algorithms for detecting separated data in binary logistic regression models, DPhil, Oxford; Albert & Anderson (1984)"),
    ),
    run=separation,
    max_cells=20_000_000,
    suppresses_inference=True,
)

EVENTS_PER_VARIABLE = CheckSpec(
    check_id="outcome.events_per_variable",
    title="Events per variable",
    requires=frozenset({"outcome.binary", "design.linear_predictor"}),
    blinding="outcome_distribution",
    thresholds=(
        Threshold("caution_below", 10.0, "fewer than 10 events of the smaller class per regressor parameter",
                  "Peduzzi et al. (1996), J Clin Epidemiol 49(12); van Smeden et al. (2016), BMC Med Res Methodol 16:163 on its limits"),
    ),
    run=events_per_variable,
)

CLUSTER_COUNT = CheckSpec(
    check_id="vce.cluster_count",
    title="Number of clusters",
    requires=frozenset({"vce.cluster"}),
    blinding="design",
    thresholds=(
        Threshold("caution_below", 40.0, "fewer than 40 clusters",
                  "Cameron, Gelbach & Miller (2008), REStat 90(3); Angrist & Pischke (2009), section 8.2"),
    ),
    run=cluster_count,
)

HETEROSKEDASTICITY = CheckSpec(
    check_id="fit.heteroskedasticity",
    title="Heteroskedasticity (Breusch-Pagan)",
    requires=frozenset({"method.least_squares", "design.linear_predictor"}),
    blinding="post_fit",
    thresholds=(Threshold("alpha", 0.05, "Breusch-Pagan p below 0.05", "Breusch & Pagan (1979), Econometrica 47(5)"),),
    run=heteroskedasticity,
)

OVERDISPERSION = CheckSpec(
    check_id="fit.overdispersion",
    title="Overdispersion (Cameron-Trivedi)",
    requires=frozenset({"outcome.count", "dispersion.fixed"}),
    blinding="post_fit",
    thresholds=(Threshold("alpha", 0.05, "one-sided p below 0.05", "Cameron & Trivedi (1990), J Econometrics 46(3)"),),
    run=overdispersion,
)
