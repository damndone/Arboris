from __future__ import annotations

from typing import Any

from ..checks.iv_checks import FIRST_STAGE_STRENGTH


def build_iv_diagnostics(
    fitted: Any, n_endog: int, n_instruments: int, strength_check: dict | None = None,
) -> dict:
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
    # v1.8.10: thresholds and verdict come from the check library's
    # iv.first_stage_strength, so the card and the run's issues agree.
    fs_diag = fitted.first_stage.diagnostics
    min_f = float(fs_diag["f.stat"].min())
    fails_below = FIRST_STAGE_STRENGTH.threshold("fails_below")
    caution_below = FIRST_STAGE_STRENGTH.threshold("caution_below")
    verdict = "weak" if min_f < fails_below else "caution" if min_f < caution_below else "strong"
    weak = {
        "first_stage_f": min_f,
        "threshold": fails_below,
        "caution_threshold": caution_below,
        "verdict": verdict,
        "message": (strength_check or {}).get("summary") or (
            f"First-stage F = {min_f:.1f}." if verdict == "strong" else
            f"First-stage F = {min_f:.1f}, below {caution_below:g}."
        ),
        "anderson_rubin_95": ((strength_check or {}).get("evidence") or {}).get("anderson_rubin_95"),
    }

    # --- endogeneity: Wu-Hausman ---
    wh = fitted.wu_hausman()
    wh_stat, wh_p = float(wh.stat), float(wh.pval)
    endogeneity = {
        "test": "wu_hausman",
        "statistic": wh_stat,
        "pvalue": wh_p,
        "verdict": "rejects_exogeneity" if wh_p < 0.05 else "does_not_reject",
        # v1.8.10: a post-fit test may inform inference, not the choice of
        # specification (design section 4.3), and not rejecting is not proof.
        "message": (
            "The Wu-Hausman test rejects exogeneity of the regressor (p < 0.05)."
            if wh_p < 0.05 else
            "The Wu-Hausman test does not reject exogeneity (p >= 0.05); this does not show the "
            "regressor is exogenous."
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
