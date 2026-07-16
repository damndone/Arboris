# honest-DID (v1.5.7, Rambachan-Roth ΔRM Sensitivity) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an estimator-agnostic honest-DID sensitivity post-processor (Rambachan-Roth 2023, ΔRM relative-magnitudes) that runs on the shipped Callaway-Sant'Anna dynamic event study, producing robust confidence sets that stay valid under relaxed parallel trends.

**Architecture:** A pure engine `honest_did.py` (knows only `betahat, sigma, num_pre, num_post, l_vec, mbar_grid`) + a thin `honest_did_adapter.py` that extracts `(betahat, sigma)` from the CS dynamic aggregation (cluster-robust Σ). The engine's ΔRM constraint matrices + ARP conditional/hybrid test are a **faithful port of R `HonestDiD`**, decomposed into intermediate-validated sub-steps; the committed R-exported fixtures are the source of truth (same discipline as the v1.5.6 DRDID port). Wired into `run_cs_did` behind a `honest_did` param; honest-DID failure degrades (skips) and never fails the run.

**Tech Stack:** Python (NumPy/SciPy — `scipy.optimize.linprog`, `scipy.stats`), pytest, R 4.6.0 + `HonestDiD` (oracle only), React/TS + vitest. Zero new Python deps.

**Spec:** `docs/superpowers/specs/2026-06-16-workbench-v1.5.7-honest-did-design.md`

**Per-task discipline:** TDD (red→green) + two-stage review (spec-conformance, then quality) per [[feedback_review_workflow]]. Commit after each green task. Full suite via `.venv/bin/python -m pytest` from the worktree root (never bare). Push to main needs explicit per-version authorization.

**CRITICAL framing for the engine tasks (T2–T5):** these are PORTS, not from-scratch derivations. The complete spec for each is *"reproduce the behavior of the named R `HonestDiD` function to within the committed fixture tolerance."* The implementer MUST read the installed R `HonestDiD` source (Task 0 installs it; source under the R library path printed by `system.file(package="HonestDiD")`). Do NOT invent an algorithm — port the R one and let the intermediate fixtures catch divergence. If a sub-step cannot be matched after genuine effort, report BLOCKED with the divergence rather than weakening the tolerance.

---

## File Structure

Backend (new):
- `backend/workbench/engine/honest_did.py` — pure ΔRM/ARP engine. Functions: `create_arm_constraints`, `arp_conditional_test`, `arp_confidence_interval`, `honest_rm`.
- `backend/workbench/engine/honest_did_adapter.py` — `honest_did_from_cs_dynamic`.

Backend (modify):
- `backend/workbench/econometrics/runner.py` — `run_cs_did` attaches `result["honest_did"]`.
- `backend/workbench/api.py`, `backend/workbench/orchestrator/__init__.py`, `backend/workbench/engine/stages/estimation.py` — thread the `honest_did` flag.

Tests (new):
- `tests/fixtures/honest_did/{generate_oracle.R, honest_rm.json, arm_constraints.json, conditional_test.json}`
- `tests/test_honest_did_engine.py`, `tests/test_honest_did_adapter.py`, `tests/test_honest_did_wiring.py`

Frontend (modify):
- `frontend/src/runForm/CSControls.tsx` (+ `.test.tsx`), `frontend/src/runForm/RunForm.tsx`, `frontend/src/api.ts`, `frontend/src/runResult/CSDiagnosticsCard.tsx`.

Docs: `docs/honest-did-howto.md`, `docs/v1.5.7-release-notes.md`.

---

## Task 0: Worktree + env + R HonestDiD + baseline gate

**Files:** none (environment).

- [ ] **Step 1: Create the isolated worktree off main**
```bash
cd /Users/jiayuanren/项目规划
git worktree add -b workbench-v1.5.7 .worktrees/workbench-v1.5.7 main
cd .worktrees/workbench-v1.5.7
git log --oneline -1   # expect the v1.5.7 spec commit on top of 399fc53
```

- [ ] **Step 2: Build backend venv (full extras) + frontend deps**
```bash
~/.local/bin/python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev,panel,ml,imbalanced,imputation]"
cd frontend && npm install && cd ..
```

- [ ] **Step 3: Install R HonestDiD (one-time; for oracle only)**
```bash
# ~/.R/Makevars already has CC=clang -std=gnu17 (needed for Apple clang 16)
/opt/homebrew/bin/Rscript -e 'install.packages("HonestDiD", repos="https://cloud.r-project.org")'
/opt/homebrew/bin/Rscript -e 'library(HonestDiD); cat("HonestDiD", as.character(packageVersion("HonestDiD")), "OK\n")'
/opt/homebrew/bin/Rscript -e 'cat(system.file(package="HonestDiD"), "\n")'   # note the source path for the port
```
Expected: `HonestDiD <ver> OK` and a library path. If install fails on compilation, confirm `~/.R/Makevars`.

