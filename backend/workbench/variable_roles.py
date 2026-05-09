"""Variable role inference for econometric workbench.

This module detects the likely econometric roles of variables (treatment,
categorical, proxy, exposure, id, time) by combining name-pattern matching
and data-type heuristics.  Each input variable receives a role entry for
every role category, with one of three statuses: "confirmed_by_rules",
"candidate", or "rejected".

Typical usage:

    roles = infer_variable_roles(df, x_vars=["x8_treatment", "city"], y_type="count")
    # roles -> {"x8_treatment": {"roles": [...]}, "city": {"roles": [...]}}
"""

from __future__ import annotations

import pandas as pd

VARIABLE_ROLE_PATTERNS: dict[str, list[str]] = {
    "treatment": ["treatment", "treated", "intervention", "policy", "program", "assigned", "did", "post"],
    "proxy": ["proxy", "index", "score", "intensity", "interaction"],
    "categorical": ["region", "state", "city", "sector", "industry", "category", "type", "code", "group", "class", "level", "tier", "rank"],
    "exposure": ["exposure", "offset", "duration", "months", "time_at_risk", "population"],
    "id": ["id", "case_id", "user_id", "firm_id", "unit_id", "gvkey", "cusip", "permno"],
    "time": ["date", "time", "year", "month", "week", "quarter", "day"],
}


def _detect_name_hints(col_name: str) -> dict[str, list[str]]:
    """Match a column name against keyword patterns for each role category.

    The column name is lower-cased and checked for substring matches from
    VARIABLE_ROLE_PATTERNS.  Returns a dict mapping role names to the
    list of matched pattern strings.
    """
    name_lower = col_name.lower()
    hints: dict[str, list[str]] = {}
    for role, patterns in VARIABLE_ROLE_PATTERNS.items():
        matched = [p for p in patterns if p in name_lower]
        if matched:
            hints[role] = matched
    return hints


def _detect_data_hints(series: pd.Series) -> list[str]:
    """Derive data-type hints from a pandas Series.

    Possible hints returned:
        all_missing, binary_0_1, positive_numeric, integer,
        low_unique_numeric, numeric, continuous, non_numeric,
        string_dtype, no_missing, high_missing, highly_unique
    """
    hints: list[str] = []
    series_clean = series.dropna()
    if len(series_clean) == 0:
        return ["all_missing"]
    nunique = int(series_clean.nunique())
    if nunique == 2:
        vals = set(series_clean.unique())
        if vals <= {0, 1} or vals <= {0.0, 1.0}:
            hints.append("binary_0_1")
    if pd.api.types.is_numeric_dtype(series_clean):
        if (series_clean > 0).all():
            hints.append("positive_numeric")
        if series_clean.dtype.kind in ("i", "u") or all(s == int(s) for s in series_clean if pd.notna(s)):
            hints.append("integer")
        if nunique <= 20 and nunique >= 3:
            hints.append("low_unique_numeric")
        hints.append("continuous" if nunique > 20 else "numeric")
    else:
        hints.append("non_numeric")
    # Only use pandas string dtype check (no isinstance fallback).
    if pd.api.types.is_string_dtype(series_clean):
        hints.append("string_dtype")
    if len(series_clean) / len(series) > 0.95:
        hints.append("no_missing")
    elif len(series_clean) / len(series) < 0.5:
        hints.append("high_missing")
    if nunique / max(len(series_clean), 1) > 0.95:
        hints.append("highly_unique")
    return hints


