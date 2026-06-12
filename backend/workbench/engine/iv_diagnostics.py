from __future__ import annotations

from typing import Any

_WEAK_F_THRESHOLD = 10.0  # Staiger-Stock rule of thumb (NOT a guarantee)


def build_iv_diagnostics(fitted: Any, n_endog: int, n_instruments: int) -> dict:
    """Build the standard IV diagnostic trio from a fitted linearmodels IV2SLS result.

    linearmodels 7.0 accessors used:
      - weak instruments: ``fitted.first_stage.diagnostics`` (DataFrame, one row per
        endog) column ``'f.stat'`` -> first-stage F per endog; report the MIN.
      - endogeneity:      ``fitted.wu_hausman()`` -> WaldTestStatistic (.stat / .pval)
      - overidentification: ``fitted.sargan`` -> WaldTestStatistic (.stat / .pval),
        only meaningful when over-identified.

    All numeric values are plain Python floats so the dict is JSON-serializable.
    """
    identification = (
        "under" if n_instruments < n_endog
        else "just" if n_instruments == n_endog
        else "over"
    )

    # --- weak instruments: min first-stage F across endog ---
    fs_diag = fitted.first_stage.diagnostics
    min_f = float(fs_diag["f.stat"].min())
    weak = {
        "first_stage_f": min_f,
        "threshold": _WEAK_F_THRESHOLD,
        "verdict": "strong" if min_f > _WEAK_F_THRESHOLD else "weak",
        "message": (
            "Instruments are strong (first-stage F > 10, rule of thumb)."
            if min_f > _WEAK_F_THRESHOLD else
            "Instruments appear weak (first-stage F <= 10); interpret with caution."
        ),
    }

    # --- endogeneity: Wu-Hausman ---
    wh = fitted.wu_hausman()
    wh_stat, wh_p = float(wh.stat), float(wh.pval)
    endogeneity = {
        "test": "wu_hausman",
        "statistic": wh_stat,
        "pvalue": wh_p,
        "verdict": "endogenous" if wh_p < 0.05 else "exogenous",
        "message": (
            "Endogeneity confirmed (p < 0.05); IV is warranted."
            if wh_p < 0.05 else
            "No endogeneity detected (p >= 0.05); OLS is consistent and more efficient."
        ),
    }

    # --- overidentification: Sargan, only when over-identified ---
    if identification == "over":
        sg = fitted.sargan
        s_stat, s_p = float(sg.stat), float(sg.pval)
        overid = {
            "applicable": True, "test": "sargan",
            "statistic": s_stat, "pvalue": s_p,
            "verdict": "suspect" if s_p < 0.05 else "not_rejected",
            "message": (
                "Instrument exogeneity rejected (p < 0.05); instruments suspect."
                if s_p < 0.05 else
                "Instrument exogeneity not rejected (p >= 0.05)."
            ),
        }
    else:
        overid = {"applicable": False, "verdict": "Not applicable (just-identified)."}

    return {
        "identification": identification,
        "weak_instruments": weak,
        "endogeneity": endogeneity,
        "overidentification": overid,
    }