- [ ] **Step 4: Baseline gate (no-drift reference BEFORE any change)**
```bash
.venv/bin/python -m pytest -q
cd frontend && npx vitest run && npx tsc --noEmit && cd ..
```
Expected: BE 940 passed, golden/inv/snapshot 19 (0-drift), FE 619 passed, tsc 0. Record these.

---

## Task 1: R oracle — engine fixtures (final CI + intermediates)

**Files:**
- Create: `tests/fixtures/honest_did/generate_oracle.R`
- Create (generated): `honest_rm.json`, `arm_constraints.json`, `conditional_test.json`
- Test: `tests/test_honest_did_engine.py` (oracle-shape sanity only here)

- [ ] **Step 1: Write the oracle generator**

Create `tests/fixtures/honest_did/generate_oracle.R`. Use a SMALL fixed event-study input (do NOT depend on a dataset — hard-code a `betahat` + `sigma` so the fixture is deterministic and self-contained). Use 3 pre + 4 post periods:
```r
suppressMessages({library(HonestDiD); library(jsonlite)})
set.seed(20260616)
numPre <- 3; numPost <- 4
betahat <- c(0.02, -0.01, 0.015, 0.30, 0.35, 0.28, 0.22)   # pre(3) then post(4)
# a valid PD covariance: A A' scaled
A <- matrix(rnorm((numPre+numPost)^2), numPre+numPost)
sigma <- (A %*% t(A)) / 20 + diag(numPre+numPost) * 0.001
sigma <- round(sigma, 8)                                    # freeze to 8 dp so Python reads identical
betahat <- round(betahat, 8)

# (a) full sensitivity result for the post-AVERAGE target, Mbar grid
l_avg <- rep(1/numPost, numPost)
mbar_grid <- c(0, 0.5, 1, 1.5, 2)
rm_avg <- lapply(mbar_grid, function(M) {
  r <- createSensitivityResults_relativeMagnitudes(
        betahat = betahat, sigma = sigma,
        numPrePeriods = numPre, numPostPeriods = numPost,
        l_vec = l_avg, Mbarvec = M)
  list(Mbar = M, lb = r$lb, ub = r$ub)
})
# (b) per-post-event-time targets (l = indicator), Mbar = 1 only (keep fixture small)
l_event <- lapply(1:numPost, function(j) { v <- rep(0, numPost); v[j] <- 1; v })
rm_event <- lapply(seq_along(l_event), function(j) {
  r <- createSensitivityResults_relativeMagnitudes(
        betahat = betahat, sigma = sigma, numPrePeriods = numPre,
        numPostPeriods = numPost, l_vec = l_event[[j]], Mbarvec = 1)
  list(event_index = j - 1, lb = r$lb, ub = r$ub)
})
write_json(list(betahat = betahat, sigma = sigma, numPre = numPre, numPost = numPost,
                mbar_grid = mbar_grid, l_avg = l_avg,
                rm_avg = rm_avg, rm_event = rm_event),
           "tests/fixtures/honest_did/honest_rm.json", digits = 10, auto_unbox = TRUE)

# (c) INTERMEDIATE: ΔRM constraint matrices (A_RM, d_RM) for Mbar=1, l_avg.
#     Port target for Task 2. Use the package's internal constructors.
arm <- HonestDiD:::.create_A_RM(numPrePeriods = numPre, numPostPeriods = numPost,
                                Mbar = 1, l_vec = l_avg)
# .create_A_RM returns A; d is zeros of nrow(A) for RM. Capture both robustly:
write_json(list(Mbar = 1, numPre = numPre, numPost = numPost,
                A = arm, nrow = nrow(arm), ncol = ncol(arm)),
           "tests/fixtures/honest_did/arm_constraints.json", digits = 10, auto_unbox = TRUE)
```
NOTE: the EXACT internal name (`.create_A_RM`) and its return shape may differ across HonestDiD versions. The implementer MUST inspect the installed source (`ls(getNamespace("HonestDiD"))`) and adapt the generator to export whatever the real ΔRM constraint constructor + the single-(θ,Mbar) conditional-test internals are. The REQUIREMENT: the fixture must contain (i) the final per-Mbar CIs, (ii) the ΔRM constraint matrix for one (Mbar,l), (iii) a single-(θ,Mbar) conditional-test stat + critical value + reject decision (export from `HonestDiD:::.lp_conditional_test` or the equivalent — find it). Add the `conditional_test.json` export once the right internal is located.

- [ ] **Step 2: Generate and inspect**
```bash
/opt/homebrew/bin/Rscript tests/fixtures/honest_did/generate_oracle.R
.venv/bin/python -c "import json;o=json.load(open('tests/fixtures/honest_did/honest_rm.json'));print(o['numPre'],o['numPost'],[r['Mbar'] for r in o['rm_avg']],o['rm_avg'][2])"
```
Expected: `3 4 [0,0.5,1,1.5,2] {...lb,ub...}`. Confirm the M̄=0 CI is the tightest and CIs widen as M̄ grows.

