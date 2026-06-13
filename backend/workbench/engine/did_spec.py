from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Sentinel values that mark a never-treated unit in a user-supplied cohort column.
_NEVER_SENTINELS = {0, "0", "", "never", "Never", "NA", "NaN", "inf"}


class DIDSpecError(ValueError):
    """Raised when a DID specification is invalid. Carries a DID_*-prefixed
    message so the estimation failure path surfaces it as a structured
    MODEL_FIT_FAILED (same mechanism as IVSpecError)."""


@dataclass
class NormalizedDID:
    """Canonical cohort table + spec summary. Downstream ATT / event-study /
    parallel-trends / Goodman-Bacon consume ONLY this."""
    frame: pd.DataFrame          # original cols + _did_cohort, _did_D, _did_event_time
    entity: str
    time: str
    y: str
    summary: dict


def _coerce_cohort_value(v):
    """Map a user cohort cell to a float period or NaN (never-treated)."""
    if pd.isna(v) or v in _NEVER_SENTINELS:
        return np.nan
    try:
        f = float(v)
    except (TypeError, ValueError):
        return np.nan
    return np.nan if np.isinf(f) else f


def _check_partition(y, time, entity, role_cols: dict):
    seen = {entity: "entity", time: "time"}
    for role, col in role_cols.items():
        if not col:
            continue
        if col == y:
            raise DIDSpecError(
                f"DID_INVALID_PARTITION: '{col}' is the dependent variable and "
                f"cannot also be the {role} column."
            )
        if col in seen:
            raise DIDSpecError(
                f"DID_INVALID_PARTITION: '{col}' appears as both {seen[col]} and "
                f"{role}; each column has exactly one role."
            )
        seen[col] = role


def validate_did_spec(
    frame: pd.DataFrame, *, mode: str, entity: str, time: str, y: str,
    cohort: str | None = None, treat: str | None = None, post: str | None = None,
    status: str | None = None,
) -> None:
    if mode not in {"cohort", "two_by_two", "status"}:
        raise DIDSpecError(f"DID_BAD_MODE: unknown mode '{mode}'.")
    for label, col in (("entity", entity), ("time", time)):
        if not col:
            raise DIDSpecError(f"DID_FIELDS_MISSING: a {label} column is required.")
        if col not in frame.columns:
            raise DIDSpecError(f"DID_COLUMN_NOT_FOUND: {label} column '{col}' not in data.")
    required = {"cohort": ["cohort"], "two_by_two": ["treat", "post"],
                "status": ["status"]}[mode]
    role_vals = {"cohort": cohort, "treat": treat, "post": post, "status": status}
    for r in required:
        col = role_vals[r]
        if not col:
            raise DIDSpecError(f"DID_FIELDS_MISSING: mode '{mode}' requires a {r} column.")
        if col not in frame.columns:
            raise DIDSpecError(f"DID_COLUMN_NOT_FOUND: {r} column '{col}' not in data.")
    _check_partition(y, time, entity,
                     {"cohort": cohort, "treat": treat, "post": post, "status": status})
    if frame[time].nunique(dropna=True) < 2:
        raise DIDSpecError(
            "DID_TOO_FEW_PERIODS: DID requires at least 2 distinct time periods."
        )
    # Build the cohort series for the comparison-group check (cheap; reused logic).
    cohort_by_entity = _cohort_series(frame, mode=mode, entity=entity, time=time,
                                      cohort=cohort, treat=treat, post=post, status=status)
    treated = {e for e, c in cohort_by_entity.items() if not pd.isna(c)}
    if not treated:
        raise DIDSpecError("DID_NO_TREATED_UNITS: no treated unit found.")
    never = {e for e, c in cohort_by_entity.items() if pd.isna(c)}
    not_yet = {e for e, c in cohort_by_entity.items()
               if not pd.isna(c) and c > frame[time].min()}
    if not never and not not_yet:
        raise DIDSpecError(
            "DID_NO_COMPARISON_GROUP: need at least one never-treated or "
            "not-yet-treated unit to form a comparison group."
        )


def _cohort_series(frame, *, mode, entity, time, cohort, treat, post, status) -> dict:
    """Return {entity_value: cohort_period or NaN}. Pure helper shared by
    validate + normalize."""
    out: dict = {}
    if mode == "cohort":
        for ent, grp in frame.groupby(entity):
            out[ent] = _coerce_cohort_value(grp[cohort].iloc[0])
    elif mode == "two_by_two":
        treated_periods = frame.loc[frame[post].astype(float) == 1, time]
        first_post = treated_periods.min() if len(treated_periods) else np.nan
        for ent, grp in frame.groupby(entity):
            is_treated = (grp[treat].astype(float) == 1).any()
            out[ent] = float(first_post) if is_treated else np.nan
    elif mode == "status":
        for ent, grp in frame.groupby(entity):
            g = grp.sort_values(time)
            d = g[status].astype(float).to_numpy()
            if np.any(np.diff(d) < 0):
                raise DIDSpecError(
                    f"DID_NON_ABSORBING: treatment for unit '{ent}' turns off after "
                    f"turning on; status mode requires absorbing treatment."
                )
            on = g.loc[g[status].astype(float) == 1, time]
            out[ent] = float(on.min()) if len(on) else np.nan
    return out


def normalize_did_input(
    frame: pd.DataFrame, *, mode: str, entity: str, time: str, y: str,
    cohort: str | None = None, treat: str | None = None, post: str | None = None,
    status: str | None = None,
) -> NormalizedDID:
    validate_did_spec(frame, mode=mode, entity=entity, time=time, y=y,
                      cohort=cohort, treat=treat, post=post, status=status)
    cohort_by_entity = _cohort_series(frame, mode=mode, entity=entity, time=time,
                                      cohort=cohort, treat=treat, post=post, status=status)
    out = frame.copy()
    out["_did_cohort"] = out[entity].map(cohort_by_entity).astype(float)
    t = pd.to_numeric(out[time], errors="coerce")
    out["_did_D"] = ((t >= out["_did_cohort"]) & out["_did_cohort"].notna()).astype(int)
    out["_did_event_time"] = (t - out["_did_cohort"])
    out.loc[out["_did_cohort"].isna(), "_did_event_time"] = np.nan

    treated_cohorts = {c for c in cohort_by_entity.values() if not pd.isna(c)}
    summary = {
        "entity": entity, "time": time, "cohort": "_did_cohort",
        "n_treated_units": sum(1 for c in cohort_by_entity.values() if not pd.isna(c)),
        "n_never_treated": sum(1 for c in cohort_by_entity.values() if pd.isna(c)),
        "staggered": len(treated_cohorts) > 1,
        "mode": mode,
    }
    return NormalizedDID(frame=out, entity=entity, time=time, y=y, summary=summary)