def infer_variable_roles(
    frame: pd.DataFrame,
    x_vars: list[str],
    y_type: str | None = None,
) -> dict:
    """Infer econometric roles for each variable in *x_vars*.

    Missing columns in *frame* are silently skipped (no special key).

    Returns a flat dict keyed by variable name, e.g.:
        {"x8_treatment": {"roles": [...]}, "x7_region_code": {"roles": [...]}}

    Each ``"roles"`` value is a list of dicts with keys:
        role, status, confidence, evidence, needs_user_confirmation
        (and optionally context_required for exposure).
    """
    roles: dict = {}
    for var in x_vars:
        if var not in frame.columns:
            continue
        series = frame[var]
        # Cast to str so name-hint detection works with non-string column names.
        name_hints = _detect_name_hints(str(var))
        data_hints = _detect_data_hints(series)
        nunique = int(series.dropna().nunique())
        var_roles: list[dict] = []

        # ------- treatment --------------------------------------------------
        # Confirmed if name hints AND binary 0/1 data.
        # Candidate if name hints only or binary 0/1 only.
        # Rejected otherwise.
        treatment_hints = name_hints.get("treatment", [])
        if treatment_hints and "binary_0_1" in data_hints:
            var_roles.append({
                "role": "treatment",
                "status": "confirmed_by_rules",
                "confidence": 0.9,
                "evidence": {"name_hints": treatment_hints, "data_hints": data_hints, "unique_count": nunique},
                "needs_user_confirmation": False,
            })
        elif treatment_hints:
            var_roles.append({
                "role": "treatment",
                "status": "candidate",
                "confidence": 0.6,
                "evidence": {"name_hints": treatment_hints, "data_hints": data_hints, "unique_count": nunique},
                "needs_user_confirmation": True,
            })
        elif "binary_0_1" in data_hints:
            var_roles.append({
                "role": "treatment",
                "status": "candidate",
                "confidence": 0.5,
                "evidence": {"name_hints": [], "data_hints": data_hints, "unique_count": nunique},
                "needs_user_confirmation": True,
            })
        else:
            var_roles.append({
                "role": "treatment",
                "status": "rejected",
                "confidence": 0.0,
                "evidence": {"name_hints": treatment_hints, "data_hints": data_hints, "unique_count": nunique},
                "needs_user_confirmation": False,
            })

        # ------- categorical ------------------------------------------------
        # Confirmed if string dtype, or if name hints AND low cardinality (3-20).
        # Candidate if low cardinality (3-20), not binary, not datetime.
        # Rejected otherwise.
        cat_hints = name_hints.get("categorical", [])
        if "string_dtype" in data_hints:
            var_roles.append({
                "role": "categorical",
                "status": "confirmed_by_rules",
                "confidence": 0.95,
                "evidence": {"name_hints": cat_hints, "data_hints": data_hints, "unique_count": nunique},
                "needs_user_confirmation": False,
            })
        elif cat_hints and 3 <= nunique <= 20:
            var_roles.append({
                "role": "categorical",
                "status": "confirmed_by_rules",
                "confidence": 0.85,
                "evidence": {"name_hints": cat_hints, "data_hints": data_hints, "unique_count": nunique},
                "needs_user_confirmation": False,
            })
        # Exclude datetime columns from categorical candidate.
        elif 3 <= nunique <= 20 and "binary_0_1" not in data_hints and not pd.api.types.is_datetime64_any_dtype(series):
            var_roles.append({
                "role": "categorical",
                "status": "candidate",
                "confidence": 0.55,
                "evidence": {"name_hints": cat_hints, "data_hints": data_hints, "unique_count": nunique},
                "needs_user_confirmation": True,
            })
        else:
            var_roles.append({
                "role": "categorical",
                "status": "rejected",
                "confidence": 0.0,
                "evidence": {"name_hints": cat_hints, "data_hints": data_hints, "unique_count": nunique},
                "needs_user_confirmation": False,
            })

        # ------- proxy ------------------------------------------------------
        # Candidate if name hints are present.
        # Rejected otherwise.
        proxy_hints = name_hints.get("proxy", [])
        if proxy_hints:
            var_roles.append({
                "role": "proxy",
                "status": "candidate",
                "confidence": 0.7 if "continuous" in data_hints else 0.5,
                "evidence": {"name_hints": proxy_hints, "data_hints": data_hints, "unique_count": nunique},
                "needs_user_confirmation": True,
            })
        else:
            var_roles.append({
                "role": "proxy",
                "status": "rejected",
                "confidence": 0.0,
                "evidence": {"name_hints": proxy_hints, "data_hints": data_hints, "unique_count": nunique},
                "needs_user_confirmation": False,
            })

        # ------- exposure ---------------------------------------------------
        # Candidate if name hints AND positive numeric values.
        # Confidence is higher when y_type is "count" (Poisson context).
        # Rejected otherwise.
        exposure_hints = name_hints.get("exposure", [])
        if exposure_hints and "positive_numeric" in data_hints:
            conf = 0.85 if y_type == "count" else 0.55
            entry: dict = {
                "role": "exposure",
                "status": "candidate",
                "confidence": conf,
                "evidence": {"name_hints": exposure_hints, "data_hints": data_hints, "unique_count": nunique},
                "needs_user_confirmation": True,
                "context_required": "count_model",
            }
            var_roles.append(entry)
        else:
            var_roles.append({
                "role": "exposure",
                "status": "rejected",
                "confidence": 0.0,
                "evidence": {"name_hints": exposure_hints, "data_hints": data_hints, "unique_count": nunique},
                "needs_user_confirmation": False,
            })

        # ------- id ---------------------------------------------------------
        # Confirmed if name hints AND highly-unique data.
        # Candidate if name hints only.
        # Rejected otherwise.
        id_hints = name_hints.get("id", [])
        if id_hints and "highly_unique" in data_hints:
            var_roles.append({
                "role": "id",
                "status": "confirmed_by_rules",
                "confidence": 0.85,
                "evidence": {"name_hints": id_hints, "data_hints": data_hints, "unique_count": nunique},
                "needs_user_confirmation": False,
            })
        elif id_hints:
            var_roles.append({
                "role": "id",
                "status": "candidate",
                "confidence": 0.6,
                "evidence": {"name_hints": id_hints, "data_hints": data_hints, "unique_count": nunique},
                "needs_user_confirmation": True,
            })
        else:
            var_roles.append({
                "role": "id",
                "status": "rejected",
                "confidence": 0.0,
                "evidence": {"name_hints": id_hints, "data_hints": data_hints, "unique_count": nunique},
                "needs_user_confirmation": False,
            })

        # ------- time -------------------------------------------------------
        # Confirmed if datetime dtype.
        # Candidate if name hints only.
        # Rejected otherwise.
        time_hints = name_hints.get("time", [])
        if pd.api.types.is_datetime64_any_dtype(series):
            var_roles.append({
                "role": "time",
                "status": "confirmed_by_rules",
                "confidence": 0.95,
                "evidence": {"name_hints": time_hints, "data_hints": data_hints + ["datetime_dtype"], "unique_count": nunique},
                "needs_user_confirmation": False,
            })
        elif time_hints:
            var_roles.append({
                "role": "time",
                "status": "candidate",
                "confidence": 0.7,
                "evidence": {"name_hints": time_hints, "data_hints": data_hints, "unique_count": nunique},
                "needs_user_confirmation": True,
            })
        else:
            var_roles.append({
                "role": "time",
                "status": "rejected",
                "confidence": 0.0,
                "evidence": {"name_hints": time_hints, "data_hints": data_hints, "unique_count": nunique},
                "needs_user_confirmation": False,
            })

        roles[var] = {"roles": var_roles}
    return roles