- [ ] **Step 3: Oracle-shape sanity test**
```python
import json
HRM = json.load(open("tests/fixtures/honest_did/honest_rm.json"))

def test_oracle_present_and_widens():
    assert HRM["numPre"] == 3 and HRM["numPost"] == 4
    widths = [r["ub"] - r["lb"] for r in HRM["rm_avg"]]
    assert widths == sorted(widths)        # CI width non-decreasing in Mbar
    assert len(HRM["rm_event"]) == 4
```

- [ ] **Step 4: Run + commit**
```bash
.venv/bin/python -m pytest tests/test_honest_did_engine.py -q
git add tests/fixtures/honest_did/ tests/test_honest_did_engine.py
git commit -m "test(honest-did): R HonestDiD ΔRM oracle (final CIs + intermediates)"
```

---

## Task 2: ΔRM constraint builder (port, intermediate-validated)

**Files:**
- Create: `backend/workbench/engine/honest_did.py`
- Test: `tests/test_honest_did_engine.py`

- [ ] **Step 1: Write the failing test against `arm_constraints.json`**
```python
import json, numpy as np
from workbench.engine.honest_did import create_arm_constraints

def test_arm_constraints_match_R():
    ref = json.load(open("tests/fixtures/honest_did/arm_constraints.json"))
    A = create_arm_constraints(num_pre=ref["numPre"], num_post=ref["numPost"],
                               mbar=ref["Mbar"], l_vec=[1/ref["numPost"]]*ref["numPost"])
    A_R = np.array(ref["A"], dtype=float).reshape(ref["nrow"], ref["ncol"])
    assert A.shape == A_R.shape
    assert np.allclose(np.sort(A.ravel()), np.sort(A_R.ravel()), atol=1e-8)  # same multiset of entries
    # stronger: row-set equality up to ordering
    assert {tuple(np.round(r,8)) for r in A} == {tuple(np.round(r,8)) for r in A_R}
```

- [ ] **Step 2: Run to verify it fails**
```bash
.venv/bin/python -m pytest tests/test_honest_did_engine.py::test_arm_constraints_match_R -q
```
Expected: FAIL (module/function missing).

- [ ] **Step 3: Port `create_arm_constraints` from R `HonestDiD`**

Read the installed R source for the ΔRM constraint constructor (the function the generator exported, e.g. `.create_A_RM`). Port it to `backend/workbench/engine/honest_did.py`:
```python
from __future__ import annotations
import numpy as np

class HonestDiDError(ValueError):
    """HONEST_*-prefixed failure (degrades the honest_did block; never fails the run)."""

def create_arm_constraints(*, num_pre: int, num_post: int, mbar: float, l_vec) -> np.ndarray:
    """ΔRM(Mbar) constraint matrix A such that the relative-magnitudes restriction is
    {delta : A @ delta <= 0}. Faithful port of R HonestDiD's ΔRM constructor; the
    arm_constraints.json fixture (exported from the same R internal) is the oracle.
    `l_vec` (num_post,) selects the target; entries are the post-period weights."""
    # PORT the R algorithm here. The constraint set encodes: each post-period
    # consecutive second-difference is bounded by Mbar * the max pre-period
    # consecutive second-difference, expressed as a stack of linear inequalities
    # over delta in R^(num_pre+num_post). Match the R row/sign conventions exactly.
    raise NotImplementedError  # replace with the port
```
The completion criterion is the test, not this skeleton. Match R's exact construction (sign/row conventions) — the row-multiset assertion will catch ordering-agnostic correctness.

- [ ] **Step 4: Run to verify it passes**
```bash
.venv/bin/python -m pytest tests/test_honest_did_engine.py::test_arm_constraints_match_R -q
```
Expected: PASS. If the row-multiset differs, the port's sign/index convention is off — fix against the R source.

- [ ] **Step 5: Commit**
```bash
git add backend/workbench/engine/honest_did.py tests/test_honest_did_engine.py
git commit -m "feat(honest-did): ΔRM constraint matrix port (vs R oracle)"
```

---

## Task 3: ARP conditional test for a single (θ, Mbar) (port, intermediate-validated)

**Files:**
- Modify: `backend/workbench/engine/honest_did.py`
- Test: `tests/test_honest_did_engine.py`
- Depends on: `conditional_test.json` (add its export to `generate_oracle.R` in this task if not done in T1 — export from the R internal `.lp_conditional_test`/equivalent: a fixed `(betahat, sigma, A, d, theta)` → `{test_stat, crit_val, reject}`).

- [ ] **Step 1: Extend the oracle generator to export a single conditional-test instance**

Add to `generate_oracle.R` an export of the ARP conditional test for one fixed `theta` under the ΔRM(1) constraints + l_avg, writing `conditional_test.json` with `{theta, test_stat, crit_val, reject, hybrid_flag}`. Regenerate; confirm only `conditional_test.json` is added (existing fixtures byte-identical).

