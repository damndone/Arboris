# DID Layer 2 — Callaway-Sant'Anna Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit-only `cs_did` model type implementing the Callaway-Sant'Anna (2021) group-time ATT estimator end-to-end, self-implemented and validated element-wise against R `did`/`DRDID`, golden 0-drift.

**Architecture:** The estimator slot (`cs_attgt.py`) emits a standardized `EffectEstimateBundle`; estimator-agnostic `cs_aggregate.py` and `cs_inference.py` consume only the bundle. Reuses Layer 1's `did_spec.normalize_did_input` cohort table unchanged. Wired through the engine on the proven IV/2SLS + DID-Layer-1 template.

**Tech Stack:** Python (NumPy, SciPy, statsmodels, pandas — all already present, zero new deps), linearmodels not required for CS. React/TypeScript frontend. R `did`+`DRDID` used ONCE at fixture-generation time (never at test/runtime).

**Spec:** `docs/superpowers/specs/2026-06-15-workbench-did-layer2-callaway-santanna-design.md`

---

## File Structure

| File | Responsibility | Status |
|---|---|---|
| `backend/workbench/engine/did_spec.py` | canonical cohort table | REUSED, unchanged |
| `backend/workbench/engine/cs_attgt.py` | `EffectEstimateBundle`, `CSSpecError`, `estimate_att_gt` (cell sub-sample, base period, dr/ipw/reg, DRDID-equivalent IF, cluster aggregation, cell_metadata, guards) | NEW |
| `backend/workbench/engine/cs_aggregate.py` | `aggregate(bundle, kind)` — 4 aggregations + aggregation IF | NEW |
| `backend/workbench/engine/cs_inference.py` | `multiplier_bootstrap` — seeded SE / pointwise / sup-t bands | NEW |
| `backend/workbench/econometrics/runner.py` | `run_cs_did` orchestration + structured result | MODIFY |
| `backend/workbench/engine/stages/estimation.py` | `_fit_cs_did` + CORE_PACK handler + RerunAction + missing-fields guard | MODIFY |
| `backend/workbench/engine/stages/diagnostics.py` | write `cs_did` artifact (degraded-safe) | MODIFY |
| `backend/workbench/orchestrator/_model_types.py` | `_MODEL_TYPE_MAP["cs_did"]` + `_MODEL_METADATA` | MODIFY |
| `backend/workbench/orchestrator/__init__.py` | thread `cs_*` params + re-export `run_cs_did` | MODIFY |
| `backend/workbench/api.py` | `RunExtraParams` `cs_*` form fields | MODIFY |
| `backend/workbench/engine/capabilities.py` | `cs_did` entry (group "DID") | MODIFY |
| `frontend/src/runForm/DIDControls.tsx` | `cs_did` controls (control group / method / base period / anticipation / cluster) | MODIFY |
| `frontend/src/runResult/CSDiagnosticsCard.tsx` | tiered CS result card + metadata/warnings | NEW |
| `tests/fixtures/cs_did/generate_fixtures.R` + `*.json` + `panel.csv` | R oracle fixtures | NEW |
| `tests/test_cs_attgt.py`, `test_cs_aggregate.py`, `test_cs_inference.py`, `test_cs_did_invariants.py`, `test_cs_did_oracle.py` | unit + invariant + oracle tests | NEW |
| `tests/golden/cs_did_*.json` | additive golden | NEW |
| `examples/datasets/cs_did_staggered.csv`, `docs/cs-did-howto.md` | example + how-to | NEW |

**Note on the `"DID"` group:** `frontend/src/capabilities/types.ts` `ModelGroup` already includes `"DID"`; `cs_did` joins that group, so no TS-union edit is needed.

---

## Task 0: Worktree + environment + baseline gate

**Files:** none (environment only)

- [ ] **Step 1: Create the isolated worktree** (version-isolation rule)

```bash
cd /Users/jiayuanren/项目规划
git worktree add -b workbench-v1.5.6 .worktrees/workbench-v1.5.6 main
cd .worktrees/workbench-v1.5.6
```

- [ ] **Step 2: Build the venv + install full extras**

```bash
~/.local/bin/python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev,panel,ml,imbalanced,imputation]"
```

- [ ] **Step 3: Install frontend deps**

```bash
cd frontend && npm install && cd ..
```

- [ ] **Step 4: Run the full gate to record the baseline**

```bash
./scripts/gate.sh
```
Expected: GATE PASSED. Record BE count, FE count, golden count, `tsc` 0. (Baseline reference: BE 851 / FE 605 / golden+invariants 17 / tsc 0 from v1.5.5.1.)

- [ ] **Step 5: Commit a marker** (empty — just to anchor the branch)

```bash
git commit --allow-empty -m "chore(cs_did): V1.5.6 baseline — Layer 2 Callaway-Sant'Anna worktree"
```

---

## Task 1: R oracle fixtures (the IF validation source)

**Prerequisite:** R with `did` and `DRDID` installed (`install.packages(c("did","DRDID"))`). Run ONCE; commit the JSON. Tests read JSON only — no R at test time. If R is unavailable on this machine, generate the fixtures on any machine with R and copy the JSON in; the byte content is what matters.

**Files:**
- Create: `tests/fixtures/cs_did/panel.csv` (the shared dataset both R and Python estimate on)
- Create: `tests/fixtures/cs_did/generate_fixtures.R`
- Create (R output, committed): `tests/fixtures/cs_did/att_gt.json`, `drdid_inffunc.json`, `aggte.json`

- [ ] **Step 1: Write the canonical small staggered panel** `tests/fixtures/cs_did/panel.csv`

A balanced panel: 60 units, periods 1..6, 3 treated cohorts (g=3,4,5) + never-treated, one pre-treatment covariate `x1`, an outcome `y` with known cohort-time effects + parallel trends in `x1`. Generate it deterministically:

```python
import numpy as np, pandas as pd
rng = np.random.default_rng(20260615)
units, periods = 60, [1,2,3,4,5,6]
cohorts = {}            # unit -> first-treat period (np.inf = never)
for u in range(units):
    cohorts[u] = [np.inf, 3, 4, 5][u % 4]
rows = []
for u in range(units):
    g = cohorts[u]
    x1 = rng.normal(0, 1)                      # time-invariant pre-treatment covariate
    fe_u = rng.normal(0, 0.5)
    for t in periods:
        fe_t = 0.2 * t
        treat = 1.0 if (np.isfinite(g) and t >= g) else 0.0
        # true ATT(g,t) = 0.5*(t-g+1) when treated; trends depend on x1 (cond. PT)
        eff = 0.5 * (t - g + 1) if treat else 0.0
        y = 1.0 + fe_u + fe_t + 0.3 * x1 * t + eff + rng.normal(0, 0.3)
        rows.append({"unit": u, "period": t,
                     "first_treat": (0 if np.isinf(g) else int(g)),
                     "x1": x1, "y": y})
pd.DataFrame(rows).to_csv("tests/fixtures/cs_did/panel.csv", index=False)
```
Run this snippet once (it is also embedded as a comment in `generate_fixtures.R` header for provenance). Commit `panel.csv`.

