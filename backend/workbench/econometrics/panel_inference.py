"""Cluster-robust inference for fixed-effects panel fits, as Stata's ``xtreg, fe``.

Fixed-effects panels, TWFE DID and TWFE event studies cluster by entity by
default (v1.8.11). Heteroskedasticity-robust errors that ignore the clustering
are not consistent when the number of periods is fixed (Stock & Watson 2008,
Econometrica 76(1)), and an unclustered DID can reject a true null far more
often than its nominal size (Bertrand, Duflo & Mullainathan 2004).

The covariance is CR1 with Stata's finite-sample rule,
``G/(G-1) * (N-1)/(N-K) * bread * meat * bread``, and inference uses
t(G - 1). K counts every estimated parameter except the fixed effects nested
within the clusters (Cameron & Miller 2015, section VI): entity effects are
nested in entity clusters (or in any coarser clusters that contain whole
entities) and do not count; time effects are not nested and do. This is what
``xtreg y x i.time, fe vce(cluster id)`` and ``reghdfe`` report.

linearmodels supplies the point estimates; the sandwich is computed here on the
within-transformed design with the grand means added back (the sum-to-zero
parameterisation linearmodels reports, intercept included). The fit is then
wrapped so the result packet, the inference kernel and every diagnostic read
the replaced covariance -- never the one still on the linearmodels object.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

_DEMEAN_TOLERANCE = 1e-13
_DEMEAN_MAX_ITERATIONS = 10_000
#: The point estimates recomputed on the within design must reproduce
#: linearmodels' to this relative precision, or the residuals the sandwich uses
#: would belong to a different fit.
_ESTIMATE_AGREEMENT = 1e-7


class PanelInferenceError(ValueError):
    """The clustered covariance cannot be computed for this fit."""


@dataclass(frozen=True)
class ClusteredCovariance:
    names: tuple[str, ...]
    covariance: np.ndarray
    n_clusters: int
    nobs: int
    #: Parameters counted in the finite-sample factor (N - 1) / (N - K).
    parameters_counted: int
    cluster_variable: str

    @property
    def df(self) -> int:
        return self.n_clusters - 1


def _within(columns: pd.DataFrame, groups: Sequence[pd.Series]) -> pd.DataFrame:
    """Sweep out each grouping's means until the columns stop changing.

    One sweep is exact for one-way effects and for balanced two-way panels;
    unbalanced two-way panels converge by alternating projections.
    """
    current = columns.astype(float)
    for _ in range(_DEMEAN_MAX_ITERATIONS):
        previous = current
        for group in groups:
            current = current - current.groupby(group.to_numpy()).transform("mean")
        scale = max(1.0, float(np.max(np.abs(previous.to_numpy()))))
        if float(np.max(np.abs(current.to_numpy() - previous.to_numpy()))) <= _DEMEAN_TOLERANCE * scale:
            return current
        if len(groups) == 1:
            return current
    raise PanelInferenceError("the within transformation did not converge")


def _nested(inner: pd.Series, outer: pd.Series) -> bool:
    """Whether every level of ``inner`` lies inside a single cluster."""
    return bool((pd.DataFrame({"inner": inner.to_numpy(), "outer": outer.to_numpy()})
                 .groupby("inner")["outer"].nunique() <= 1).all())


def clustered_covariance(
    frame: pd.DataFrame,
    *,
    y: str,
    regressors: Sequence[str],
    entity: pd.Series | None,
    time: pd.Series | None,
    clusters: pd.Series,
    cluster_variable: str,
    params: pd.Series,
) -> ClusteredCovariance:
    """The Stata-rule CR1 covariance of a fixed-effects fit.

    ``frame`` holds exactly the estimation rows, in the fit's order; ``params``
    are linearmodels' estimates, named ``Intercept`` and ``regressors``.
    """
    clusters = pd.Series(clusters.to_numpy(), index=frame.index)
    if clusters.isna().any():
        raise PanelInferenceError(f"the cluster variable {cluster_variable} has missing values in the estimation sample")
    n_clusters = int(clusters.nunique())
    if n_clusters < 2:
        raise PanelInferenceError(f"clustering by {cluster_variable} needs at least two clusters; the sample has {n_clusters}")
    columns = [y, *regressors]
    raw = frame[columns].astype(float)
    groups = [group for group in (entity, time) if group is not None]
    groups = [pd.Series(group.to_numpy(), index=frame.index) for group in groups]
    within = _within(raw, groups) + raw.mean() if groups else raw
    design = np.column_stack([np.ones(len(within)), within[list(regressors)].to_numpy()])
    outcome = within[y].to_numpy()
    names = ("Intercept", *regressors)
    estimates, *_ = np.linalg.lstsq(design, outcome, rcond=None)
    reported = np.array([float(params[name]) for name in names])
    if not np.allclose(estimates, reported, rtol=_ESTIMATE_AGREEMENT, atol=_ESTIMATE_AGREEMENT * max(1.0, np.abs(reported).max())):
        raise PanelInferenceError("the within design does not reproduce the fitted estimates")
    residuals = outcome - design @ reported

    bread = np.linalg.pinv(design.T @ design)
    scores = pd.DataFrame(design * residuals[:, None]).groupby(clusters.to_numpy()).sum().to_numpy()
    meat = scores.T @ scores

    nobs = len(frame)
    counted = design.shape[1]
    if entity is not None and not _nested(pd.Series(entity.to_numpy()), clusters.reset_index(drop=True)):
        counted += int(entity.nunique()) - 1
    if time is not None and not _nested(pd.Series(time.to_numpy()), clusters.reset_index(drop=True)):
        counted += int(time.nunique()) - 1
    if nobs <= counted:
        raise PanelInferenceError("the sample has no residual degrees of freedom")
    factor = n_clusters / (n_clusters - 1) * (nobs - 1) / (nobs - counted)
    return ClusteredCovariance(
        names=names,
        covariance=factor * bread @ meat @ bread,
        n_clusters=n_clusters,
        nobs=nobs,
        parameters_counted=counted,
        cluster_variable=cluster_variable,
    )


class ClusteredPanelResult:
    """A linearmodels panel fit whose inference is the clustered one.

    Every attribute not replaced here is the underlying fit's. The replaced
    ones are the ones a reader of inference uses: the covariance, standard
    errors, t statistics, p-values and intervals, and the facts the inference
    kernel records (``cov_type``, ``use_t``, ``df_resid_inference``).
    """

    cov_type = "cluster"
    use_t = True
    debiased = True

    def __init__(self, fitted: Any, inference: ClusteredCovariance) -> None:
        self._fitted = fitted
        self.inference = inference
        names = list(fitted.params.index)
        order = [inference.names.index(name) for name in names]
        matrix = inference.covariance[np.ix_(order, order)]
        self.cov = pd.DataFrame(matrix, index=names, columns=names)
        self.std_errors = pd.Series(np.sqrt(np.diag(matrix)), index=names, name="std_error")
        self.tstats = fitted.params / self.std_errors
        self.pvalues = pd.Series(2 * stats.t.sf(np.abs(self.tstats), inference.df), index=names, name="pvalue")
        self.df_resid_inference = float(inference.df)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._fitted, name)

    def conf_int(self, level: float = 0.95) -> pd.DataFrame:
        critical = stats.t.ppf(0.5 + level / 2, self.inference.df)
        return pd.DataFrame(
            {"lower": self._fitted.params - critical * self.std_errors,
             "upper": self._fitted.params + critical * self.std_errors},
        )


__all__ = ["ClusteredCovariance", "ClusteredPanelResult", "PanelInferenceError", "clustered_covariance"]