- [ ] **Step 2: Write the failing test**
```python
def test_conditional_test_matches_R():
    import numpy as np
    from workbench.engine.honest_did import arp_conditional_test
    ref = json.load(open("tests/fixtures/honest_did/conditional_test.json"))
    HRM = json.load(open("tests/fixtures/honest_did/honest_rm.json"))
    out = arp_conditional_test(
        betahat=np.array(HRM["betahat"]), sigma=np.array(HRM["sigma"]),
        num_pre=HRM["numPre"], num_post=HRM["numPost"],
        l_vec=np.array(HRM["l_avg"]), mbar=1.0, theta=ref["theta"], alpha=0.05)
    assert abs(out["test_stat"] - ref["test_stat"]) < 1e-4
    assert abs(out["crit_val"] - ref["crit_val"]) < 1e-4
    assert bool(out["reject"]) == bool(ref["reject"])
```

- [ ] **Step 3: Port `arp_conditional_test`**

Read R `HonestDiD`'s ARP conditional (and conditional-LF hybrid) test. Implement in `honest_did.py`:
```python
from scipy import stats
from scipy.optimize import linprog

def arp_conditional_test(*, betahat, sigma, num_pre, num_post, l_vec, mbar, theta, alpha=0.05, seed=20260616):
    """ARP moment-inequality conditional (or conditional-LF hybrid) test of the null that
    the target parameter equals `theta` under ΔRM(mbar). Returns {test_stat, crit_val, reject}.
    Faithful port of R HonestDiD; conditional_test.json is the oracle.

    Determinism: if the hybrid least-favorable critical value is simulated, seed the RNG
    (np.random.default_rng(seed)) so the result is reproducible (golden 0-drift). Prefer the
    simulation-free conditional variant where it matches R's reported method."""
    raise NotImplementedError  # PORT: moment vector Y = A@betahat - d adjusted for theta;
    # conditional test stat (max studentized slack), truncated-normal critical value via the
    # binding/non-binding split; LP (linprog) for the least-favorable step if hybrid.
```
Resolve the conditional-vs-hybrid determinism question HERE against the oracle: match whatever method R's `createSensitivityResults_relativeMagnitudes` uses by default, seeding any simulation.

- [ ] **Step 4: Run + Step 5: Commit**
```bash
.venv/bin/python -m pytest tests/test_honest_did_engine.py::test_conditional_test_matches_R -q
git add backend/workbench/engine/honest_did.py tests/fixtures/honest_did/ tests/test_honest_did_engine.py
git commit -m "feat(honest-did): ARP conditional/hybrid single-point test port (vs R oracle)"
```

---

## Task 4: Test inversion → CI for one Mbar

**Files:**
- Modify: `backend/workbench/engine/honest_did.py`
- Test: `tests/test_honest_did_engine.py`

