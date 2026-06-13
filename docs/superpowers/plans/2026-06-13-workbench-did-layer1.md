# DID Layer 1 — Classic DID Full Kit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit-only `did` model type delivering classic DID full kit — TWFE ATT, event study, parallel-trends test, Goodman-Bacon decomposition — end-to-end, golden 0-drift.

**Architecture:** All input forms normalize to one canonical cohort table (`engine/did_spec.py`); ATT + event study reuse `linearmodels` PanelOLS via two new `runner.py` helpers; Goodman-Bacon is a self-implemented pure module (`engine/goodman_bacon.py`); `engine/did_diagnostics.py` assembles the JSON-safe diagnostic bundle; wiring mirrors the IV/2SLS template exactly (`_fit_did` in CORE_PACK, diagnostics-stage branch, `_MODEL_TYPE_MAP`, param threading, capabilities, frontend controls + tiered result card).

**Tech Stack:** Python 3.11 / pandas / numpy / linearmodels (PanelOLS, existing `panel` extra) / pytest; React + TypeScript / vitest / tsc.

**Spec:** `docs/superpowers/specs/2026-06-13-workbench-did-layer1-design.md`

**Conventions referenced throughout:**
- Canonical cohort columns the normalizer emits: `_did_cohort` (first-treatment period; `NaN` = never-treated), `_did_D` (0/1 = `time >= cohort`), `_did_event_time` (`time - cohort`; `NaN` for never-treated).
- Antifragility gates: G0-1 full suite via `python -m pytest`; G0-2 golden 0-drift + new params inert when empty; G0-3 wiring tests go red if wiring deleted (assert real args, not just completion); G0-5 manifest/capabilities changes need 4-way sync.
- Backend test run: `.venv/bin/python -m pytest` (NOT bare pytest historically — fixed in 1.5.4.3, but `-m` form is always safe). Full gate: `./scripts/gate.sh` from worktree root.

---

## File Structure

**New backend files:**
- `backend/workbench/engine/did_spec.py` — `DIDSpecError`, `validate_did_spec`, `normalize_did_input`, `NormalizedDID`.
- `backend/workbench/engine/goodman_bacon.py` — `goodman_bacon_decompose` (pure).
- `backend/workbench/engine/did_diagnostics.py` — `build_did_diagnostics`.

**New backend tests:**
- `tests/test_did_spec.py`, `tests/test_goodman_bacon.py`, `tests/test_did_runner.py`, `tests/test_did_diagnostics.py`, `tests/test_did_wiring.py`.

**Modified backend files:**
- `backend/workbench/econometrics/runner.py` — `run_did`, `run_event_study`; delete stranded `run_fixed_effects`.
- `backend/workbench/engine/stages/estimation.py` — `_fit_did` + CORE_PACK handler + rerun action.
- `backend/workbench/engine/stages/diagnostics.py` — `did` branch.
- `backend/workbench/orchestrator/_model_types.py` — `_MODEL_TYPE_MAP["did"]`.
- `backend/workbench/orchestrator/__init__.py` — param threading.
- `backend/workbench/api.py` — Form fields.
- `backend/workbench/engine/capabilities.py` — `did` UI meta + order entry.
- `tests/test_engine_golden.py` — kwargs-forwarding `_run` + additive DID goldens.
- Contract schema + sample (capabilities) — 4-way sync.

**New frontend files:**
- `frontend/src/runForm/DIDControls.tsx` (+ `.test.tsx`).
- `frontend/src/runResult/DIDDiagnosticsCard.tsx` (+ `.test.tsx`).

**Modified frontend files:**
- `frontend/src/runForm/RunForm.tsx` — post `did_*` params.

**New assets:** `examples/datasets/did_staggered_adoption.csv`, `docs/did-howto.md`.

---

## Task 0: Worktree + environment + baseline gate

**Files:** none (environment only).

- [ ] **Step 1: Create the isolated worktree and branch**

From the repo root (`/Users/jiayuanren/项目规划`):

```bash
git worktree add .worktrees/workbench-v1.5.5-did -b workbench-v1.5.5-did 75a8d23
cd .worktrees/workbench-v1.5.5-did
```

(Version-isolation rule: every new version gets its own branch AND worktree. Base = current `main` head `75a8d23`. Rename the branch/folder if the maintainer assigns a different version number.)

- [ ] **Step 2: Build the venv with full extras**

```bash
~/.local/bin/python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev,panel,ml,imbalanced,imputation]"
cd frontend && npm install && cd ..
```

- [ ] **Step 3: Run the full gate to establish the green baseline**

```bash
./scripts/gate.sh
```

Expected: GATE PASSED. Record the baseline counts (BE test count, FE test count, golden count, `tsc --noEmit` 0 errors). All later tasks must keep these green and only ADD.

- [ ] **Step 4: Commit nothing** — this task produces no tracked changes. Proceed to Task 1.

---

## Task 1: `engine/did_spec.py` — canonical cohort normalizer + validation

**Files:**
- Create: `backend/workbench/engine/did_spec.py`
- Test: `tests/test_did_spec.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_did_spec.py
import numpy as np
import pandas as pd
import pytest

from workbench.engine.did_spec import (
    DIDSpecError,
    NormalizedDID,
    normalize_did_input,
    validate_did_spec,
)


def _panel():
    # entities A,B treated in 2020; C never treated; years 2018-2021.
    rows = []
    for ent, cohort in [("A", 2020), ("B", 2020), ("C", 0)]:
        for year in range(2018, 2022):
            rows.append({"id": ent, "year": year, "y": 1.0, "first_treat": cohort})
    return pd.DataFrame(rows)


def test_cohort_mode_derives_D_and_event_time():
    norm = normalize_did_input(
        _panel(), mode="cohort", entity="id", time="year", y="y", cohort="first_treat"
    )
    assert isinstance(norm, NormalizedDID)
    f = norm.frame
    # A in 2020 is treated (year >= cohort), in 2019 not.
    a2020 = f[(f["id"] == "A") & (f["year"] == 2020)].iloc[0]
    a2019 = f[(f["id"] == "A") & (f["year"] == 2019)].iloc[0]
    assert a2020["_did_D"] == 1 and a2020["_did_event_time"] == 0
    assert a2019["_did_D"] == 0 and a2019["_did_event_time"] == -1
    # never-treated C: D always 0, event_time NaN, cohort NaN.
    c = f[f["id"] == "C"]
    assert (c["_did_D"] == 0).all()
    assert c["_did_event_time"].isna().all()
    assert norm.summary["n_treated_units"] == 2
    assert norm.summary["n_never_treated"] == 1
    assert norm.summary["staggered"] is False


def test_two_by_two_mode_maps_to_cohort():
    rows = []
    for ent, treat in [("A", 1), ("B", 0)]:
        for year, post in [(2018, 0), (2021, 1)]:
            rows.append({"id": ent, "year": year, "y": 1.0, "treat": treat, "post": post})
    norm = normalize_did_input(
        pd.DataFrame(rows), mode="two_by_two", entity="id", time="year", y="y",
        treat="treat", post="post",
    )
    # treated A gets cohort = earliest year where post==1 (2021); control B never.
    a = norm.frame[norm.frame["id"] == "A"]
    assert a[a["year"] == 2021].iloc[0]["_did_D"] == 1
    assert norm.summary["n_never_treated"] == 1


def test_status_mode_requires_absorbing_treatment():
    rows = [
        {"id": "A", "year": 2019, "y": 1.0, "D": 0},
        {"id": "A", "year": 2020, "y": 1.0, "D": 1},
        {"id": "A", "year": 2021, "y": 1.0, "D": 0},  # turns OFF -> non-absorbing
    ]
    with pytest.raises(DIDSpecError, match="DID_NON_ABSORBING"):
        normalize_did_input(
            pd.DataFrame(rows), mode="status", entity="id", time="year", y="y", status="D"
        )


def test_validate_requires_two_periods_and_comparison_group():
    one_period = pd.DataFrame([{"id": "A", "year": 2020, "y": 1.0, "first_treat": 2020}])
    with pytest.raises(DIDSpecError, match="DID_TOO_FEW_PERIODS"):
        validate_did_spec(one_period, mode="cohort", entity="id", time="year", y="y",
                          cohort="first_treat")
    # all units treated at the same time, no never/not-yet group at the boundary
    all_treated = pd.DataFrame(
        [{"id": e, "year": yr, "y": 1.0, "first_treat": 2018}
         for e in ("A", "B") for yr in (2018, 2019)]
    )
    with pytest.raises(DIDSpecError, match="DID_NO_COMPARISON_GROUP"):
        validate_did_spec(all_treated, mode="cohort", entity="id", time="year", y="y",
                          cohort="first_treat")


def test_role_column_overlap_with_y_rejected():
    with pytest.raises(DIDSpecError, match="DID_INVALID_PARTITION"):
        validate_did_spec(_panel(), mode="cohort", entity="id", time="year", y="y",
                          cohort="y")  # cohort == y


def test_staggered_flag_true_for_multiple_cohorts():
    rows = []
    for ent, cohort in [("A", 2019), ("B", 2021), ("C", 0)]:
        for year in range(2018, 2022):
            rows.append({"id": ent, "year": year, "y": 1.0, "first_treat": cohort})
    norm = normalize_did_input(pd.DataFrame(rows), mode="cohort", entity="id",
                               time="year", y="y", cohort="first_treat")
    assert norm.summary["staggered"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_did_spec.py -v`
