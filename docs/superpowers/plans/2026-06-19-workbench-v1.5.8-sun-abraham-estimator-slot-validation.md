# Sun-Abraham estimator-slot validation (v1.5.8) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal, faithful Sun-Abraham (SA) interaction-weighted event-study estimator that produces the same `EffectEstimateBundle` as Callaway-Sant'Anna, reusing the entire downstream (aggregation + sup-t bands + honest-DID ΔRM/ΔSD) through one shared `_finalize_did_bundle`, validated element-wise against `fixest::sunab`.

**Architecture:** A new self-implemented saturated two-way-FE estimator (`engine/sa_attgt.py`) — entity-demeaned within-OLS over observed rows, sparse design, QR/SVD solve with collinearity metadata, analytic N-scaled entity influence function — emits an `EffectEstimateBundle`. `run_cs_did`'s downstream is extracted verbatim into an estimator-agnostic `_finalize_did_bundle` that both `run_cs_did` and the new `run_sa_did` call. SA is an explicit-only `sa_did` model_type.

**Tech Stack:** Python 3.11, NumPy, SciPy (`scipy.sparse`, `scipy.linalg`/`numpy.linalg.lstsq` QR/SVD); React/TS + vitest; R `fixest` 0.12+ for committed JSON oracles only (installed once; suite never invokes R).

**Spec:** `docs/superpowers/specs/2026-06-19-workbench-v1.5.8-sun-abraham-estimator-slot-validation-design.md`

**Conventions carried from prior DID versions (do not relitigate):**
- `EffectEstimateBundle` (defined in `backend/workbench/engine/cs_attgt.py:21`): `estimates (K,)`, `influence_func (N,K)` **entity rows holding RAW influence values** (O(1) per entity — NOT divided by N), `cluster_ids`, `cell_metadata` (K dicts with `g,t,event_time,valid,...`), `weights={"n_g":...,"p_g":...}`, `vcov_config`, `diagnostics`, `aux={"n_total":N,"row_cohort","row_cluster"}`.
- **Scaling convention (the linchpin).** `cs_aggregate._se(col,row_cluster,N) = sqrt(Σ_c S_c²)/N` with `S_c = Σ_{i∈c} col_i`; the honest adapter builds `Σ=(S'S)/N²`. So a single IF column's bare cluster vcov = `(_se)² = (1/N²)Σ_c S_c²`. **SA must scale its IF the same way** (see Task 4).
- Degrade-not-fail: estimator raises typed `SASpecError`; the honest block already wraps `except Exception`. Bad inputs → structured MODEL_FIT_FAILED via the estimation stage's `except ValueError`.
- Golden freezes status/artifacts/coef only. Gate = `./scripts/gate.sh` from the worktree root; **never bare pytest** (use `.venv/bin/python -m pytest`). FE gate = `cd frontend && npx vitest run && npx tsc --noEmit`.
- R generates committed JSON fixtures only; the suite never calls R.
- **Every implementer commits LOCALLY only — NEVER `git push`** (the v1.5.7.1 incident).

---

## Target bundle shape (what Task 3-5 build toward)

For each identified `(g, e≠−1)` cell (cohort `g`, relative time `e`, `t=g+e`):
- canonical key `f"g={g}|e={e}|t={g+e}"`, cells sorted by `(g, e)`.
- `estimates[k] = CATT(g,e)`; `influence_func[:,k] = φ_{·,k}` (N-scaled entity IF, Task 4).
- `cell_metadata[k] = {"g":g,"t":g+e,"event_time":e,"valid":True,"n_treated":<int>,"n_control":<int>,"warning":None}`.
- `weights["n_g"][g]` = entity count of cohort g; `aux={"n_total":N,"row_cohort":(N,),"row_cluster":(N,)}` (never-treated counted in N, `row_cohort` sentinel 0.0; mirror cs_attgt:433-435).
- Reference period (`e=−1`), reference cohort, and dropped/collinear/zero-support cells are **absent** (no placeholder rows). `diagnostics` carries `dropped_cells`, `collinear_cells`, `support_zero_cells`.

---

## Task 0: Worktree, environment, R `fixest`, baseline gate

**Files:** none (environment only)

- [ ] **Step 1: Confirm spec + plan committed on local main**

Run: `git -C /Users/jiayuanren/项目规划 log --oneline -4`
Expected: the v1.5.8 spec commit + this plan commit on `main`, above `1423e1d`.

- [ ] **Step 2: Create the isolated worktree off local main**

```bash
cd /Users/jiayuanren/项目规划
git worktree add -b workbench-v1.5.8 .worktrees/workbench-v1.5.8 main
```

- [ ] **Step 3: Build backend venv (full extras) + frontend deps**

```bash
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.5.8
~/.local/bin/python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev,panel,ml,imbalanced,imputation]"
cd frontend && npm install
```

- [ ] **Step 4: Install R `fixest` (once; persists outside the worktree)**

Run: `Rscript -e 'if(!requireNamespace("fixest",quietly=TRUE)) install.packages("fixest", repos="https://cloud.r-project.org"); library(fixest); packageVersion("fixest")'`
Expected: prints a version (≥0.11). If the compile fails, ensure `~/.R/Makevars` has `CC=clang -std=gnu17` (the established fix). `fixest::sunab` must exist: `Rscript -e 'library(fixest); exists("sunab")'` → TRUE.

- [ ] **Step 5: Baseline gate (must be green before any change)**

```bash
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.5.8
./scripts/gate.sh
```
Expected: GATE PASSED — BE 1035 / golden 20 0-drift / FE 627 / tsc 0 (the v1.5.7.1 ship baseline).

---

## Task 1: R oracle — `fixest::sunab` (balanced + unbalanced + collinear)

Generate committed JSON oracles with the **locked `ssc(adj=FALSE, cluster.adj=FALSE)`口径** and **parsed `(g,e)` keys** (never positional). Three fixtures: balanced (full common support), unbalanced, and one with a zero-support cohort×period.

