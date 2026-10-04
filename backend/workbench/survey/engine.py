"""Where Design, Estimator and Variance meet — and the only place they meet.

`estimate_with_design` is deliberately ignorant of model families.  It asks the
estimator what it can do, asks the design what that permits, and refuses
combinations that are derivably impossible.  There is no family axis anywhere in
this module, and adding one would defeat the purpose of the block.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

from .design import DF_CONVENTIONS, SurveyDesign
from .errors import SurveyCompositionError, SurveyEngineError
from .estimator import EstimatorSpec, missing_capabilities

#: Above this share of unusable replicates the result is refused rather than
#: reported.  Silently dropping them shrinks the standard error with nothing on
#: screen to say so.
MAX_REPLICATE_FAILURE_RATE = 0.2


@dataclass(frozen=True)
class ReplicateSummary:
    attempted: int
    succeeded: int
    failed: int
    failure_reasons: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class JointTest:
    statistic: float
    df: int
    ddf: int
    p_value: float


@dataclass
class DesignEstimate:
    estimates: dict[str, float]
    standard_errors: dict[str, float]
    degf: int
    method: str
    covariance: np.ndarray
    terms: list[str]
    replicate_summary: ReplicateSummary | None = None
    df_convention: str = "design"

    @property
    def residual_degf(self) -> int:
        """Design df less the parameters spent: `degf - p + 1` (R's `df.residual`
        for svyglm). Reported alongside degf whichever convention is chosen."""
        return self.degf - len(self.terms) + 1

    @property
    def inference_degf(self) -> int:
        """The df coefficient t tests and intervals use, by the chosen convention.

        Here degf is 8 and p is 3: qt(.975, 8) = 2.306 under "design",
        qt(.975, 6) = 2.447 under "design_minus_p" -- not a subtle difference.
        """
        return self.degf if self.df_convention == "design" else self.residual_degf

    def _critical(self) -> float:
        return float(stats.t.ppf(0.975, self.inference_degf))

    @property
    def ci_lower(self) -> dict[str, float]:
        c = self._critical()
        return {k: self.estimates[k] - c * self.standard_errors[k] for k in self.terms}

    @property
    def ci_upper(self) -> dict[str, float]:
        c = self._critical()
        return {k: self.estimates[k] + c * self.standard_errors[k] for k in self.terms}

    def joint_test(self, terms: list[str]) -> JointTest:
        """Design-based Wald test of the terms jointly equal to zero.

        "design": the Korn-Graubard adjusted F, (d - q + 1) / (d q) W on
        (q, d - q + 1) with d the design df (Stata's default after svy).
        "design_minus_p": W / q on (q, degf - p + 1), R's regTermTest.
        """
        idx = [self.terms.index(t) for t in terms]
        beta = np.array([self.estimates[t] for t in terms])
        vcov = self.covariance[np.ix_(idx, idx)]
        q = len(terms)
        wald = float(beta @ np.linalg.solve(vcov, beta))
        if self.df_convention == "design":
            d = self.degf
            ddf = d - q + 1
            if ddf <= 0:
                raise SurveyEngineError(
                    "SURVEY_TOO_FEW_DESIGN_DF",
                    f"{q} constraints need more than {d} design degrees of freedom",
                )
            stat = wald * ddf / (d * q)
        else:
            ddf = self.residual_degf
            stat = wald / q
        return JointTest(
            statistic=stat, df=q, ddf=ddf,
            p_value=float(stats.f.sf(stat, q, ddf)),
        )


def _as_arrays(values: Mapping[str, object], terms: list[str]) -> np.ndarray:
    return np.array([np.asarray(values[t], dtype=float) for t in terms])


def estimate_with_design(
    design: SurveyDesign,
    estimator: EstimatorSpec,
    *,
    method: str,
    replicate_type: str | None = None,
    df_convention: str = "design",
) -> DesignEstimate:
    if df_convention not in DF_CONVENTIONS:
        raise SurveyEngineError(
            "SURVEY_DF_CONVENTION_INVALID",
            f"unknown degrees-of-freedom convention {df_convention!r}; use one of {list(DF_CONVENTIONS)}",
        )
    missing = missing_capabilities(estimator, method)
    if missing:
        raise SurveyCompositionError(
            "SURVEY_ESTIMATOR_LACKS_CAPABILITY",
            f"{estimator.name!r} cannot use the {method!r} variance channel",
            missing_capabilities=missing,
            estimator=estimator.name,
            method=method,
        )

    mask = design.subpop_mask()
    frame = design.frame.loc[mask]
    weights = design.weights[mask]

    point = dict(estimator.refit(frame, weights))
    terms = list(point)

    if method == "linearization":
        contributions = _as_arrays(estimator.influence(frame, weights), terms).T
        cov = design._design_variance(contributions, mask=mask)
        summary = None
    elif method == "replicate":
        cov, summary = _replicate_covariance(
            design, estimator, terms, point, replicate_type=replicate_type
        )
    else:
        raise SurveyEngineError("SURVEY_VARIANCE_METHOD_UNKNOWN", method)

    return DesignEstimate(
        estimates=point,
        standard_errors={t: float(np.sqrt(cov[i, i])) for i, t in enumerate(terms)},
        degf=design.degf,
        method=method,
        covariance=cov,
        terms=terms,
        replicate_summary=summary,
        df_convention=df_convention,
    )


def _replicate_covariance(
    design: SurveyDesign,
    estimator: EstimatorSpec,
    terms: list[str],
    point: dict[str, float],
    *,
    replicate_type: str | None,
) -> tuple[np.ndarray, ReplicateSummary]:
    from .replicates import build_replicates

    rep_weights, scales = build_replicates(design, replicate_type)
    mask = design.subpop_mask()
    frame = design.frame.loc[mask]
    theta0 = np.array([point[t] for t in terms])

    thetas: list[np.ndarray] = []
    used_scales: list[float] = []
    reasons: dict[str, int] = {}
    for column, scale in zip(rep_weights.T, scales, strict=True):
        try:
            fitted = estimator.refit(frame, column[mask])
            thetas.append(np.array([float(fitted[t]) for t in terms]))
            used_scales.append(scale)
        except Exception as exc:  # noqa: BLE001 - the reason is reported, not swallowed
            reason = type(exc).__name__
            reasons[reason] = reasons.get(reason, 0) + 1

    attempted = rep_weights.shape[1]
    succeeded = len(thetas)
    summary = ReplicateSummary(
        attempted=attempted,
        succeeded=succeeded,
        failed=attempted - succeeded,
        failure_reasons=reasons,
    )

    if succeeded == 0 or summary.failed / attempted > MAX_REPLICATE_FAILURE_RATE:
        raise SurveyEngineError(
            "SURVEY_REPLICATE_FAILURE_RATE_EXCEEDED",
            f"{summary.failed}/{attempted} replicates failed",
            attempted=attempted,
            failed=summary.failed,
            failure_reasons=reasons,
        )

    # R centres replicate deviations on the mean of the replicates, not on the
    # full-sample estimate (`survey.replicates.mse` defaults to FALSE).  The gap
    # is small enough to look like noise and large enough to fail a 1e-8 oracle.
    theta_matrix = np.array(thetas)
    deviations = theta_matrix - theta_matrix.mean(axis=0)
    cov = np.zeros((len(terms), len(terms)), dtype=float)
    for deviation, scale in zip(deviations, used_scales, strict=True):
        cov += scale * np.outer(deviation, deviation)
    return cov, summary
