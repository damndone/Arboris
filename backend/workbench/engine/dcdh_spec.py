"""dCDH treatment-path input model (binary non-absorbing).

did_spec is cohort/absorbing-only (even its `status` mode raises DID_NON_ABSORBING),
so dCDH needs its own normalizer; did_spec stays untouched. v1.5.9 analysis sample =
baseline=0 units whose FIRST switch is 0->1 ("first-up switchers"); baseline=1 units
are excluded from both treatment and control with a recorded reason. After the first
0->1 a unit may switch back 1->0 and STAYS in the sample (event_time keeps counting
from the first up-switch) — the genuinely non-absorbing part.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


class DCDHSpecError(ValueError):
    """DCDH_* failure (bad dCDH spec) -> structured MODEL_FIT_FAILED."""


@dataclass
class TreatmentPathPanel:
    frame: pd.DataFrame          # original cols + _dcdh_* derived columns
    entity: str
    time: str
    y: str
    treatment: str
    excluded_units: list = field(default_factory=list)   # baseline=1 (with reason)
    summary: dict = field(default_factory=dict)


def normalize_treatment_path(frame, *, entity, time, y, treatment) -> TreatmentPathPanel:
    for label, col in (("entity", entity), ("time", time), ("outcome", y),
                       ("treatment", treatment)):
        if not col:
            raise DCDHSpecError(f"DCDH_FIELDS_MISSING: a {label} column is required.")
        if col not in frame.columns:
            raise DCDHSpecError(f"DCDH_COLUMN_NOT_FOUND: {label} column '{col}' not in data.")

    out = frame.copy()
    t = pd.to_numeric(out[time], errors="coerce")
    if t.dropna().nunique() < 2:
        raise DCDHSpecError("DCDH_TOO_FEW_PERIODS: need >=2 time periods.")
    d = pd.to_numeric(out[treatment], errors="coerce")
    if not set(pd.unique(d.dropna())) <= {0, 1}:
        raise DCDHSpecError("DCDH_NON_BINARY_TREATMENT: treatment must be 0/1 "
                            "(continuous intensity is deferred).")
    if out.duplicated(subset=[entity, time]).any():
        raise DCDHSpecError("DCDH_DUPLICATE_OBS: duplicate (entity, time) rows.")
    out["_dcdh_D"] = d.astype(int)

    # Per-entity derivations on the time-sorted path.
    baseline: dict = {}
    first_switch: dict = {}
    direction: dict = {}
    any_switch = False
    for ent, grp in out.groupby(entity):
        g = grp.assign(_t=pd.to_numeric(grp[time], errors="coerce")).sort_values("_t")
        dd = g["_dcdh_D"].to_numpy()
        tt = g["_t"].to_numpy()
        baseline[ent] = int(dd[0])
        diff = np.diff(dd)
        idx = np.flatnonzero(diff != 0)
        if idx.size == 0:
            first_switch[ent] = np.nan
            direction[ent] = "none"
        else:
            any_switch = True
            j = int(idx[0])
            first_switch[ent] = float(tt[j + 1])
            direction[ent] = "up" if diff[j] > 0 else "down"
    if not any_switch:
        raise DCDHSpecError("DCDH_NO_SWITCHERS: no unit changes treatment over time.")

    out["_dcdh_baseline"] = out[entity].map(baseline).astype(int)
    out["_dcdh_first_switch"] = out[entity].map(first_switch).astype(float)
    out["_dcdh_first_switch_direction"] = out[entity].map(direction)

    eligible = {e for e in baseline if baseline[e] == 0 and direction[e] == "up"}
    if not eligible:
        raise DCDHSpecError("DCDH_NO_ELIGIBLE_UP_SWITCHERS: no baseline=0 first-up "
                            "switcher (baseline=1 / down-switch-first deferred).")

    # event_time only for eligible first-up switchers; NaN otherwise.
    is_elig = out[entity].isin(eligible)
    ev = t - out["_dcdh_first_switch"]
    out["_dcdh_event_time"] = np.where(is_elig, ev, np.nan)

    excluded_units = sorted((e for e in baseline if baseline[e] == 1), key=str)
    summary = {"entity": entity, "time": time, "treatment": treatment,
               "n_eligible_switchers": len(eligible),
               "n_excluded_baseline1": len(excluded_units)}
    return TreatmentPathPanel(frame=out, entity=entity, time=time, y=y,
                              treatment=treatment, excluded_units=excluded_units,
                              summary=summary)
