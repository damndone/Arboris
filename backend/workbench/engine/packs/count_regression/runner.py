"""Numerical implementations owned by this model family pack."""
from __future__ import annotations
from typing import Any
import pandas as pd
import statsmodels.formula.api as smf
from ....econometrics.normalize import normalize_statsmodels_result
from ....econometrics.fit_support import (
    _formula_term, _ols_formula, _ensure_numeric_y, _ensure_numeric_x,
    _add_engine, _root_cause_suffix, _attach_average_marginal_effects,
)

def run_poisson(
    frame: pd.DataFrame, y: str, x: list[str], model_id: str,
    exposure_col: str | None = None,
    categorical_x: set[str] | None = None,
) -> tuple[dict[str, Any], Any]:
    frame = _ensure_numeric_y(frame, y)
    series = frame[y].dropna()
    if (series < 0).any():
        raise ValueError(
            f"Poisson model requires non-negative y, "
            f"but column '{y}' has negative values."
        )
    if not pd.api.types.is_numeric_dtype(series):
        raise ValueError(
            f"Poisson model requires numeric y, "
            f"but column '{y}' is non-numeric."
        )
    if not (series == series.astype(int)).all():
        raise ValueError(
            f"Poisson model requires integer y (counts), "
            f"but column '{y}' has non-integer values."
        )

    cat = categorical_x or set()
    formula = _ols_formula(y, [_formula_term(column, column in cat) for column in x])

    exposure_actually_used = False
    if exposure_col is not None and exposure_col in frame.columns:
        exposure_vals = frame[exposure_col].values
        if (exposure_vals <= 0).any():
            import warnings
            warnings.warn(
                f"Exposure column '{exposure_col}' contains non-positive values "
                f"(zeros or negatives). Falling back to standard Poisson "
                f"without exposure adjustment."
            )
            fitted = smf.poisson(formula=formula, data=frame).fit(disp=False, maxiter=100)
        else:
            from statsmodels.genmod.families import Poisson
            fitted = smf.glm(
                formula=formula, data=frame,
                family=Poisson(),
                exposure=exposure_vals,
            ).fit(disp=False, maxiter=100)
            exposure_actually_used = True
    else:
        fitted = smf.poisson(formula=formula, data=frame).fit(disp=False, maxiter=100)

    if not getattr(fitted, "converged", True):
        raise ValueError(
            f"Poisson model {model_id} did not converge."
        )
    result = normalize_statsmodels_result(fitted, model_id)
    if exposure_actually_used:
        result["model_type"] = "poisson_rate"
        result["exposure_col"] = exposure_col
    else:
        result["model_type"] = "poisson"
    _attach_average_marginal_effects(result, fitted)
    return _add_engine(result), fitted



def run_negative_binomial(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    model_id: str,
    categorical_x: set[str] | None = None,
    *,
    dispersion: str = "mean",
    alpha: float | None = None,
) -> tuple[dict[str, Any], Any]:
    from ....econometrics.count_models import fit_negative_binomial

    frame = _ensure_numeric_y(frame, y)
    frame = _ensure_numeric_x(frame, x)
    cat = categorical_x or set()
    formula = _ols_formula(y, [_formula_term(column, column in cat) for column in x])
    try:
        return fit_negative_binomial(frame, formula, model_id, dispersion=dispersion, alpha=alpha, y_column=y)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            f"Negative Binomial model {model_id} failed to fit.{_root_cause_suffix(exc)}"
        ) from exc



def run_glm(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    model_id: str,
    family_name: str,
    categorical_x: set[str] | None = None,
    *,
    alpha: float | None = None,
) -> tuple[dict[str, Any], Any]:
    from ....econometrics.count_models import fit_glm

    frame = _ensure_numeric_y(frame, y)
    frame = _ensure_numeric_x(frame, x)
    cat = categorical_x or set()
    formula = _ols_formula(y, [_formula_term(column, column in cat) for column in x])
    try:
        return fit_glm(frame, formula, model_id, family_name, alpha=alpha)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            f"GLM model {model_id} failed to fit.{_root_cause_suffix(exc)}"
        ) from exc