Expected: FAIL (`ModuleNotFoundError: workbench.engine.did_spec`).

- [ ] **Step 3: Implement `did_spec.py`**

```python
# backend/workbench/engine/did_spec.py
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
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def _check_partition(y, time, entity, role_cols: dict):
    seen = {entity: "entity", time: "time"}
    for role, col in role_cols.items():
        if col is None:
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
    latest = frame[time].max()
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_did_spec.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/did_spec.py tests/test_did_spec.py
git commit -m "feat(did): canonical cohort normalizer + spec validation"
```

---

## Task 2: `engine/goodman_bacon.py` — pure decomposition (risk center)

**Files:**
- Create: `backend/workbench/engine/goodman_bacon.py`
- Test: `tests/test_goodman_bacon.py`

The decomposition expresses the two-way-FE DiD estimate as a weighted average of all
2×2 DiD comparisons among treatment-timing groups (Goodman-Bacon 2021). Comparison
types: `treated_vs_untreated` (timing group vs never-treated), `earlier_vs_later`
(early group treated, later group as not-yet-treated control — "good"), and
`later_vs_earlier` (later group treated, earlier group as already-treated control —
"forbidden"/"bad", the bias source). The weighted average equals the TWFE estimate;
that identity is the primary correctness test.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_goodman_bacon.py
import numpy as np
import pandas as pd
import pytest

from workbench.goodman_bacon_ref import twfe_did_coefficient  # test helper, Step 3b
from workbench.engine.goodman_bacon import goodman_bacon_decompose


def _staggered_panel():
    # Two timing groups (treated 2019 and 2021) + a never-treated group.
    rng = np.random.default_rng(0)
    rows = []
    cohorts = {"A": 2019, "B": 2019, "C": 2021, "D": 2021, "E": 0, "F": 0}
    for ent, cohort in cohorts.items():
        unit_fe = rng.normal()
        for year in range(2017, 2023):
            treated = 1 if (cohort and year >= cohort) else 0
            y = unit_fe + 0.1 * (year - 2017) + 2.0 * treated + rng.normal(0, 0.01)
            rows.append({"id": ent, "year": year, "y": y, "first_treat": cohort})
    return pd.DataFrame(rows)


def test_components_have_three_types_and_weights_sum_to_one():
    frame = _staggered_panel()
    res = goodman_bacon_decompose(frame, y="y", entity="id", time="year",
                                  cohort="first_treat")
    types = {c["type"] for c in res["components"]}
    assert types <= {"treated_vs_untreated", "earlier_vs_later", "later_vs_earlier"}
    assert "later_vs_earlier" in types  # staggered => forbidden comparison present
    total_w = sum(c["weight"] for c in res["components"])
    assert total_w == pytest.approx(1.0, abs=1e-9)
    assert 0.0 <= res["forbidden_weight"] <= 1.0


def test_weighted_average_equals_twfe_estimate():
    # The decomposition identity: sum(weight * estimate) == TWFE DiD coefficient.
    frame = _staggered_panel()
    res = goodman_bacon_decompose(frame, y="y", entity="id", time="year",
                                  cohort="first_treat")
    twfe = twfe_did_coefficient(frame, y="y", entity="id", time="year",
                                cohort="first_treat")
    assert res["weighted_avg"] == pytest.approx(twfe, abs=1e-6)


def test_no_forbidden_comparison_when_single_cohort_plus_never():
    rows = []
    for ent, cohort in [("A", 2020), ("B", 2020), ("C", 0), ("D", 0)]:
        for year in range(2018, 2022):
            rows.append({"id": ent, "year": year, "y": float(year >= cohort and cohort > 0),
                         "first_treat": cohort})
    res = goodman_bacon_decompose(pd.DataFrame(rows), y="y", entity="id",
                                  time="year", cohort="first_treat")
    assert res["forbidden_weight"] == pytest.approx(0.0, abs=1e-9)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_goodman_bacon.py -v`
Expected: FAIL (modules not found).

- [ ] **Step 3a: Implement `goodman_bacon.py`**

```python
# backend/workbench/engine/goodman_bacon.py
from __future__ import annotations

import numpy as np
import pandas as pd


def _two_by_two_did(panel: pd.DataFrame, y, entity, time, treat_group, ctrl_group,
                    pre_periods, post_periods) -> float:
    """Standard 2x2 DiD: (treat_post - treat_pre) - (ctrl_post - ctrl_pre)."""
    def cell(group, periods):
        sub = panel[(panel["_grp"] == group) & (panel[time].isin(periods))]
        return sub[y].mean()
    return ((cell(treat_group, post_periods) - cell(treat_group, pre_periods))
            - (cell(ctrl_group, post_periods) - cell(ctrl_group, pre_periods)))


def goodman_bacon_decompose(frame: pd.DataFrame, *, y: str, entity: str, time: str,
                            cohort: str) -> dict:
    """Decompose the TWFE DiD estimate into weighted 2x2 comparisons.

    Pure, deterministic. Requires a balanced panel keyed by (entity, time). The
    weighted average of component estimates equals the TWFE DiD coefficient.
    """
    df = frame.copy()
    df["_cohort_val"] = pd.to_numeric(df[cohort], errors="coerce")
    # Never-treated cohort encoded as NaN; treat as +inf timing group "U".
    df["_grp"] = df["_cohort_val"].fillna(np.inf)
    times = sorted(df[time].unique())
    n_periods = len(times)
    groups = sorted(g for g in df["_grp"].unique())
    treated_groups = [g for g in groups if np.isfinite(g)]
    never = np.inf in groups

    n_total = df[entity].nunique()
    # Group sample shares n_k (fraction of units in timing group k).
    share = {g: df[df["_grp"] == g][entity].nunique() / n_total for g in groups}
    # Fraction of time each treated group spends treated, D_k.
    Dbar = {}
    for k in treated_groups:
        post = sum(1 for t in times if t >= k)
        Dbar[k] = post / n_periods

    components: list[dict] = []
    weights_raw: list[tuple[str, float, float]] = []  # (type, weight_raw, estimate)

    # (1) timing group k vs never-treated U.
    if never:
        for k in treated_groups:
            pre = [t for t in times if t < k]
            post = [t for t in times if t >= k]
            if not pre or not post:
                continue
            est = _two_by_two_did(df, y, entity, time, k, np.inf, pre, post)
            w = (share[k] * share[np.inf]) * (Dbar[k] * (1 - Dbar[k]))
            weights_raw.append(("treated_vs_untreated", w, est))

    # (2) pairs of timing groups (k earlier, l later).
    for i, k in enumerate(treated_groups):
        for l in treated_groups[i + 1:]:
            # 2a. earlier-vs-later ("good"): k treated, l as not-yet-treated control,
            #     window = periods before l's treatment.
            pre_k = [t for t in times if t < k]
            mid = [t for t in times if k <= t < l]
            if pre_k and mid:
                est = _two_by_two_did(df, y, entity, time, k, l, pre_k, mid)
                w = (share[k] * share[l]) * ((Dbar[k] - Dbar[l]) * (1 - (Dbar[k] - Dbar[l])))
                weights_raw.append(("earlier_vs_later", max(w, 0.0), est))
            # 2b. later-vs-earlier ("forbidden"): l treated, k as already-treated
            #     control, window = periods from k's treatment onward.
            mid2 = [t for t in times if k <= t < l]
            post_l = [t for t in times if t >= l]
            if mid2 and post_l:
                est = _two_by_two_did(df, y, entity, time, l, k, mid2, post_l)
                w = (share[k] * share[l]) * (Dbar[l] * (1 - Dbar[k]))
                weights_raw.append(("later_vs_earlier", max(w, 0.0), est))

    total = sum(w for _, w, _ in weights_raw)
    if total <= 0:
        return {"components": [], "weighted_avg": 0.0, "forbidden_weight": 0.0,
                "message": "No valid 2x2 comparisons (degenerate timing)."}

    for typ, w, est in weights_raw:
        components.append({"type": typ, "weight": float(w / total),
                           "estimate": float(est)})
    weighted_avg = float(sum(c["weight"] * c["estimate"] for c in components))
    forbidden_weight = float(sum(c["weight"] for c in components
                                 if c["type"] == "later_vs_earlier"))
    return {
        "components": components,
        "weighted_avg": weighted_avg,
        "forbidden_weight": forbidden_weight,
        "message": (
            f"{forbidden_weight:.0%} of the TWFE estimate comes from 'forbidden' "
            f"later-vs-earlier comparisons (already-treated units as controls); "
            f"under staggered adoption the TWFE estimate may be biased."
            if forbidden_weight > 0 else
            "No forbidden comparisons; TWFE reduces to clean 2x2 DiD."
        ),
    }