**Files:**
- Create: `tests/fixtures/sa_did/generate_oracle.R`
- Create (generated): `tests/fixtures/sa_did/sunab_balanced.json`, `sunab_unbalanced.json`, `sunab_collinear.json`
- Create: `tests/fixtures/sa_did/panel_balanced.csv`, `panel_unbalanced.csv`, `panel_collinear.csv`

- [ ] **Step 1: Read fixest::sunab's coefficient naming + aggregation API**

Run:
```bash
Rscript -e 'library(fixest); ?sunab' 2>/dev/null | head -40
Rscript -e 'library(fixest)
 set.seed(1); d <- expand.grid(id=1:30, year=2000:2008)
 d$g <- rep(sample(c(2003,2005,10000), 30, TRUE), times=9)   # 10000 = never
 d$y <- rnorm(nrow(d)) + 0.5*( (d$year>=d$g) * (d$year-d$g+1) )
 m <- feols(y ~ sunab(g, year) | id + year, d, ssc=ssc(adj=FALSE, cluster.adj=FALSE))
 print(names(coef(m)))            # SEE the coefficient name pattern
 print(coef(m)[1:3])'
```
Record the exact coefficient-name pattern (e.g. `year::-3:cohort::2003` or `g = 2003 x year = -3` style) — Task 3/5 parse `g` and `e` out of it. WRITE the pattern into your report.

- [ ] **Step 2: Write `generate_oracle.R`**

Build each panel in R (also write the CSV the engine will read so both sides see identical data), fit `sunab`, and dump coefficients + bare cluster vcov + the aggregated event study, each tagged with a parsed `(g,e)` key:

```r
library(fixest); library(jsonlite)
emit <- function(d, path_csv, path_json) {
  write.csv(d, path_csv, row.names = FALSE)
  m  <- feols(y ~ sunab(cohort, year) | id + year, data = d,
              ssc = ssc(adj = FALSE, cluster.adj = FALSE))
  V  <- vcov(m, cluster = ~id, ssc = ssc(adj = FALSE, cluster.adj = FALSE))
  cf <- coef(m)
  nm <- names(cf)
  # parse e (relative period) out of fixest's sunab names; sunab uses the relative
  # period as the coefficient label. Adapt the regex to the pattern found in Step 1.
  e_of <- as.numeric(sub(".*?(-?[0-9]+).*", "\\1", nm))
  agg <- summary(m, agg = "att")           # aggregated event-study (the dynamic target)
  acf <- coef(agg); anm <- names(acf)
  ae  <- as.numeric(sub(".*?(-?[0-9]+).*", "\\1", anm))
  write_json(list(
      coef = as.numeric(cf), coef_e = e_of, coef_name = nm,
      vcov = unname(as.matrix(V)),
      agg_estimate = as.numeric(acf), agg_e = ae,
      ssc = "adj=FALSE,cluster.adj=FALSE", cluster = "id"),
    path_json, digits = 16, matrix = "rowmajor", auto_unbox = TRUE)
}
# balanced: full common support
set.seed(11); ...                  # build a balanced panel where every cohort is
                                   # observed at every in-range relative period
emit(d_bal, "tests/fixtures/sa_did/panel_balanced.csv", "tests/fixtures/sa_did/sunab_balanced.json")
# unbalanced: drop some (id,year) rows so N_{g,e} != n_g
emit(d_unb, "tests/fixtures/sa_did/panel_unbalanced.csv", "tests/fixtures/sa_did/sunab_unbalanced.json")
# collinear/zero-support: a cohort with no obs at some relative period
emit(d_col, "tests/fixtures/sa_did/panel_collinear.csv", "tests/fixtures/sa_did/sunab_collinear.json")
```

NOTE: `sunab` aggregates COHORTS into a single relative-period event study by default. The per-cohort CATT(g,e) is exposed via the interaction terms — if `sunab`'s default only returns the aggregated path, ALSO fit the fully-saturated interactions explicitly (`feols(y ~ i(cohort, rel_period, ref=-1) | id+year)` after constructing `rel_period = year - cohort` with never-treated excluded) to get per-(g,e) coefficients + their vcov. Record BOTH the per-(g,e) (for Task 3/4) and the aggregated path (for Task 5). Confirm with Step 1 which the names correspond to.

- [ ] **Step 3: Generate + sanity-check**

```bash
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.5.8
Rscript tests/fixtures/sa_did/generate_oracle.R
.venv/bin/python -c "import json; [print(p, 'finite' , all(map(lambda v: v==v, json.load(open(f'tests/fixtures/sa_did/{p}'))['coef']))) for p in ['sunab_balanced.json','sunab_unbalanced.json','sunab_collinear.json']]"
```
Expected: all finite; the collinear fixture has at least one cohort×period absent from `coef_e`.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/sa_did/
git commit -m "test(sa-did): fixest::sunab oracle (balanced/unbalanced/collinear, locked ssc)"
```

---

## Task 2: `sa_spec.py` — input normalization + reference-cohort selection

**Files:**
- Create: `backend/workbench/engine/sa_spec.py`
- Test: `tests/test_sa_spec.py`

SA reuses the same normalized DID input as CS (`did_spec.normalize_did_input` gives a frame with entity/time/y/cohort, never-treated as non-finite cohort). `sa_spec` adds SA-specific validation + ref-cohort selection.

- [ ] **Step 1: Write the failing test**

```python
import numpy as np, pandas as pd, pytest
from workbench.engine.sa_spec import select_reference_cohort, validate_sa_input, SASpecError

def test_reference_cohort_never_when_present():
    cohort = np.array([2003., 2005., np.inf, np.nan])   # inf & nan = never
    ref, has_never = select_reference_cohort(cohort)
    assert has_never is True and ref is None

def test_reference_cohort_last_treated_when_no_never():
    cohort = np.array([2003., 2005., 2004.])
    ref, has_never = select_reference_cohort(cohort)
    assert has_never is False and ref == 2005.0

def test_validate_requires_two_periods_and_a_treated_cohort():
    with pytest.raises(SASpecError, match="SA_NO_TREATED_COHORT"):
        validate_sa_input(cohort=np.array([np.inf, np.inf]), times=np.array([1, 2]))