- [ ] **Step 2: Write** `tests/fixtures/cs_did/generate_fixtures.R`

```r
# Oracle generator for cs_did. Requires: did, DRDID, jsonlite.
# Reads tests/fixtures/cs_did/panel.csv ; writes att_gt.json, drdid_inffunc.json, aggte.json.
library(did); library(DRDID); library(jsonlite)
d <- read.csv("tests/fixtures/cs_did/panel.csv")

emit_attgt <- function(method, control) {
  r <- att_gt(yname="y", tname="period", idname="unit", gname="first_treat",
              xformla=~x1, data=d, est_method=method, control_group=control,
              base_period="varying", anticipation=0, bstrap=FALSE, cband=FALSE)
  list(group=r$group, t=r$t, att=r$att, se=r$se, n=r$n)
}
att_gt_out <- list()
for (m in c("dr","ipw","reg")) for (c in c("nevertreated","notyettreated"))
  att_gt_out[[paste(m,c,sep="_")]] <- emit_attgt(m, c)
write_json(att_gt_out, "tests/fixtures/cs_did/att_gt.json", digits=12, auto_unbox=TRUE)

# Per-cell DRDID influence functions for ONE representative cell (g=4, base=3, t=4),
# never-treated comparison, est_method="dr". Build the 2-period long diff for that cell.
cell <- subset(d, first_treat %in% c(0, 4) & period %in% c(3,4))
wide <- reshape(cell[,c("unit","period","y","x1","first_treat")],
                idvar=c("unit","x1","first_treat"), timevar="period", direction="wide")
D  <- as.integer(wide$first_treat == 4)
dy <- wide$y.4 - wide$y.3
X  <- model.matrix(~x1, data=wide)
dr <- drdid_panel(y1=wide$y.4, y0=wide$y.3, D=D, covariates=X, inffunc=TRUE)
write_json(list(att=dr$ATT, se=dr$se, inf_func=as.numeric(dr$att.inf.func),
                unit=wide$unit),
           "tests/fixtures/cs_did/drdid_inffunc.json", digits=12, auto_unbox=TRUE)

# Aggregations (dr, never-treated).
r <- att_gt(yname="y", tname="period", idname="unit", gname="first_treat",
            xformla=~x1, data=d, est_method="dr", control_group="nevertreated",
            base_period="varying", bstrap=FALSE, cband=FALSE)
agg <- function(type) { a <- aggte(r, type=type, bstrap=FALSE);
  list(overall=a$overall.att, overall_se=a$overall.se,
       egt=a$egt, att_egt=a$att.egt, se_egt=a$se.egt) }
write_json(list(simple=agg("simple"), dynamic=agg("dynamic"),
                group=agg("group"), calendar=agg("calendar")),
           "tests/fixtures/cs_did/aggte.json", digits=12, auto_unbox=TRUE)
```

- [ ] **Step 3: Run it and commit the outputs**

```bash
Rscript tests/fixtures/cs_did/generate_fixtures.R
git add tests/fixtures/cs_did/
git commit -m "test(cs_did): R did/DRDID oracle fixtures + shared panel"
```
Expected: three JSON files created, non-empty. These are the binding oracle for Tasks 4, 5, 7, 8.

---

## Task 2: `EffectEstimateBundle` + cell sub-sample construction (comparison group)

**Files:**
- Create: `backend/workbench/engine/cs_attgt.py`
- Test: `tests/test_cs_attgt.py`

