from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
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


def prepare_did_att(fitted: Any) -> dict[str, Any] | ValueError:
    """Capture the ATT or its diagnostic error without retaining the fit."""
    try:
        return _att_from_fitted(fitted)
    except Exception as exc:  # noqa: BLE001 - diagnostics publish the error message
        return ValueError(str(exc))


def _parallel_trends(event_study: dict) -> dict:
    """Joint Wald test that every pre-period (lead) coefficient is zero.

    Uses the leads' full covariance, as Stata's ``testparm``: F(q, G - 1) under
    clustered errors, chi2(q) / q against F(q, inf) otherwise. (Before v1.8.11
    this averaged the squared t statistics, which ignores the correlation
    between the leads.)"""
    terms = event_study.get("pre_period_terms") or []
    if not terms:
        return {"test": "joint_pre_leads_f", "statistic": None, "pvalue": None,
                "n_pre_leads": 0, "verdict": "unavailable", "reason": "no_estimable_pre_period_leads",
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
                "n_pre_leads": 0, "verdict": "unavailable", "reason": "no_estimable_pre_period_leads",
                "message": "No estimable pre-period leads available to test."}
    f_stat = float(beta @ np.linalg.solve(covariance, beta) / q)
    df_den = event_study.get("effective_df")
    pvalue = float(stats.f.sf(f_stat, q, df_den)) if df_den else float(stats.chi2.sf(f_stat * q, q))
    df1 = q
    verdict = "rejected" if pvalue < 0.05 else "not_rejected"
    return {"test": "joint_pre_leads_f" if df_den else "joint_pre_leads_wald", "statistic": f_stat if df_den else f_stat*q,
            "pvalue": round(pvalue, 6), "n_pre_leads": df1, "verdict": verdict,
            "df_num": q, "df_den": df_den,
            "distribution": "F" if df_den else "chi2",
            "statistic_definition": "wald_over_q" if df_den else "wald_chi_square",
            "tested_pre_leads": [term for term, included in zip(terms, keep) if included],
            "omitted_pre_leads": [term for term, included in zip(terms, keep) if not included],
            "message": (
                "Zero pre-period coefficients are not rejected; this does not establish counterfactual parallel trends."
                if verdict == "not_rejected" else
                "Zero pre-period coefficients are rejected; review the design and identifying assumptions.")}


def build_did_diagnostics(fitted: Any, norm: NormalizedDID, frame, *,
                          covariance: str = "clustered", cluster_col: str | None = None,
                          prepared_att: dict[str, Any] | ValueError | None = None) -> dict:
    """Build DID diagnostics using the fitted ATT or its prepared summary."""
    # The event study is unidentified for a single treatment cohort (event-time
    # indicators collinear with the time fixed effects). Skip it gracefully — the
    # ATT is still valid — exactly as Bacon is skipped on an unbalanced panel.
    try:
        # The event study deep-copies its input and retains it during both fits.
        event_columns = {norm.y, norm.entity, norm.time, "_did_event_time", cluster_col}
        event_frame = pd.DataFrame(
            {column: frame[column] for column in frame.columns if column in event_columns},
            index=frame.index, copy=False,
        )
        es = run_event_study(event_frame, y=norm.y, x=[], entity=norm.entity,
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

    if isinstance(prepared_att, ValueError):
        raise prepared_att
    att = _att_from_fitted(fitted) if prepared_att is None else prepared_att.copy()
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