```

- [ ] **Step 2: Run → FAIL (ImportError).**

Run: `.venv/bin/python -m pytest tests/test_sa_spec.py -v`

- [ ] **Step 3: Implement**

```python
import numpy as np

class SASpecError(ValueError):
    """SA_* failure (bad SA spec)."""

def select_reference_cohort(cohort):
    """Reference cohort for SA: None when a never-treated group exists (the natural
    comparison); otherwise the LAST-treated cohort as the normalization baseline.
    never-treated = non-finite cohort (NaN or inf)."""
    cohort = np.asarray(cohort, dtype=float)
    finite = cohort[np.isfinite(cohort)]
    has_never = bool(np.any(~np.isfinite(cohort)))
    if has_never:
        return None, True
    if finite.size == 0:
        raise SASpecError("SA_NO_TREATED_COHORT: no treated cohort and no never-treated group.")
    return float(np.max(finite)), False

def validate_sa_input(*, cohort, times):
    cohort = np.asarray(cohort, dtype=float)
    if np.unique(np.asarray(times)).size < 2:
        raise SASpecError("SA_TOO_FEW_PERIODS: need >=2 time periods.")
    if cohort[np.isfinite(cohort)].size == 0:
        raise SASpecError("SA_NO_TREATED_COHORT: no treated cohort present.")
    return True
```

- [ ] **Step 4: Run → PASS.** **Step 5: Commit** `git add backend/workbench/engine/sa_spec.py tests/test_sa_spec.py && git commit -m "feat(sa-did): SA input validation + reference-cohort selection"`

---

## Task 3: SA estimator — saturated within-OLS coefficients (CATT)

Build the saturated design (sparse), entity-demean over observed rows, solve via QR/lstsq with rank detection, extract CATT(g,e). Validate coefficients vs the oracle **joined on the `(g,e)` key**.

**Files:**
- Create: `backend/workbench/engine/sa_attgt.py`
- Test: `tests/test_sa_attgt.py`

- [ ] **Step 1: Write the failing coefficient test (join on key, not index)**

```python
import json, numpy as np, pandas as pd
from pathlib import Path
from workbench.engine.sa_attgt import estimate_sa_saturated   # returns dict: keys "g","e","beta", + drop metadata
_FIX = Path(__file__).parent / "fixtures" / "sa_did"

def _load(panel):
    d = pd.read_csv(_FIX / f"panel_{panel}.csv")
    o = json.loads((_FIX / f"sunab_{panel}.json").read_text())
    return d, o

def test_sa_coefficients_match_fixest_balanced():
    d, o = _load("balanced")
    res = estimate_sa_saturated(d, entity="id", time="year", y="y", cohort="cohort")
    # build {(g,e): beta} from engine and from oracle, join on key
    got = {(float(g), float(e)): float(b) for g, e, b in zip(res["g"], res["e"], res["beta"])}
    # oracle: per-(g,e) coef; map names->(g,e) via the parser (Task 1 recorded the pattern)
    want = {(float(g), float(e)): float(b)
            for g, e, b in zip(o["coef_g"], o["coef_e"], o["coef"])}
    assert set(got) == set(want), (set(got) ^ set(want))
    for k in want:
        assert abs(got[k] - want[k]) < 1e-8, (k, got[k], want[k])
```

(If Task 1's oracle stored only relative-period `e` for the aggregated path, ensure the per-(g,e) fixture also stores `coef_g`. Adjust the oracle in Task 1 if missing — the per-cell coefficients MUST carry both g and e.)

- [ ] **Step 2: Run → FAIL (ImportError).**

- [ ] **Step 3: Implement the estimator core**

```python
import numpy as np
import pandas as pd
from scipy import sparse
from .sa_spec import select_reference_cohort, validate_sa_input, SASpecError

def _build_design(df, entity, time, y, cohort):
    """Returns (y, D_sparse, col_keys, entity_codes, N, drop_info).
    D = [time dummies (drop first), interaction dummies for (g,e), e!=-1, g!=ref]."""
    ent = df[entity].to_numpy()
    tim = df[time].to_numpy()
    yv  = df[y].to_numpy(dtype=float)
    coh = df[cohort].to_numpy(dtype=float)
    validate_sa_input(cohort=coh, times=tim)
    ref_cohort, has_never = select_reference_cohort(coh)

    ent_u, ent_codes = np.unique(ent, return_inverse=True)
    tim_u, tim_codes = np.unique(tim, return_inverse=True)
    N = ent_u.size
    n_obs = df.shape[0]

    # time dummies (drop first for identification under the entity FE)
    time_cols, time_keys = [], []
    for j in range(1, tim_u.size):
        time_cols.append(sparse.csc_matrix(((tim_codes == j).astype(float)[:, None])))
        time_keys.append(("time", float(tim_u[j])))

    # interaction dummies: treated, finite cohort, g != ref_cohort, e = t-g != -1
    treated = np.isfinite(coh)
    rel = np.where(treated, tim - coh, np.nan)
    inter_cols, inter_keys = [], []
    gs = sorted({float(g) for g in coh[treated] if (ref_cohort is None or g != ref_cohort)})
    for g in gs:
        es = sorted({float(e) for e in rel[(coh == g)] if np.isfinite(e) and e != -1.0})
        for e in es:
            col = ((coh == g) & (rel == e)).astype(float)
            if col.sum() == 0:
                continue
            inter_cols.append(sparse.csc_matrix(col[:, None]))
            inter_keys.append((float(g), float(e)))

    D = sparse.hstack(time_cols + inter_cols, format="csc") if (time_cols or inter_cols) \
        else sparse.csc_matrix((n_obs, 0))
    col_keys = time_keys + inter_keys
    return yv, D, col_keys, ent_codes, N, {"ref_cohort": ref_cohort, "has_never": has_never,
                                           "n_inter": len(inter_keys)}

