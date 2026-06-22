# v1.5.9 de Chaisemartin–D'Haultfœuille (dCDH) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal-faithful, binary non-absorbing de Chaisemartin–D'Haultfœuille DID estimator (`model_type="dcdh"`) — first-up switchers, dynamic `effect_ℓ` + `placebo_ℓ` (primary) + overall ATT (experimental) — self-implemented and validated element-wise against R `DIDmultiplegtDYN`.

**Architecture:** dCDH breaks the `(g,t)` `EffectEstimateBundle` and introduces a new narrow cross-estimator contract `EventStudyBundle` (`engine/event_study.py`). A new treatment-path input model (`engine/dcdh_spec.py`) sits beside the cohort-based `did_spec` (untouched). The estimator (`engine/dcdh_estimator.py`) emits the bundle; `run_dcdh` reuses `multiplier_bootstrap` for sup-t bands and assembles `dcdh.json` **without** touching `_finalize_did_bundle`. honest-DID is not connected (placebos are the native pre-trend device).

**Tech Stack:** Python (NumPy/pandas/SciPy, zero new deps), R `DIDmultiplegtDYN` (oracle generation only — the suite never calls R), React/TypeScript frontend, pytest + vitest gate via `./scripts/gate.sh`.

**Spec:** `docs/superpowers/specs/2026-06-22-workbench-v1.5.9-dcdh-design.md`

**Base:** origin/main `fc22964` (tag `v1.5.8`). Worktree `.worktrees/workbench-v1.5.9` (branch `workbench-v1.5.9`).

---

## Cross-cutting rules (apply to EVERY task)

- **NEVER `git push`.** Commit locally only. Pushing main / moving tags requires separate human authorization at ship time.
- **Gate = `./scripts/gate.sh`** from the worktree root (BE full + golden 0-drift + vitest + tsc). Never bare `pytest` for the gate; per-test `pytest path::name -v` is fine while iterating.
- **golden 0-drift is a HARD gate.** CS/SA/DID goldens must not move. Anti-touch means *running* the goldens, not just diffing files (a shared helper could change without the file changing).
- **Oracle is authoritative.** Where this plan sketches estimator numerics, the committed `DIDmultiplegtDYN` oracle is the source of truth. If the sketch's numbers disagree with the oracle, the **oracle is right** — rebuild the construction to match and record the corrected recipe in `docs/v1.5.9-IMPL-NOTES.md`. (This is exactly how v1.5.8 SA went; do not trust pseudocode over the oracle.)
- Commit after each task with `git add <explicit paths>` (never `git commit -a`).
- Subagents: never pass a `model` param.

---

## File structure

**Create:**
- `tests/fixtures/dcdh/generate_oracle.R` — R oracle generator (locked DYN口径).
- `tests/fixtures/dcdh/panel_nonabsorbing.csv` + `dyn_nonabsorbing.json` — main fixture + oracle.
- `tests/fixtures/dcdh/panel_baseline1.csv` + `dyn_baseline1.json` — exclusion fixture.
- `tests/fixtures/dcdh/panel_placebo.csv` + `dyn_placebo.json` — placebo≈0 fixture.
- `backend/workbench/engine/event_study.py` — `EventStudyBundle`.
- `backend/workbench/engine/dcdh_spec.py` — `DCDHSpecError`, `normalize_treatment_path`, `TreatmentPathPanel`.
- `backend/workbench/engine/dcdh_estimator.py` — `estimate_dcdh_dynamic`, `dcdh_influence`, `estimate_dcdh`.
- `frontend/src/runForm/DCDHControls.tsx`, `frontend/src/runResult/DCDHResultCard.tsx` (+ tests).
- `tests/test_dcdh_spec.py`, `test_dcdh_estimator.py`, `test_event_study.py`, `test_run_dcdh.py`,
  `test_dcdh_qa_edge.py`, `test_dcdh_wiring.py`, `test_dcdh_oracle_metadata.py`,
  `test_dcdh_sample_accounting.py`, `test_dcdh_no_finalize_touch.py`.
- `docs/v1.5.9-IMPL-NOTES.md`, `docs/dcdh-howto.md`, `docs/v1.5.9-release-notes.md`.

**Modify:**
- `backend/workbench/econometrics/runner.py` — add `run_dcdh`.
- `backend/workbench/engine/stages/estimation.py` — `_fit_dcdh` + CORE_PACK + pre-estimation check.
- `backend/workbench/orchestrator/_model_types.py` — `dcdh` metadata + continuous.
- `backend/workbench/orchestrator/__init__.py` — thread `did_treatment_path` + re-export `run_dcdh`.
- `backend/workbench/api.py` — `did_treatment_path` Form param.
- `backend/workbench/engine/stages/diagnostics.py` — write `dcdh.json` artifact.
- `backend/workbench/engine/capabilities.py` — `dcdh` entry + UI order.
- `frontend/src/capabilities/types.ts` + contract schema/sample — 4-way sync.
- `tests/test_engine_golden.py` + `tests/golden/dcdh_nonabsorbing.json` — additive golden.

---

## Task 0: Worktree environment

**Files:** none (environment only).

- [ ] **Step 1: Build venv + frontend deps**

Run from the worktree root:
```bash
~/.local/bin/python3.11 -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -e ".[dev,panel,ml,imbalanced,imputation]"
(cd frontend && npm install --silent)
```

- [ ] **Step 2: Install the R oracle dependency (once)**

```bash
Rscript -e 'if (!requireNamespace("DIDmultiplegtDYN", quietly=TRUE)) install.packages("DIDmultiplegtDYN", repos="https://cloud.r-project.org")'
Rscript -e 'cat(as.character(packageVersion("DIDmultiplegtDYN")), "\n")'
```
If compilation fails, ensure `~/.R/Makevars` has `CC=clang -std=gnu17` and retry. Record the printed version — it goes into every oracle JSON's metadata (Task 1).

- [ ] **Step 3: Verify the baseline gate is green before any change**

Run: `./scripts/gate.sh`
Expected: `>>> GATE PASSED` (BE 1082 / golden 22 0-drift / FE 632 / tsc 0).

- [ ] **Step 4: Commit** (no-op if nothing tracked changed; otherwise commit env-only files if any).

---

## Task 1: R oracle + fixtures (authoritative)

**Files:**
- Create: `tests/fixtures/dcdh/generate_oracle.R`
- Create (generated): `panel_nonabsorbing.csv`/`dyn_nonabsorbing.json`, `panel_baseline1.csv`/`dyn_baseline1.json`, `panel_placebo.csv`/`dyn_placebo.json`
- Test: `tests/test_dcdh_oracle_metadata.py`