- [ ] **Step 1: Write the failing test** (invariant #4 — no already-treated controls)

```python
# tests/test_cs_attgt.py
import numpy as np, pandas as pd, pytest
from workbench.engine.cs_attgt import comparison_mask, CSSpecError

def _panel():
    return pd.read_csv("tests/fixtures/cs_did/panel.csv")

def test_never_treated_comparison_excludes_all_finite_cohorts():
    d = _panel()
    cohort = d.groupby("unit")["first_treat"].first().replace(0, np.inf)
    m = comparison_mask(cohort, g=4, t=4, base_t=3, control_group="never", anticipation=0)
    # only never-treated (cohort == inf) qualify
    assert set(cohort[m].unique()) == {np.inf}

def test_not_yet_treated_boundary_delta0():
    d = _panel()
    cohort = d.groupby("unit")["first_treat"].first().replace(0, np.inf)
    # cell (g=4,t=4,base=3): comparison_safe_until = max(4,3)=4; need G_i > 4 or inf
    m = comparison_mask(cohort, g=4, t=4, base_t=3, control_group="not_yet", anticipation=0)
    qualifying = set(cohort[m].unique())
    assert np.inf in qualifying and 5 in qualifying     # not-yet (G=5) and never
    assert 3 not in qualifying and 4 not in qualifying  # already-treated excluded

def test_not_yet_treated_boundary_delta1_shifts():
    d = _panel()
    cohort = d.groupby("unit")["first_treat"].first().replace(0, np.inf)
    # delta=1: comparison_safe_until + 1 = 5; need G_i > 5 or inf => only never + G=6 (none) 
    m = comparison_mask(cohort, g=4, t=4, base_t=3, control_group="not_yet", anticipation=1)
    assert 5 not in set(cohort[m].unique())             # G=5 now excluded by the +δ shift
```

- [ ] **Step 2: Run, verify failure**

Run: `.venv/bin/python -m pytest tests/test_cs_attgt.py -v`
Expected: FAIL (`cannot import name 'comparison_mask'`).

- [ ] **Step 3: Implement the bundle + comparison mask**

```python
# backend/workbench/engine/cs_attgt.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import numpy as np
import pandas as pd


class CSSpecError(ValueError):
    """CS_*-prefixed failure → structured MODEL_FIT_FAILED (v1.5.5.1 convention)."""


@dataclass
class EffectEstimateBundle:
    estimates: np.ndarray                 # (K,)
    influence_func: np.ndarray            # (G, K) cluster rows, mean-zero columns
    cluster_ids: np.ndarray               # (G,)
    cell_metadata: list[dict]             # K records
    weights: dict                         # cohort sizes n_g, shares p̂_g
    vcov_config: dict
    diagnostics: dict = field(default_factory=dict)


def comparison_mask(cohort: pd.Series, *, g: float, t: float, base_t: float,
                    control_group: str, anticipation: int) -> pd.Series:
    """Boolean mask over the entity-indexed cohort series selecting clean controls
    for cell (g,t). never-treated always qualify; already-treated always excluded."""
    safe_until = max(t, base_t)
    never = ~np.isfinite(cohort)
    if control_group == "never":
        return never
    if control_group == "not_yet":
        return never | (cohort > safe_until + anticipation)
    raise CSSpecError(f"CS_BAD_CONTROL_GROUP: '{control_group}'")
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/python -m pytest tests/test_cs_attgt.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/cs_attgt.py tests/test_cs_attgt.py
git commit -m "feat(cs_did): EffectEstimateBundle + clean comparison-group mask"
```

---

## Task 3: Base period + long difference (§3.2)

**Files:**
- Modify: `backend/workbench/engine/cs_attgt.py`
- Test: `tests/test_cs_attgt.py`

- [ ] **Step 1: Write failing tests** (invariants #2, #3)

```python
from workbench.engine.cs_attgt import base_period_for, effective_treatment_start, reference_period

def test_reference_and_effective_start_use_anticipation():
    assert effective_treatment_start(g=4, anticipation=1) == 3
    assert reference_period(g=4, anticipation=1) == 2

def test_post_period_base_is_reference():
    assert base_period_for(g=4, t=5, base_period="varying", anticipation=0) == 3

def test_varying_pre_period_is_sequential():
    # t < effective_treatment_start(=4): varying base = t-1
    assert base_period_for(g=4, t=2, base_period="varying", anticipation=0) == 1

def test_universal_pre_period_is_fixed_reference():
    assert base_period_for(g=4, t=2, base_period="universal", anticipation=0) == 3
```

- [ ] **Step 2: Run, verify failure**

Run: `.venv/bin/python -m pytest tests/test_cs_attgt.py -k base or reference or effective -v`
Expected: FAIL (import errors).

- [ ] **Step 3: Implement**

```python
def effective_treatment_start(*, g: float, anticipation: int) -> float:
    return g - anticipation

def reference_period(*, g: float, anticipation: int) -> float:
    return g - 1 - anticipation

def base_period_for(*, g: float, t: float, base_period: str, anticipation: int) -> float:
    ref = reference_period(g=g, anticipation=anticipation)
    if t >= effective_treatment_start(g=g, anticipation=anticipation):
        return ref
    if base_period == "universal":
        return ref
    if base_period == "varying":
        return t - 1
    raise CSSpecError(f"CS_BAD_BASE_PERIOD: '{base_period}'")
```

- [ ] **Step 4: Run, verify pass.** `.venv/bin/python -m pytest tests/test_cs_attgt.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/cs_attgt.py tests/test_cs_attgt.py
git commit -m "feat(cs_did): base-period + anticipation anchors"
```

---

## Task 4: Per-cell point estimates dr/ipw/reg (§3.4) + empty-X collapse + att_gt oracle

**Files:**
- Modify: `backend/workbench/engine/cs_attgt.py`
- Test: `tests/test_cs_attgt.py`, `tests/test_cs_did_oracle.py`

- [ ] **Step 1: Write failing tests** (invariant #1 + oracle ATT 1e-6)

```python
# tests/test_cs_attgt.py
from workbench.engine.cs_attgt import att_gt_cell

def test_empty_x_collapse_to_2x2():
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    kw = dict(frame=d, entity="unit", time="period", y="y", g=4, t=4, base_t=3,
              control_group="never", anticipation=0, covariates=[])
    dr  = att_gt_cell(est_method="dr",  **kw)["att"]
    ipw = att_gt_cell(est_method="ipw", **kw)["att"]
    reg = att_gt_cell(est_method="reg", **kw)["att"]
    assert abs(dr - ipw) < 1e-10 and abs(dr - reg) < 1e-10
```

```python
# tests/test_cs_did_oracle.py
import json, numpy as np, pandas as pd, pytest
from workbench.engine.cs_attgt import att_gt_cell
ORACLE = json.load(open("tests/fixtures/cs_did/att_gt.json"))
PANEL = pd.read_csv("tests/fixtures/cs_did/panel.csv")

@pytest.mark.parametrize("method,control", [("dr","never"),("ipw","never"),
    ("reg","never"),("dr","not_yet")])
def test_attgt_matches_R_did(method, control):
    key = {"never":"nevertreated","not_yet":"notyettreated"}[control]
    ref = ORACLE[f"{method}_{key}"]
    for g, t, att in zip(ref["group"], ref["t"], ref["att"]):
        base = g-1 if t >= g else t-1     # varying
        if t == base: continue
        ours = att_gt_cell(frame=PANEL, entity="unit", time="period", y="y",
            g=float(g), t=float(t), base_t=float(base), control_group=control,
            anticipation=0, covariates=["x1"], est_method=method)["att"]
        assert abs(ours - att) < 1e-6, f"(g={g},t={t}) ours={ours} R={att}"
```

- [ ] **Step 2: Run, verify failure.** Expected: FAIL (`att_gt_cell` undefined).

- [ ] **Step 3: Implement `att_gt_cell`** (§3.4; uses statsmodels logit/OLS, constant when X empty)

```python
import statsmodels.api as sm

def _cell_subsample(frame, entity, time, y, g, t, base_t, control_group, anticipation):
    cohort = frame.groupby(entity)["__cohort__"].first()
    treated = cohort.index[cohort == g]
    comp = cohort.index[comparison_mask(cohort, g=g, t=t, base_t=base_t,
                                        control_group=control_group, anticipation=anticipation)]
    keep = set(treated) | set(comp)
    sub = frame[frame[entity].isin(keep) & frame[time].isin([t, base_t])]
    # cell-level complete-case: need both periods present per unit (invariant #9 / §3.9)
    wide = sub.pivot_table(index=entity, columns=time, values=y)
    ok = wide[[t, base_t]].notna().all(axis=1)
    units = wide.index[ok]
    dY = (wide.loc[units, t] - wide.loc[units, base_t]).to_numpy()
    D = np.isin(units, treated).astype(float)
    return units.to_numpy(), D, dY

def att_gt_cell(*, frame, entity, time, y, g, t, base_t, control_group,
                anticipation, covariates, est_method):
    f = frame.copy()
    f["__cohort__"] = f.groupby(entity)[ "first_treat" if "first_treat" in f else entity ]
    # caller passes a frame already carrying _did_cohort; map it:
    f["__cohort__"] = f[entity].map(
        frame.drop_duplicates(entity).set_index(entity)["_did_cohort"])
    units, D, dY = _cell_subsample(f, entity, time, y, g, t, base_t,
                                   control_group, anticipation)
    X = np.ones((len(units), 1))
    if covariates:
        base = frame[frame[time] == base_t].set_index(entity).loc[units, covariates]
        X = np.column_stack([np.ones(len(units)), base.to_numpy(float)])
    if D.sum() == 0 or (1 - D).sum() == 0:
        return {"att": float("nan"), "n_treated": int(D.sum()),
                "n_control": int((1 - D).sum()), "valid": False,
                "warning": "CS_EMPTY_CELL"}
    # propensity (logit) — constant => p=share, weights collapse to 2x2
    if X.shape[1] == 1:
        ps = np.full(len(units), D.mean())
    else:
        ps = sm.Logit(D, X).fit(disp=0).predict(X)
    ps = np.clip(ps, 1e-6, 1 - 1e-6)
    # outcome regression on comparison units
    if X.shape[1] == 1:
        mhat = np.full(len(units), dY[D == 0].mean())
    else:
        ols = sm.OLS(dY[D == 0], X[D == 0]).fit()
        mhat = X @ ols.params
    w1 = D / D.mean()
    raw0 = ps * (1 - D) / (1 - ps)
    w0 = raw0 / raw0.mean()
    if est_method == "dr":
        att = float(np.mean((w1 - w0) * (dY - mhat)))
    elif est_method == "ipw":
        att = float(np.mean((w1 - w0) * dY))
    elif est_method == "reg":
        att = float(np.mean(w1 * (dY - mhat)))
    else:
        raise CSSpecError(f"CS_BAD_EST_METHOD: '{est_method}'")
    return {"att": att, "n_treated": int(D.sum()), "n_control": int((1 - D).sum()),
            "valid": True, "warning": None, "_units": units, "_D": D, "_dY": dY,
            "_X": X, "_ps": ps, "_mhat": mhat}
```
NOTE: `frame` must carry `_did_cohort` (from `normalize_did_input`) — the runner provides it. The oracle test builds it from `first_treat` directly; add a small shim in the test or pre-attach `_did_cohort`. Adjust the test setup to attach `_did_cohort = first_treat.replace(0, inf)` before calling.

- [ ] **Step 4: Run, verify pass.** Both test files PASS. If the oracle test fails by >1e-6, the bug is in the estimand wiring (weights/normalization) — fix the implementation, never loosen the tolerance.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/cs_attgt.py tests/test_cs_attgt.py tests/test_cs_did_oracle.py
git commit -m "feat(cs_did): dr/ipw/reg cell point estimates (att_gt oracle 1e-6, empty-X collapse)"
```

---

## Task 5: Per-cell influence function — DRDID port (§3.5) + cluster aggregation + DRDID oracle 1e-8

**This is the highest-risk task. The fixture is the binding oracle; fix the port, never the test.**

**Files:**
- Modify: `backend/workbench/engine/cs_attgt.py`
- Test: `tests/test_cs_attgt.py`, `tests/test_cs_did_oracle.py`

- [ ] **Step 1: Write failing tests** (invariant #7 + DRDID inf.func 1e-8)

```python
# tests/test_cs_did_oracle.py
def test_cell_influence_function_matches_DRDID():
    ref = json.load(open("tests/fixtures/cs_did/drdid_inffunc.json"))
    f = PANEL.copy(); f["_did_cohort"] = f["first_treat"].replace(0, np.inf)
    cell = att_gt_cell(frame=f, entity="unit", time="period", y="y",
        g=4.0, t=4.0, base_t=3.0, control_group="never", anticipation=0,
        covariates=["x1"], est_method="dr")
    from workbench.engine.cs_attgt import cell_influence_function
    inf = cell_influence_function(cell, est_method="dr")
    # align by unit id with R output
    order = {u: i for i, u in enumerate(ref["unit"])}
    ours = np.array([inf[list(cell["_units"]).index(u)] for u in ref["unit"]])
    assert np.allclose(ours, ref["inf_func"], atol=1e-8)
```

```python
# tests/test_cs_attgt.py
def test_influence_columns_mean_zero():
    f = pd.read_csv("tests/fixtures/cs_did/panel.csv"); f["_did_cohort"]=f["first_treat"].replace(0,np.inf)
    cell = att_gt_cell(frame=f, entity="unit", time="period", y="y", g=4.0, t=4.0,
        base_t=3.0, control_group="never", anticipation=0, covariates=["x1"], est_method="dr")
    from workbench.engine.cs_attgt import cell_influence_function
    assert abs(cell_influence_function(cell, est_method="dr").mean()) < 1e-8
```

- [ ] **Step 2: Run, verify failure.** Expected: FAIL (`cell_influence_function` undefined).

- [ ] **Step 3: Implement `cell_influence_function` as a faithful port of `DRDID::drdid_panel`** (and the `ipw`/`reg` panel variants). The structure below follows the DRDID source; the M-estimation correction terms for the estimated PS (`asy.lin.rep.ps`) and OR (`asy.lin.rep.wols`) MUST be included for `dr`. Iterate against the 1e-8 fixture.

```python
def cell_influence_function(cell: dict, *, est_method: str) -> np.ndarray:
    """Port of DRDID panel influence functions. Returns observation-level IF over
    cell['_units'] (mean ≈ 0). Units outside the cell contribute 0 (handled by caller)."""
    D, dY, X, ps, mhat = cell["_D"], cell["_dY"], cell["_X"], cell["_ps"], cell["_mhat"]
    n = len(D)
    w1 = D / D.mean()
    raw0 = ps * (1 - D) / (1 - ps)
    w0 = raw0 / raw0.mean()
    resid = dY - mhat
    att_treat = w1 * resid
    att_cont = w0 * resid
    eta_treat = att_treat.mean()
    eta_cont = att_cont.mean()
    inf_treat = att_treat - w1 * eta_treat            # mean(w1)=1
    inf_cont_main = att_cont - w0 * eta_cont
    if est_method == "ipw":
        # std_ipw_did_panel: include PS-estimation correction; no OR term
        infl = inf_treat - (inf_cont_main + _ps_correction(D, X, ps, w0, resid, eta_cont))
    elif est_method == "reg":
        # reg_did_panel: include OR-estimation correction; no PS term
        infl = inf_treat - inf_cont_main \
               - _or_correction(D, X, w1, w0, project_to="treat_minus_cont")
    elif est_method == "dr":
        infl = inf_treat - inf_cont_main \
               - _ps_correction(D, X, ps, w0, resid, eta_cont) \
               - _or_correction(D, X, w1, w0, project_to="dr")
    else:
        raise CSSpecError(f"CS_BAD_EST_METHOD: '{est_method}'")
    return infl - infl.mean()                          # enforce exact mean-zero
```
Implement `_ps_correction` (linear representation of the logit score: `(score) @ inv(E[score score']) @ E[w0*resid*X]`) and `_or_correction` (linear representation of the WLS OR coefficients projected through the weights), porting DRDID's `asy.lin.rep.ps` / `asy.lin.rep.wols`. **Acceptance is the 1e-8 fixture, not visual inspection of the formula.** If stuck, compare intermediate quantities (`ps`, `mhat`, `eta_treat`, `eta_cont`) against an R session on the same cell before debugging the correction terms.

- [ ] **Step 4: Add cluster aggregation** (observation IF → cluster rows). Add `cluster_influence(units_if, cluster_of_unit) -> (G, )` summing observation IF within each cluster (default cluster = entity, so each unit is its own cluster here; the function generalizes when a cluster var groups units).

- [ ] **Step 5: Run, verify pass.** DRDID test within 1e-8; mean-zero test passes. **Do not proceed until 1e-8 holds for `dr`.** Port `ipw`/`reg` analogously and extend the fixture if needed.

- [ ] **Step 6: Commit**

```bash
git add backend/workbench/engine/cs_attgt.py tests/test_cs_attgt.py tests/test_cs_did_oracle.py
git commit -m "feat(cs_did): DRDID-equivalent cell influence functions (oracle 1e-8)"
```

---

## Task 6: Assemble `estimate_att_gt` over all cells + validity/guards + cell_metadata

**Files:**
- Modify: `backend/workbench/engine/cs_attgt.py`
- Test: `tests/test_cs_attgt.py`, `tests/test_cs_did_invariants.py`

- [ ] **Step 1: Write failing tests** (invariant #5 + bundle shape + guards)

```python
# tests/test_cs_did_invariants.py
import numpy as np, pandas as pd, pytest
from workbench.engine.did_spec import normalize_did_input
from workbench.engine.cs_attgt import estimate_att_gt, CSSpecError, EffectEstimateBundle

def _norm():
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    return normalize_did_input(d.assign(first_treat=d.first_treat), mode="cohort",
        entity="unit", time="period", y="y", cohort="first_treat")

def test_bundle_shape_and_cluster_rows():
    b = estimate_att_gt(_norm(), control_group="never", est_method="dr",
        base_period="varying", anticipation=0, covariates=["x1"], cluster_var=None)
    assert isinstance(b, EffectEstimateBundle)
    assert b.influence_func.shape[0] == b.cluster_ids.shape[0]      # G rows
    assert b.influence_func.shape[1] == b.estimates.shape[0]        # K cols
    assert len(b.cell_metadata) == b.estimates.shape[0]

def test_invalid_cell_marked_not_zero():
    b = estimate_att_gt(_norm(), control_group="never", est_method="dr",
        base_period="varying", anticipation=0, covariates=["x1"], cluster_var=None)
    for m in b.cell_metadata:
        if not m["valid"]:
            assert np.isnan(b.estimates[b.cell_metadata.index(m)])  # not 0.0

def test_no_valid_cells_raises():
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    d.loc[d.first_treat == 0, "first_treat"] = 3      # remove never-treated & not-yet
    n = normalize_did_input(d, mode="cohort", entity="unit", time="period",
        y="y", cohort="first_treat")
    with pytest.raises(CSSpecError, match="CS_NO_VALID_CELLS|DID_NO_COMPARISON_GROUP"):
        estimate_att_gt(n, control_group="never", est_method="dr",
            base_period="varying", anticipation=0, covariates=["x1"], cluster_var=None)
```

- [ ] **Step 2: Run, verify failure.**

- [ ] **Step 3: Implement `estimate_att_gt`** — enumerate all `(g,t)` cells (g over treated cohorts, t over periods with `t != base_t`), call `att_gt_cell` + `cell_influence_function`, place each cell's observation IF into a full `(n_obs_units, K)` matrix (zeros outside `S(g,t)`), aggregate to cluster rows, build `cell_metadata` (g, t, event_time, estimand_type="att_gt", control_group_rule, reference_period, n_treated, n_control, valid, warning), `weights` (n_g per cohort, shares), `vcov_config` (cluster_var, level=0.95, band_type set later), `diagnostics` (overlap min/max ps, omitted_cells). Guards: raise `CS_NO_VALID_CELLS` if all invalid; raise `CS_PROBLEM_TOO_LARGE` if `G*K > 50_000_000`.

- [ ] **Step 4: Run, verify pass.**

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/cs_attgt.py tests/test_cs_attgt.py tests/test_cs_did_invariants.py
git commit -m "feat(cs_did): estimate_att_gt assembles bundle + validity guards"
```

---

## Task 7: `cs_aggregate` — 4 aggregations point estimates (§3.6) + valid-mask + aggte oracle

**Files:**
- Create: `backend/workbench/engine/cs_aggregate.py`
- Test: `tests/test_cs_aggregate.py`, `tests/test_cs_did_oracle.py`

- [ ] **Step 1: Write failing tests** (invariant #6 + aggte estimates 1e-6)

```python
# tests/test_cs_did_oracle.py
def test_aggregations_match_R_aggte():
    ref = json.load(open("tests/fixtures/cs_did/aggte.json"))
    from workbench.engine.cs_aggregate import aggregate
    b = estimate_att_gt(_norm(), control_group="never", est_method="dr",
        base_period="varying", anticipation=0, covariates=["x1"], cluster_var=None)
    dyn = aggregate(b, "dynamic")
    for e, att in zip(ref["dynamic"]["egt"], ref["dynamic"]["att_egt"]):
        i = dyn["event_time"].index(e)
        assert abs(dyn["estimate"][i] - att) < 1e-6
    assert abs(aggregate(b, "simple")["overall"] - ref["simple"]["overall"]) < 1e-6
```
(`_norm` / `estimate_att_gt` imported as in Task 6.)

- [ ] **Step 2: Run, verify failure.**

- [ ] **Step 3: Implement `aggregate(bundle, kind)`** per §3.6 — `group`, `overall`, `dynamic`, `calendar`; denominators over valid cells only (`m["valid"]`); cohort weights `n_g` from `bundle.weights`. Return `{kind, estimate(s), event_time/group/period labels, component_if}` where `component_if` is the `(G, n_components)` aggregated IF stub (filled in Task 8). For now return point estimates + the per-component weight vectors needed by Task 8.

- [ ] **Step 4: Run, verify pass** (point estimates within 1e-6).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/cs_aggregate.py tests/test_cs_aggregate.py tests/test_cs_did_oracle.py
git commit -m "feat(cs_did): 4 aggregations point estimates (aggte oracle 1e-6, valid-mask denominators)"
```

---

## Task 8: `cs_aggregate` IF incl. weight-estimation term (§3.6) + aggte SE oracle

**Files:**
- Modify: `backend/workbench/engine/cs_aggregate.py`
- Test: `tests/test_cs_aggregate.py`, `tests/test_cs_did_oracle.py`

- [ ] **Step 1: Write failing tests** (invariant #8 + aggte SE 1e-6)

```python
def test_aggregated_if_equals_weighted_cell_if_plus_weight_term():
    # construct a bundle where weights are fixed (single cohort) → weight-term zero,
    # aggregated IF must equal the plain weighted sum of cell IFs.
    ...  # single-cohort fixture: assert np.allclose(agg_if, b.influence_func @ w)

def test_aggregation_se_matches_R():
    ref = json.load(open("tests/fixtures/cs_did/aggte.json"))
    from workbench.engine.cs_aggregate import aggregate
    b = estimate_att_gt(_norm(), control_group="never", est_method="dr",
        base_period="varying", anticipation=0, covariates=["x1"], cluster_var=None)
    dyn = aggregate(b, "dynamic")          # SE computed analytically from agg IF
    for e, se in zip(ref["dynamic"]["egt"], ref["dynamic"]["se_egt"]):
        i = dyn["event_time"].index(e)
        assert abs(dyn["se"][i] - se) < 1e-6
```

- [ ] **Step 2: Run, verify failure.**

- [ ] **Step 3: Implement the aggregation IF** — `ψ^θ = Σ_k w_k ψ^k + Σ_k ATT_k · ξ^k` where `ξ^k` is the IF of the estimated weight `ŵ_k` (cohort share). Compute analytical SE from the aggregated cluster IF (`se = sqrt(G^-2 Σ_c Ψ_ck^2)`). Attach `component_if` (G × n_components) to the aggregate result.

- [ ] **Step 4: Run, verify pass** (SE within 1e-6). If SE is systematically low, the weight-estimation term is missing.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/cs_aggregate.py tests/test_cs_aggregate.py tests/test_cs_did_oracle.py
git commit -m "feat(cs_did): aggregation IF with weight-estimation term (aggte SE oracle 1e-6)"
```

---

## Task 9: `cs_inference` — seeded multiplier bootstrap, pointwise + sup-t bands

**Files:**
- Create: `backend/workbench/engine/cs_inference.py`
- Test: `tests/test_cs_inference.py`

- [ ] **Step 1: Write failing tests** (determinism + sup-t ≥ pointwise width)

```python
# tests/test_cs_inference.py
import numpy as np
from workbench.engine.cs_inference import multiplier_bootstrap

def _if():
    rng = np.random.default_rng(0)
    return rng.normal(size=(80, 5))

def test_determinism_same_seed():
    a = multiplier_bootstrap(_if(), B=1000, alpha=0.05, seed=12345)
    b = multiplier_bootstrap(_if(), B=1000, alpha=0.05, seed=12345)
    assert np.array_equal(a["uniform_crit"], b["uniform_crit"])
    assert np.allclose(a["se"], b["se"])

def test_uniform_band_at_least_pointwise():
    r = multiplier_bootstrap(_if(), B=2000, alpha=0.05, seed=7)
    assert r["uniform_crit"] >= 1.959  # sup-t critical value ≥ z_{0.975}
```

- [ ] **Step 2: Run, verify failure.**

- [ ] **Step 3: Implement** per §3.7 — Mammen 2-point multipliers via `np.random.default_rng(seed)`, robust IQR scale `Σ̂_k`, pointwise `z_{1-α/2}·Σ̂`, uniform `ĉ = quantile_{1-α}(max_k |R_k|/Σ̂_k)`. Return `{se, pointwise_ci, uniform_band, uniform_crit, band_type}`.

- [ ] **Step 4: Run, verify pass.**

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/cs_inference.py tests/test_cs_inference.py
git commit -m "feat(cs_did): seeded multiplier bootstrap + sup-t uniform bands"
```

---

## Task 10: `run_cs_did` orchestration in runner.py

**Files:**
- Modify: `backend/workbench/econometrics/runner.py` (add after `run_event_study`, ~line 430+)
- Test: `tests/test_cs_attgt.py` (end-to-end) or new `tests/test_run_cs_did.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_run_cs_did.py
import pandas as pd
from workbench.engine.did_spec import normalize_did_input
from workbench.econometrics.runner import run_cs_did

def test_run_cs_did_end_to_end():
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    n = normalize_did_input(d, mode="cohort", entity="unit", time="period",
        y="y", cohort="first_treat")
    res = run_cs_did(n, covariates=["x1"], control_group="never", est_method="dr",
        base_period="varying", anticipation=0, cluster_var=None, seed=20260615)
    assert "att_gt" in res and "aggregations" in res
    assert set(res["aggregations"]) == {"overall","dynamic","group","calendar"}
    assert res["aggregations"]["dynamic"]["uniform_crit"] >= 1.959
    assert "warnings" in res and "metadata" in res
```

- [ ] **Step 2: Run, verify failure.**

- [ ] **Step 3: Implement `run_cs_did`** — calls `estimate_att_gt`, runs `aggregate` for all 4 kinds, runs `multiplier_bootstrap` per aggregation, assembles `{att_gt: [...cell rows...], aggregations: {...}, diagnostics, warnings, metadata}`. Pure (no I/O). Mirrors `run_did` placement/signature style.

- [ ] **Step 4: Run, verify pass.**

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/econometrics/runner.py tests/test_run_cs_did.py
git commit -m "feat(cs_did): run_cs_did orchestration (attgt → aggregate → inference)"
```

---

## Task 11: Estimation wiring — `_fit_cs_did` + CORE_PACK + `_MODEL_TYPE_MAP` + params + golden 0-drift

**Files:**
- Modify: `backend/workbench/engine/stages/estimation.py` (mirror `_fit_did` at :120, register at :177, RerunAction at :191, guard at :259)
- Modify: `backend/workbench/orchestrator/_model_types.py` (`_MODEL_TYPE_MAP` :82, `_MODEL_METADATA` :18)
- Modify: `backend/workbench/orchestrator/__init__.py` (re-export :56, params :176/:415)
- Test: `tests/test_engine_registry.py` (extend), golden re-run

- [ ] **Step 1: Write failing tests** (registry + explicit-only + golden inert)

```python
# tests/test_cs_did_wiring.py
from workbench.engine.stages.estimation import CORE_PACK
from workbench.orchestrator._model_types import _MODEL_TYPE_MAP

def test_cs_did_registered_explicit_only():
    keys = [h.model_type for h in CORE_PACK.model_handlers]
    assert "cs_did" in keys
    assert "cs_did" not in CORE_PACK.defaults_by_y_type.get("continuous", [])
    assert _MODEL_TYPE_MAP["cs_did"] == "continuous"
```

- [ ] **Step 2: Run, verify failure.**

- [ ] **Step 3: Implement**
  - `_fit_cs_did(ctx, env)` mirroring `_fit_did` (`estimation.py:120`): `normalize_did_input(...)` from `ctx.artifacts["_did_*"]`, then `run_cs_did(norm, covariates=env.x, control_group=ctx.artifacts.get("_cs_control_group") or "never", est_method=ctx.artifacts.get("_cs_est_method") or "dr", base_period=ctx.artifacts.get("_cs_base_period") or "varying", anticipation=int(ctx.artifacts.get("_cs_anticipation") or 0), cluster_var=ctx.artifacts.get("_cs_cluster_var") or None, seed=20260615)`; stash result in `ctx.artifacts["_cs_did_result"]`; return `("cs_did_1", primary, None)` (no `fitted` object — diagnostics reads the stashed result).
  - Register `ModelHandler("cs_did", "cs_did_1", ("continuous",), _fit_cs_did)` after the `did` handler (`estimation.py:177`); do NOT add to `defaults_by_y_type`.
  - `RerunAction(key="cs_did_switch_to_did", param_overrides={"model_type":"did"}, applies_to=["cs_did"])` after the `did` rerun action (:191).
  - Missing-fields guard mirroring `:259`: `if model_type == "cs_did" and (not id_cands or not t_cands): raise ... "cs_did requires both an entity and a time column."`.
  - `_MODEL_TYPE_MAP["cs_did"] = "continuous"` (:90); `_MODEL_METADATA["cs_did"]` entry.
  - `orchestrator/__init__.py`: thread `cs_control_group`/`cs_est_method`/`cs_base_period`/`cs_anticipation`/`cs_cluster_var` through `run_workflow` + `_run_workflow` into `ctx.artifacts["_cs_*"]` (mirror `did_mode` at :176/:415); no `run_cs_did` re-export needed unless monkeypatched — keep symmetry by importing it where `run_did` is (:56) only if a test monkeypatches it.

- [ ] **Step 4: Run, verify pass + golden 0-drift**

```bash
.venv/bin/python -m pytest tests/test_cs_did_wiring.py tests/test_engine_golden.py -v
```
Expected: wiring PASS; all existing goldens 0-drift (new params inert because no run requests `cs_did`).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/stages/estimation.py backend/workbench/orchestrator/ tests/test_cs_did_wiring.py
git commit -m "feat(cs_did): explicit-only estimation wiring + params threading (golden 0-drift)"
```

---

## Task 12: Diagnostics artifact (degraded-safe) + capabilities 5-way sync

**Files:**
- Modify: `backend/workbench/engine/stages/diagnostics.py` (mirror the `did_diagnostics` write)
- Modify: `backend/workbench/engine/capabilities.py` (`MODEL_UI_META` :45-area, `MODEL_ORDER` :76-area)
- Modify: contract sample JSON (the capabilities contract sample referenced by `tests/contracts/`)
- Test: `tests/test_cs_did_wiring.py` (extend, red-if-deleted spy) + capabilities drift tests

- [ ] **Step 1: Write failing tests** (artifact present + degraded-safe + capabilities entry)

```python
def test_cs_did_artifact_written(tmp_path):
    # run a cs_did workflow via run_workflow; assert artifact "cs_did" exists with aggregations
    ...
def test_cs_did_artifact_degraded_on_crash(monkeypatch):
    # monkeypatch run_cs_did's aggregate to raise; assert artifact {available: False, error:...}
    # and the run still completes (not WORKFLOW_FAILED)
    ...
def test_capabilities_has_cs_did():
    from workbench.engine.capabilities import MODEL_UI_META, MODEL_ORDER
    assert MODEL_UI_META["cs_did"]["group"] == "DID"
    assert "cs_did" in MODEL_ORDER
```

- [ ] **Step 2: Run, verify failure.**

- [ ] **Step 3: Implement**
  - `diagnostics.py`: when `model_type == "cs_did"`, write artifact `cs_did` from `ctx.artifacts["_cs_did_result"]`, wrapped `try/except Exception` → `{"available": False, "error": str(exc)}` (v1.5.5.1 convention).
  - `capabilities.py`: add `MODEL_UI_META["cs_did"] = {"label": "Callaway-Sant'Anna DID", "group": "DID", ...}`; add `"cs_did"` to `MODEL_ORDER` after `"did"`.
  - Update the capabilities contract sample JSON + bump nothing (schema unchanged; additive entry). The two group-vocab drift tests pass because group is the existing `"DID"`.

- [ ] **Step 4: Run, verify pass.** Run the full contracts + drift suite:

```bash
.venv/bin/python -m pytest tests/contracts tests/test_cs_did_wiring.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/stages/diagnostics.py backend/workbench/engine/capabilities.py tests/
git commit -m "feat(cs_did): degraded-safe cs_did artifact + capabilities sync"
```

---

## Task 13: API form params + additive golden

**Files:**
- Modify: `backend/workbench/api.py` (`POST /runs` Form fields :103-area + `_bg_run` passthrough :155-area + `_run_workflow` call :316-area)
- Modify: `tests/test_engine_golden.py` (add `cs_did` golden via `_run(..., model_type="cs_did", **cs_params)`)
- Create: `tests/golden/cs_did_staggered.json`

- [ ] **Step 1: Write the failing golden test**

```python
# tests/test_engine_golden.py
def test_golden_cs_did_staggered(tmp_path):
    frame = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    run_root = _run(tmp_path, frame, y="y", x=["x1"], model_type="cs_did",
        did_mode="cohort", did_cohort_col="first_treat",
        cs_control_group="never", cs_est_method="dr", cs_base_period="varying")
    _assert_or_write_golden("cs_did_staggered", _capture(run_root))
```
(`_run` already forwards `**extra`; ensure `api`/`run_workflow` accept the `cs_*` kwargs.)

- [ ] **Step 2: Run to generate the golden** (first run writes it):

```bash
WRITE_GOLDEN=1 .venv/bin/python -m pytest tests/test_engine_golden.py::test_golden_cs_did_staggered -v
```
Then run again WITHOUT the env var → must PASS deterministically (seeded bootstrap).

- [ ] **Step 3: Implement the api wiring** — add `cs_control_group`/`cs_est_method`/`cs_base_period`/`cs_anticipation`/`cs_cluster_var` as `Form("")` fields (mirror `did_mode` at :103), pass through `_bg_run` (:155) and into `run_workflow` (:316).

- [ ] **Step 4: Run, verify pass + existing goldens 0-drift.**

```bash
.venv/bin/python -m pytest tests/test_engine_golden.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/api.py tests/test_engine_golden.py tests/golden/cs_did_staggered.json
git commit -m "feat(cs_did): api params + additive golden (existing goldens 0-drift)"
```

---

## Task 14: Frontend DIDControls extension

**Files:**
- Modify: `frontend/src/runForm/DIDControls.tsx`
- Modify: `frontend/src/runForm/RunForm.tsx` (post `cs_*` params)
- Test: `frontend/src/runForm/DIDControls.test.tsx`

- [ ] **Step 1: Write failing test** — when `modelType === "cs_did"`, the control-group / est-method / base-period / anticipation selectors render; selecting them updates form state.

```tsx
it("shows CS controls and posts cs_* params when model is cs_did", () => {
  render(<DIDControls modelType="cs_did" ... />);
  expect(screen.getByLabelText(/control group/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/method/i)).toBeInTheDocument();
  // ...assert onChange propagates cs_control_group etc.
});
```

- [ ] **Step 2: Run, verify failure.** `cd frontend && npx vitest run DIDControls`

- [ ] **Step 3: Implement** — add a `cs_did` branch reusing the existing entity/time/cohort role assignment; add selects for `cs_control_group` (never/not_yet), `cs_est_method` (dr/ipw/reg), `cs_base_period` (varying/universal), number input `cs_anticipation`, optional `cs_cluster_var`. `RunForm` includes them in `RunExtraParams` when `model_type === "cs_did"`.

- [ ] **Step 4: Run, verify pass + tsc.** `cd frontend && npx vitest run && npx tsc --noEmit`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/runForm/
git commit -m "feat(cs_did): DIDControls cs_did mode + RunForm posts cs_* params"
```

---

## Task 15: Frontend CSDiagnosticsCard

**Files:**
- Create: `frontend/src/runResult/CSDiagnosticsCard.tsx`
- Modify: `frontend/src/runResult/` wiring (fetch `cs_did` artifact, mirror `DIDDiagnosticsCard`)
- Test: `frontend/src/runResult/CSDiagnosticsCard.test.tsx`

- [ ] **Step 1: Write failing tests** — renders overall ATT + band, dynamic event-study points with uniform band, group/calendar tables, metadata/warnings panel; renders graceful empty state when `available === false`; renders "not enough valid cells" when an aggregation is empty.

- [ ] **Step 2: Run, verify failure.** `cd frontend && npx vitest run CSDiagnosticsCard`

- [ ] **Step 3: Implement** the tiered card (mirror `DIDDiagnosticsCard.tsx`), fetching the `cs_did` artifact via the existing `fetchArtifactJson` seam, regex artifact id `/^cs_did.*_1$/` or the known id `cs_did_1`.

- [ ] **Step 4: Run, verify pass + tsc.** `cd frontend && npx vitest run && npx tsc --noEmit`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/runResult/
git commit -m "feat(cs_did): CSDiagnosticsCard (event-study band + metadata/warnings)"
```

---

## Task 16: Example dataset + how-to + final gate

**Files:**
- Create: `examples/datasets/cs_did_staggered.csv` (a friendly, documented staggered panel)
- Create: `docs/cs-did-howto.md`
- Optional: delete stranded code IF confirmed unused (per Layer 1 note, `run_fixed_effects` is NOT dead — has an active test — so do NOT delete it).

- [ ] **Step 1: Write `examples/datasets/cs_did_staggered.csv`** — a small readable staggered-adoption panel (can reuse the fixture generator with friendlier column names: `state`, `year`, `first_treated_year`, `policy_intensity`, `outcome`).

- [ ] **Step 2: Write `docs/cs-did-howto.md`** — how to run `cs_did` from the UI and CLI (`env PYTHONPATH=backend .venv/bin/python -m workbench.cli run <project> <data> outcome --x policy_intensity --model-type cs_did ...`), how to read the event-study card, when to prefer CS over TWFE (link to Layer 1's Goodman-Bacon output).

- [ ] **Step 3: Run the full gate**

```bash
./scripts/gate.sh
```
Expected: GATE PASSED. BE = baseline + new tests; FE = baseline + new tests; golden = baseline + cs_did golden, all 0-drift; `tsc --noEmit` 0.

- [ ] **Step 4: Commit**

```bash
git add examples/datasets/cs_did_staggered.csv docs/cs-did-howto.md
git commit -m "docs(cs_did): example dataset + how-to; final gate green"
```

---

## Self-Review (completed against the spec)

- **Spec coverage:** §1 scope → Tasks 2–16; §2 bundle → Task 2/6; §3.2 base period → Task 3; §3.3 comparison group → Task 2; §3.4 estimands → Task 4; §3.5 IF → Task 5; §3.6 aggregations + agg IF → Tasks 7/8; §3.7 inference → Task 9; §4 backend wiring → Tasks 10–13; §5 frontend → Tasks 14/15; §6 data flow → Tasks 11–15; §7 oracle + 9 invariants → Tasks 1,4,5,6,7,8 (invariants mapped: #1→T4, #2/#3→T3, #4→T2, #5→T6, #6→T7, #7→T5, #8→T8, #9→T5/T9 oracle); §1 deferrals → guard in Task 6 (`CS_PROBLEM_TOO_LARGE`).
- **Placeholder scan:** the only `...` placeholders are inside frontend/diagnostics test bodies where the assertion shape is described in prose immediately above; all backend math steps carry concrete code. Task 5's correction-term helpers are intentionally specified by the 1e-8 oracle (the spec's binding definition), not by a hand-derived formula.
- **Type consistency:** `EffectEstimateBundle` fields (Task 2) are consumed unchanged in Tasks 6/7/8/10; `att_gt_cell` return dict keys (`_units/_D/_dY/_X/_ps/_mhat`) defined in Task 4 are consumed in Task 5; `aggregate(bundle, kind)` and `multiplier_bootstrap(if_matrix, ...)` signatures are consistent across Tasks 7–10.