def _entity_demean(vec_or_mat, ent_codes, N):
    """Within transform over OBSERVED rows per entity (no padding)."""
    counts = np.bincount(ent_codes, minlength=N).astype(float)
    if sparse.issparse(vec_or_mat):
        M = vec_or_mat.toarray()
    else:
        M = np.asarray(vec_or_mat, dtype=float)
        if M.ndim == 1:
            M = M[:, None]
    sums = np.zeros((N, M.shape[1]))
    np.add.at(sums, ent_codes, M)
    means = sums / counts[:, None]
    return M - means[ent_codes]

def estimate_sa_saturated(df, *, entity, time, y, cohort, _return_internals=False):
    yv, D, col_keys, ent_codes, N, drop = _build_design(df, entity, time, y, cohort)
    yd = _entity_demean(yv, ent_codes, N).ravel()
    Dd = _entity_demean(D, ent_codes, N)                      # dense (n_obs x P)
    # rank-revealing solve; lstsq returns rank; detect dropped/collinear columns
    beta, _res, rank, sv = np.linalg.lstsq(Dd, yd, rcond=None)
    # identify collinear columns via QR pivoting for honest drop metadata
    q, r, piv = _qr_pivot(Dd)                                 # see helper below
    tol = max(Dd.shape) * np.finfo(float).eps * (abs(r[0, 0]) if r.size else 1.0)
    indep = piv[: int(np.sum(np.abs(np.diag(r)) > tol))]
    collinear_idx = sorted(set(range(Dd.shape[1])) - set(indep.tolist()))
    # refit on identified columns only (stable)
    Dind = Dd[:, sorted(indep)]
    beta_ind, _r2, _rk, _sv = np.linalg.lstsq(Dind, yd, rcond=None)
    bmap = dict(zip(sorted(indep), beta_ind))
    # collect interaction coefficients (skip time cols), in (g,e) order
    g_out, e_out, b_out = [], [], []
    collinear_cells, dropped_cells = [], []
    for j, key in enumerate(col_keys):
        if key[0] == "time":
            continue
        g, e = key
        if j in bmap:
            g_out.append(g); e_out.append(e); b_out.append(float(bmap[j]))
        else:
            collinear_cells.append({"g": g, "e": e})
    order = np.lexsort((np.array(e_out), np.array(g_out)))
    res = {"g": list(np.array(g_out)[order]), "e": list(np.array(e_out)[order]),
           "beta": list(np.array(b_out)[order]),
           "collinear_cells": collinear_cells, "dropped_cells": dropped_cells,
           "ref_cohort": drop["ref_cohort"], "has_never": drop["has_never"]}
    if _return_internals:
        res["_internals"] = {"Dd": Dd, "yd": yd, "ent_codes": ent_codes, "N": N,
                             "col_keys": col_keys, "indep": sorted(indep), "bmap": bmap}
    return res

def _qr_pivot(A):
    from scipy.linalg import qr
    q, r, piv = qr(A, mode="economic", pivoting=True)
    return q, r, piv