```

- [ ] **Step 3b: Add the TWFE reference helper (test-only, in the package so tests import it)**

```python
# backend/workbench/goodman_bacon_ref.py
"""Reference TWFE DiD coefficient used to validate the Bacon decomposition
identity (weighted_avg == TWFE). Kept tiny and dependency-light (statsmodels
OLS with entity+time dummies) so the test does not depend on linearmodels."""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm


def twfe_did_coefficient(frame: pd.DataFrame, *, y, entity, time, cohort) -> float:
    df = frame.copy()
    cv = pd.to_numeric(df[cohort], errors="coerce")
    t = pd.to_numeric(df[time], errors="coerce")
    df["_D"] = ((t >= cv) & cv.notna()).astype(float)
    X = pd.concat(
        [df["_D"],
         pd.get_dummies(df[entity], prefix="e", drop_first=True).astype(float),
         pd.get_dummies(df[time], prefix="t", drop_first=True).astype(float)],
        axis=1,
    )
    X = sm.add_constant(X)
    model = sm.OLS(df[y].astype(float), X).fit()
    return float(model.params["_D"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_goodman_bacon.py -v`
Expected: PASS (3 tests). The `weighted_avg == twfe` test is the correctness anchor; if it fails, the weight formulas are wrong — fix the weights, not the test.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/goodman_bacon.py backend/workbench/goodman_bacon_ref.py tests/test_goodman_bacon.py
git commit -m "feat(did): self-implemented Goodman-Bacon decomposition + identity test"
```

---

## Task 3: `runner.py` — `run_did` (ATT) + `run_event_study`

**Files:**
- Modify: `backend/workbench/econometrics/runner.py` (add two functions after `run_iv_2sls`, around line 402)
- Test: `tests/test_did_runner.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_did_runner.py
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("linearmodels")

from workbench.econometrics.runner import run_did, run_event_study
from workbench.engine.did_spec import normalize_did_input


def _panel(effect=2.0):
    rng = np.random.default_rng(1)
    rows = []
    for ent, cohort in [("A", 2020), ("B", 2020), ("C", 0), ("D", 0)]:
        fe = rng.normal()
        for year in range(2018, 2023):
            d = 1 if (cohort and year >= cohort) else 0
            y = fe + 0.1 * (year - 2018) + effect * d + rng.normal(0, 0.01)
            rows.append({"id": ent, "year": year, "y": y, "first_treat": cohort})
    return pd.DataFrame(rows)


def test_run_did_recovers_att():
    norm = normalize_did_input(_panel(effect=2.0), mode="cohort", entity="id",
                               time="year", y="y", cohort="first_treat")
    primary, fitted = run_did(norm.frame, y="y", x=[], entity="id", time="year",
                              model_id="did_1")
    assert primary["model_type"] == "did"
    assert "_did_D" in primary["coefficients"]
    assert primary["coefficients"]["_did_D"]["estimate"] == pytest.approx(2.0, abs=0.1)


def test_run_event_study_returns_path_with_reference_period_dropped():
    norm = normalize_did_input(_panel(), mode="cohort", entity="id", time="year",
                               y="y", cohort="first_treat")
    es = run_event_study(norm.frame, y="y", x=[], entity="id", time="year",
                         event_time_col="_did_event_time", ref_period=-1)
    assert es["ref_period"] == -1
    assert -1 not in es["event_time"]            # reference period omitted
    assert len(es["coef"]) == len(es["event_time"]) == len(es["se"])
    # post-period effect is positive and ~2.0; pre-period near 0.
    idx0 = es["event_time"].index(0)
    assert es["coef"][idx0] == pytest.approx(2.0, abs=0.3)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_did_runner.py -v`
Expected: FAIL (`ImportError: cannot import name 'run_did'`).

- [ ] **Step 3: Implement the two functions** (insert after `run_iv_2sls`, before `run_time_series_diagnostics`)

```python
def run_did(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    entity: str,
    time: str,
    model_id: str,
    covariance: str = "robust",
) -> tuple[dict[str, Any], Any]:
    """TWFE DID: y ~ 1 + _did_D + x... + EntityEffects + TimeEffects. The
    coefficient on _did_D is the ATT. Expects the canonical cohort frame from
    normalize_did_input (must contain _did_D)."""
    panel_module = require_optional_dependency(
        "linearmodels.panel", extra="panel", engine="linearmodels", model_type="did",
    )
    data = _ensure_numeric_y(frame.copy(), y)
    data = _ensure_numeric_x(data, x)
    data = data.set_index([entity, time])

    terms = ["1", "_did_D", *[_linearmodels_term(c) for c in x],
             "EntityEffects", "TimeEffects"]
    formula = f"{_linearmodels_term(y)} ~ {' + '.join(terms)}"
    fitted = panel_module.PanelOLS.from_formula(formula, data=data).fit(cov_type=covariance)
    return _normalize_linearmodels_result(fitted, model_id, "did"), fitted


def run_event_study(
    frame: pd.DataFrame,
    y: str,
    x: list[str],
    entity: str,
    time: str,
    event_time_col: str,
    ref_period: int = -1,
    covariance: str = "robust",
) -> dict[str, Any]:
    """Dynamic DID: regress y on event-time dummies (reference period omitted)
    under two-way FE. Returns the coefficient path keyed by event_time. Never-
    treated rows (NaN event_time) contribute to the FE baseline only."""
    panel_module = require_optional_dependency(
        "linearmodels.panel", extra="panel", engine="linearmodels", model_type="did",
    )
    data = _ensure_numeric_y(frame.copy(), y)
    data = _ensure_numeric_x(data, x)
    evt = data[event_time_col]
    event_values = sorted(int(v) for v in evt.dropna().unique() if int(v) != ref_period)

    dummy_terms = []
    for k in event_values:
        col = f"_evt_{'m' if k < 0 else 'p'}{abs(k)}"
        data[col] = ((evt == k)).astype(float).fillna(0.0)
        dummy_terms.append(col)

    data = data.set_index([entity, time])
    terms = ["1", *dummy_terms, *[_linearmodels_term(c) for c in x],
             "EntityEffects", "TimeEffects"]
    formula = f"{_linearmodels_term(y)} ~ {' + '.join(terms)}"
    fitted = panel_module.PanelOLS.from_formula(formula, data=data).fit(cov_type=covariance)

    coef, se, ci_lo, ci_hi = [], [], [], []
    conf = fitted.conf_int()
    for k in event_values:
        col = f"_evt_{'m' if k < 0 else 'p'}{abs(k)}"
        coef.append(_json_safe_float(fitted.params.get(col)))
        se.append(_json_safe_float(fitted.std_errors.get(col)))
        ci_lo.append(_json_safe_float(conf.loc[col].iloc[0]))
        ci_hi.append(_json_safe_float(conf.loc[col].iloc[1]))
    return {
        "event_time": event_values,
        "coef": coef, "se": se, "ci_lower": ci_lo, "ci_upper": ci_hi,
        "ref_period": ref_period,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_did_runner.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/econometrics/runner.py tests/test_did_runner.py
git commit -m "feat(did): run_did (TWFE ATT) + run_event_study helpers"
```

---

## Task 4: `engine/did_diagnostics.py` — assemble the bundle

**Files:**
- Create: `backend/workbench/engine/did_diagnostics.py`
- Test: `tests/test_did_diagnostics.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_did_diagnostics.py
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("linearmodels")

from workbench.econometrics.runner import run_did
from workbench.engine.did_spec import normalize_did_input
from workbench.engine.did_diagnostics import build_did_diagnostics


def _panel(staggered=False):
    rng = np.random.default_rng(2)
    cohorts = ({"A": 2019, "B": 2021, "C": 0} if staggered
               else {"A": 2020, "B": 2020, "C": 0})
    rows = []
    for ent, cohort in cohorts.items():
        fe = rng.normal()
        for year in range(2017, 2023):
            d = 1 if (cohort and year >= cohort) else 0
            rows.append({"id": ent, "year": year,
                         "y": fe + 0.1 * (year - 2017) + 2.0 * d + rng.normal(0, 0.01),
                         "first_treat": cohort})
    return pd.DataFrame(rows)


def test_bundle_has_all_four_sections_and_is_json_safe():
    norm = normalize_did_input(_panel(), mode="cohort", entity="id", time="year",
                               y="y", cohort="first_treat")
    _, fitted = run_did(norm.frame, y="y", x=[], entity="id", time="year", model_id="did_1")
    diag = build_did_diagnostics(fitted, norm, norm.frame, covariance="robust")
    assert set(diag) >= {"att", "event_study", "parallel_trends", "goodman_bacon", "spec"}
    assert isinstance(diag["att"]["estimate"], float)
    assert diag["parallel_trends"]["verdict"] in {"not_rejected", "rejected"}
    import json
    json.dumps(diag)  # must not raise


def test_staggered_panel_attaches_interpretation_restriction():
    norm = normalize_did_input(_panel(staggered=True), mode="cohort", entity="id",
                               time="year", y="y", cohort="first_treat")
    _, fitted = run_did(norm.frame, y="y", x=[], entity="id", time="year", model_id="did_1")
    diag = build_did_diagnostics(fitted, norm, norm.frame, covariance="robust")
    assert diag["spec"]["staggered"] is True
    assert "interpretation_restriction" in diag
    assert "Layer 2" in diag["interpretation_restriction"]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_did_diagnostics.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `did_diagnostics.py`**

```python
# backend/workbench/engine/did_diagnostics.py
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
    es = run_event_study(frame, y=norm.y, x=[], entity=norm.entity, time=norm.time,
                         event_time_col="_did_event_time", ref_period=-1,
                         covariance=covariance)
    att = _att_from_fitted(fitted)
    att["covariance"] = covariance
    pt = _parallel_trends(es)
    bacon = goodman_bacon_decompose(frame, y=norm.y, entity=norm.entity,
                                    time=norm.time, cohort="_did_cohort")
    out = {
        "att": att,
        "event_study": es,
        "parallel_trends": pt,
        "goodman_bacon": bacon,
        "spec": norm.summary,
    }
    if norm.summary.get("staggered"):
        out["interpretation_restriction"] = (
            "Staggered adoption detected. The TWFE estimate mixes good and "
            "'forbidden' comparisons (Goodman-Bacon weight "
            f"{bacon['forbidden_weight']:.0%}). For staggered designs prefer a "
            "modern estimator — see Layer 2 (Callaway-Sant'Anna)."
        )
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_did_diagnostics.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/did_diagnostics.py tests/test_did_diagnostics.py
git commit -m "feat(did): build_did_diagnostics (att + event-study + parallel-trends + bacon)"
```

---

## Task 5: `_fit_did` adapter + CORE_PACK registration

**Files:**
- Modify: `backend/workbench/engine/stages/estimation.py` (add `_fit_did` after `_fit_iv_2sls` ~line 118; add `ModelHandler` to CORE_PACK ~line 148; add `RerunAction` ~line 155)
- Test: `tests/test_did_wiring.py`

- [ ] **Step 1: Write the failing wiring test (G0-3: red if wiring deleted)**

```python
# tests/test_did_wiring.py
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("linearmodels")

from workbench import orchestrator as orch
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def _staggered_csv(tmp_path):
    rng = np.random.default_rng(3)
    rows = []
    for ent, cohort in [("A", 2019), ("B", 2019), ("C", 2021), ("D", 2021),
                        ("E", 0), ("F", 0)]:
        fe = rng.normal()
        for year in range(2017, 2023):
            d = 1 if (cohort and year >= cohort) else 0
            rows.append({"id": ent, "year": year,
                         "y": fe + 0.1 * (year - 2017) + 2.0 * d + rng.normal(0, 0.01),
                         "first_treat": cohort})
    src = tmp_path / "did.csv"
    pd.DataFrame(rows).to_csv(src, index=False)
    return src


def test_did_run_calls_run_did_with_real_args(tmp_path, monkeypatch):
    src = _staggered_csv(tmp_path)
    project = create_project(tmp_path, "demo")
    captured = {}
    real = orch.run_did

    def spy(frame, **kwargs):
        captured.update(kwargs)
        captured["has_did_D"] = "_did_D" in frame.columns
        return real(frame, **kwargs)

    monkeypatch.setattr(orch, "run_did", spy)
    result = run_workflow(project.root, [src], mode="auto", y="y", x=[],
                          model_type="did", entity_col="id", time_col="year",
                          did_mode="cohort", did_cohort_col="first_treat")
    assert captured["entity"] == "id" and captured["time"] == "year"
    assert captured["has_did_D"] is True  # normalized cohort frame was passed
    run_root = project.root / "runs" / result["run_id"]
    assert (run_root / "did_diagnostics.json").exists()
```

(This test also exercises Tasks 6–8; it will not fully pass until those land. Run it after Task 8. For Task 5, assert only that the handler resolves — see Step 2.)

- [ ] **Step 2: Add a focused Task-5 unit test**

```python
# append to tests/test_did_wiring.py
def test_did_handler_registered_and_explicit_only():
    from workbench.engine.registry import MODEL_REGISTRY, resolve
    from workbench.engine.context import ModelingContext
    from workbench.engine.context import DataHandle
    assert "did" in MODEL_REGISTRY  # explicit handler present
    # 'did' is NOT a y_type default: an auto continuous run must resolve to ols.
    ctx = ModelingContext(data=DataHandle(frame=pd.DataFrame(), artifact_id="raw",
                          provenance=()), y_col="y", x_cols=[], requested_model_type="auto")
    ctx.y_type = "continuous"
    assert resolve(ctx).model_id != "did_1"
```

(Confirm `MODEL_REGISTRY` import path and `resolve` signature against `engine/registry.py` before running; adjust the assertion to the registry's actual membership API if it differs.)

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_did_wiring.py::test_did_handler_registered_and_explicit_only -v`
Expected: FAIL (`did` not in registry).

- [ ] **Step 4: Implement `_fit_did` + register**

Add after `_fit_iv_2sls` (estimation.py ~line 118):

```python
def _fit_did(ctx, env):
    from ..did_spec import normalize_did_input
    mode = ctx.artifacts.get("_did_mode") or "cohort"
    id_cands = ctx.artifacts.get("_id_candidates") or []
    t_cands = ctx.artifacts.get("_time_candidates") or []
    entity = id_cands[0] if id_cands else None
    time = t_cands[0] if t_cands else None
    norm = normalize_did_input(
        ctx.data.frame,
        mode=mode,
        entity=entity,
        time=time,
        y=ctx.artifacts["_normalized_y"],
        cohort=ctx.artifacts.get("_did_cohort_col") or None,
        treat=ctx.artifacts.get("_did_treat_col") or None,
        post=ctx.artifacts.get("_did_post_col") or None,
        status=ctx.artifacts.get("_did_status_col") or None,
    )
    ctx.artifacts["_did_normalized"] = norm  # DiagnosticsStage reuses this
    primary, fitted = _orch().run_did(
        norm.frame,
        y=norm.y,
        x=ctx.artifacts["_normalized_x"],
        entity=norm.entity,
        time=norm.time,
        model_id="did_1",
        covariance=ctx.artifacts.get("_covariance") or "robust",
    )
    return "did_1", primary, fitted   # MUST return fitted (diagnostics needs it)
```

Add to `CORE_PACK.model_handlers` (after the `iv_2sls` handler, line 148):

```python
        ModelHandler("did", "did_1", ("continuous",), _fit_did),
```

Add to `CORE_PACK.rerun_actions` (after the `iv_switch_to_ols` action):

```python
        RerunAction(
            key="did_switch_to_panel_ols",
            label="Switch to plain Panel FE",
            param_overrides={"model_type": "panel_ols"},
            applies_to=["did"],
        ),
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_did_wiring.py::test_did_handler_registered_and_explicit_only -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/workbench/engine/stages/estimation.py tests/test_did_wiring.py
git commit -m "feat(did): _fit_did adapter + CORE_PACK handler (explicit-only) + rerun action"
```

---

## Task 6: `_MODEL_TYPE_MAP["did"]`

**Files:**
- Modify: `backend/workbench/orchestrator/_model_types.py:82-99` (the `_MODEL_TYPE_MAP` dict)
- Test: `tests/test_did_wiring.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_did_wiring.py
def test_did_model_type_maps_to_continuous():
    from workbench.orchestrator._model_types import _MODEL_TYPE_MAP, _type_for_model
    assert _MODEL_TYPE_MAP.get("did") == "continuous"
```

(Confirm the public accessor name `_type_for_model` against `_model_types.py:100`; import only what exists.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_did_wiring.py::test_did_model_type_maps_to_continuous -v`
Expected: FAIL (`None != "continuous"`).

- [ ] **Step 3: Implement** — add the entry next to `"iv_2sls": "continuous",` (line 89):

```python
    "did": "continuous",
```

- [ ] **Step 4: Run to verify pass** — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/orchestrator/_model_types.py tests/test_did_wiring.py
git commit -m "feat(did): map did model_type to continuous in validation gate"
```

---

## Task 7: Param threading — `orchestrator/__init__.py` + `api.py`

**Files:**
- Modify: `backend/workbench/orchestrator/__init__.py` (`run_workflow` sig ~line 172, `_run_workflow` call ~line 209, `_run_workflow` sig ~line 356, artifact writes ~line 396)
- Modify: `backend/workbench/api.py` (Form fields ~line 101, parse + pass ~line 112 & 149, `_bg_run` sig ~line 268 & call ~line 303)
- Test: covered by `test_did_wiring.py::test_did_run_calls_run_did_with_real_args` (run end of Task 8)

- [ ] **Step 1: Add params to `run_workflow` signature** (after `iv_instruments`, line 173):

```python
    did_mode: str = "",
    did_cohort_col: str = "",
    did_treat_col: str = "",
    did_post_col: str = "",
    did_status_col: str = "",
```

- [ ] **Step 2: Forward them in the `_run_workflow(...)` call** (after `iv_instruments=iv_instruments,`, line 210):

```python
            did_mode=did_mode,
            did_cohort_col=did_cohort_col,
            did_treat_col=did_treat_col,
            did_post_col=did_post_col,
            did_status_col=did_status_col,
```

- [ ] **Step 3: Add params to `_run_workflow` signature** (after `iv_instruments`, line 357) — same five lines as Step 1.

- [ ] **Step 4: Write them into `ctx.artifacts`** (after the `_iv_instruments` line, 397):

```python
    ctx.artifacts["_did_mode"] = did_mode
    ctx.artifacts["_did_cohort_col"] = normalize_column_name(did_cohort_col) if did_cohort_col else ""
    ctx.artifacts["_did_treat_col"] = normalize_column_name(did_treat_col) if did_treat_col else ""
    ctx.artifacts["_did_post_col"] = normalize_column_name(did_post_col) if did_post_col else ""
    ctx.artifacts["_did_status_col"] = normalize_column_name(did_status_col) if did_status_col else ""
```

- [ ] **Step 5: `api.py` Form fields** (after `iv_instruments`, line 102):

```python
    did_mode: str = Form(""),
    did_cohort_col: str = Form(""),
    did_treat_col: str = Form(""),
    did_post_col: str = Form(""),
    did_status_col: str = Form(""),
```

- [ ] **Step 6: `api.py` — thread into `_bg_run`** — add to the `_bg_run(...)` signature (after `iv_instruments`, line 269) and to its `run_workflow(...)` call (after `iv_instruments=...`, line 304):

```python
    # signature:
    did_mode: str = "",
    did_cohort_col: str = "",
    did_treat_col: str = "",
    did_post_col: str = "",
    did_status_col: str = "",
    # call:
            did_mode=did_mode,
            did_cohort_col=did_cohort_col,
            did_treat_col=did_treat_col,
            did_post_col=did_post_col,
            did_status_col=did_status_col,
```

And pass the Form values into the `_bg_run(...)` invocation in the POST handler (mirror how `iv_endog_list` is passed at line 149):

```python
            did_mode, did_cohort_col, did_treat_col, did_post_col, did_status_col,
```

(Inspect lines 140-155 to match the exact positional/keyword style used for the IV args, and keep it consistent.)

- [ ] **Step 7: Run the inert-param golden guard** (proves empty did_* changes nothing):

Run: `.venv/bin/python -m pytest tests/test_engine_golden.py -v`
Expected: PASS, 0 drift (the existing goldens are unchanged because all `did_*` default to `""`).

- [ ] **Step 8: Commit**

```bash
git add backend/workbench/orchestrator/__init__.py backend/workbench/api.py
git commit -m "feat(did): thread did_* params api -> run_workflow -> ctx.artifacts (inert when empty)"
```

---

## Task 8: DiagnosticsStage writes the `did_diagnostics` artifact

**Files:**
- Modify: `backend/workbench/engine/stages/diagnostics.py` (add a branch after the `iv_2sls` block, ~line 121)
- Test: `test_did_wiring.py::test_did_run_calls_run_did_with_real_args`

- [ ] **Step 1: Implement the branch** (immediately after the `if model_type == "iv_2sls":` block ends at line 121):

```python
        if model_type == "did":
            from ..did_diagnostics import build_did_diagnostics
            did_fitted = fitted_models.get("did_1")
            norm = ctx.artifacts.get("_did_normalized")
            if did_fitted is not None and norm is not None:
                did_diag = build_did_diagnostics(
                    did_fitted, norm, norm.frame,
                    covariance=ctx.artifacts.get("_covariance") or "robust",
                )
                did_diag_path = run_root / "did_diagnostics.json"
                write_json(did_diag_path, did_diag)
                register_artifact(
                    run_root,
                    "did_diagnostics",
                    did_diag_path,
                    "model_diagnostic",
                    "econometrics",
                    model_input_ids,
                )
```

(Confirm `write_json`, `register_artifact`, `run_root`, `model_input_ids` are already in scope in this method — they are, as used by the `iv_2sls` branch above.)

- [ ] **Step 2: Run the full end-to-end wiring test**

Run: `.venv/bin/python -m pytest tests/test_did_wiring.py -v`
Expected: PASS (all 4 tests, including `test_did_run_calls_run_did_with_real_args` which now finds `did_diagnostics.json`).

- [ ] **Step 3: Commit**

```bash
git add backend/workbench/engine/stages/diagnostics.py
git commit -m "feat(did): DiagnosticsStage writes did_diagnostics artifact"
```

---

## Task 9: Capabilities entry + 4-way sync

**Files:**
- Modify: `backend/workbench/engine/capabilities.py` (`MODEL_UI_META` ~line 39, `MODEL_UI_ORDER` ~line 69)
- Modify: the capabilities drift-guard test + contract schema/sample (find via grep below)
- Test: existing capabilities/contract tests + a new membership assertion

- [ ] **Step 1: Locate the 4 sync points**

```bash
grep -rn "iv_2sls" backend/workbench/engine/capabilities.py tests/ docs/ | grep -iv pycache
```

Expect: (1) `capabilities.py` MODEL_UI_META + MODEL_UI_ORDER; (2) a drift-guard test pinning the model-type set; (3) a contract schema; (4) a contract sample JSON. Note each path.

- [ ] **Step 2: Write the failing membership test**

```python
# tests/test_did_capabilities.py
from workbench.engine.capabilities import MODEL_UI_META, MODEL_UI_ORDER


def test_did_in_capabilities():
    assert "did" in MODEL_UI_META
    assert MODEL_UI_META["did"]["group"] == "DID"
    assert MODEL_UI_META["did"]["requires"] == ["panel", "treatment_timing"]
    assert "did" in MODEL_UI_ORDER
```

- [ ] **Step 3: Run to verify failure** — Expected: FAIL (`"did" not in MODEL_UI_META`).

- [ ] **Step 4: Implement** — add to `MODEL_UI_META` (after the `iv_2sls` entry, line 44):

```python
    "did": {
        "label": "DID (Difference-in-Differences)",
        "group": "DID",
        "description": "Two-way fixed-effects DID with event study, parallel-trends test, and Goodman-Bacon decomposition.",
        "requires": ["panel", "treatment_timing"],
    },
```

Add `"did",` to `MODEL_UI_ORDER` (after `"iv_2sls",`, line 69).

- [ ] **Step 5: Update the drift-guard test + contract schema + sample** found in Step 1 — add `"did"` to whatever pinned set / enum / sample list includes `"iv_2sls"`, additively. Show the diff is additive only (no existing entry changed).

- [ ] **Step 6: Run capabilities + contract tests**

Run: `.venv/bin/python -m pytest tests/test_did_capabilities.py tests/contracts -v`
Expected: PASS. Then run the full suite to confirm no drift-guard breakage:
Run: `.venv/bin/python -m pytest -q`
Expected: PASS (baseline + new tests).

- [ ] **Step 7: Commit**

```bash
git add backend/workbench/engine/capabilities.py tests/test_did_capabilities.py tests/contracts docs
git commit -m "feat(did): capabilities entry + 4-way contract sync"
```

---

## Task 10: Additive goldens (staggered + 2×2 degenerate)

**Files:**
- Modify: `tests/test_engine_golden.py` (extend `_run` to forward kwargs; add two tests)
- Create: `tests/golden/did.json`, `tests/golden/did_two_by_two.json` (auto-written on first run)

- [ ] **Step 1: Extend `_run` to forward extra workflow kwargs** (test_engine_golden.py:12)

```python
def _run(tmp_path, frame, *, y, x, mode="auto", model_type="auto", **extra):
    source = tmp_path / "data.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], mode=mode, y=y, x=x,
                          model_type=model_type, **extra)
    return project.root / "runs" / result["run_id"], result
```

(Pure superset — existing callers pass no `extra`, so the 8 existing goldens are unaffected.)

- [ ] **Step 2: Add the DID golden tests**

```python
def test_golden_did_staggered(tmp_path):
    import numpy as np
    rng = np.random.default_rng(7)
    rows = []
    for ent, cohort in [("A", 2019), ("B", 2019), ("C", 2021), ("D", 2021),
                        ("E", 0), ("F", 0)]:
        fe = rng.normal()
        for year in range(2017, 2023):
            d = 1 if (cohort and year >= cohort) else 0
            rows.append({"id": ent, "year": year,
                         "y": round(fe + 0.1 * (year - 2017) + 2.0 * d, 6),
                         "first_treat": cohort})
    run_root, _ = _run(tmp_path, pd.DataFrame(rows), y="y", x=[], model_type="did",
                       entity_col="id", time_col="year", did_mode="cohort",
                       did_cohort_col="first_treat")
    snap = _capture(run_root)
    assert snap["status"] == "completed"
    assert "did_diagnostics" in snap["artifacts"]
    _assert_or_write_golden("did_staggered", snap)


def test_golden_did_two_by_two(tmp_path):
    rows = []
    for ent, treat in [("A", 1), ("B", 1), ("C", 0), ("D", 0)]:
        for year, post in [(2018, 0), (2019, 0), (2021, 1), (2022, 1)]:
            rows.append({"id": ent, "year": year, "treat": treat, "post": post,
                         "y": round(1.0 + 2.0 * (treat * post), 6)})
    run_root, _ = _run(tmp_path, pd.DataFrame(rows), y="y", x=[], model_type="did",
                       entity_col="id", time_col="year", did_mode="two_by_two",
                       did_treat_col="treat", did_post_col="post")
    _assert_or_write_golden("did_two_by_two", _capture(run_root))
```

- [ ] **Step 3: First run writes goldens (skips), second run asserts**

Run twice: `.venv/bin/python -m pytest tests/test_engine_golden.py -v`
Expected: first run skips the two new goldens (writes the files); second run PASS, all goldens (8 existing 0-drift + 2 new). **Open `tests/golden/did_staggered.json` and sanity-check** the captured ATT coefficient ≈ 2.0 before committing.

- [ ] **Step 4: Commit**

```bash
git add tests/test_engine_golden.py tests/golden/did_staggered.json tests/golden/did_two_by_two.json
git commit -m "test(did): additive goldens (staggered + 2x2), 0-drift on existing 8"
```

---

## Task 11: Frontend `DIDControls.tsx`

**Files:**
- Create: `frontend/src/runForm/DIDControls.tsx`, `frontend/src/runForm/DIDControls.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/runForm/DIDControls.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { DIDControls, type DIDRoleValue } from "./DIDControls";

const base: DIDRoleValue = { mode: "cohort", entity: "", time: "", cohort: "",
  treat: "", post: "", status: "" };

describe("DIDControls", () => {
  it("shows cohort role selectors in cohort mode", () => {
    render(<DIDControls columns={["id", "year", "first_treat", "y"]} value={base}
      onChange={() => {}} />);
    expect(screen.getByLabelText("did-entity")).toBeInTheDocument();
    expect(screen.getByLabelText("did-cohort")).toBeInTheDocument();
  });

  it("switches to two_by_two mode and exposes treat/post", () => {
    const onChange = vi.fn();
    render(<DIDControls columns={["id", "year", "treat", "post"]} value={base}
      onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("did-mode"), { target: { value: "two_by_two" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ mode: "two_by_two" }));
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/runForm/DIDControls.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `DIDControls.tsx`** (mirror IVControls' field/select idiom + ios classes)

```tsx
// frontend/src/runForm/DIDControls.tsx
export type DIDMode = "cohort" | "two_by_two" | "status";

export interface DIDRoleValue {
  mode: DIDMode;
  entity: string;
  time: string;
  cohort: string;
  treat: string;
  post: string;
  status: string;
}

function ColumnSelect(props: {
  label: string; aria: string; columns: string[]; value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="ios-field" key={props.aria}>
      <span>{props.label}</span>
      <select aria-label={props.aria} value={props.value}
        onChange={(e) => props.onChange(e.target.value)}>
        <option value="">—</option>
        {props.columns.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    </label>
  );
}

export function DIDControls(props: {
  columns: string[];
  value: DIDRoleValue;
  onChange: (v: DIDRoleValue) => void;
}) {
  const { columns, value, onChange } = props;
  const set = (patch: Partial<DIDRoleValue>) => onChange({ ...value, ...patch });

  return (
    <div className="ios-group" aria-label="DID settings">
      <div className="ios-group-label">DID 设定 · 选择输入模式与角色列</div>
      <label className="ios-field">
        <span>输入模式</span>
        <select aria-label="did-mode" value={value.mode}
          onChange={(e) => set({ mode: e.target.value as DIDMode })}>
          <option value="cohort">队列(首次处理时点)</option>
          <option value="two_by_two">经典 2×2(组 + 期)</option>
          <option value="status">处理状态(D_it)</option>
        </select>
      </label>

      {value.mode !== "two_by_two" && (
        <>
          <ColumnSelect label="个体 (entity)" aria="did-entity" columns={columns}
            value={value.entity} onChange={(v) => set({ entity: v })} />
          <ColumnSelect label="时间 (time)" aria="did-time" columns={columns}
            value={value.time} onChange={(v) => set({ time: v })} />
        </>
      )}
      {value.mode === "cohort" && (
        <ColumnSelect label="首次处理时点 (cohort)" aria="did-cohort" columns={columns}
          value={value.cohort} onChange={(v) => set({ cohort: v })} />
      )}
      {value.mode === "two_by_two" && (
        <>
          <ColumnSelect label="处理组 (treat)" aria="did-treat" columns={columns}
            value={value.treat} onChange={(v) => set({ treat: v })} />
          <ColumnSelect label="时期 (post)" aria="did-post" columns={columns}
            value={value.post} onChange={(v) => set({ post: v })} />
        </>
      )}
      {value.mode === "status" && (
        <ColumnSelect label="处理状态 (D_it)" aria="did-status" columns={columns}
          value={value.status} onChange={(v) => set({ status: v })} />
      )}
      <div className="ios-hint" aria-live="polite">
        需要 ≥2 个时间期,且至少 1 个处理单位 + 1 个对照(从不处理/尚未处理)。
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && npx vitest run src/runForm/DIDControls.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/runForm/DIDControls.tsx frontend/src/runForm/DIDControls.test.tsx
git commit -m "feat(did): DIDControls role-assignment UI (cohort/2x2/status modes)"
```

---

## Task 12: `DIDDiagnosticsCard.tsx` (tiered) + RunForm posting

**Files:**
- Create: `frontend/src/runResult/DIDDiagnosticsCard.tsx`, `frontend/src/runResult/DIDDiagnosticsCard.test.tsx`
- Modify: `frontend/src/runForm/RunForm.tsx` (post `did_*` params)

- [ ] **Step 1: Write the failing card test**

```tsx
// frontend/src/runResult/DIDDiagnosticsCard.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { DIDDiagnosticsCard, type DIDDiagnostics } from "./DIDDiagnosticsCard";

const diag: DIDDiagnostics = {
  att: { estimate: 2.13, std_error: 0.41, pvalue: 0.0, ci: [1.33, 2.93],
    spec: "twfe", covariance: "robust" },
  event_study: { event_time: [-2, 0, 1], coef: [0.0, 1.8, 2.4], se: [0.3, 0.4, 0.5],
    ci_lower: [-0.6, 1.0, 1.4], ci_upper: [0.6, 2.6, 3.4], ref_period: -1 },
  parallel_trends: { test: "joint_pre_leads_f", statistic: 0.62, pvalue: 0.71,
    n_pre_leads: 1, verdict: "not_rejected", message: "ok" },
  goodman_bacon: { components: [
    { type: "treated_vs_untreated", weight: 0.7, estimate: 2.3 },
    { type: "later_vs_earlier", weight: 0.3, estimate: 1.1 }],
    weighted_avg: 2.06, forbidden_weight: 0.3, message: "..." },
  spec: { entity: "id", time: "year", cohort: "_did_cohort", n_treated_units: 4,
    n_never_treated: 2, staggered: true, mode: "cohort" },
};

describe("DIDDiagnosticsCard", () => {
  it("shows ATT headline and verdict pills collapsed", () => {
    render(<DIDDiagnosticsCard diagnostics={diag} />);
    expect(screen.getByText(/2\.13/)).toBeInTheDocument();
    expect(screen.getByText(/未拒绝/)).toBeInTheDocument();
  });

  it("reveals full event-study table on expand", () => {
    render(<DIDDiagnosticsCard diagnostics={diag} />);
    expect(screen.queryByLabelText("did-event-study-table")).toBeNull();
    fireEvent.click(screen.getByText(/展开完整数据/));
    expect(screen.getByLabelText("did-event-study-table")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure** — `cd frontend && npx vitest run src/runResult/DIDDiagnosticsCard.test.tsx` → FAIL.

- [ ] **Step 3: Implement `DIDDiagnosticsCard.tsx`** (tiered; event-study drawn as inline SVG from the numeric path; mirror IVDiagnosticsCard verdict-pill styling)

```tsx
// frontend/src/runResult/DIDDiagnosticsCard.tsx
import { useState } from "react";

export interface DIDDiagnostics {
  att: { estimate: number; std_error: number; pvalue: number; ci: [number, number];
    spec: string; covariance: string };
  event_study: { event_time: number[]; coef: number[]; se: number[];
    ci_lower: number[]; ci_upper: number[]; ref_period: number };
  parallel_trends: { test: string; statistic: number | null; pvalue: number | null;
    n_pre_leads: number; verdict: "not_rejected" | "rejected"; message: string };
  goodman_bacon: { components: { type: string; weight: number; estimate: number }[];
    weighted_avg: number; forbidden_weight: number; message: string };
  spec: { entity: string; time: string; cohort: string; n_treated_units: number;
    n_never_treated: number; staggered: boolean; mode: string };
  interpretation_restriction?: string;
}

function EventStudyChart({ es }: { es: DIDDiagnostics["event_study"] }) {
  const W = 260, H = 90, pad = 8;
  const xs = es.event_time;
  if (!xs.length) return null;
  const all = [...es.coef, ...es.ci_lower, ...es.ci_upper];
  const lo = Math.min(...all), hi = Math.max(...all);
  const sx = (i: number) => pad + (i / Math.max(xs.length - 1, 1)) * (W - 2 * pad);
  const sy = (v: number) => H - pad - ((v - lo) / Math.max(hi - lo, 1e-9)) * (H - 2 * pad);
  const zeroIdx = xs.findIndex((k) => k >= 0);
  const pts = es.coef.map((c, i) => `${sx(i)},${sy(c)}`).join(" ");
  return (
    <svg width={W} height={H} aria-label="did-event-study-chart">
      <line x1={pad} y1={sy(0)} x2={W - pad} y2={sy(0)} stroke="#ccc" />
      {zeroIdx >= 0 && <line x1={sx(zeroIdx)} y1={0} x2={sx(zeroIdx)} y2={H}
        stroke="#f55" strokeDasharray="4 3" />}
      {es.coef.map((c, i) => (
        <line key={i} x1={sx(i)} y1={sy(es.ci_lower[i])} x2={sx(i)} y2={sy(es.ci_upper[i])}
          stroke="#4a6cf7" opacity={0.5} />
      ))}
      <polyline points={pts} fill="none" stroke="#4a6cf7" strokeWidth={2} />
    </svg>
  );
}

export function DIDDiagnosticsCard({ diagnostics }: { diagnostics: DIDDiagnostics }) {
  const [open, setOpen] = useState(false);
  const d = diagnostics;
  const ptColor = d.parallel_trends.verdict === "not_rejected" ? "#137a3a" : "#c0392b";
  const ptText = d.parallel_trends.verdict === "not_rejected" ? "未拒绝" : "已拒绝";
  return (
    <div className="result-card" aria-label="did-diagnostics">
      <h3>DID 诊断</h3>
      <div>
        <span>ATT</span>{" "}
        <strong style={{ fontSize: 20 }}>{d.att.estimate.toFixed(2)}</strong>{" "}
        <span>SE {d.att.std_error.toFixed(2)} · p {d.att.pvalue.toFixed(3)} · 95%CI
          [{d.att.ci[0].toFixed(2)}, {d.att.ci[1].toFixed(2)}]</span>
      </div>
      <EventStudyChart es={d.event_study} />
      <div>
        平行趋势 <span style={{ color: ptColor }}>{ptText}</span>
        {d.parallel_trends.pvalue != null && <> (p={d.parallel_trends.pvalue})</>}
      </div>
      <div>
        Goodman-Bacon 坏比较权重 {(d.goodman_bacon.forbidden_weight * 100).toFixed(0)}%
        · 加权均值 {d.goodman_bacon.weighted_avg.toFixed(2)}
      </div>

      <button onClick={() => setOpen((v) => !v)}>{open ? "▾ 收起" : "▸ 展开完整数据"}</button>

      {open && (
        <div>
          <table aria-label="did-event-study-table">
            <thead><tr><th>event_time</th><th>coef</th><th>se</th><th>95% CI</th></tr></thead>
            <tbody>
              {d.event_study.event_time.map((k, i) => (
                <tr key={k}>
                  <td>{k}</td><td>{d.event_study.coef[i].toFixed(3)}</td>
                  <td>{d.event_study.se[i].toFixed(3)}</td>
                  <td>[{d.event_study.ci_lower[i].toFixed(2)}, {d.event_study.ci_upper[i].toFixed(2)}]</td>
                </tr>
              ))}
            </tbody>
          </table>
          <table aria-label="did-bacon-table">
            <thead><tr><th>比较类型</th><th>权重</th><th>估计</th></tr></thead>
            <tbody>
              {d.goodman_bacon.components.map((c, i) => (
                <tr key={i}><td>{c.type}</td><td>{c.weight.toFixed(2)}</td>
                  <td>{c.estimate.toFixed(2)}</td></tr>
              ))}
            </tbody>
          </table>
          <div>规格: entity={d.spec.entity} · time={d.spec.time} · 处理单位
            {d.spec.n_treated_units} · 从不处理 {d.spec.n_never_treated} · 错位
            {d.spec.staggered ? "是" : "否"}</div>
          {d.interpretation_restriction && (
            <div role="note" style={{ borderLeft: "3px solid #f0a020", paddingLeft: 8 }}>
              ⚠ {d.interpretation_restriction}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run to verify pass** — `cd frontend && npx vitest run src/runResult/DIDDiagnosticsCard.test.tsx` → PASS.

- [ ] **Step 5: Wire RunForm to post `did_*` params + render the card**

Inspect `RunForm.tsx` for how it posts `iv_endog`/`iv_instruments` via `RunExtraParams` and how it renders `IVDiagnosticsCard` / `IVControls` conditionally on `model_type === "iv_2sls"`. Mirror exactly for `did`: render `<DIDControls>` when `model_type === "did"`; post `model_type=did`, `entity_col`, `time_col`, `did_mode`, `did_cohort_col`, `did_treat_col`, `did_post_col`, `did_status_col` (from `DIDRoleValue`); exclude DID role columns from `x` (same pattern as IV excludes endog/instruments from exog). Render `<DIDDiagnosticsCard>` from the fetched `did_diagnostics` artifact (mirror how `IVDiagnosticsCard` consumes `iv_diagnostics`). Add a RunForm test asserting the POST body carries `did_mode` and that role columns are absent from `x`.

- [ ] **Step 6: Run frontend gate**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: PASS, tsc 0 errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/runResult/DIDDiagnosticsCard.tsx frontend/src/runResult/DIDDiagnosticsCard.test.tsx frontend/src/runForm/RunForm.tsx frontend/src/runForm/RunForm.test.tsx
git commit -m "feat(did): tiered DIDDiagnosticsCard + RunForm wiring (post did_* params)"
```

---

## Task 13: Example dataset, docs, dead-code cleanup, final gate

**Files:**
- Create: `examples/datasets/did_staggered_adoption.csv`, `docs/did-howto.md`
- Modify: `backend/workbench/econometrics/runner.py` (delete `run_fixed_effects` if unused)

- [ ] **Step 1: Confirm `run_fixed_effects` is dead, then delete**

```bash
grep -rn "run_fixed_effects" backend/ tests/ frontend/ | grep -iv pycache
```

If the only hit is the definition in `runner.py` (no callers, no tests), delete the function. If anything references it, SKIP the deletion and note it in the commit message.

- [ ] **Step 2: Create the example dataset**

```bash
.venv/bin/python - <<'PY'
import csv, random
random.seed(0)
rows = [("id","year","first_treat","y")]
for ent, cohort in [("A",2019),("B",2019),("C",2021),("D",2021),("E",0),("F",0)]:
    fe = random.gauss(0,1)
    for year in range(2017,2023):
        d = 1 if (cohort and year>=cohort) else 0
        rows.append((ent,year,cohort, round(fe+0.1*(year-2017)+2.0*d+random.gauss(0,0.05),4)))
with open("examples/datasets/did_staggered_adoption.csv","w",newline="") as f:
    csv.writer(f).writerows(rows)
print("wrote", len(rows)-1, "rows")
PY
```

- [ ] **Step 3: Write `docs/did-howto.md`** — mirror the structure of `docs/iv-2sls-howto.md`: what DID estimates; the three input modes (cohort / 2×2 / status) and which columns each needs; how to read the ATT, event-study chart (pre = parallel-trends eyes, post = dynamic path), parallel-trends test, and Goodman-Bacon forbidden weight; the staggered-adoption caveat + Layer 2 pointer; a worked CLI example using `examples/datasets/did_staggered_adoption.csv`:

```
env PYTHONPATH=backend .venv/bin/python -m workbench.cli run <project> examples/datasets/did_staggered_adoption.csv y --x "" --model-type did --entity-col id --time-col year --did-mode cohort --did-cohort-col first_treat
```

(Verify the CLI flag names exist / add them if the CLI exposes model params; if the CLI does not yet thread `did_*`, document the API/GUI path instead and note CLI support as a follow-up — do NOT invent flags.)

- [ ] **Step 4: Run the full gate**

```bash
./scripts/gate.sh
```

Expected: GATE PASSED — BE (baseline + new did tests) / golden (8 + 2 new, 0-drift) / FE (baseline + DIDControls + DIDDiagnosticsCard + RunForm) / `tsc --noEmit` 0 errors.

- [ ] **Step 5: Commit**

```bash
git add examples/datasets/did_staggered_adoption.csv docs/did-howto.md backend/workbench/econometrics/runner.py
git commit -m "docs(did): howto + example dataset; chore: drop stranded run_fixed_effects"
```

---

## Self-Review (completed during authoring)

- **Spec coverage:** §1 four deliverables → Tasks 3 (ATT, event-study), 4 (parallel-trends assembly), 2 (Goodman-Bacon). §2 canonical cohort + 3 modes → Task 1. §3.1–3.10 backend touch points → Tasks 1–9. §4 frontend → Tasks 11–12. §5 data flow → Tasks 5–8 end-to-end test. §6 golden + Bacon-reference + spec/event-study tests → Tasks 2, 10, plus per-task tests. §7 risks → mitigated (Bacon identity test T2; inert params T7; explicit-only T5). §8 touch list + run_fixed_effects cleanup → Task 13. No gaps.
- **Placeholder scan:** No TBD/TODO. The two "inspect the existing pattern and mirror exactly" steps (Task 7 Step 6 api positional style; Task 12 Step 5 RunForm) point at a concrete template file with the exact symbols to replicate — these are integration points where the surrounding code must be read to match style; the DID payload to add is fully specified.
- **Type consistency:** `NormalizedDID` (frame/entity/time/y/summary) consistent across Tasks 1/4/5/8. `_did_D`/`_did_event_time`/`_did_cohort` column names consistent across Tasks 1/2/3/4. `DIDRoleValue` fields consistent across Tasks 11/12. `did_diagnostics` artifact id consistent Tasks 8/12. `run_did`/`run_event_study` signatures consistent Tasks 3/4/5.
- **Uncertainty flags for the executor:** verify exact registry membership API (Task 5 Step 2), `_model_types` accessor name (Task 6), the 4 capability sync points (Task 9 Step 1), and CLI flag existence (Task 13 Step 3) against the live code before asserting — each step says so inline.