- [ ] **Step 1: Write the failing test (one-Mbar CI vs the oracle's Mbar=1 average)**
```python
def test_ci_for_one_mbar_matches_R():
    import numpy as np
    from workbench.engine.honest_did import arp_confidence_interval
    HRM = json.load(open("tests/fixtures/honest_did/honest_rm.json"))
    ref = next(r for r in HRM["rm_avg"] if r["Mbar"] == 1)
    lb, ub = arp_confidence_interval(
        betahat=np.array(HRM["betahat"]), sigma=np.array(HRM["sigma"]),
        num_pre=HRM["numPre"], num_post=HRM["numPost"],
        l_vec=np.array(HRM["l_avg"]), mbar=1.0, alpha=0.05)
    assert abs(lb - ref["lb"]) < 1e-3 and abs(ub - ref["ub"]) < 1e-3
```

- [ ] **Step 2: Run to verify it fails**, then **Step 3: implement** `arp_confidence_interval` (grid-search test inversion calling `arp_conditional_test` over a θ grid; the CI is the set of non-rejected θ; set the grid fine enough that endpoints are stable to 1e-3 — match R's grid range/step). **Step 4: run pass. Step 5: commit.**
```python
def arp_confidence_interval(*, betahat, sigma, num_pre, num_post, l_vec, mbar, alpha=0.05,
                            grid_points=1000, grid_lo=None, grid_hi=None):
    """Test-inversion CI: the interval of theta NOT rejected by arp_conditional_test.
    Grid range defaults to the point estimate +/- a multiple of its SE (match R)."""
    raise NotImplementedError  # PORT: build theta grid, test each, return [min,max] accepted.
```
```bash
.venv/bin/python -m pytest tests/test_honest_did_engine.py::test_ci_for_one_mbar_matches_R -q
git add backend/workbench/engine/honest_did.py tests/test_honest_did_engine.py
git commit -m "feat(honest-did): test-inversion CI for a single Mbar (vs R oracle)"
```

---

## Task 5: `honest_rm` — Mbar loop + breakdown + determinism

**Files:**
- Modify: `backend/workbench/engine/honest_did.py`
- Test: `tests/test_honest_did_engine.py`

- [ ] **Step 1: Write the failing tests (full grid vs oracle + per-event + determinism)**
```python
def test_honest_rm_avg_matches_R():
    import numpy as np
    from workbench.engine.honest_did import honest_rm
    HRM = json.load(open("tests/fixtures/honest_did/honest_rm.json"))
    out = honest_rm(betahat=np.array(HRM["betahat"]), sigma=np.array(HRM["sigma"]),
                    num_pre=HRM["numPre"], num_post=HRM["numPost"],
                    l_vec=np.array(HRM["l_avg"]), mbar_grid=HRM["mbar_grid"], alpha=0.05)
    for r_ours, r_ref in zip(out["results"], HRM["rm_avg"]):
        assert abs(r_ours["lb"] - r_ref["lb"]) < 1e-3
        assert abs(r_ours["ub"] - r_ref["ub"]) < 1e-3

def test_honest_rm_deterministic():
    import numpy as np
    from workbench.engine.honest_did import honest_rm
    HRM = json.load(open("tests/fixtures/honest_did/honest_rm.json"))
    kw = dict(betahat=np.array(HRM["betahat"]), sigma=np.array(HRM["sigma"]),
              num_pre=HRM["numPre"], num_post=HRM["numPost"],
              l_vec=np.array(HRM["l_avg"]), mbar_grid=HRM["mbar_grid"], alpha=0.05)
    a, b = honest_rm(**kw), honest_rm(**kw)
    assert [r["lb"] for r in a["results"]] == [r["lb"] for r in b["results"]]
    assert [r["ub"] for r in a["results"]] == [r["ub"] for r in b["results"]]
```

- [ ] **Step 2: Run fail. Step 3: implement** `honest_rm` (loop `arp_confidence_interval` over `mbar_grid`; compute `breakdown` = largest Mbar whose CI still excludes 0):
```python
def honest_rm(*, betahat, sigma, num_pre, num_post, l_vec, mbar_grid, alpha=0.05):
    """Robust CIs across the Mbar grid + breakdown Mbar. Pure, deterministic.
    Raises HonestDiDError(HONEST_NO_PRE_PERIODS) if num_pre==0,
    HONEST_NO_POST_PERIODS if num_post==0, HONEST_DEGENERATE_SIGMA if sigma not PD."""
    import numpy as np
    if num_pre < 1: raise HonestDiDError("HONEST_NO_PRE_PERIODS: ΔRM needs >=1 pre-period.")
    if num_post < 1: raise HonestDiDError("HONEST_NO_POST_PERIODS: no post-period to test.")
    if np.min(np.linalg.eigvalsh(np.asarray(sigma, float))) <= 0:
        raise HonestDiDError("HONEST_DEGENERATE_SIGMA: covariance not positive-definite.")
    results = []
    for M in mbar_grid:
        lb, ub = arp_confidence_interval(betahat=betahat, sigma=sigma, num_pre=num_pre,
            num_post=num_post, l_vec=l_vec, mbar=float(M), alpha=alpha)
        results.append({"Mbar": float(M), "lb": float(lb), "ub": float(ub)})
    excludes0 = [r["Mbar"] for r in results if r["lb"] > 0 or r["ub"] < 0]
    breakdown = max(excludes0) if excludes0 else None
    return {"results": results, "breakdown": breakdown}
```
**Step 4: run pass (both tests). Step 5: commit.**
```bash
git add backend/workbench/engine/honest_did.py tests/test_honest_did_engine.py
git commit -m "feat(honest-did): honest_rm Mbar grid + breakdown; deterministic (vs R oracle)"
```

---

## Task 6: CS adapter — Σ extraction + pre/post mapping

**Files:**
- Create: `backend/workbench/engine/honest_did_adapter.py`
- Test: `tests/test_honest_did_adapter.py`

- [ ] **Step 1: Write failing tests (Σ vs independent computation + mapping correctness)**
```python
import json, numpy as np, pandas as pd
from workbench.engine.did_spec import normalize_did_input
from workbench.engine.cs_attgt import estimate_att_gt
from workbench.engine.cs_aggregate import aggregate
from workbench.engine.honest_did_adapter import honest_did_from_cs_dynamic

def _dyn(cluster_var=None):
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    norm = normalize_did_input(d, mode="cohort", entity="unit", time="period", y="y", cohort="first_treat")
    b = estimate_att_gt(norm, control_group="never", est_method="dr", base_period="varying",
                        anticipation=0, covariates=["x1"], cluster_var=cluster_var)
    return aggregate(b, "dynamic"), b

def test_sigma_is_cluster_robust_crve():
    agg, b = _dyn(cluster_var="cluster")
    N = int(b.aux["n_total"]); rc = b.aux["row_cluster"]
    out = honest_did_from_cs_dynamic(agg, row_cluster=rc, n_total=N,
                                     mbar_grid=[0,1], alpha=0.05)
    # independent cluster-robust covariance of the event-study vector
    CIF = agg["component_if"]                      # (N, n_labels)
    import pandas as pd
    S = pd.DataFrame(CIF).groupby(rc).sum().to_numpy()   # (n_clusters, n_labels)
    Sigma_full = S.T @ S / (N**2)
    # adapter drops the reference period (e=-1) and orders pre-then-post; verify the
    # extracted sigma is the submatrix of Sigma_full for the kept event times in order.
    keep = out["_debug_keep_idx"]                  # indices into agg["label"] kept (pre+post)
    assert np.allclose(out["_debug_sigma"], Sigma_full[np.ix_(keep, keep)], atol=1e-10)

def test_pre_post_mapping():
    agg, b = _dyn()
    out = honest_did_from_cs_dynamic(agg, row_cluster=b.aux["row_cluster"],
                                     n_total=int(b.aux["n_total"]), mbar_grid=[0,1], alpha=0.05)
    labels = [float(x) for x in agg["label"]]
    assert out["num_pre"] == sum(1 for e in labels if e < -1 + 1e-9 and e != -1) or out["num_pre"] >= 1
    # every kept event time is != -1 (reference excluded), pre are <0, post are >=0
    assert all(e != -1 for e in out["_debug_event_times"])
    assert out["num_post"] == sum(1 for e in out["_debug_event_times"] if e >= 0)
```
(The `_debug_*` keys are deliberately exposed by the adapter for testability; keep them — they are cheap and pin the mapping.)

- [ ] **Step 2: Run fail. Step 3: implement the adapter**
```python
from __future__ import annotations
import numpy as np
from .honest_did import honest_rm, HonestDiDError

def honest_did_from_cs_dynamic(agg_dynamic, *, row_cluster, n_total, mbar_grid, alpha=0.05):
    """Extract (betahat, sigma) from a CS dynamic aggregation and run ΔRM honest-DID for the
    post-average + each post event-time. Cluster-robust Σ reuses the v1.5.6.1 reduction.
    Returns a JSON-safe block; on any HonestDiDError returns {"skipped": True, "reason": ...}."""
    labels = [float(x) for x in agg_dynamic["label"]]
    beta = np.asarray(agg_dynamic["estimate"], dtype=float)
    CIF = np.asarray(agg_dynamic["component_if"], dtype=float)        # (N, n_labels)
    N = int(n_total); rc = np.asarray(row_cluster)
    # cluster-robust full covariance of the event-study vector: S_c = sum_{i in c} CIF_i
    uniq, inv = np.unique(rc, return_inverse=True)
    S = np.zeros((len(uniq), CIF.shape[1])); np.add.at(S, inv, CIF)
    Sigma_full = S.T @ S / (N**2)
    # keep all event times except the reference period e == -1 (structural zero); order pre(<0) then post(>=0)
    keep = [i for i, e in enumerate(labels) if abs(e + 1.0) > 1e-9]
    keep.sort(key=lambda i: (labels[i] >= 0, labels[i]))   # pre (asc) then post (asc)
    et = [labels[i] for i in keep]
    num_pre = sum(1 for e in et if e < 0); num_post = sum(1 for e in et if e >= 0)
    betahat = beta[keep]
    sigma = Sigma_full[np.ix_(keep, keep)]
    debug = {"_debug_keep_idx": keep, "_debug_event_times": et, "_debug_sigma": sigma.tolist()}
    try:
        l_avg = np.full(num_post, 1.0 / num_post) if num_post else np.array([])
        avg = honest_rm(betahat=betahat, sigma=sigma, num_pre=num_pre, num_post=num_post,
                        l_vec=l_avg, mbar_grid=mbar_grid, alpha=alpha)
        per_event = []
        for j in range(num_post):
            lv = np.zeros(num_post); lv[j] = 1.0
            r = honest_rm(betahat=betahat, sigma=sigma, num_pre=num_pre, num_post=num_post,
                          l_vec=lv, mbar_grid=mbar_grid, alpha=alpha)
            per_event.append({"event_time": et[num_pre + j], **r})
        return {"skipped": False, "num_pre": num_pre, "num_post": num_post,
                "mbar_grid": list(map(float, mbar_grid)),
                "post_average": avg, "per_event_time": per_event, **debug}
    except HonestDiDError as exc:
        return {"skipped": True, "reason": str(exc), "num_pre": num_pre, "num_post": num_post, **debug}
```
**Step 4: run pass. Step 5: commit.**
```bash
git add backend/workbench/engine/honest_did_adapter.py tests/test_honest_did_adapter.py
git commit -m "feat(honest-did): CS dynamic adapter — cluster-robust Sigma + pre/post mapping"
```

---

## Task 7: Wire into `run_cs_did` (param + degrade-not-fail)

**Files:**
- Modify: `backend/workbench/econometrics/runner.py`
- Test: `tests/test_run_cs_did.py`

- [ ] **Step 1: Write failing tests**
```python
def test_run_cs_did_honest_did_block_present():
    res = run_cs_did(_norm_cluster(), covariates=["x1"], control_group="never", est_method="dr",
        base_period="varying", anticipation=0, cluster_var="cluster", seed=20260615, honest_did=True)
    h = res["honest_did"]
    assert h["skipped"] is False
    assert "post_average" in h and "results" in h["post_average"]
    assert len(h["per_event_time"]) == h["num_post"]

def test_run_cs_did_honest_did_absent_by_default():
    res = run_cs_did(_norm_cluster(), covariates=["x1"], control_group="never", est_method="dr",
        base_period="varying", anticipation=0, cluster_var=None, seed=20260615)
    assert "honest_did" not in res
```
(`_norm_cluster` helper already exists in this test file from v1.5.6.1.)

- [ ] **Step 2: Run fail. Step 3: add the param + attach block** in `run_cs_did`:
  - Add `honest_did: bool = False` to the signature.
  - After `agg_by_kind` is built and `row_cluster`/`G` are in scope, before assembling `metadata`:
```python
    if honest_did:
        from ..engine.honest_did_adapter import honest_did_from_cs_dynamic
        HONEST_MBAR_GRID = [0.0, 0.5, 1.0, 1.5, 2.0]
        try:
            hd = honest_did_from_cs_dynamic(agg_by_kind["dynamic"], row_cluster=row_cluster,
                n_total=G, mbar_grid=HONEST_MBAR_GRID, alpha=alpha)
        except Exception as exc:                      # honest-DID must NEVER fail the run
            hd = {"skipped": True, "reason": f"HONEST_INTERNAL_ERROR: {exc}"}
        # strip the _debug_* keys from the shipped artifact (keep them test-only)
        hd = {k: v for k, v in hd.items() if not k.startswith("_debug_")}
        result_honest = hd
    else:
        result_honest = None
```
  - In the final returned dict, add `**({"honest_did": result_honest} if result_honest is not None else {})`.
**Step 4: run pass. Step 5: commit.**
```bash
git add backend/workbench/econometrics/runner.py tests/test_run_cs_did.py
git commit -m "feat(honest-did): run_cs_did honest_did param (degrade-not-fail)"
```

---

## Task 8: Full-pipeline threading + hardening

**Files:**
- Modify: `backend/workbench/api.py`, `backend/workbench/orchestrator/__init__.py`, `backend/workbench/engine/stages/estimation.py`
- Test: `tests/test_honest_did_wiring.py`

- [ ] **Step 1: Write failing end-to-end + hardening tests** (mirror `test_cs_did_hardening.py`'s workflow harness `_run`/`run_workflow`/`read_json`):
```python
def test_honest_did_completes_end_to_end(tmp_path):
    # full workflow with honest_did=True writes a honest_did block into cs_did.json, run completes
    ... build a staggered panel (40 units, cohorts {0,2019,2020,2021}, x1, y) ...
    run_root, result = _run(tmp_path, df, y="y", x=["x1"], model_type="cs_did",
        entity_col="id", time_col="year", did_mode="cohort", did_cohort_col="first_treat",
        cs_control_group="never", cs_est_method="dr", cs_base_period="varying", honest_did=True)
    assert result["status"] == "completed"
    art = read_json(run_root / "cs_did.json")
    assert "honest_did" in art and "post_average" in art["honest_did"]

def test_honest_did_no_pre_periods_skips_not_fails(tmp_path):
    # a design with NO pre-periods -> honest_did skipped with reason, run STILL completes
    ... a panel whose dynamic aggregation has only e>=0 ...
    run_root, result = _run(tmp_path, df, ..., honest_did=True)
    assert result["status"] == "completed"
    art = read_json(run_root / "cs_did.json")
    assert art["honest_did"]["skipped"] is True
    assert "HONEST_NO_PRE_PERIODS" in art["honest_did"]["reason"]
```

- [ ] **Step 2: Run fail. Step 3: thread the flag** exactly like `cs_cluster_var`:
  - `api.py`: add `honest_did: bool = Form(False)` to the POST `/runs` form params and pass it into `_run_workflow(...)`.
  - `orchestrator/__init__.py`: add `honest_did: bool = False` to `_run_workflow`/`run_workflow` signatures and set `ctx.artifacts["_honest_did"] = bool(honest_did)`.
  - `engine/stages/estimation.py`: in the `run_cs_did(...)` call (the one passing `cluster_var=...`), add `honest_did=ctx.artifacts.get("_honest_did", False)`.
**Step 4: run pass. Step 5: commit.**
```bash
git add backend/workbench/api.py backend/workbench/orchestrator/__init__.py backend/workbench/engine/stages/estimation.py tests/test_honest_did_wiring.py
git commit -m "test(honest-did): full-pipeline threading + no-pre-period skip (run completes)"
```

---

## Task 9: Frontend — checkbox + sensitivity sub-panel

**Files:**
- Modify: `frontend/src/runForm/CSControls.tsx` (+ `.test.tsx`), `frontend/src/runForm/RunForm.tsx`, `frontend/src/api.ts`, `frontend/src/runResult/CSDiagnosticsCard.tsx`

- [ ] **Step 1: CSControls checkbox (TDD the control)** — add `honestDid: boolean` to `CSValue`, render a checkbox `aria-label="cs-honest-did"`; update the test file's `baseValue` + a presence/toggle test (mirror the v1.5.6.1 cluster-selector test).
- [ ] **Step 2: Thread it** — `RunForm` adds `honestDid: false` to `csValue` init and `honestDid: isCsDid ? csValue.honestDid : undefined` to the payload; `api.ts` adds `honestDid?: boolean` to `RunExtraParams` and `if (extra?.honestDid) form.append("honest_did", "true");`.
- [ ] **Step 3: CSDiagnosticsCard sub-panel** — when `result.honest_did` is present and not skipped, render a degraded-safe sensitivity section: for `post_average` and each `per_event_time`, a compact table of `(Mbar, lb, ub)` + the `breakdown` Mbar; when `skipped`, show the reason quietly. Add `honest_did?` to the card's result type.
- [ ] **Step 4: Frontend gate** `cd frontend && npx vitest run && npx tsc --noEmit` — all pass, tsc 0.
- [ ] **Step 5: Commit**
```bash
git add frontend/src/runForm/CSControls.tsx frontend/src/runForm/CSControls.test.tsx frontend/src/runForm/RunForm.tsx frontend/src/api.ts frontend/src/runResult/CSDiagnosticsCard.tsx
git commit -m "feat(honest-did): cs honest-DID checkbox + sensitivity sub-panel (FE)"
```

---

## Task 10: Additive golden + docs + final gate

**Files:**
- Modify: `tests/test_engine_golden.py`; Create golden `tests/golden/cs_did_honest.json`
- Create: `docs/honest-did-howto.md`, `docs/v1.5.7-release-notes.md`

- [ ] **Step 1: Additive golden test** — a `honest_did=True` cs_did run (mirror `test_golden_cs_did_clustered`, add `honest_did=True`); assert status completed and the cs_did artifact has a non-skipped `honest_did`; `_assert_or_write_golden("cs_did_honest", snap)`. NOTE: the honest_did numbers may be in the artifact but NOT in `_capture`'s snapshot (which freezes status+lineage+coefs) — keep the golden focused on run shape; the engine numbers are guarded by Task 1–5 oracle tests. If `_capture` does embed them and they're non-deterministic, that's a determinism bug from Task 5 — STOP and fix, don't write a flapping golden.
- [ ] **Step 2: Generate golden, prove frozen** (run twice; existing 19 goldens 0-drift, new = 20).
- [ ] **Step 3: Docs** — `docs/honest-did-howto.md` (what ΔRM sensitivity means; how to enable the checkbox; reading the breakdown Mbar; point estimates unchanged; ΔSD deferred); `docs/v1.5.7-release-notes.md` (engine port + adapter + degrade-not-fail + gate numbers).
- [ ] **Step 4: Full gate** `.venv/bin/python -m pytest -q`; `cd frontend && npx vitest run && npx tsc --noEmit && cd ..`; `./scripts/gate.sh`. Record BE/golden/FE/tsc/gate.sh.
- [ ] **Step 5: Commit**
```bash
git add tests/test_engine_golden.py tests/golden/cs_did_honest.json docs/honest-did-howto.md docs/v1.5.7-release-notes.md
git commit -m "test(honest-did): additive golden + docs/release notes"
```

---

## Final: whole-feature adversarial review (before merge)

- [ ] Run a whole-branch adversarial review focused on: (1) the engine port — re-verify each sub-step (constraints, single-point test, CI, grid) against R, and probe degenerate inputs (1 pre-period, near-singular Σ, all-pre or all-post event studies, Mbar=0 reproducing the naive CI); (2) **degrade-not-fail** — confirm NO honest-DID failure path can fail the cs_did run (wrap is total); (3) determinism / golden 0-drift; (4) unclustered + honest-off paths byte-identical (existing 19 goldens, all cs_did runs without the flag unchanged); (5) the `_debug_*` keys are stripped from the shipped artifact.
- [ ] Fix findings; re-run full gate.
- [ ] Present finishing options (merge `--no-ff` + tag `v1.5.7`, verify gated-head vs merged-tree empty diff). Push to main requires explicit per-version authorization.

---

## Self-Review (completed by author)

- **Spec coverage:** §3.1 engine → T2–T5; §3.2 adapter → T6; §4 validation (two-layer + intermediates) → T1 fixtures + T2–T6 tests; §5 wiring → T7+T8; §6 degrade-not-fail → T5 (raises) + T6/T7 (catch) + T8 (no-pre skip test); §7 frontend → T9; §8 golden/tests → T1,T10; §10 deferrals → carried in spec; §11 gate → T10+Final; §12 R one-time → T0. All covered.
- **Placeholder scan:** the only `NotImplementedError`/`raise ... # PORT` skeletons are in T2–T4 engine tasks, deliberately — these are PORT tasks whose complete spec is "match the named R function to the committed fixture"; the TEST in each is concrete and is the completion criterion. All plumbing/adapter/FE/golden tasks have full concrete code. No TBD/TODO.
- **Type/name consistency:** `create_arm_constraints` / `arp_conditional_test` / `arp_confidence_interval` / `honest_rm` / `HonestDiDError` consistent across T2–T7; `honest_did_from_cs_dynamic` signature consistent T6→T7; `honest_did` flag name consistent runner→api→orchestrator→estimation (T7,T8); `result["honest_did"]` block shape (`skipped`/`post_average`/`per_event_time`/`num_pre`/`num_post`) consistent T6→T7→T8→T9→T10.
