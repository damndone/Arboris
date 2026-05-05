from __future__ import annotations

from typing import Any

import numpy as np
from statsmodels.stats.outliers_influence import variance_inflation_factor

from .normalize import _json_safe_float


def compute_diagnostics(
    fitted: Any,
    exog: Any,
    model_id: str,
    model_family: str = "ols",
) -> dict[str, Any]:
    resid = getattr(fitted, "resid", None)
    if resid is None:
        resid = getattr(fitted, "resid_response", None)
    if resid is None:
        resid = fitted.fittedvalues  # fallback: won't work for diagnostics but prevents crash
    n = int(fitted.nobs)

    diag: dict[str, Any] = {"model_id": model_id, "nobs": n}

    _compute_vif(exog, diag)

    if model_family in ("ols", "fixed_effects"):
        _compute_breusch_pagan(fitted, resid, diag)
        _compute_durbin_watson(resid, diag)
        _compute_jarque_bera(resid, n, diag)
        _compute_cooks_distance(fitted, diag)

    if model_family in ("logit",):
        _check_separation(fitted, diag)

    return diag


def _compute_vif(exog: Any, diag: dict[str, Any]) -> None:
    if exog.shape[1] < 2:
        diag["vif"] = {}
        return
    try:
        import pandas as pd
        import statsmodels.api as sm

        exog_array = sm.add_constant(exog)
        vif_values: dict[str, float | None] = {}
        for i, col in enumerate(exog_array.columns if isinstance(exog_array, pd.DataFrame) else range(exog_array.shape[1])):
            try:
                vif = float(variance_inflation_factor(exog_array.values, i))
                vif_values[str(col)] = None if not np.isfinite(vif) else round(vif, 2)
            except Exception:
                vif_values[str(col)] = None
        diag["vif"] = vif_values
    except Exception:
        diag["vif"] = {"error": "VIF computation failed"}


def _compute_breusch_pagan(fitted: Any, resid: Any, diag: dict[str, Any]) -> None:
    try:
        from statsmodels.stats.diagnostic import het_breuschpagan

        bp_stat, bp_p, _, _ = het_breuschpagan(resid, fitted.model.exog)
        diag["breusch_pagan"] = {
            "lm": _json_safe_float(bp_stat),
            "p_value": _json_safe_float(bp_p),
        }
    except Exception:
        diag["breusch_pagan"] = {"lm": None, "p_value": None}


def _compute_durbin_watson(resid: Any, diag: dict[str, Any]) -> None:
    try:
        from statsmodels.stats.stattools import durbin_watson

        dw = float(durbin_watson(resid))
        diag["durbin_watson"] = round(dw, 3) if np.isfinite(dw) else None
    except Exception:
        diag["durbin_watson"] = None


def _compute_jarque_bera(resid: Any, n: int, diag: dict[str, Any]) -> None:
    if n < 30:
        diag["jarque_bera"] = {"statistic": None, "p_value": None}
        return
    try:
        from statsmodels.stats.stattools import jarque_bera

        jb_stat, jb_p, _, _ = jarque_bera(resid)
        diag["jarque_bera"] = {
            "statistic": _json_safe_float(jb_stat),
            "p_value": _json_safe_float(jb_p),
        }
    except Exception:
        diag["jarque_bera"] = {"statistic": None, "p_value": None}


def _check_separation(fitted: Any, diag: dict[str, Any]) -> None:
    separation: dict[str, Any] = {
        "converged": bool(getattr(fitted, "converged", True)),
        "max_abs_coef": None,
        "max_std_error": None,
        "pred_prob_min": None,
        "pred_prob_max": None,
        "warning": None,
    }
    try:
        params = getattr(fitted, "params", None)
        if params is not None:
            import numpy as np
            vals = np.abs([float(v) for v in params.values() if hasattr(params, "values")] if hasattr(params, "values") else np.abs(list(params)))
            if len(vals) > 0:
                separation["max_abs_coef"] = round(float(np.max(vals)), 2)
        bse = getattr(fitted, "bse", None)
        if bse is not None:
            import numpy as np
            se_vals = [float(v) for v in (bse.values if hasattr(bse, "values") else bse)]
            if se_vals:
                separation["max_std_error"] = round(float(np.max(se_vals)), 2)
        fittedvals = getattr(fitted, "fittedvalues", None)
        if fittedvals is not None:
            import numpy as np
            fv = np.asarray(fittedvals, dtype=float)
            separation["pred_prob_min"] = round(float(np.min(fv)), 6)
            separation["pred_prob_max"] = round(float(np.max(fv)), 6)
    except Exception:
        pass
    if not separation["converged"]:
        separation["warning"] = "Model did not converge. Check for complete or quasi-complete separation."
    elif separation["max_abs_coef"] is not None and separation["max_abs_coef"] > 10:
        separation["warning"] = "Large coefficients detected (max |coef| > 10). Possible quasi-separation."
    elif separation["pred_prob_min"] is not None and separation["pred_prob_min"] < 1e-6:
        separation["warning"] = "Very small predicted probabilities. Possible quasi-separation."
    diag["separation"] = separation


def _compute_cooks_distance(fitted: Any, diag: dict[str, Any]) -> None:
    try:
        from statsmodels.stats.outliers_influence import OLSInfluence

        influence = OLSInfluence(fitted)
        cooks = [float(v) for v in influence.cooks_distance[0]]
        hat = [float(v) for v in influence.hat_matrix_diag]
        threshold = 4 / len(cooks) if cooks else 0.005
        max_cook = round(max(cooks), 4) if cooks else None
        n_high = sum(1 for v in cooks if v > threshold) if cooks else 0
        severe = sum(1 for v in cooks if v > 0.5) if cooks else 0
        diag["cooks_distance"] = {
            "max": max_cook,
            "threshold": round(threshold, 4),
            "n_high": n_high,
            "n_severe": severe,
            "leverage_max": round(max(hat), 4) if hat else None,
        }
    except Exception:
        diag["cooks_distance"] = {"max": None, "n_high": 0, "leverage_max": None}
