from __future__ import annotations

from typing import Any

import numpy as np
from scipy import stats

from ..econometrics.runner import run_event_study
from .goodman_bacon import goodman_bacon_decompose
from .did_spec import NormalizedDID


def _att_from_fitted(fitted) -> dict:
    if fitted.params.get("_did_D") is None:
        raise ValueError(
            "DID_ATT_ABSORBED: the treatment indicator _did_D was absorbed/dropped; "
            "ATT not identified"
        )
    est = float(fitted.params["_did_D"])
    se = float(fitted.std_errors["_did_D"])
    p = float(fitted.pvalues["_did_D"])
    ci = fitted.conf_int().loc["_did_D"]
    return {"estimate": est, "std_error": se, "pvalue": round(p, 6),
            "ci": [float(ci.iloc[0]), float(ci.iloc[1])], "spec": "twfe"}


def _parallel_trends(event_study: dict) -> dict:
    """Joint Wald test that every pre-period (lead) coefficient is zero.

    Uses the leads' full covariance, as Stata's ``testparm``: F(q, G - 1) under
    clustered errors, chi2(q) / q against F(q, inf) otherwise. (Before v1.8.11
    this averaged the squared t statistics, which ignores the correlation
    between the leads.)"""
    terms = event_study.get("pre_period_terms") or []
    if not terms:
        return {"test": "joint_pre_leads_f", "statistic": None, "pvalue": None,
                "n_pre_leads": 0, "verdict": "not_rejected",
                "message": "No pre-period leads available to test."}
    beta = np.asarray([np.nan if v is None else v for v in event_study["pre_period_estimates"]], dtype=float)
    covariance = np.asarray(
        [[np.nan if v is None else v for v in row] for row in event_study["pre_period_covariance"]], dtype=float
    )
    # An absorbed lead has no estimate; the test covers the leads that have one.
    keep = np.isfinite(beta) & np.isfinite(np.diag(covariance)) & (np.diag(covariance) > 0)
    beta, covariance = beta[keep], covariance[np.ix_(keep, keep)]
    q = int(keep.sum())
    if q == 0:
        return {"test": "joint_pre_leads_f", "statistic": None, "pvalue": None,
                "n_pre_leads": 0, "verdict": "not_rejected",
                "message": "No estimable pre-period leads available to test."}
    f_stat = float(beta @ np.linalg.solve(covariance, beta) / q)
    df_den = event_study.get("effective_df")
    pvalue = float(stats.f.sf(f_stat, q, df_den)) if df_den else float(stats.chi2.sf(f_stat * q, q))
    df1 = q
    verdict = "rejected" if pvalue < 0.05 else "not_rejected"
    return {"test": "joint_pre_leads_f", "statistic": f_stat,
            "pvalue": round(pvalue, 6), "n_pre_leads": df1, "verdict": verdict,
            "df_num": q, "df_den": df_den,
            "distribution": "F" if df_den else "chi2",
            "message": (
                "Pre-trend leads jointly insignificant (p >= 0.05); parallel "
                "trends not rejected." if verdict == "not_rejected" else
                "Pre-trend leads jointly significant (p < 0.05); parallel trends "
                "rejected — DID identifying assumption is suspect.")}


def build_did_diagnostics(fitted: Any, norm: NormalizedDID, frame, *,
                          covariance: str = "clustered", cluster_col: str | None = None) -> dict:
    # The event study is unidentified for a single treatment cohort (event-time
    # indicators collinear with the time fixed effects). Skip it gracefully — the
    # ATT is still valid — exactly as Bacon is skipped on an unbalanced panel.
    try:
        es = run_event_study(frame, y=norm.y, x=[], entity=norm.entity,
                             time=norm.time, event_time_col="_did_event_time",
                             ref_period=-1, covariance=covariance, cluster_col=cluster_col)
        es["applicable"] = True
    except ValueError as exc:
        if not str(exc).startswith(
            ("DID_EVENT_STUDY_UNIDENTIFIED", "DID_EVENT_TIME_NONINTEGER")
        ):
            raise
        es = {"applicable": False, "message": str(exc), "event_time": [],
              "coef": [], "se": [], "ci_lower": [], "ci_upper": [], "ref_period": -1}

    att = _att_from_fitted(fitted)
    att["covariance"] = covariance
    pt = _parallel_trends(es)

    # Goodman-Bacon requires a balanced panel; skip gracefully if it can't run.
    try:
        bacon = goodman_bacon_decompose(frame, y=norm.y, entity=norm.entity,
                                        time=norm.time, cohort="_did_cohort")
        bacon["applicable"] = True
    except ValueError as exc:
        # Only the panel-shape contract errors mean "skip Bacon"; any other
        # ValueError is a real bug and must propagate, not be mislabeled.
        if not str(exc).startswith(("DID_UNBALANCED_PANEL", "DID_BACON_EMPTY_CELL")):
            raise
        bacon = {"applicable": False, "message": str(exc),
                 "components": [], "weighted_avg": None, "forbidden_weight": None}

    out = {
        "att": att,
        "event_study": es,
        "parallel_trends": pt,
        "goodman_bacon": bacon,
        "spec": norm.summary,
    }
    if norm.summary.get("staggered"):
        fw = bacon.get("forbidden_weight")
        fw_txt = f" (Goodman-Bacon weight {fw:.0%})" if isinstance(fw, (int, float)) else ""
        out["interpretation_restriction"] = (
            "Staggered adoption detected. The TWFE estimate mixes good and "
            f"'forbidden' comparisons{fw_txt}. For staggered designs prefer a "
            "modern estimator — see Layer 2 (Callaway-Sant'Anna)."
        )
    return out