**Locked DYN口径 (write into every JSON's `metadata`):** no covariates; `effects = <L>`; `placebo = <P>`; `same_switchers = TRUE`; `cluster = "id"`; a fixed `seed`; `package_version`. Use `DIDmultiplegtDYN::did_multiplegt_dyn(df, "y", "id", "year", "d", effects=L, placebo=P, cluster="id", same_switchers=TRUE)`.

- [ ] **Step 1: Write `generate_oracle.R`**

The script builds three binary non-absorbing panels and, for each, runs `did_multiplegt_dyn`, then writes a JSON oracle. **Decode what the fitted object exposes** for per-ℓ estimates, SEs, N_switchers, and (if present) any IF/vcov — store whatever is exposed; the Python命门 test (Task 5) grades itself on what is available.

```r
#!/usr/bin/env Rscript
# Workbench v1.5.9 — DIDmultiplegtDYN JSON oracle generator.
# RUN FROM WORKTREE ROOT:  Rscript tests/fixtures/dcdh/generate_oracle.R
# The Python suite NEVER calls R; it reads the committed CSV + JSON.
# LOCKED 口径: no covariates; same_switchers=TRUE; cluster=~id; fixed effects/placebo/seed.
suppressMessages({ library(DIDmultiplegtDYN); library(jsonlite) })

L <- 3L; P <- 2L; SEED <- 909L
PKG_VERSION <- as.character(packageVersion("DIDmultiplegtDYN"))
out_dir <- "tests/fixtures/dcdh"

fit_dyn <- function(d) {
  set.seed(SEED)
  did_multiplegt_dyn(df = d, outcome = "y", group = "id", time = "year",
                     treatment = "d", effects = L, placebo = P,
                     cluster = "id", same_switchers = TRUE, graph_off = TRUE)
}

# Robustly pull the per-ℓ table out of the fitted object. DIDmultiplegtDYN stores
# results in `m$results$Effects` (matrix: Estimate, SE, ... rows "Effect_1".."Effect_L")
# and `m$results$Placebos` (rows "Placebo_1".."Placebo_P"). N (switchers) is the
# "N" / "Switchers" column when present. Inspect names() and adapt if the package
# version differs — the ORACLE shape is whatever this version emits.
extract <- function(m) {
  eff <- m$results$Effects
  plb <- m$results$Placebos
  ate <- tryCatch(as.numeric(m$results$ATE["Estimate"]), error = function(e) NA_real_)
  ate_se <- tryCatch(as.numeric(m$results$ATE["SE"]), error = function(e) NA_real_)
  to_rows <- function(tab) {
    if (is.null(tab)) return(list(estimate = numeric(0), se = numeric(0), n = numeric(0)))
    cn <- colnames(tab)
    est_c <- cn[grep("^Estimate", cn)][1]; se_c <- cn[grep("^SE", cn)][1]
    n_c <- cn[grep("^N|Switchers", cn)][1]
    list(estimate = as.numeric(tab[, est_c]),
         se = as.numeric(tab[, se_c]),
         n = if (!is.na(n_c)) as.numeric(tab[, n_c]) else rep(NA_real_, nrow(tab)))
  }
  list(effects = to_rows(eff), placebos = to_rows(plb),
       overall = list(estimate = ate, se = ate_se))
}

write_fixture <- function(d, name) {
  m <- fit_dyn(d); ex <- extract(m)
  obj <- list(
    fixture = name,
    metadata = list(effects = L, placebos = P, same_switchers = TRUE,
                    cluster = "id", seed = SEED, package_version = PKG_VERSION),
    # event_time axis: placebos are -P..-1, effects are 0..L-1 (ℓ=0 is F-1 -> F).
    effect_estimate = ex$effects$estimate, effect_se = ex$effects$se, effect_n = ex$effects$n,
    placebo_estimate = ex$placebos$estimate, placebo_se = ex$placebos$se, placebo_n = ex$placebos$n,
    overall_estimate = ex$overall$estimate, overall_se = ex$overall$se
  )
  write_json(obj, file.path(out_dir, paste0("dyn_", name, ".json")),
             digits = 16, auto_unbox = TRUE, pretty = TRUE)
  write.csv(d[, c("id", "year", "d", "y")],
            file.path(out_dir, paste0("panel_", name, ".csv")), row.names = FALSE)
  cat(sprintf("[%s] effects=%d placebos=%d\n", name, length(ex$effects$estimate),
              length(ex$placebos$estimate)))
}

# PANEL 1 — non-absorbing main: 120 units, years 1..8, baseline d=0. Half the units
# switch up 0->1 at staggered years {3,4,5}; among those, a third later switch back
# 1->0 (non-absorbing). Remaining units are not-yet/never switchers (controls).
make_nonabsorbing <- function() {
  set.seed(909); N <- 120L; Tn <- 8L; ids <- 1:N
  fy <- c(3,4,5,NA,NA)[((ids - 1) %% 5) + 1]   # first up-switch year; NA = never
  d <- expand.grid(id = ids, year = 1:Tn)
  d$fy <- fy[d$id]
  d$d <- as.integer(!is.na(d$fy) & d$year >= d$fy)
  # switch-back: units with id %% 6 == 0 turn OFF two periods after switching on
  back <- (d$id %% 6 == 0) & !is.na(d$fy) & d$year >= d$fy + 2
  d$d[back] <- 0L
  fe_id <- rnorm(N)[d$id]; fe_yr <- (1:Tn)[d$year] * 0.1
  d$y <- fe_id + fe_yr + 0.8 * d$d + rnorm(nrow(d), sd = 0.3)
  d[order(d$id, d$year), ]
}
# PANEL 2 — baseline=1 / down-switchers: some units start treated (d=1 at year 1)
# and switch 1->0; combined with baseline=0 up-switchers. Tests exclusion accounting.
make_baseline1 <- function() {
  d <- make_nonabsorbing()
  flip <- d$id %in% c(2, 7, 12, 17)            # force baseline=1 for a few units
  d$d[flip] <- ifelse(d$year[flip] <= 4, 1L, 0L)
  d[order(d$id, d$year), ]
}
# PANEL 3 — placebo≈0: same switch structure, NO treatment effect (coef 0).
make_placebo <- function() {
  d <- make_nonabsorbing()
  fe_id <- rnorm(120)[d$id]; fe_yr <- (1:8)[d$year] * 0.1
  d$y <- fe_id + fe_yr + 0.0 * d$d + rnorm(nrow(d), sd = 0.3)
  d[order(d$id, d$year), ]
}

write_fixture(make_nonabsorbing(), "nonabsorbing")
write_fixture(make_baseline1(),    "baseline1")
write_fixture(make_placebo(),      "placebo")
cat("DONE.\n")
```

- [ ] **Step 2: Generate the fixtures**

Run: `Rscript tests/fixtures/dcdh/generate_oracle.R`
Expected: three `[name] effects=3 placebos=2` lines + `DONE.` and 6 new files in `tests/fixtures/dcdh/`.
If `m$results$Effects` is structured differently in the installed version, inspect with `str(m$results)` and adjust `extract()` — the oracle's shape is whatever this package version emits (record it in `docs/v1.5.9-IMPL-NOTES.md`).

- [ ] **Step 3: Write the oracle-metadata test**

```python
# tests/test_dcdh_oracle_metadata.py
import json
from pathlib import Path
import pytest

_FIX = Path(__file__).parent / "fixtures" / "dcdh"
_REQUIRED = {"effects", "placebos", "same_switchers", "cluster", "seed", "package_version"}

@pytest.mark.parametrize("name", ["nonabsorbing", "baseline1", "placebo"])
def test_oracle_has_locked_kou_jing_metadata(name):
    o = json.loads((_FIX / f"dyn_{name}.json").read_text())
    assert "metadata" in o, f"{name} oracle missing metadata block"
    assert _REQUIRED <= set(o["metadata"]), _REQUIRED - set(o["metadata"])
    assert o["metadata"]["same_switchers"] is True
    assert o["metadata"]["cluster"] == "id"
```

- [ ] **Step 4: Run the test**

Run: `.venv/bin/python -m pytest tests/test_dcdh_oracle_metadata.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/dcdh/ tests/test_dcdh_oracle_metadata.py
git commit -m "test(dcdh): DIDmultiplegtDYN oracle generator + fixtures + metadata gate"
```

---

## Task 2: `EventStudyBundle` contract

**Files:**
- Create: `backend/workbench/engine/event_study.py`
- Test: `tests/test_event_study.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_event_study.py
import numpy as np
from workbench.engine.event_study import EventStudyBundle
from workbench.engine.cs_inference import multiplier_bootstrap

def _bundle():
    N, L = 50, 4
    rng = np.random.default_rng(0)
    return EventStudyBundle(
        estimates=np.arange(L, dtype=float),
        influence_func=rng.standard_normal((N, L)),
        event_times=np.array([-2.0, -1.0, 0.0, 1.0]),
        cluster_ids=np.arange(N),
        n_switchers=np.array([10, 12, 14, 14]),
        aux={"n_total": N, "row_cluster": np.arange(N)},
    )

def test_event_times_is_sole_axis_and_labels_are_derived():
    b = _bundle()
    assert b.labels == ["placebo", "placebo", "effect", "effect"]
    # labels is a derived property, not a stored field
    assert "labels" not in b.__dataclass_fields__

def test_multiplier_bootstrap_consumes_raw_arrays_not_the_bundle_type():
    b = _bundle()
    # MUST pass arrays — multiplier_bootstrap must not depend on EventStudyBundle.
    out = multiplier_bootstrap(b.influence_func, B=200, alpha=0.05, seed=1,
                               estimates=b.estimates, clusters=b.aux["row_cluster"])
    assert out["uniform_band"].shape == (4, 2)
    assert "uniform_crit" in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_event_study.py -v`
Expected: FAIL (`ModuleNotFoundError: workbench.engine.event_study`).

- [ ] **Step 3: Implement `event_study.py`**

```python
"""Narrow cross-estimator event-study contract.

EventStudyBundle is the seam consumed by sup-t band inference (and, later, any
estimator that produces a dynamic event study directly — dCDH today; CS/SA could
promote their internal dynamic IF onto this seam in the future). event_times is the
SOLE primary axis; labels is a derived display-only field.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class EventStudyBundle:
    estimates: np.ndarray        # (L,) aligned to event_times
    influence_func: np.ndarray   # (N, L) entity rows, mean-zero columns, N-scaled
    event_times: np.ndarray      # (L,) SOLE primary axis; <0 = placebo, >=0 = effect
    cluster_ids: np.ndarray      # (n_clusters,) descriptive
    n_switchers: np.ndarray      # (L,) per-event-time switcher count
    aux: dict = field(default_factory=dict)         # {"n_total": N, "row_cluster": (N,)}
    diagnostics: dict = field(default_factory=dict)

    @property
    def labels(self) -> list[str]:
        return ["placebo" if e < 0 else "effect" for e in self.event_times]
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_event_study.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/event_study.py tests/test_event_study.py
git commit -m "feat(dcdh): EventStudyBundle narrow cross-estimator contract"
```

---

## Task 3: `dcdh_spec.py` — treatment-path input model

**Files:**
- Create: `backend/workbench/engine/dcdh_spec.py`
- Test: `tests/test_dcdh_spec.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dcdh_spec.py
import numpy as np, pandas as pd, pytest
from workbench.engine.dcdh_spec import (
    normalize_treatment_path, TreatmentPathPanel, DCDHSpecError)

def _panel(rows):
    return pd.DataFrame(rows, columns=["id", "year", "d", "y"])

def _up_switcher_panel():
    rows = []
    for i in range(6):                    # 6 units, baseline d=0, switch up at year 3
        for yr in range(1, 6):
            rows.append([i, yr, int(yr >= 3), float(i + yr)])
    for i in range(6, 10):                # 4 never-switchers (controls)
        for yr in range(1, 6):
            rows.append([i, yr, 0, float(i + yr)])
    return _panel(rows)

def test_normalize_returns_panel_with_derived_columns():
    p = normalize_treatment_path(_up_switcher_panel(), entity="id", time="year", y="y", treatment="d")
    assert isinstance(p, TreatmentPathPanel)
    f = p.frame
    for col in ("_dcdh_D", "_dcdh_baseline", "_dcdh_first_switch",
                "_dcdh_first_switch_direction", "_dcdh_event_time"):
        assert col in f.columns
    # eligible up-switcher (id 0): first switch year 3, direction up, event_time filled
    u0 = f[f["id"] == 0].sort_values("year")
    assert u0["_dcdh_baseline"].iloc[0] == 0
    assert u0["_dcdh_first_switch"].iloc[0] == 3
    assert u0["_dcdh_first_switch_direction"].iloc[0] == "up"
    assert list(u0["_dcdh_event_time"]) == [-2, -1, 0, 1, 2]
    # never-switcher (id 6): direction none, event_time NaN
    u6 = f[f["id"] == 6]
    assert (u6["_dcdh_first_switch_direction"] == "none").all()
    assert u6["_dcdh_event_time"].isna().all()

def test_baseline1_down_switcher_excluded_with_reason():
    rows = []
    for yr in range(1, 6):                # baseline=1 unit that switches 1->0
        rows.append([0, yr, int(yr <= 2), 1.0])
    for i in range(1, 5):                 # eligible up-switchers so the sample isn't empty
        for yr in range(1, 6):
            rows.append([i, yr, int(yr >= 3), float(i + yr)])
    p = normalize_treatment_path(_panel(rows), entity="id", time="year", y="y", treatment="d")
    assert 0 in p.excluded_units                      # baseline=1 excluded
    assert p.frame.loc[p.frame["id"] == 0, "_dcdh_event_time"].isna().all()

def test_non_binary_raises():
    rows = [[0, yr, 2 * int(yr >= 3), 1.0] for yr in range(1, 6)]
    with pytest.raises(DCDHSpecError, match="DCDH_NON_BINARY_TREATMENT"):
        normalize_treatment_path(_panel(rows), entity="id", time="year", y="y", treatment="d")

def test_no_switchers_raises():
    rows = [[i, yr, 0, 1.0] for i in range(4) for yr in range(1, 4)]
    with pytest.raises(DCDHSpecError, match="DCDH_NO_SWITCHERS"):
        normalize_treatment_path(_panel(rows), entity="id", time="year", y="y", treatment="d")

def test_no_eligible_up_switchers_raises():
    # switchers exist but all are baseline=1 down-switchers
    rows = [[i, yr, int(yr <= 2), 1.0] for i in range(4) for yr in range(1, 5)]
    with pytest.raises(DCDHSpecError, match="DCDH_NO_ELIGIBLE_UP_SWITCHERS"):
        normalize_treatment_path(_panel(rows), entity="id", time="year", y="y", treatment="d")

def test_too_few_periods_raises():
    rows = [[i, 1, 0, 1.0] for i in range(4)]
    with pytest.raises(DCDHSpecError, match="DCDH_TOO_FEW_PERIODS"):
        normalize_treatment_path(_panel(rows), entity="id", time="year", y="y", treatment="d")

def test_duplicate_obs_raises():
    rows = [[0, 1, 0, 1.0], [0, 1, 1, 2.0], [0, 2, 1, 3.0]]
    with pytest.raises(DCDHSpecError, match="DCDH_DUPLICATE_OBS"):
        normalize_treatment_path(_panel(rows), entity="id", time="year", y="y", treatment="d")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_dcdh_spec.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `dcdh_spec.py`**

```python
"""dCDH treatment-path input model (binary non-absorbing).

did_spec is cohort/absorbing-only (even its `status` mode raises DID_NON_ABSORBING),
so dCDH needs its own normalizer. did_spec stays untouched. v1.5.9 analysis sample =
baseline=0 units whose FIRST switch is 0->1 ("first-up switchers"); baseline=1 units
are excluded from both treatment and control with a recorded reason.
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
    baseline = {}; first_switch = {}; direction = {}
    any_switch = False
    for ent, grp in out.groupby(entity):
        g = grp.assign(_t=pd.to_numeric(grp[time], errors="coerce")).sort_values("_t")
        dd = g["_dcdh_D"].to_numpy()
        tt = g["_t"].to_numpy()
        baseline[ent] = int(dd[0])
        diff = np.diff(dd)
        idx = np.flatnonzero(diff != 0)
        if idx.size == 0:
            first_switch[ent] = np.nan; direction[ent] = "none"
        else:
            any_switch = True
            j = idx[0]
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

    excluded_units = sorted(e for e in baseline if baseline[e] == 1)
    summary = {"entity": entity, "time": time, "treatment": treatment,
               "n_eligible_switchers": len(eligible),
               "n_excluded_baseline1": len(excluded_units)}
    return TreatmentPathPanel(frame=out, entity=entity, time=time, y=y,
                              treatment=treatment, excluded_units=excluded_units,
                              summary=summary)
```

> NOTE: `DCDH_IRREGULAR_TIME` validation is deferred to the estimator (Task 4) where the consecutive-grid requirement is actually consumed; add it there if the long-difference construction needs it. Keep this module focused on path classification.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_dcdh_spec.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/dcdh_spec.py tests/test_dcdh_spec.py
git commit -m "feat(dcdh): treatment-path input model + DCDH_* validations"
```

---

## Task 4: `estimate_dcdh_dynamic` — point estimates vs DYN (oracle-authoritative)

**Files:**
- Create: `backend/workbench/engine/dcdh_estimator.py`
- Test: `tests/test_dcdh_estimator.py` (point-estimate portion)

> **This is the research-grade core. The committed `dyn_*.json` is authoritative.** The construction below is a long-difference sketch; if its numbers disagree with the oracle, rebuild it to match the oracle and document the corrected recipe in `docs/v1.5.9-IMPL-NOTES.md`. Hard contracts that must hold regardless: (1) `ℓ=0` is the `F-1 -> F` long difference; (2) per-`(F, ℓ)` control set = baseline=0, not-yet-up-switched before `F-1+ℓ`, observed at both reference and target period; (3) event axis = placebos at negative ℓ, effects at ℓ>=0.

- [ ] **Step 1: Write the failing test (point estimates vs oracle)**

```python
# tests/test_dcdh_estimator.py
import json
from pathlib import Path
import numpy as np, pandas as pd, pytest
from workbench.engine.dcdh_spec import normalize_treatment_path
from workbench.engine.dcdh_estimator import estimate_dcdh_dynamic

_FIX = Path(__file__).parent / "fixtures" / "dcdh"

def _norm(name):
    d = pd.read_csv(_FIX / f"panel_{name}.csv")
    return normalize_treatment_path(d, entity="id", time="year", y="y", treatment="d")

def _oracle(name):
    return json.loads((_FIX / f"dyn_{name}.json").read_text())

def test_effect_point_estimates_match_dyn_nonabsorbing():
    o = _oracle("nonabsorbing")
    res = estimate_dcdh_dynamic(_norm("nonabsorbing"))
    # res["effect"][ℓ] aligned to event_time 0..L-1 == oracle effect_estimate order
    got = list(res["effect_estimate"])
    want = list(o["effect_estimate"])
    assert len(got) == len(want)
    for ell, (a, b) in enumerate(zip(got, want)):
        assert abs(a - b) < 1e-6, (ell, a, b)

def test_placebo_point_estimates_match_dyn_nonabsorbing():
    o = _oracle("nonabsorbing")
    res = estimate_dcdh_dynamic(_norm("nonabsorbing"))
    for j, (a, b) in enumerate(zip(res["placebo_estimate"], o["placebo_estimate"])):
        assert abs(a - b) < 1e-6, (j, a, b)

def test_ell0_is_F_minus_1_to_F_definition():
    # The first effect (ℓ=0) corresponds to the period OF the first up-switch
    # relative to the period before it; assert it aligns to oracle Effect_1.
    o = _oracle("nonabsorbing")
    res = estimate_dcdh_dynamic(_norm("nonabsorbing"))
    assert abs(res["effect_estimate"][0] - o["effect_estimate"][0]) < 1e-6

def test_risk_set_recorded_per_ell():
    res = estimate_dcdh_dynamic(_norm("nonabsorbing"))
    rs = res["risk_set_by_ell"]
    assert all({"ell", "n_switchers", "n_controls"} <= set(r) for r in rs)
    assert all(r["n_switchers"] > 0 for r in rs)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dcdh_estimator.py -k "point or ell0 or risk_set" -v`
Expected: FAIL (`ModuleNotFoundError` / not implemented).

- [ ] **Step 3: Implement `estimate_dcdh_dynamic`**

Implement the long-difference DID_ℓ on the `TreatmentPathPanel`:
- For each first-up-switch time `F` (from `_dcdh_first_switch` of eligible units) and each horizon `ℓ` in `0..L-1`: switchers' `ΔY = Y_{F-1+ℓ} - Y_{F-1}` vs the same calendar-time `ΔY` of the per-`(F, ℓ)` control set (baseline=0, not yet up-switched by `F-1+ℓ`, observed at both `F-1` and `F-1+ℓ`); aggregate across `F` weighted by switcher counts → `effect_estimate[ℓ]`.
- Placebos: symmetric pre-period long differences `Y_{F-1-j} - Y_{F-1}` for `j` in `1..P` → `placebo_estimate[j-1]`.
- Record `risk_set_by_ell = [{"ell": ℓ, "n_switchers": …, "n_controls": …, "dropped_reason": …}, …]`.
- Return a dict: `{"effect_estimate": [...], "placebo_estimate": [...], "event_time": [...], "risk_set_by_ell": [...], "_internals": {...for IF in Task 5...}}`.

Write the actual NumPy implementation here. **Validate against the oracle as you go**; when a number is off, the oracle wins — adjust the construction (common gotchas: ℓ indexing off-by-one vs DYN's 1-based `Effect_1`; whether `same_switchers=TRUE` restricts the switcher set to those observed at all horizons; control-set "not yet switched" boundary at `F-1+ℓ` vs `F+ℓ`). Record the validated recipe in `docs/v1.5.9-IMPL-NOTES.md`.

- [ ] **Step 4: Run to verify point estimates pass**

Run: `.venv/bin/python -m pytest tests/test_dcdh_estimator.py -k "point or ell0 or risk_set" -v`
Expected: PASS (≤1e-6 vs oracle). If alignment requires a recipe change, update `_IMPL-NOTES` and re-run.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/dcdh_estimator.py tests/test_dcdh_estimator.py docs/v1.5.9-IMPL-NOTES.md
git commit -m "feat(dcdh): long-difference DID_l point estimates (oracle-validated)"
```

---

## Task 5: `dcdh_influence` — analytic IF / per-ℓ SE (命门, graded)

**Files:**
- Modify: `backend/workbench/engine/dcdh_estimator.py`
- Test: `tests/test_dcdh_estimator.py` (SE portion)

> **Graded oracle branch (decide which applies after Step 1 inspects the oracle):**
> - **If `dyn_*.json` carries per-ℓ SE** (it does, via `effect_se`): the IF must reconstruct those SEs. Target tol: tight/near-tight (start 1e-6; if the DYN variance estimator has a small-sample correction this implementation doesn't mirror exactly, relax to 1e-4 and DOCUMENT the residual口径 difference — do NOT claim "IF matches DYN internals").
> - **If a future version exposes DYN's IF/vcov:** add a direct IF/vcov alignment test then. Not required now.

- [ ] **Step 1: Write the failing test (per-ℓ SE reconstruction)**

```python
# append to tests/test_dcdh_estimator.py
from workbench.engine.dcdh_estimator import dcdh_influence
from workbench.engine.cs_aggregate import _se

def test_if_reconstructs_dyn_per_ell_se_nonabsorbing():
    o = _oracle("nonabsorbing")
    res = estimate_dcdh_dynamic(_norm("nonabsorbing"))
    IF, row_cluster, N = dcdh_influence(res)        # (N, L_total), (N,), int
    L_eff = len(o["effect_estimate"])
    # effect columns are the LAST L_eff columns (placebos first, then effects),
    # matching event_time ordering. Reconstruct each effect SE from its IF column.
    for ell in range(L_eff):
        col = IF[:, -L_eff + ell]
        se = _se(col, row_cluster, N)
        want = o["effect_se"][ell]
        assert abs(se - want) < 1e-4, (ell, se, want)   # graded tol; see notes

def test_if_columns_mean_zero():
    res = estimate_dcdh_dynamic(_norm("nonabsorbing"))
    IF, _, _ = dcdh_influence(res)
    assert np.max(np.abs(IF.sum(axis=0))) < 1e-6
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dcdh_estimator.py -k "reconstructs or mean_zero" -v`
Expected: FAIL.

- [ ] **Step 3: Implement `dcdh_influence`**

Implement the analytic influence function for each ℓ (switcher contribution + control contribution), N-scaled so `_se(col, row_cluster, N)` reproduces the oracle per-ℓ SE. `dcdh_influence(res)` returns `(IF (N_all, L_total), row_cluster (N_all,), N_all)` with never/excluded rows = 0. **Oracle-authoritative**: align the scale to the committed `effect_se`; if the DYN SE口径 has a correction this can't mirror exactly, settle at the documented graded tol and record it in `docs/v1.5.9-IMPL-NOTES.md`. Do not claim the IF equals DYN's internal IF unless the oracle exposes it.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_dcdh_estimator.py -v`
Expected: all PASS (SE within the documented graded tol).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/dcdh_estimator.py tests/test_dcdh_estimator.py docs/v1.5.9-IMPL-NOTES.md
git commit -m "feat(dcdh): analytic influence function reconstructing DYN per-l SE"
```

---

## Task 6: `estimate_dcdh` → `EventStudyBundle` (assembly + clustering + sample accounting)

**Files:**
- Modify: `backend/workbench/engine/dcdh_estimator.py`
- Test: `tests/test_dcdh_estimator.py` (bundle portion) + `tests/test_dcdh_sample_accounting.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_dcdh_estimator.py
from workbench.engine.dcdh_estimator import estimate_dcdh
from workbench.engine.event_study import EventStudyBundle

def test_estimate_dcdh_returns_bundle_with_event_axis():
    o = _oracle("nonabsorbing")
    b = estimate_dcdh(_norm("nonabsorbing"), cluster_var=None)
    assert isinstance(b, EventStudyBundle)
    L = len(o["placebo_estimate"]) + len(o["effect_estimate"])
    assert b.estimates.shape == (L,)
    assert b.influence_func.shape == (b.aux["n_total"], L)
    assert b.event_times.shape == (L,) and b.n_switchers.shape == (L,)
    # placebos (negative event_time) precede effects (>=0)
    assert list(b.event_times) == sorted(b.event_times)
    assert b.labels.count("placebo") == len(o["placebo_estimate"])

def test_cluster_var_guards():
    import pytest
    from workbench.engine.dcdh_spec import DCDHSpecError
    n = _norm("nonabsorbing")
    n.frame["clu"] = 1.0
    with pytest.raises(DCDHSpecError, match="DCDH_CLUSTER_SINGLE"):
        estimate_dcdh(n, cluster_var="clu")
```

```python
# tests/test_dcdh_sample_accounting.py
import json
from pathlib import Path
import pandas as pd
from workbench.engine.dcdh_spec import normalize_treatment_path
from workbench.engine.dcdh_estimator import estimate_dcdh

_FIX = Path(__file__).parent / "fixtures" / "dcdh"

def test_excluded_risk_set_and_n_switchers_consistent():
    d = pd.read_csv(_FIX / "panel_baseline1.csv")
    n = normalize_treatment_path(d, entity="id", time="year", y="y", treatment="d")
    b = estimate_dcdh(n, cluster_var=None)
    # excluded baseline=1 units never appear as switchers; n_switchers per ell matches risk set
    rs = {r["ell"]: r["n_switchers"] for r in b.diagnostics["risk_set_by_ell"]}
    effect_ev = [int(e) for e in b.event_times if e >= 0]
    for ell, ev in enumerate(effect_ev):
        assert int(b.n_switchers[list(b.event_times).index(ev)]) == rs[ell]
    assert set(b.diagnostics["excluded_units"]) == set(n.excluded_units)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_dcdh_estimator.py -k "bundle or cluster" tests/test_dcdh_sample_accounting.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `estimate_dcdh`**

Assemble the `EventStudyBundle`: combine placebo + effect estimates onto one sorted `event_times` axis (placebos negative, effects ≥0), build the `(N, L)` IF from `dcdh_influence`, per-event-time `n_switchers`, `aux={"n_total": N, "row_cluster": …}`, and `diagnostics={"risk_set_by_ell": …, "excluded_units": n.excluded_units, "sample": n.summary}`. Clustering mirrors SA (`engine/sa_attgt.py` `estimate_sa`): entity-default `row_cluster`; when `cluster_var` is a real non-entity column, resolve per-unit with the same guards (`DCDH_CLUSTER_COL_MISSING` / `DCDH_CLUSTER_COL_NAN` / `DCDH_CLUSTER_SINGLE` / `DCDH_CLUSTER_COL_BAD`, `.astype(str)` coercion).

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_dcdh_estimator.py tests/test_dcdh_sample_accounting.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/dcdh_estimator.py tests/test_dcdh_estimator.py tests/test_dcdh_sample_accounting.py
git commit -m "feat(dcdh): EventStudyBundle assembly + cluster guards + sample accounting"
```

---

## Task 7: `run_dcdh` — sup-t bands + result dict (no `_finalize_did_bundle`)

**Files:**
- Modify: `backend/workbench/econometrics/runner.py`
- Test: `tests/test_run_dcdh.py`, `tests/test_dcdh_no_finalize_touch.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_run_dcdh.py
import json
from pathlib import Path
import numpy as np, pandas as pd
from workbench.engine.dcdh_spec import normalize_treatment_path
from workbench.econometrics import runner

_FIX = Path(__file__).parent / "fixtures" / "dcdh"

def _norm(name):
    d = pd.read_csv(_FIX / f"panel_{name}.csv")
    return normalize_treatment_path(d, entity="id", time="year", y="y", treatment="d")

def test_run_dcdh_result_shape():
    res = runner.run_dcdh(_norm("nonabsorbing"), cluster_var=None)
    es = res["event_study"]
    assert es["label_kind"] == "event_time"
    L = len(es["event_time"])
    for key in ("estimate", "se", "kind", "n_switchers"):
        assert len(es[key]) == L
    assert es["uniform_band"] and es["uniform_crit"] is not None
    assert res["overall_att"]["experimental"] is True
    assert res["honest_did"] is None and res["honest_did_supported"] is False
    json.dumps(res, allow_nan=False)        # JSON-safe

def test_run_dcdh_deterministic():
    a = runner.run_dcdh(_norm("nonabsorbing"), cluster_var=None)
    b = runner.run_dcdh(_norm("nonabsorbing"), cluster_var=None)
    assert json.dumps(a["event_study"], sort_keys=True) == json.dumps(b["event_study"], sort_keys=True)
```

```python
# tests/test_dcdh_no_finalize_touch.py
import pandas as pd
from pathlib import Path
from workbench.engine.dcdh_spec import normalize_treatment_path
from workbench.econometrics import runner

_FIX = Path(__file__).parent / "fixtures" / "dcdh"

def test_run_dcdh_does_not_call_finalize_did_bundle(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("run_dcdh must NOT call _finalize_did_bundle")
    monkeypatch.setattr(runner, "_finalize_did_bundle", _boom)
    d = pd.read_csv(_FIX / "panel_nonabsorbing.csv")
    n = normalize_treatment_path(d, entity="id", time="year", y="y", treatment="d")
    runner.run_dcdh(n, cluster_var=None)    # must not raise
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_run_dcdh.py tests/test_dcdh_no_finalize_touch.py -v`
Expected: FAIL (`AttributeError: run_dcdh`).

- [ ] **Step 3: Implement `run_dcdh` in `runner.py`** (place beside `run_sa_did`)

```python
def run_dcdh(norm, *, cluster_var, seed=20260622, B=1000, alpha=0.05):
    """de Chaisemartin-D'Haultfoeuille dynamic DID (binary non-absorbing, first-up
    switchers). Emits an EventStudyBundle; reuses multiplier_bootstrap for sup-t
    bands. Does NOT go through _finalize_did_bundle (that is (g,t)-bundle-specific)."""
    from ..engine.dcdh_estimator import estimate_dcdh
    from ..engine.cs_inference import multiplier_bootstrap
    from ..engine.cs_aggregate import _se
    import numpy as np

    norm.frame = _ensure_numeric_y(norm.frame, norm.y)
    b = estimate_dcdh(norm, cluster_var=cluster_var)
    N = int(b.aux["n_total"]); row_cluster = b.aux["row_cluster"]
    est = np.asarray(b.estimates, dtype=float)

    boot = multiplier_bootstrap(b.influence_func, B=B, alpha=alpha, seed=seed,
                                estimates=est, clusters=row_cluster)
    se = [float(_se(b.influence_func[:, k], row_cluster, N)) for k in range(est.size)]

    ev = [float(e) for e in b.event_times]
    event_study = {
        "label_kind": "event_time",
        "event_time": ev,
        "estimate": [float(x) for x in est],
        "se": se,
        "pointwise_ci": boot["pointwise_ci"].tolist(),
        "uniform_band": boot["uniform_band"].tolist(),
        "uniform_crit": boot["uniform_crit"],
        "kind": list(b.labels),
        "n_switchers": [int(x) for x in b.n_switchers],
    }
    # overall ATT (secondary / experimental) = switcher-weighted mean of effect cols
    eff_idx = [k for k, e in enumerate(ev) if e >= 0]
    if eff_idx:
        w = np.array([b.n_switchers[k] for k in eff_idx], dtype=float)
        w = w / w.sum() if w.sum() else np.full(len(eff_idx), 1.0 / len(eff_idx))
        overall = float(np.dot(w, est[eff_idx]))
        overall_if = b.influence_func[:, eff_idx] @ w
        overall_se = float(_se(overall_if, row_cluster, N))
    else:
        overall, overall_se = None, None
    result = {
        "estimator": "dcdh",
        "event_study": event_study,
        "overall_att": {"estimate": overall, "se": overall_se, "experimental": True},
        "diagnostics": b.diagnostics,
        "honest_did": None,
        "honest_did_supported": False,
        "interpretation_restrictions": [
            "Non-absorbing binary treatment; event origin = first 0->1 switch. "
            "Units may switch back to 0 after the first up-switch (still included).",
            "baseline=1 units are excluded from both treatment and control in this version.",
        ],
        "warnings": [],
        "metadata": {"n_units": N, "estimator": "dcdh", "cluster_var": cluster_var},
    }
    return _json_safe_dcdh(result)
```

Add a small JSON-safe helper near the top of the module (mirror the cs/sa `_json_safe` used by diagnostics — non-finite floats → `None`):

```python
def _json_safe_dcdh(obj):
    import math
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _json_safe_dcdh(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe_dcdh(v) for v in obj]
    return obj
```

> If `runner.py` already imports/defines a `_json_safe`, reuse it instead of adding a duplicate.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_run_dcdh.py tests/test_dcdh_no_finalize_touch.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/econometrics/runner.py tests/test_run_dcdh.py tests/test_dcdh_no_finalize_touch.py
git commit -m "feat(dcdh): run_dcdh sup-t bands + result dict (no _finalize_did_bundle)"
```

---

## Task 8: Estimation handler + registration + pre-estimation check

**Files:**
- Modify: `backend/workbench/engine/stages/estimation.py`
- Modify: `backend/workbench/orchestrator/_model_types.py`
- Modify: `backend/workbench/orchestrator/__init__.py`
- Test: `tests/test_dcdh_wiring.py` (registration portion)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dcdh_wiring.py
import pandas as pd
from pathlib import Path
from workbench.engine.stages.estimation import CORE_PACK
from workbench.orchestrator import _model_types

_FIX = Path(__file__).parent / "fixtures" / "dcdh"

def test_dcdh_registered_explicit_only():
    handlers = {h.model_type for h in CORE_PACK.model_handlers}
    assert "dcdh" in handlers
    # explicit-only: NOT in defaults_by_y_type
    for y_type, mt in CORE_PACK.defaults_by_y_type.items():
        assert mt != "dcdh"

def test_dcdh_model_type_is_continuous():
    assert _model_types._MODEL_TYPE_MAP["dcdh"] == "continuous"
    assert _model_types._MODEL_METADATA["dcdh"]["model_id"] == "dcdh_1"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dcdh_wiring.py -k "registered or continuous" -v`
Expected: FAIL.

- [ ] **Step 3: Implement the handler + registration**

In `estimation.py`, add beside `_fit_sa_did`:
```python
def _fit_dcdh(ctx, env):
    from ..dcdh_spec import normalize_treatment_path
    id_cands = ctx.artifacts.get("_id_candidates") or []
    t_cands = ctx.artifacts.get("_time_candidates") or []
    norm = normalize_treatment_path(
        ctx.data.frame,
        entity=id_cands[0] if id_cands else None,
        time=t_cands[0] if t_cands else None,
        y=ctx.artifacts["_normalized_y"],
        treatment=ctx.artifacts.get("_dcdh_treatment_col"),
    )
    ctx.artifacts["_dcdh_normalized"] = norm
    result = _orch().run_dcdh(
        norm,
        cluster_var=ctx.artifacts.get("_cs_cluster_var") or None,   # reuse cluster channel
    )
    ctx.artifacts["_dcdh_result"] = result
    oa = result["overall_att"]
    primary = {"schema_version": 1, "model_id": "dcdh_1", "model_type": "dcdh",
        "engine": "workbench", "nobs": int(result["metadata"]["n_units"]), "r_squared": None,
        "coefficients": {"ATT": {"estimate": oa["estimate"], "std_error": oa["se"],
            "p_value": None, "source_id": "model_results.dcdh_1.coefficients.ATT"}},
        "warnings": result["warnings"]}
    return "dcdh_1", primary, None
```
Register in `CORE_PACK.model_handlers` (beside the sa_did line):
```python
        ModelHandler("dcdh", "dcdh_1", ("continuous",), _fit_dcdh),
```
Add the pre-estimation requirement (beside the sa_did check ~line 353):
```python
        if model_type == "dcdh" and (not id_cands or not t_cands):
            raise WorkflowValidationError(
                "dcdh requires both an entity and a time column.",
                {"model_type": "dcdh", "has_entity": bool(id_cands), "has_time": bool(t_cands)},
            )
```
In `_model_types.py`: add `"dcdh": {"model_id": "dcdh_1", "engine": "workbench"}` to `_MODEL_METADATA` and `"dcdh": "continuous"` to `_MODEL_TYPE_MAP`.
In `orchestrator/__init__.py`: re-export `run_dcdh` alongside `run_sa_did` (add to the `from ..econometrics.runner import (...)` list and any `__all__`/re-export hub).

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_dcdh_wiring.py -k "registered or continuous" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/stages/estimation.py backend/workbench/orchestrator/_model_types.py backend/workbench/orchestrator/__init__.py tests/test_dcdh_wiring.py
git commit -m "feat(dcdh): explicit-only _fit_dcdh handler + registration + pre-estimation check"
```

---

## Task 9: API param + workflow threading + artifact write (end-to-end)

**Files:**
- Modify: `backend/workbench/api.py`
- Modify: `backend/workbench/orchestrator/__init__.py`
- Modify: `backend/workbench/engine/stages/diagnostics.py`
- Test: `tests/test_dcdh_wiring.py` (end-to-end portion)

- [ ] **Step 1: Write the failing end-to-end test**

```python
# append to tests/test_dcdh_wiring.py
from workbench.orchestrator import run_workflow
from workbench.projects import create_project
from workbench.artifacts import read_json

def test_dcdh_end_to_end_writes_artifact(tmp_path):
    src = tmp_path / "data.csv"
    pd.read_csv(_FIX / "panel_nonabsorbing.csv").to_csv(src, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [src], mode="explicit", model_type="dcdh",
                          y="y", x="", entity_col="id", time_col="year",
                          did_treatment_path="d")
    run_root = project.root / "runs" / result["run_id"]
    art = read_json(run_root / "dcdh.json")
    assert art["estimator"] == "dcdh"
    assert art["event_study"]["label_kind"] == "event_time"
    assert art["honest_did_supported"] is False
```

> Check `run_workflow`'s signature for the exact entity/time kwargs (`entity_col`/`time_col` are threaded in `_run_workflow`). If `run_workflow` forwards `**kwargs` to `_run_workflow`, `did_treatment_path` must be added to BOTH signatures.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dcdh_wiring.py -k end_to_end -v`
Expected: FAIL (unexpected kwarg `did_treatment_path` / missing artifact).

- [ ] **Step 3: Thread the param + write the artifact**

In `api.py` POST `/runs` signature (beside `did_status_col`, ~line 107): add
```python
    did_treatment_path: str = Form(""),
```
and include `did_treatment_path` in the call that forwards form fields into the workflow (beside `did_status_col` ~line 161).

In `orchestrator/__init__.py` `_run_workflow` (and `run_workflow` if it forwards explicitly): add a `did_treatment_path: str = ""` parameter and thread:
```python
    ctx.artifacts["_dcdh_treatment_col"] = normalize_column_name(did_treatment_path) if did_treatment_path else ""
```
(beside the `_did_status_col` line ~439).

In `diagnostics.py`, add a dCDH artifact block (mirror the `sa_did` block exactly):
```python
        if model_type == "dcdh":
            dcdh_result = ctx.artifacts.get("_dcdh_result")
            if dcdh_result is not None:
                try:
                    dcdh_artifact = _json_safe(dcdh_result)
                    dcdh_artifact.setdefault("available", True)
                except Exception as exc:  # noqa: BLE001 - any failure degrades
                    dcdh_artifact = {"available": False, "error": str(exc)}
                dcdh_path = run_root / "dcdh.json"
                write_json(dcdh_path, dcdh_artifact)
                register_artifact(run_root, "dcdh", dcdh_path,
                                  "model_diagnostic", "econometrics", model_input_ids)
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_dcdh_wiring.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/api.py backend/workbench/orchestrator/__init__.py backend/workbench/engine/stages/diagnostics.py tests/test_dcdh_wiring.py
git commit -m "feat(dcdh): did_treatment_path API param + workflow threading + dcdh.json artifact"
```

---

## Task 10: capabilities (4-way sync)

**Files:**
- Modify: `backend/workbench/engine/capabilities.py`
- Modify: frontend capabilities type + contract schema/sample (locate via Step 1)
- Test: `tests/test_dcdh_wiring.py` (capabilities portion) + the existing capabilities contract test

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_dcdh_wiring.py
from workbench.engine.capabilities import MODEL_DESCRIPTIONS, MODEL_UI_ORDER  # adjust to real names

def test_dcdh_in_capabilities():
    assert "dcdh" in MODEL_DESCRIPTIONS
    assert MODEL_DESCRIPTIONS["dcdh"]["group"] == "dCDH"
    assert MODEL_DESCRIPTIONS["dcdh"]["requires"] == ["entity", "time", "treatment_path"]
    assert "dcdh" in MODEL_UI_ORDER
```
> Confirm the real symbol names for the descriptions dict + UI order in `capabilities.py` (the cs_did/sa_did entries live in the same dict; UI order is `MODEL_UI_ORDER`). Adjust the import to match.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dcdh_wiring.py -k capabilities -v`
Expected: FAIL.

- [ ] **Step 3: Add the capabilities entry**

In `capabilities.py`, add beside `sa_did`:
```python
    "dcdh": {
        "label": "de Chaisemartin-D'Haultfoeuille DID",
        "group": "dCDH",
        "description": "Dynamic DID for binary non-absorbing (switching) treatment using not-yet-switched controls (de Chaisemartin & D'Haultfoeuille). Handles treatments that turn on and off, which CS/SA cannot. Event study + native placebo pre-trend tests.",
        "requires": ["entity", "time", "treatment_path"],
    },
```
and add `"dcdh"` to `MODEL_UI_ORDER` (after `"sa_did"`).

Then complete the **4-way sync**: (a) backend dict (done); (b) the capabilities drift-guard test fixture (find it: `grep -rn "schema_version\|capabilities" tests/contracts/`); (c) frontend `frontend/src/capabilities/types.ts` (add `treatment_path` to the role enum if roles are typed); (d) contract sample JSON. Update each so the existing capabilities contract test passes with the new additive entry. **Do not bump `schema_version`** (additive model + additive role enum value).

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_dcdh_wiring.py -k capabilities tests/contracts -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/capabilities.py frontend/src/capabilities/types.ts tests/ <contract sample paths>
git commit -m "feat(dcdh): capabilities entry + 4-way sync (additive, no schema bump)"
```

---

## Task 11: Frontend — controls + result card

**Files:**
- Create: `frontend/src/runForm/DCDHControls.tsx` (+ `DCDHControls.test.tsx`)
- Create: `frontend/src/runResult/DCDHResultCard.tsx` (+ `DCDHResultCard.test.tsx`)
- Modify: the run-form + run-result wiring that dispatches on `model_type` (follow how `sa_did` is wired — `grep -rn "sa_did\|SADiagnostics\|CSControls" frontend/src`)

- [ ] **Step 1: Write the failing FE tests**

`DCDHControls.test.tsx`: renders entity/time/outcome/treatment-column selectors; the live identification badge shows an eligible-switcher pre-check estimate **labeled as an estimate** (e.g. "≈N eligible switchers (pre-check)").

`DCDHResultCard.test.tsx` (include the honest-DID negative test):
```tsx
import { render, screen } from "@testing-library/react";
import { DCDHResultCard } from "./DCDHResultCard";

const base = {
  estimator: "dcdh",
  event_study: { label_kind: "event_time", event_time: [-1, 0, 1],
    estimate: [0.0, 0.8, 1.0], se: [0.1, 0.1, 0.1],
    pointwise_ci: [[-0.2,0.2],[0.6,1.0],[0.8,1.2]],
    uniform_band: [[-0.3,0.3],[0.5,1.1],[0.7,1.3]], uniform_crit: 2.4,
    kind: ["placebo","effect","effect"], n_switchers: [20,20,18] },
  overall_att: { estimate: 0.9, se: 0.1, experimental: true },
  diagnostics: { risk_set_by_ell: [], excluded_units: [] },
  honest_did: null, honest_did_supported: false,
  interpretation_restrictions: [],
};

test("renders event study + experimental overall ATT", () => {
  render(<DCDHResultCard result={base} />);
  expect(screen.getByText(/experimental/i)).toBeInTheDocument();
});

test("does NOT render a Honest-DID block when honest_did_supported is false", () => {
  render(<DCDHResultCard result={base} />);
  expect(screen.queryByText(/honest/i)).toBeNull();
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npx vitest run src/runResult/DCDHResultCard.test.tsx src/runForm/DCDHControls.test.tsx`
Expected: FAIL (components not found).

- [ ] **Step 3: Implement the components**

`DCDHControls.tsx`: role-assignment for entity/time/outcome + a dedicated **treatment column** select bound to the new `did_treatment_path` form field; live badge computed client-side as a **pre-check estimate only** (count baseline=0 first-up switchers from the previewed data) with explicit "pre-check; backend diagnostics authoritative" wording. Does NOT reuse `CSControls`.

`DCDHResultCard.tsx`: event-study plot (reuse the dynamic line sub-component from the CS/SA result card if cleanly importable, else a minimal inline chart) with placebo (event_time<0) visually separated from effect (≥0), sup-t band, per-point `n_switchers` annotation, overall ATT with an `experimental` badge, diagnostics (excluded units / risk set), and `interpretation_restrictions`. **Render a Honest-DID block only if `result.honest_did_supported`** (here always false → never). Does NOT reuse `CSDiagnosticsCard`.

Wire both into the run-form/run-result dispatch the same way `sa_did` is wired.

- [ ] **Step 4: Run to verify they pass + tsc**

Run: `cd frontend && npx vitest run src/runResult/DCDHResultCard.test.tsx src/runForm/DCDHControls.test.tsx && npx tsc --noEmit`
Expected: tests PASS, tsc 0 errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/runForm/DCDHControls.tsx frontend/src/runForm/DCDHControls.test.tsx frontend/src/runResult/DCDHResultCard.tsx frontend/src/runResult/DCDHResultCard.test.tsx frontend/src/<dispatch files>
git commit -m "feat(dcdh): frontend controls + result card (honest-DID block suppressed)"
```

---

## Task 12: Golden (additive) + CS/SA 0-drift gate + QA edge

**Files:**
- Modify: `tests/test_engine_golden.py`
- Create: `tests/golden/dcdh_nonabsorbing.json`
- Test: `tests/test_dcdh_qa_edge.py`

- [ ] **Step 1: Write the QA-edge tests**

```python
# tests/test_dcdh_qa_edge.py
import json
from pathlib import Path
import numpy as np, pandas as pd, pytest
from workbench.engine.dcdh_spec import normalize_treatment_path, DCDHSpecError
from workbench.econometrics import runner

_FIX = Path(__file__).parent / "fixtures" / "dcdh"

def _norm(name):
    d = pd.read_csv(_FIX / f"panel_{name}.csv")
    return normalize_treatment_path(d, entity="id", time="year", y="y", treatment="d")

def test_nonabsorbing_switchback_runs():
    # the main fixture contains 0->1->0 switch-backs; run must complete + serialize
    res = runner.run_dcdh(_norm("nonabsorbing"), cluster_var=None)
    json.dumps(res, allow_nan=False)

def test_placebo_near_zero():
    o = json.loads((_FIX / "dyn_placebo.json").read_text())
    res = runner.run_dcdh(_norm("placebo"), cluster_var=None)
    es = res["event_study"]
    plac = [es["estimate"][i] for i, k in enumerate(es["kind"]) if k == "placebo"]
    assert max(abs(p) for p in plac) < 0.25   # placebos near 0 (DGP has no effect)

def test_nonnumeric_y_raises_clean():
    d = pd.read_csv(_FIX / "panel_nonabsorbing.csv"); d["y"] = "abc"
    n = normalize_treatment_path(d, entity="id", time="year", y="y", treatment="d")
    with pytest.raises(ValueError, match="non-numeric"):
        runner.run_dcdh(n, cluster_var=None)

def test_cluster_var_real_column_serializes():
    n = _norm("nonabsorbing"); n.frame["clu"] = (n.frame["id"] % 5 + 1).astype(float)
    res = runner.run_dcdh(n, cluster_var="clu")
    json.dumps(res, allow_nan=False)
```

- [ ] **Step 2: Run to verify they fail/pass appropriately, then add the golden**

Run: `.venv/bin/python -m pytest tests/test_dcdh_qa_edge.py -v` (fix any real issues surfaced).

Add a dCDH case to `tests/test_engine_golden.py` mirroring the `sa_did_staggered` golden test (run `run_workflow` with `model_type="dcdh"`, `did_treatment_path="d"`, capture via `_capture`, compare to `tests/golden/dcdh_nonabsorbing.json`). Generate the golden once by running the new test with a "write if missing" path or by saving `_capture(run_root)` output, then commit it.

- [ ] **Step 3: Run the FULL golden suite (0-drift hard gate)**

Run: `.venv/bin/python -m pytest tests/test_engine_golden.py tests/test_lineage_invariants.py tests/test_behavior_snapshot.py -v`
Expected: ALL pass, including the unchanged CS/SA/DID goldens (0-drift) + the new additive `dcdh_nonabsorbing` golden.

- [ ] **Step 4: Full gate**

Run: `./scripts/gate.sh`
Expected: `>>> GATE PASSED` (BE = 1082 + new dcdh tests, golden additive 0-drift, FE = 632 + new FE tests, tsc 0).

- [ ] **Step 5: Commit**

```bash
git add tests/test_dcdh_qa_edge.py tests/test_engine_golden.py tests/golden/dcdh_nonabsorbing.json
git commit -m "test(dcdh): QA edge cases + additive golden + CS/SA 0-drift gate"
```

---

## Task 13: Docs + whole-feature adversarial review

**Files:**
- Create: `docs/dcdh-howto.md`, `docs/v1.5.9-release-notes.md`
- Finalize: `docs/v1.5.9-IMPL-NOTES.md`

- [ ] **Step 1: Write `docs/dcdh-howto.md`** — when to use dCDH vs CS/SA (non-absorbing vs absorbing), the `did_treatment_path` input, reading the event study + placebos, the `experimental` overall ATT, and the v1.5.9 scope limits (binary, first-up, baseline=1 excluded).

- [ ] **Step 2: Write `docs/v1.5.9-release-notes.md`** — feature summary, gate numbers, validation tolerances (graded), deferrals.

- [ ] **Step 3: Finalize `docs/v1.5.9-IMPL-NOTES.md`** — the validated estimator recipe (corrected vs the plan sketch), the SE口径 + graded tol actually achieved, the DYN object shape decoded in Task 1, and the locked口径.

- [ ] **Step 4: Two-role adversarial review** (subagents; no `model` param). Run a **Reviewer** and a **Test & QA** pass over the whole feature (probes: IF scaling/命门, control-set boundary correctness, switch-back inclusion, baseline=1 exclusion no-leak, JSON-safety, determinism, no-finalize-touch, golden 0-drift, FE honest-DID suppression). Fix any blockers inline; add probe tests. If subagents are rate-limited, run both roles inline in separate clean passes.

- [ ] **Step 5: Final gate + commit**

```bash
./scripts/gate.sh    # must PASS
git add docs/dcdh-howto.md docs/v1.5.9-release-notes.md docs/v1.5.9-IMPL-NOTES.md tests/
git commit -m "docs(dcdh): how-to + release notes + impl notes; adversarial-review fixes"
```

---

## Ship (after all tasks, with explicit human authorization)

1. `git checkout main && git merge --no-ff workbench-v1.5.9` (commit msg: release v1.5.9 dCDH).
2. Empty-diff verify: `git diff --stat HEAD <branch-head>` is empty.
3. `git tag v1.5.9 <merge-commit>`.
4. **Ask for push authorization**, then `git push origin main && git push origin v1.5.9`.
5. Ask whether to clean worktree caches (`.venv` + `frontend/node_modules`).

---

## Self-review checklist (run before handing off)

- **Spec coverage:** §1 scope → T3/T4 (first-up, binary, deferrals); §3 EventStudyBundle → T2; §4 input → T3; §5 estimator/IF/3 hard contracts → T4/T5; §6 result dict → T7; §7 frontend → T11; §8 oracle/metadata → T1; §9 all 9 test files → T1/T4/T5/T6/T7/T9/T11/T12; §10 process → cross-cutting rules + Ship. ✅
- **Placeholder scan:** estimator numerics are intentionally oracle-authoritative (T4/T5), not fabricated — the contracts (ℓ=0, risk set, axis, graded SE) are explicit. Wiring tasks carry exact code. ✅
- **Type consistency:** `EventStudyBundle` fields (T2) used identically in T6/T7; `run_dcdh` signature (T7) matches `_fit_dcdh` call (T8); `did_treatment_path` field name consistent across T8/T9/T11; `_dcdh_*` columns consistent T3→T4→T6. ✅