```

- [ ] **Step 4: Run → PASS for balanced (1e-8). Then add + pass the unbalanced coefficient test (same join-on-key, panel "unbalanced") and a collinear test asserting the zero-support cohort×period is absent from `beta` and present in `collinear_cells`/`dropped_cells`.** Iterate the design/`ref` handling until coefficients match `fixest` on all three fixtures. The likely mismatch source is the dropped reference-period/cohort or the time-dummy identification — reconcile against the oracle (authoritative) and the Task-1 name pattern.

- [ ] **Step 5: Commit** `git add backend/workbench/engine/sa_attgt.py tests/test_sa_attgt.py && git commit -m "feat(sa-did): saturated within-OLS CATT coefficients (fixest-validated)"`

---

## Task 4: SA influence function — N-scaled entity IF (the honest-DID命门)

The IF column for coefficient `k` is `φ_{i,k} = N · [(D̃'D̃)⁺ Σ_t D̃_it ε̂_it]_k`. The `N` factor makes `cs_aggregate._se` and the honest adapter (`Σ=(S'S)/N²`) reproduce the **bare** cluster vcov. **First confirm the cs_attgt convention, then pin SA's IF against `fixest` bare vcov.**

**Files:**
- Modify: `backend/workbench/engine/sa_attgt.py`
- Test: `tests/test_sa_attgt.py`

- [ ] **Step 1: Write the failing IF-scaling hard test (join on key; bare ssc)**

```python
from workbench.engine.cs_aggregate import _se

def test_sa_if_reconstructs_fixest_bare_cluster_vcov():
    d, o = _load("balanced")
    res = estimate_sa_saturated(d, entity="id", time="year", y="y", cohort="cohort",
                                _return_internals=True)
    IF = sa_influence(res)                       # (N, K) aligned to res["g"]/["e"]
    N = res["_internals"]["N"]
    # per-entity cluster == entity here, so vcov_kk = (1/N^2) * sum_i IF[i,k]^2
    keys = list(zip(res["g"], res["e"]))
    want = {(float(g), float(e)): float(v)
            for g, e, v in zip(o["coef_g"], o["coef_e"], np.diag(np.asarray(o["vcov"])))}
    for k, (g, e) in enumerate(keys):
        rc = np.arange(N)                        # entity-clustered == identity
        se = _se(IF[:, k], rc, N)
        assert abs(se*se - want[(g, e)]) < 1e-6, (g, e, se*se, want[(g, e)])
```

- [ ] **Step 2: Run → FAIL (no `sa_influence`).**

- [ ] **Step 3: Implement `sa_influence`**

```python
def sa_influence(res):
    """N-scaled entity influence function (N, K) for the interaction coefficients,
    aligned to res["g"]/res["e"] order. φ_{i,k} = N * [(D̃'D̃)^+ Σ_t D̃_it ε̂_it]_k.
    Matches the EffectEstimateBundle convention so cs_aggregate._se and the honest
    adapter reproduce the bare cluster vcov."""
    I = res["_internals"]
    Dd, yd, ent_codes, N = I["Dd"], I["yd"], I["ent_codes"], I["N"]
    indep, col_keys, bmap = I["indep"], I["col_keys"], I["bmap"]
    Dind = Dd[:, indep]
    beta = np.array([bmap[j] for j in indep])
    resid = yd - Dind @ beta                                  # within residuals ε̂
    XtX = Dind.T @ Dind
    XtX_inv = np.linalg.pinv(XtX)                             # identified subspace
    # per-observation score s_it = Dind_it * ε̂_it ; entity-sum then map through bread
    scored = Dind * resid[:, None]                            # (n_obs, |indep|)
    ent_sum = np.zeros((N, Dind.shape[1]))
    np.add.at(ent_sum, ent_codes, scored)                    # Σ_t per entity
    phi = N * (ent_sum @ XtX_inv.T)                          # (N, |indep|), N-scaled
    # select interaction columns in res order
    inter_pos = {j: p for p, j in enumerate(indep)}
    cols = []
    gE = list(zip(res["g"], res["e"]))
    key_to_j = {col_keys[j]: j for j in indep if col_keys[j][0] != "time"}
    for (g, e) in gE:
        j = key_to_j[(g, e)]
        cols.append(phi[:, inter_pos[j]])
    return np.column_stack(cols)
```

- [ ] **Step 4: Run → PASS (1e-6) on balanced. Then add the same reconstruction test on `unbalanced` (coefficients differ from did-aggregation but the per-(g,e) vcov must still match fixest bare vcov — the estimator-level IF is exact regardless of balance).** This is the линchpin gate; if it fails, the honest-DID inheritance is wrong — do NOT loosen 1e-6, reconcile the N-scaling against cs_attgt's convention (read `cs_aggregate._se` + the honest adapter) and `fixest`'s bare `ssc`.

- [ ] **Step 5: Commit** `git add backend/workbench/engine/sa_attgt.py tests/test_sa_attgt.py && git commit -m "feat(sa-did): N-scaled analytic IF (reconstructs fixest bare cluster vcov)"`

---

## Task 5: Assemble `EffectEstimateBundle` + balanced aggregation oracle

Wrap Task 3/4 into `estimate_sa(norm, *, cluster_var) -> EffectEstimateBundle` with valid-filtering, cell_metadata, weights, aux. Validate `cs_aggregate.aggregate(bundle,"dynamic")` matches `fixest::sunab`'s aggregated event study on **balanced** (1e-6), join on `e`.

**Files:**
- Modify: `backend/workbench/engine/sa_attgt.py`
- Test: `tests/test_sa_attgt.py`

- [ ] **Step 1: Write the failing bundle + aggregation test**

```python
from workbench.engine.cs_attgt import EffectEstimateBundle
from workbench.engine.cs_aggregate import aggregate
from workbench.engine.did_spec import normalize_did_input

def _norm(panel):
    d = pd.read_csv(_FIX / f"panel_{panel}.csv")
    return normalize_did_input(d, mode="cohort", entity="id", time="year", y="y", cohort="cohort")

def test_sa_bundle_is_effectestimatebundle_and_consumable():
    b = estimate_sa(_norm("balanced"), cluster_var=None)
    assert isinstance(b, EffectEstimateBundle)
    assert b.influence_func.shape[0] == b.aux["n_total"]
    assert b.influence_func.shape[1] == len(b.cell_metadata) == len(b.estimates)
    assert all(m["valid"] for m in b.cell_metadata)        # only identified cells enter
    agg = aggregate(b, "dynamic")                          # must not raise
    assert len(agg["label"]) > 0

def test_sa_dynamic_matches_fixest_balanced():
    d, o = _load("balanced")
    b = estimate_sa(_norm("balanced"), cluster_var=None)
    agg = aggregate(b, "dynamic")
    got = {float(e): float(v) for e, v in zip(agg["label"], agg["estimate"])}
    want = {float(e): float(v) for e, v in zip(o["agg_e"], o["agg_estimate"])}
    common = set(got) & set(want)
    assert common, (set(got), set(want))
    for e in common:
        assert abs(got[e] - want[e]) < 1e-6, (e, got[e], want[e])
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement `estimate_sa`**

```python
def estimate_sa(norm, *, cluster_var=None):
    df = norm.frame
    res = estimate_sa_saturated(df, entity=norm.entity, time=norm.time, y=norm.y,
                                cohort=norm.cohort, _return_internals=True)
    IF = sa_influence(res)                                  # (N, K)
    g_arr = np.array(res["g"]); e_arr = np.array(res["e"])
    estimates = np.array(res["beta"], dtype=float)
    # cell_metadata (valid-only; collinear/dropped already excluded by Task 3)
    coh = df[norm.cohort].to_numpy(float)
    n_by_g = {float(g): int(np.unique(df.loc[coh == g, norm.entity]).size)
              for g in np.unique(coh[np.isfinite(coh)])}
    meta = []
    for g, e in zip(g_arr, e_arr):
        meta.append({"g": float(g), "t": float(g + e), "event_time": float(e),
                     "valid": True, "n_treated": n_by_g.get(float(g), 0),
                     "n_control": None, "warning": None})
    # aux mirrors cs_attgt:433-435
    ent_u = np.unique(df[norm.entity].to_numpy())
    N = res["_internals"]["N"]
    # entity-aligned cohort (0 = never) and cluster id, in the SAME entity order as IF rows
    ent_codes = res["_internals"]["ent_codes"]
    # IF rows are in np.unique(entity) order; build per-entity cohort/cluster aligned to that
    first_row = {}
    ent_raw = df[norm.entity].to_numpy()
    for i in range(df.shape[0]):
        first_row.setdefault(ent_codes[i], i)
    order_rows = [first_row[c] for c in range(N)]
    row_cohort = np.array([coh[r] if np.isfinite(coh[r]) else 0.0 for r in order_rows], float)
    if cluster_var and cluster_var != norm.entity:
        cl = df[cluster_var].to_numpy()
        row_cluster = np.array([cl[r] for r in order_rows])
    else:
        row_cluster = np.array([ent_raw[r] for r in order_rows])
    weights = {"n_g": n_by_g, "p_g": {}}
    aux = {"n_total": int(N), "row_cohort": row_cohort, "row_cluster": row_cluster}
    diagnostics = {"dropped_cells": res["dropped_cells"],
                   "collinear_cells": res["collinear_cells"],
                   "support_zero_cells": res["dropped_cells"],
                   "sample_spec": {"estimator": "sa", "cluster_var": cluster_var,
                                   "ref_cohort": res["ref_cohort"], "has_never": res["has_never"]}}
    clustered = bool(cluster_var and cluster_var != norm.entity)
    vcov_config = {"cluster_var": cluster_var if clustered else norm.entity,
                   "cluster_level": cluster_var if clustered else "entity",
                   "confidence_level": 0.95, "band_type": None}
    return EffectEstimateBundle(estimates=estimates, influence_func=IF, aux=aux,
        cluster_ids=np.unique(row_cluster), cell_metadata=meta, weights=weights,
        vcov_config=vcov_config, diagnostics=diagnostics)
```

- [ ] **Step 4: Run → PASS.** If `test_sa_dynamic_matches_fixest_balanced` fails, first confirm the balanced fixture truly has full common support (Task 1); a support gap (not weighting) is the usual culprit per spec §4.2.

- [ ] **Step 5: Commit** `git add backend/workbench/engine/sa_attgt.py tests/test_sa_attgt.py && git commit -m "feat(sa-did): EffectEstimateBundle assembly + balanced dynamic matches fixest"`

---

## Task 6: Extract `_finalize_did_bundle` (behavior-frozen) + anti-fork guard

Pull `run_cs_did`'s downstream (att_gt table, four aggregations + bands, warnings, metadata, honest-DID, return dict) into an estimator-agnostic helper. `run_cs_did` calls it → CS golden 0-drift. Add the anti-fork guard test.

**Files:**
- Modify: `backend/workbench/econometrics/runner.py`
- Test: `tests/test_finalize_did_bundle.py`, `tests/test_engine_golden.py` (unchanged — proves 0-drift)

- [ ] **Step 1: Extract the helper (verbatim move).** Create `_finalize_did_bundle(bundle, *, seed, B, alpha, honest_did) -> dict` containing exactly the current `run_cs_did` body from the `G = bundle.influence_func.shape[0]` line (runner.py:530) through the `return {...}` (runner.py:616-618). Then `run_cs_did` becomes:

```python
def run_cs_did(norm, *, covariates, control_group, est_method, base_period,
               anticipation, cluster_var, seed=20260615, B=1000, alpha=0.05,
               honest_did=False):
    from ..engine.cs_attgt import estimate_att_gt
    norm.frame = _ensure_numeric_y(norm.frame, norm.y)
    bundle = estimate_att_gt(norm, control_group=control_group, est_method=est_method,
        base_period=base_period, anticipation=anticipation,
        covariates=list(covariates), cluster_var=cluster_var)
    md = {"control_group": control_group, "est_method": est_method,
          "base_period": base_period, "anticipation": anticipation,
          "covariates": list(covariates), "cluster_var": cluster_var}
    return _finalize_did_bundle(bundle, seed=seed, B=B, alpha=alpha,
                                honest_did=honest_did, extra_metadata=md)
```

The metadata block in `_finalize_did_bundle` currently reads CS-specific names (control_group/est_method/base_period/anticipation). Move those into the `extra_metadata` dict the caller passes, and have `_finalize_did_bundle` merge `extra_metadata` into `metadata` (so SA can pass its own). The estimator-agnostic fields (n_units, n_clusters, n_cohorts, n_valid_cells, n_cells, B, alpha, seed, confidence_level, band_type, cluster_level) stay computed inside. **No `if estimator==...` branches.**

- [ ] **Step 2: Anti-fork guard test**

```python
import inspect, re
from workbench.econometrics import runner

def test_finalize_did_bundle_has_no_estimator_branch():
    src = inspect.getsource(runner._finalize_did_bundle)
    assert not re.search(r'estimator\s*==', src), "no estimator-name branch allowed"
    assert '"cs"' not in src and "'cs'" not in src
    assert '"sa"' not in src and "'sa'" not in src

def test_finalize_did_bundle_signature_is_estimator_agnostic():
    params = set(inspect.signature(runner._finalize_did_bundle).parameters)
    assert "bundle" in params and "extra_metadata" in params
    assert "estimator" not in params
```

- [ ] **Step 3: Run the anti-fork test + the FULL backend suite + golden.**

Run: `.venv/bin/python -m pytest tests/test_finalize_did_bundle.py tests/test_engine_golden.py tests/test_run_cs_did.py tests/test_honest_did_wiring.py -q && .venv/bin/python -m pytest -q`
Expected: all pass; **golden 0-drift** (cs_did golden byte-identical — the refactor is behavior-frozen). Prove byte-identity: `git stash` is NOT needed; the golden test passing IS the proof.

- [ ] **Step 4: Commit** `git add backend/workbench/econometrics/runner.py tests/test_finalize_did_bundle.py && git commit -m "refactor(did): extract estimator-agnostic _finalize_did_bundle (CS 0-drift) + anti-fork guard"`

---

## Task 7: `run_sa_did` + estimator registration + pipeline threading

**Files:**
- Modify: `backend/workbench/econometrics/runner.py`, `backend/workbench/estimation.py`, `backend/workbench/orchestrator/_model_types.py`, `backend/workbench/engine/capabilities.py`, `backend/workbench/api.py`, `backend/workbench/orchestrator/__init__.py` (+ `_run_workflow`)
- Test: `tests/test_run_sa_did.py`, `tests/test_sa_did_wiring.py`

- [ ] **Step 1: `run_sa_did` (no estimator-specific downstream — the acceptance test)**

```python
def run_sa_did(norm, *, cluster_var, seed=20260615, B=1000, alpha=0.05, honest_did=False):
    """Sun-Abraham interaction-weighted event study end to end. Constructs the SA
    bundle then defers ENTIRELY to _finalize_did_bundle (estimator-slot validation)."""
    from ..engine.sa_attgt import estimate_sa
    norm.frame = _ensure_numeric_y(norm.frame, norm.y)
    bundle = estimate_sa(norm, cluster_var=cluster_var)
    md = {"estimator": "sun_abraham", "cluster_var": cluster_var}
    return _finalize_did_bundle(bundle, seed=seed, B=B, alpha=alpha,
                                honest_did=honest_did, extra_metadata=md)
```

- [ ] **Step 2: Register `sa_did` explicit-only.** In `estimation.py` add `_fit_sa_did` to CORE_PACK `model_handlers` (NOT `defaults_by_y_type`), mirroring `_fit_cs_did`. In `orchestrator/_model_types.py` add `"sa_did": "continuous"` to `_MODEL_TYPE_MAP` + metadata. In `capabilities.py` add an "SA" group requiring roles entity/time/cohort (4-way sync: backend key / drift-guard / FE type / contract sample). Thread `sa_did` through `api.py` POST form + `_run_workflow` + `orchestrator.run_workflow`/`_run_workflow` exactly as `cs_did` is threaded (same did_mode/cohort/entity/time params; SA ignores covariates/control_group/est_method/base_period).

- [ ] **Step 3: Wiring tests**

```python
def test_run_sa_did_end_to_end(tmp_path):
    # build a small staggered panel, run via the workflow with model_type="sa_did",
    # assert cs_did-shaped sa_did.json: aggregations.dynamic present, honest_did when flagged
    ...
def test_run_sa_did_has_no_downstream_logic():
    import inspect
    from workbench.econometrics import runner
    src = inspect.getsource(runner.run_sa_did)
    # the only non-trivial call is estimate_sa + _finalize_did_bundle
    assert "_finalize_did_bundle" in src and "aggregate(" not in src and "honest_did_from_cs" not in src
```

(Decide the artifact name: emit `sa_did.json` mirroring `cs_did.json`. The diagnostics stage writes it via the same `_json_safe(result)` path keyed on `model_type=="sa_did"`.)

- [ ] **Step 4: Run wiring tests + full suite + golden 0-drift.** **Step 5: Commit** `git add -A && git commit -m "feat(sa-did): run_sa_did + sa_did explicit-only registration + pipeline threading"`

---

## Task 8: Unbalanced aggregation-weight characterization + warning

**Files:**
- Modify: `backend/workbench/econometrics/runner.py` (in `_finalize_did_bundle` or a small helper) / `backend/workbench/engine/sa_attgt.py`
- Test: `tests/test_sa_attgt.py`, `tests/test_run_sa_did.py`

- [ ] **Step 1: Failing test — unbalanced diverges + warns**

```python
def test_sa_unbalanced_dynamic_differs_and_warns():
    d, o = _load("unbalanced")
    b = estimate_sa(_norm("unbalanced"), cluster_var=None)
    agg = aggregate(b, "dynamic")
    got = {float(e): float(v) for e, v in zip(agg["label"], agg["estimate"])}
    want = {float(e): float(v) for e, v in zip(o["agg_e"], o["agg_estimate"])}
    # characterize: at least one common e differs beyond 1e-6 (did n_g vs sunab observed weighting)
    diffs = [abs(got[e]-want[e]) for e in (set(got)&set(want))]
    assert max(diffs) > 1e-6   # documents the architectural boundary (NOT a bug)
```

(If the unbalanced fixture happens to NOT diverge, make it more unbalanced in Task 1 until it does — the divergence is the point being characterized.)

- [ ] **Step 2: Detect unbalance + attach the warning.** In `estimate_sa`, set `diagnostics["balanced"] = <bool>` (a panel is balanced iff every entity has every period, computed over observed rows). In `_finalize_did_bundle`, when `bundle.diagnostics.get("balanced") is False`, append to the dynamic aggregation block an `interpretation_restrictions` entry:

> "This event-study uses did-style cohort-size (n_g) aggregation weights. In unbalanced panels this may differ from fixest::sunab's aggregation (which weights by observed counts per relative period)."

This is estimator-agnostic (keys off `diagnostics["balanced"]`, not the estimator name — CS bundles simply set `balanced=True` or omit it, so CS output is 0-drift). **Do NOT compute a quantified X** (spec §4.2 risk #5).

- [ ] **Step 3: Test the warning surfaces in `sa_did.json` for an unbalanced run and is ABSENT for a balanced run; confirm CS golden 0-drift (CS sets balanced True/omitted → no new key).** **Step 4: Commit.**

---

## Task 9: honest-DID free-inheritance + additive golden

**Files:**
- Test: `tests/test_sa_did_wiring.py`, `tests/test_engine_golden.py`

- [ ] **Step 1: honest-DID inheritance test (real run, coarse grid)**

```python
def test_sa_honest_did_runs_free(tmp_path, monkeypatch):
    from workbench.econometrics import runner
    monkeypatch.setattr(runner, "HONEST_MBAR_GRID", [0.0, 1.0])
    monkeypatch.setattr(runner, "HONEST_GRID_POINTS", 150)
    # run a >=2-pre staggered panel via model_type="sa_did", honest_did=True
    # assert sa_did.json honest_did = {"rm": {...}, "sd": {...}} both status "ok"
    # (ΔRM + ΔSD/FLCI inherited for free through the same adapter), strict-JSON valid
    ...
```

- [ ] **Step 2: Additive golden `sa_did` (monkeypatched small grid).** Add `test_golden_sa_did` mirroring `test_golden_cs_did_honest`: `_capture` freezes status/artifacts/coef only; guard the `sa_did.json` structure (`aggregations.dynamic`, `honest_did.rm`/`.sd` both ok). 20→21 goldens, 0-drift on the existing 20.

- [ ] **Step 3: Run golden + wiring; full suite green.** **Step 4: Commit.**

---

## Task 10: Frontend — SA controls + SA event-study card

**Files:**
- Modify: `frontend/src/runForm/CSControls.tsx` (or a thin `SAControls` reusing it), `frontend/src/runForm/RunForm.tsx`, `frontend/src/api.ts`, `frontend/src/runResult/CSDiagnosticsCard.tsx` (reuse) or a thin `SADiagnosticsCard`, model-type select
- Test: corresponding `.test.tsx`

- [ ] **Step 1 (TDD):** Add a vitest case that, given an `sa_did` capability + an `sa_did.json`-shaped payload (dynamic aggregation + nested `{rm,sd}` honest block), renders the event-study + honest panels (reuse `CSDiagnosticsCard`'s rendering — the payload is the same shape). Assert the SA estimator is selectable and posts `model_type=sa_did` with cohort/entity/time roles. Run → FAIL.
- [ ] **Step 2:** Wire `sa_did` into the model-type select (driven by the capabilities manifest), reuse `CSControls`' role assignment, post `sa_did`. Reuse `CSDiagnosticsCard` for results (same contract → minimal new code). Run → PASS.
- [ ] **Step 3:** `npx vitest run && npx tsc --noEmit` → green, 0 type errors, no `any`. **Step 4: Commit.**

---

## Task 11: Docs

**Files:**
- Create: `docs/sa-did-howto.md`, `docs/v1.5.8-release-notes.md`

- [ ] **Step 1:** `sa-did-howto.md` — plain-language SA vs CS (saturated interaction TWFE vs per-cell DRDID; when to use which; no covariates in SA), how to read the same event-study + honest panels, and the unbalanced caveat (did-style weighting; for strict fixest::sunab on unbalanced panels, note the difference).
- [ ] **Step 2:** `v1.5.8-release-notes.md` — what shipped (minimal faithful SA; estimator-slot validation), the architectural result (bundle is the seam; `_finalize_did_bundle` shared; CS 0-drift; anti-fork guard), validation facts (fixest::sunab oracle, locked `ssc`; coef 1e-8 / IF-reconstructs-bare-vcov 1e-6 / balanced dynamic 1e-6 / unbalanced characterized-not-aligned), honest-DID (ΔRM+ΔSD) inherited free, zero new Python deps, `fixest` for oracle only. Deferred: DR/IPW/covariates, observed-period unbalanced weighting, binning, `l_vec`.
- [ ] **Step 3: Commit.**

---

## Task 12: Final whole-feature adversarial review + finish branch

Not a code-writing task. Two-role review (Reviewer + Test&QA) before merge (the v1.5.6.1/v1.5.7/v1.5.7.1 lesson).

- [ ] **Step 1: Reviewer** — read every changed file adversarially. Probe: the IF N-scaling (does `_se`/honest Σ reconstruct fixest bare vcov on BOTH balanced & unbalanced? join on key, not index); the anti-fork guard genuinely fails if an estimator branch is added; CS golden truly 0-drift through `_finalize_did_bundle`; valid-filtering (no collinear/dropped/reference cell leaks into estimates/IF/aggregation); last-treated path (no never-treated) produces sane output; degrade-not-fail on SA failures (SA_* → MODEL_FIT_FAILED, honest still degrades); determinism; sparse design doesn't blow memory on a larger panel; `(g,e)` key parsing robust to the fixest name pattern.
- [ ] **Step 2: Test&QA** — prove end-to-end via real runs: SA happy path (balanced) → sa_did.json with dynamic + honest {rm,sd}; unbalanced → warning present + run completes; collinear/zero-support cohort×period → absent from estimates, run completes; no-never-treated → last-treated reference works; honest-DID inherited (ΔRM+ΔSD both ok); additivity (non-SA artifacts unchanged). Fill any thin assertions. Add the reproducible gate command.
- [ ] **Step 3: Full gate** `./scripts/gate.sh` → GATE PASSED (BE ≥1035+new / golden 0-drift / FE ≥627+new / tsc 0).
- [ ] **Step 4: Finish** — superpowers:finishing-a-development-branch. `--no-ff` merge `workbench-v1.5.8` into `main` + tag `v1.5.8`; verify gated-head vs merged-tree empty diff (EXIT=0). **Push requires explicit per-version authorization — ask first.** After ship, ask about worktree cache cleanup.

---

## Self-review notes (spec coverage map)

- Spec §2.1 (saturated model, ref period −1, ref cohort never|last-treated, pre-period cells) → Tasks 2, 3. §2.2 (within over observed rows; sparse D + dense K×K bread; QR/SVD + dropped/collinear/support_zero metadata; no direct inverse) → Task 3. §2.3 (N-scaled entity IF; rows entity-level; **IF scaling hard test reconstructs fixest bare vcov**) → Task 4. §2.4 (locked `ssc`口径) → Task 1 + Task 4.
- §3 (bundle mapping; **valid as downstream filter**; **`(g,e)` column-mapping, join-on-key**) → Tasks 1 (parser), 3, 5. §4.1 (`_finalize_did_bundle` behavior-frozen + **anti-fork guard**) → Task 6. §4.2 (unbalanced reuse + qualitative warning, no quantified X, balanced-qualifier oracle) → Tasks 1, 5, 8.
- §5 (fixest oracle; coef 1e-8 / vcov 1e-6 / balanced dynamic 1e-6 / unbalanced characterize / honest chain / collinearity) → Tasks 1,3,4,5,8,9. §6 (integration, sa_did explicit-only, 4-way sync, FE reuse) → Tasks 7, 10. §7 (process, no-push, two-role review, finish) → Tasks 0, 12.
- Acceptance test (§1: `run_sa_did` no estimator-specific downstream; CS 0-drift through `_finalize_did_bundle`) → Task 6 (guard) + Task 7 (`test_run_sa_did_has_no_downstream_logic`).
- Type/name consistency: `estimate_sa_saturated` (Task 3) → `sa_influence` (Task 4) → `estimate_sa` (Task 5) → `run_sa_did`/`_finalize_did_bundle(extra_metadata=...)` (Tasks 6,7). Canonical key `g={g}|e={e}|t={g+e}` and join-on-key used in Tasks 1,3,4,5.
- Open research risk flagged in-task (not placeholders): Task 1 fixest name-pattern + whether per-(g,e) coefficients need the explicit `i(cohort, rel, ref=-1)` fit; Task 3 reference/time-dummy identification reconciled against the oracle; Task 4 N-scaling reconciled against cs_attgt convention. All have explicit oracle gates + "the oracle is authoritative" instructions.
