from __future__ import annotations

from typing import Any

import numpy as np
from scipy import stats

from ..econometrics.runner import run_event_study
from .goodman_bacon import goodman_bacon_decompose
from .did_spec import NormalizedDID


def _att_from_fitted(fitted) -> dict:
    est = float(fitted.params["_did_D"])
    se = float(fitted.std_errors["_did_D"])
    p = float(fitted.pvalues["_did_D"])
    ci = fitted.conf_int().loc["_did_D"]
    return {"estimate": est, "std_error": se, "pvalue": round(p, 6),
            "ci": [float(ci.iloc[0]), float(ci.iloc[1])], "spec": "twfe"}


def _parallel_trends(event_study: dict) -> dict:
    """Joint significance of the pre-period (lead) coefficients via a Wald-style
    F approximation: mean((coef/se)^2) over leads ~ F(df1, inf)."""
    leads = [(c, s) for k, c, s in zip(event_study["event_time"],
                                       event_study["coef"], event_study["se"]) if k < 0]
    if not leads:
        return {"test": "joint_pre_leads_f", "statistic": None, "pvalue": None,
                "n_pre_leads": 0, "verdict": "not_rejected",
                "message": "No pre-period leads available to test."}
    z2 = [(c / s) ** 2 for c, s in leads if s and s > 0]
    f_stat = float(np.mean(z2)) if z2 else 0.0
    df1 = len(z2)
    pvalue = float(stats.f.sf(f_stat, df1, 10_000)) if df1 else 1.0
    verdict = "rejected" if pvalue < 0.05 else "not_rejected"
    return {"test": "joint_pre_leads_f", "statistic": f_stat,
            "pvalue": round(pvalue, 6), "n_pre_leads": df1, "verdict": verdict,
            "message": (
                "Pre-trend leads jointly insignificant (p >= 0.05); parallel "
                "trends not rejected." if verdict == "not_rejected" else
                "Pre-trend leads jointly significant (p < 0.05); parallel trends "
                "rejected — DID identifying assumption is suspect.")}


def build_did_diagnostics(fitted: Any, norm: NormalizedDID, frame, *,
                          covariance: str = "robust") -> dict:
    # The event study is unidentified for a single treatment cohort (event-time
    # indicators collinear with the time fixed effects). Skip it gracefully — the
    # ATT is still valid — exactly as Bacon is skipped on an unbalanced panel.
    try:
        es = run_event_study(frame, y=norm.y, x=[], entity=norm.entity,
                             time=norm.time, event_time_col="_did_event_time",
                             ref_period=-1, covariance=covariance)
        es["applicable"] = True
    except ValueError as exc:
        if not str(exc).startswith("DID_EVENT_STUDY_UNIDENTIFIED"):
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
