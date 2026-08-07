"""Factorial ANOVA and ANCOVA on the existing least-squares path.

There is no regression engine here.  Factors, interactions and covariates are
already expressible in the declarative term layer, and the fit goes through
statsmodels the same way OLS does; what this module adds is the
sums-of-squares decomposition, effect sizes and post-hoc comparisons that turn
a linear model into an analysis of variance.  A parallel implementation would
be a second place for the same statistics to drift.

The sums-of-squares type is required rather than defaulted.  SPSS's GLM gives
Type III, R's `aov` gives Type I, and on an unbalanced design they disagree --
on the committed fixture SS(factor_a) is 166.74 against 104.05, a 60% gap.
Choosing one silently would hand a user numbers that differ from the software
they came from with nothing indicating a choice was made for them.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from statsmodels.stats.anova import anova_lm

SUPPORTED_SUMS_OF_SQUARES = (1, 2, 3)


class AnovaOptionsError(ValueError):
    """An ANOVA request that cannot be admitted."""


def validate_anova_model_options(options: Any) -> None:
    if not isinstance(options, dict):
        raise AnovaOptionsError("ANOVA_OPTIONS_INVALID: model_options must be an object")

    if "sums_of_squares" not in options:
        raise AnovaOptionsError(
            "ANOVA_SUMS_OF_SQUARES_REQUIRED: declare sums_of_squares as 1, 2 or 3. "
            "There is no default because SPSS reports Type III and R's aov reports "
            "Type I, and on an unbalanced design they disagree."
        )
    ss_type = options["sums_of_squares"]
    if ss_type not in SUPPORTED_SUMS_OF_SQUARES:
        raise AnovaOptionsError(
            f"ANOVA_SUMS_OF_SQUARES_INVALID: {ss_type!r} is not one of "
            f"{SUPPORTED_SUMS_OF_SQUARES}"
        )

    categorical = options.get("categorical") or []
    if not isinstance(categorical, list) or not categorical:
        raise AnovaOptionsError(
            "ANOVA_FACTORS_REQUIRED: at least one categorical factor must be declared"
        )

    posthoc = options.get("posthoc")
    if posthoc is not None and posthoc not in {"tukey", "bonferroni"}:
        raise AnovaOptionsError(
            f"ANOVA_POSTHOC_INVALID: {posthoc!r} is not one of ('tukey', 'bonferroni')"
        )


def _term(column: str, *, categorical: bool, ss_type: int) -> str:
    if not categorical:
        return f"Q('{column}')"
    # Type III main effects are only interpretable under sum-to-zero coding.
    # With treatment contrasts the quantity reported as a "main effect" is the
    # effect at the reference level -- a different thing wearing the same name.
    coding = ", Sum" if ss_type == 3 else ""
    return f"C(Q('{column}'){coding})"


def build_formula(y: str, x: list[str], *, categorical: list[str], interactions: list[list[str]], ss_type: int) -> str:
    cat = set(categorical)
    main = [_term(column, categorical=column in cat, ss_type=ss_type) for column in x]
    parts = list(main)
    for combo in interactions or []:
        parts.append(":".join(_term(c, categorical=c in cat, ss_type=ss_type) for c in combo))
    return f"Q('{y}') ~ " + " + ".join(parts)


#: statsmodels labels these `Intercept` and `Residual`; the conventional
#: statistical labels, and the ones R reports, carry the parentheses and the
#: plural. Normalising here means the table reads the same as the reference
#: output instead of asking every consumer to translate.
_CANONICAL_TERMS = {"Intercept": "(Intercept)", "Residual": "Residuals"}


def _public_term(label: str, columns: list[str]) -> str:
    """Map a patsy term back to the columns the user declared."""
    text = str(label)
    if text in _CANONICAL_TERMS:
        return _CANONICAL_TERMS[text]
    for column in sorted(columns, key=len, reverse=True):
        text = text.replace(f"C(Q('{column}'), Sum)", column)
        text = text.replace(f"C(Q('{column}'))", column)
        text = text.replace(f"Q('{column}')", column)
    return text


def fit_anova(
    frame: pd.DataFrame, *, y: str, x: list[str], options: dict[str, Any], model_id: str
) -> dict[str, Any]:
    validate_anova_model_options(options)
    ss_type = int(options["sums_of_squares"])
    categorical = list(options.get("categorical") or [])
    interactions = [list(pair) for pair in (options.get("interactions") or [])]

    formula = build_formula(
        y, x, categorical=categorical, interactions=interactions, ss_type=ss_type
    )
    fitted = smf.ols(formula=formula, data=frame).fit()
    table = anova_lm(fitted, typ=ss_type)

    columns = [y, *x]
    rows: list[dict[str, Any]] = []
    residual_ss = float(table.loc["Residual", "sum_sq"]) if "Residual" in table.index else None
    for label, row in table.iterrows():
        rows.append({
            "term": _public_term(label, columns),
            "sum_sq": float(row["sum_sq"]),
            "df": float(row["df"]),
            "f": float(row["F"]) if "F" in row and not pd.isna(row["F"]) else None,
            "p_value": float(row["PR(>F)"]) if "PR(>F)" in row and not pd.isna(row["PR(>F)"]) else None,
        })

    partial_eta: dict[str, float] = {}
    if residual_ss:
        for entry in rows:
            if entry["term"] == "Residuals":
                continue
            partial_eta[entry["term"]] = entry["sum_sq"] / (entry["sum_sq"] + residual_ss)

    result: dict[str, Any] = {
        "contract": "anova_result",
        "schema_version": 1,
        "model_id": model_id,
        "model_type": "anova",
        "engine": "statsmodels",
        "nobs": int(fitted.nobs),
        "coefficients": {
            _public_term(name, columns): {
                "estimate": float(value),
                "std_error": float(fitted.bse[name]),
                "p_value": float(fitted.pvalues[name]),
            }
            for name, value in fitted.params.items()
        },
        "validation": {"status": "ok"},
        "sums_of_squares_type": ss_type,
        "contrast_coding": "sum" if ss_type == 3 else "treatment",
        "anova_table": rows,
        "effect_sizes": {"partial_eta_squared": partial_eta},
        "r_squared": float(fitted.rsquared),
    }

    posthoc = options.get("posthoc")
    if posthoc:
        result["posthoc"] = _posthoc(frame, y=y, categorical=categorical, correction=posthoc)
    return result


def _posthoc(frame: pd.DataFrame, *, y: str, categorical: list[str], correction: str) -> dict[str, Any]:
    """Pairwise comparisons per factor.

    An omnibus F says something differs; it does not say which pair, and that
    is the question the user actually asked.
    """
    from ....statistical_tests import posthoc_anova

    comparisons: list[dict[str, Any]] = []
    for factor in categorical:
        groups = {
            str(level): pd.to_numeric(frame.loc[frame[factor] == level, y], errors="coerce")
            .dropna()
            .tolist()
            for level in sorted(frame[factor].dropna().unique(), key=str)
        }
        groups = {k: v for k, v in groups.items() if len(v) >= 2}
        if len(groups) < 2:
            continue
        outcome = posthoc_anova(groups, correction=correction)
        for row in outcome.get("comparisons", []):
            comparisons.append({**row, "factor": factor})
    return {"correction": correction, "comparisons": comparisons}
