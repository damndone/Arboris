# honest-DID ΔSD / FLCI (v1.5.7.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Rambachan-Roth ΔSD (smoothness) sensitivity family to the shipped honest-DID feature, inferred via FLCI (fixed-length confidence interval) convex optimization, as a second track alongside the existing ΔRM test-inversion path.

**Architecture:** Estimator-agnostic engine additions in `engine/honest_did.py` (second-difference operator ported from R, folded-normal critical value, per-h convex QP, `flci`/`honest_sd` entries), surfaced through the existing `honest_did_adapter` (frozen Σ snapshot → run both `honest_rm` and `honest_sd`) and `runner.run_cs_did` (same `honest_did` flag now emits a nested `{rm, sd}` block with a `status`/`reason` failure taxonomy), rendered three-state in `CSDiagnosticsCard`.

**Tech Stack:** Python 3.11, NumPy, SciPy (`linalg.solve`, `optimize.minimize` SLSQP, `optimize.brentq`, `stats.norm`); React/TypeScript + vitest; R `HonestDiD` 0.2.8 for committed JSON oracles only (already installed; no new R packages).

**Spec:** `docs/superpowers/specs/2026-06-19-workbench-v1.5.7.1-honest-did-sd-flci-design.md`

**Conventions carried from v1.5.7 (do not relitigate):**
- Σ ordered **pre (event time < 0) then post (≥ 0), excluding the reference e = −1**.
- All honest-DID degeneracies **degrade, never fail the run**: engine raises `HonestDiDError`; adapter catches → `status`/`reason`; runner wraps `except Exception`.
- Engine numbers validated by R oracle tests; **golden freezes only `status`/`artifacts`/`coef`, never honest-DID numbers**.
- Gate via `./scripts/gate.sh` from the worktree root. **Never** bare `pytest` for the suite (use `.venv/bin/python -m pytest`). FE gate = `cd frontend && npx vitest run && npx tsc --noEmit`.
- R is used only to (re)generate committed JSON fixtures; the test suite never invokes R.

---

## Target JSON contract (the shape every task builds toward)

`run_root/cs_did.json` `honest_did` block after this version:

```json
"honest_did": {
  "rm": {
    "status": "ok",
    "reason": null,
    "num_pre": 2, "num_post": 4,
    "mbar_grid": [0.0, 0.5, 1.0, 1.5, 2.0],
    "post_average":  { "results": [{"Mbar": 0.0, "lb": -0.1, "ub": 0.2}], "breakdown": null },
    "per_event_time": [{ "event_time": 0.0, "results": [{"Mbar": 0.0, "lb": -0.1, "ub": 0.2}], "breakdown": null }]
  },
  "sd": {
    "status": "ok",
    "reason": null,
    "method": "FLCI",
    "num_pre": 2, "num_post": 4,
    "m_grid": [0.0, 0.011, 0.022, 0.033, 0.044],
    "scale": 0.022,
    "post_average":  { "results": [{"M": 0.0, "lb": -0.1, "ub": 0.2}], "breakdown": null },
    "per_event_time": [{ "event_time": 0.0, "results": [{"M": 0.0, "lb": -0.1, "ub": 0.2}], "breakdown": null }]
  }
}
```

- `status ∈ {"ok", "degraded", "not_available"}`. `not_available` = a deterministic guard fired (e.g. `HONEST_SD_INSUFFICIENT_PERIODS`); `degraded` = an unexpected error was contained. Both carry a `reason` string; `status:"ok"` → `reason: null`.
- RM results key is `"Mbar"`; SD results key is `"M"` (different parameters; the FE table is parameterized over the key).
- Both `rm` and `sd` are **always present**. Non-finite numbers serialize to `null` (existing `_json_safe`).
- A shared top-level `_debug_*` snapshot (Σ, kept indices, event times) lives in the adapter return and is stripped by the runner — it is the single frozen statistics snapshot both tracks read.

---

## Task 0: Worktree, environment, baseline gate

**Files:** none (environment only)

- [ ] **Step 1: Confirm the plan + spec are committed on local main**

Run: `git -C /Users/jiayuanren/项目规划 log --oneline -3`
Expected: the v1.5.7.1 spec commit (`docs(v1.5.7.1): ... design spec`) and this plan commit are present on `main`, on top of `c2a9c08`.

- [ ] **Step 2: Create the isolated worktree off local main**

```bash
cd /Users/jiayuanren/项目规划
git worktree add -b workbench-v1.5.7.1 .worktrees/workbench-v1.5.7.1 main
```
Expected: worktree created at `.worktrees/workbench-v1.5.7.1` on branch `workbench-v1.5.7.1`.

- [ ] **Step 3: Build the backend venv (full extras)**

```bash
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.5.7.1
~/.local/bin/python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev,panel,ml,imbalanced,imputation]"
```
Expected: install completes; `linearmodels`, `scikit-learn`, `statsmodels` present.

- [ ] **Step 4: Build the frontend deps**

```bash
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.5.7.1/frontend
npm install
```
Expected: `node_modules` populated.

- [ ] **Step 5: Verify R HonestDiD is importable (oracle prerequisite)**

Run: `Rscript -e 'library(HonestDiD); packageVersion("HonestDiD")'`
Expected: prints `0.2.8` (toolchain + package persist outside the worktree from v1.5.7). If it fails, the v1.5.7 progress note records the fix: `brew install rust cmake gmp glpk` then reinstall with `CPPFLAGS`/`LDFLAGS`/`PKG_CONFIG_PATH` pointing at `/opt/homebrew`.

- [ ] **Step 6: Run the baseline gate (must be green before any change)**

```bash
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.5.7.1
./scripts/gate.sh
```
Expected: GATE PASSED — BE 989 / golden 20 (0-drift) / FE 624 / tsc 0 (the v1.5.7 ship baseline).

---

## Task 1: R oracle — port input + ΔSD/FLCI fixtures

Generate committed JSON oracles from R `HonestDiD` for: (a) the `.create_A_SD` constraint matrix (operator correctness), (b) `findOptimalFLCI` over an M-grid (the FLCI numbers). Reuse the existing fixture dataset/Σ from v1.5.7 so the engine tests share one covariance.

**Files:**
- Modify: `tests/fixtures/honest_did/generate_oracle.R`
- Create (generated): `tests/fixtures/honest_did/a_sd.json`, `tests/fixtures/honest_did/flci_sd.json`

- [ ] **Step 1: Read the existing oracle generator and the installed R source**

Run:
```bash
sed -n '1,80p' /Users/jiayuanren/项目规划/.worktrees/workbench-v1.5.7.1/tests/fixtures/honest_did/generate_oracle.R
ls /opt/homebrew/lib/R/4.6/site-library/HonestDiD/R/
```
Read `HonestDiD`'s `R/` sources for the **exact** signatures + internals of `createSensitivityResults`, `findOptimalFLCI`, `.findOptimalFLCI_helper`, and `.create_A_SD`. Note in particular: how `.create_A_SD(numPrePeriods, numPostPeriods)` inserts the reference period (the second differences are taken over the augmented integer grid with the reference period at 0), and the **h-grid bounds + `numPoints`** used inside `.findOptimalFLCI_helper`. These two facts drive Tasks 2 and 4.

- [ ] **Step 2: Append the ΔSD oracle generation to `generate_oracle.R`**

Reuse the same `betahat`/`sigma`/`numPrePeriods`/`numPostPeriods` already defined for the ΔRM fixtures. Append:

```r
# ---- ΔSD / FLCI oracle (v1.5.7.1) ----
library(jsonlite)

# (a) the ΔSD second-difference constraint operator
A_sd <- HonestDiD:::.create_A_SD(numPrePeriods = numPrePeriods,
                                 numPostPeriods = numPostPeriods)
write_json(list(numPrePeriods = numPrePeriods,
                numPostPeriods = numPostPeriods,
                A_sd = A_sd),
           "tests/fixtures/honest_did/a_sd.json",
           digits = 16, matrix = "rowmajor", auto_unbox = TRUE)

# (b) FLCI over an M grid for the post-period average target
l_avg <- rep(1 / numPostPeriods, numPostPeriods)
Mvec  <- c(0, 0.5, 1.0, 1.5, 2.0) * max(sqrt(diag(sigma)))   # mirror engine scaling
flci_rows <- lapply(Mvec, function(M) {
  r <- HonestDiD::findOptimalFLCI(betahat = betahat, sigma = sigma,
                                  numPrePeriods = numPrePeriods,
                                  numPostPeriods = numPostPeriods,
                                  l_vec = l_avg, M = M, alpha = 0.05)
  list(M = M,
       optimalHalfLength = r$optimalHalfLength,
       lb = r$FLCI[1], ub = r$FLCI[2])
})
write_json(list(l_vec = l_avg, alpha = 0.05, Mvec = Mvec, results = flci_rows),
           "tests/fixtures/honest_did/flci_sd.json",
           digits = 16, auto_unbox = TRUE)
```

(If `findOptimalFLCI`'s return field names differ in 0.2.8, use the names found in Step 1; the three values needed are the optimal half-length and the two CI endpoints.)

- [ ] **Step 3: Generate the fixtures**

```bash
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.5.7.1
Rscript tests/fixtures/honest_did/generate_oracle.R
```
Expected: `a_sd.json` and `flci_sd.json` created, both with finite numbers.

- [ ] **Step 4: Commit the oracle**

```bash
git add tests/fixtures/honest_did/generate_oracle.R tests/fixtures/honest_did/a_sd.json tests/fixtures/honest_did/flci_sd.json
git commit -m "test(honest-did): ΔSD operator + FLCI R oracles (v1.5.7.1)"
```

---

## Task 2: ΔSD second-difference operator `_create_a_sd`

Port R's `.create_A_SD` and validate the matrix element-wise against `a_sd.json`. This is the operator whose L∞ ball defines Δ^SD; the FLCI dual (Task 4) is built from it.

**Files:**
- Modify: `backend/workbench/engine/honest_did.py`
- Test: `tests/test_honest_did_engine.py`

- [ ] **Step 1: Write the failing test**

```python
import json, numpy as np
from pathlib import Path
from workbench.engine.honest_did import _create_a_sd, HonestDiDError
import pytest

_FIX = Path(__file__).parent / "fixtures" / "honest_did"

def test_create_a_sd_matches_r_oracle():
    o = json.loads((_FIX / "a_sd.json").read_text())
    A = _create_a_sd(num_pre=o["numPrePeriods"], num_post=o["numPostPeriods"])
    expected = np.asarray(o["A_sd"], dtype=float)
    assert A.shape == expected.shape
    assert np.allclose(A, expected, atol=1e-9)

def test_create_a_sd_requires_three_total_periods():
    with pytest.raises(HonestDiDError, match="HONEST_SD_INSUFFICIENT_PERIODS"):
        _create_a_sd(num_pre=1, num_post=1)  # T=2 augmented < 3 -> rank-deficient
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.5.7.1 && .venv/bin/python -m pytest tests/test_honest_did_engine.py -k a_sd -v`
Expected: FAIL with `ImportError: cannot import name '_create_a_sd'`.

- [ ] **Step 3: Implement `_create_a_sd`**

Add to `engine/honest_did.py`. Match the R `.create_A_SD` row structure exactly (the test against `a_sd.json` is the ground truth — adjust the augmented-grid/reference handling until it matches):

```python
def _create_a_sd(*, num_pre: int, num_post: int) -> np.ndarray:
    """Second-difference operator for ΔSD, ported from R HonestDiD ``.create_A_SD``.

    Rows are the second differences of the trend over the integer event-time grid
    with the reference period (0) inserted. ``Δ^SD(M) = {δ : ‖A δ‖_∞ ≤ M}``.
    Validated element-wise against ``a_sd.json``.
    """
    num_pre = int(num_pre)
    num_post = int(num_post)
    # Augmented length includes the inserted reference period; second differences
    # need at least 3 augmented points to be non-empty / full row rank.
    if num_pre + num_post < 2 or (num_pre + num_post + 1) < 3:
        raise HonestDiDError(
            "HONEST_SD_INSUFFICIENT_PERIODS: ΔSD needs enough periods to bound "
            "second differences (effectively num_pre >= 2 for an identified FLCI)."
        )
    # Build the (num_pre+num_post+1)-length augmented integer grid with reference 0
    # at index num_pre, then second differences, then DROP the reference column.
    T_aug = num_pre + num_post + 1
    D = np.zeros((T_aug - 2, T_aug))
    for i in range(T_aug - 2):
        D[i, i] = 1.0
        D[i, i + 1] = -2.0
        D[i, i + 2] = 1.0
    ref_col = num_pre  # the inserted reference period
    A = np.delete(D, ref_col, axis=1)
    return A
```

NOTE: if the oracle test fails, the discrepancy is the reference-period convention. Inspect `a_sd.json`'s shape and a couple of rows, compare to the R source read in Task 1, and adjust (R may not drop the reference column, or may order differently). The oracle is authoritative.

- [ ] **Step 4: Run to verify pass**

Run: `cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.5.7.1 && .venv/bin/python -m pytest tests/test_honest_did_engine.py -k a_sd -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/honest_did.py tests/test_honest_did_engine.py
git commit -m "feat(honest-did): ΔSD second-difference operator (R .create_A_SD port)"
```

---

## Task 3: Folded-normal critical value `_folded_normal_quantile`

The FLCI half-length multiplier `c_α(t)` = the `(1−α)` quantile of `|N(t,1)|`. Implement via Brent root-find on `Φ(c−t) − Φ(−c−t) = 1−α`, with a monotone-enforcing cache to kill `argmin` jitter (spec §2.6).

**Files:**
- Modify: `backend/workbench/engine/honest_did.py`
- Test: `tests/test_honest_did_engine.py`

- [ ] **Step 1: Write the failing test**

```python
from workbench.engine.honest_did import _folded_normal_quantile
from scipy.stats import norm

def test_folded_normal_quantile_t0_is_standard_normal():
    # |N(0,1)| (1-alpha) quantile == standard two-sided z_{1-alpha/2}
    assert abs(_folded_normal_quantile(0.0, alpha=0.05) - norm.ppf(0.975)) < 1e-8

def test_folded_normal_quantile_strictly_increasing_in_t():
    ts = [0.0, 0.5, 1.0, 2.0, 5.0]
    vals = [_folded_normal_quantile(t, alpha=0.05) for t in ts]
    assert all(b > a for a, b in zip(vals, vals[1:]))

def test_folded_normal_quantile_satisfies_cdf_equation():
    t, c = 1.3, None
    c = _folded_normal_quantile(t, alpha=0.05)
    assert abs((norm.cdf(c - t) - norm.cdf(-c - t)) - 0.95) < 1e-8
```

- [ ] **Step 2: Run to verify failure**

Run: `... -m pytest tests/test_honest_did_engine.py -k folded -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement**

```python
from scipy.optimize import brentq
from scipy.stats import norm

def _folded_normal_quantile(t: float, *, alpha: float = 0.05) -> float:
    """(1-alpha) quantile of the folded normal |N(t,1)| (t >= 0 in practice).

    Root of g(c) = Φ(c-t) - Φ(-c-t) - (1-alpha) = 0, strictly increasing in c.
    """
    t = abs(float(t))
    target = 1.0 - alpha
    def g(c):
        return (norm.cdf(c - t) - norm.cdf(-c - t)) - target
    lo = norm.ppf(1.0 - alpha / 2.0)   # value at t=0 is a lower bound
    hi = lo + t + 10.0                 # generous upper bracket; g(hi) > 0
    return float(brentq(g, lo, hi, xtol=1e-12, rtol=1e-14))


def _folded_normal_quantile_monotone(ts) -> np.ndarray:
    """c_alpha over a sequence of t values, forced non-decreasing to remove
    sub-ULP solver noise that could perturb the outer argmin."""
    out = np.array([_folded_normal_quantile(t) for t in ts], dtype=float)
    return np.maximum.accumulate(out)
```

(If `alpha` must thread through `_folded_normal_quantile_monotone`, add it as a kwarg — Task 4 calls it with the run's alpha.)

- [ ] **Step 4: Run to verify pass**

Run: `... -m pytest tests/test_honest_did_engine.py -k folded -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/honest_did.py tests/test_honest_did_engine.py
git commit -m "feat(honest-did): folded-normal critical value (monotone-cached)"
```

---

## Task 4: FLCI single-M `flci`

Convex QP per h (min variance s.t. consistency equalities + L1 bias ≤ h/M) over a mirrored h-grid; half-length = `sqrt(minVar)·c_α(h/sqrt(minVar))`. Validate the FLCI endpoints + half-length against `flci_sd.json` at 1e-6, and the M=0 anchor against the classical CI.

**Files:**
- Modify: `backend/workbench/engine/honest_did.py`
- Test: `tests/test_honest_did_engine.py`

- [ ] **Step 1: Write the failing tests (oracle + M=0 anchor)**

```python
import json, numpy as np
from pathlib import Path
from scipy.stats import norm
from workbench.engine.honest_did import flci
_FIX = Path(__file__).parent / "fixtures" / "honest_did"

def _load_inputs():
    # Reuse the same betahat/sigma the ΔRM oracle uses. The generator records
    # them; load from whichever fixture carries them (e.g. honest_rm.json).
    o = json.loads((_FIX / "honest_rm.json").read_text())
    return np.asarray(o["betahat"], float), np.asarray(o["sigma"], float), \
           int(o["numPrePeriods"]), int(o["numPostPeriods"])

def test_flci_matches_r_oracle_over_m_grid():
    beta, sigma, npre, npost = _load_inputs()
    o = json.loads((_FIX / "flci_sd.json").read_text())
    l_vec = np.asarray(o["l_vec"], float)
    for row in o["results"]:
        r = flci(betahat=beta, sigma=sigma, num_pre=npre, num_post=npost,
                 l_vec=l_vec, m=row["M"], alpha=o["alpha"])
        assert abs(r["half_length"] - row["optimalHalfLength"]) < 1e-6
        assert abs(r["lb"] - row["lb"]) < 1e-6
        assert abs(r["ub"] - row["ub"]) < 1e-6

def test_flci_m_zero_is_classical_ci():
    beta, sigma, npre, npost = _load_inputs()
    l_vec = np.full(npost, 1.0 / npost)
    r = flci(betahat=beta, sigma=sigma, num_pre=npre, num_post=npost,
             l_vec=l_vec, m=0.0, alpha=0.05)
    post = beta[npre:]
    sd = float(np.sqrt(l_vec @ sigma[npre:, npre:] @ l_vec))
    center = float(l_vec @ post)
    assert abs(r["half_length"] - sd * norm.ppf(0.975)) < 1e-8
    assert abs(r["lb"] - (center - sd * norm.ppf(0.975))) < 1e-8
```

- [ ] **Step 2: Run to verify failure**

Run: `... -m pytest tests/test_honest_did_engine.py -k flci -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement `flci`**

```python
from scipy.linalg import solve as _linsolve
from scipy.optimize import minimize

def _flci_bias_map(num_pre: int, num_post: int) -> np.ndarray:
    """B such that maxBias(w_full) = M * ||B w_full||_1 for Δ^SD.
    B = (A A^T)^{-1} A, A = ΔSD operator. Built via linear solve, never inverse."""
    A = _create_a_sd(num_pre=num_pre, num_post=num_post)   # (k x T)
    gram = A @ A.T                                          # (k x k), SPD
    return _linsolve(gram, A, assume_a="pos")              # = (A A^T)^{-1} A

def flci(*, betahat, sigma, num_pre, num_post, l_vec, m, alpha=0.05,
         h_points: int = 100) -> dict:
    """Fixed-Length CI for the target l'τ_post under Δ^SD(m). Faithful to R
    HonestDiD findOptimalFLCI; validated to 1e-6. Deterministic (no MC/bootstrap)."""
    betahat = np.asarray(betahat, float).reshape(-1)
    sigma = np.asarray(sigma, float)
    l_vec = np.asarray(l_vec, float).reshape(-1)
    p, q = int(num_pre), int(num_post)
    T = p + q
    center = float(l_vec @ betahat[p:])
    z = norm.ppf(1.0 - alpha / 2.0)
    sd_post = float(np.sqrt(l_vec @ sigma[p:, p:] @ l_vec))

    if m == 0.0:                       # classical CI anchor (no bias term)
        hl = sd_post * z
        return {"half_length": hl, "lb": center - hl, "ub": center + hl}

    B = _flci_bias_map(p, q)           # (k x T)
    # constant + linear vectors over the integer event grid (reference 0 dropped)
    grid = np.array([i - p for i in range(T + 1) if (i - p) != 0
                     ], dtype=float)[:T] if False else \
           np.array([e for e in range(-p, q + 1) if e != 0], dtype=float)
    one = np.ones(T)

    def w_full(w_pre):
        return np.concatenate([-w_pre, l_vec])

    def variance(w_pre):
        w = w_full(w_pre); return float(w @ sigma @ w)

    def var_grad(w_pre):
        w = w_full(w_pre)
        g = 2.0 * (sigma @ w)
        return -g[:p]                  # d/d w_pre of w' Σ w  (w_pre enters as -)

    cons_eq = (
        {"type": "eq", "fun": lambda wp: float(one @ w_full(wp))},
        {"type": "eq", "fun": lambda wp: float(grid @ w_full(wp))},
    )

    def min_variance_given_h(h):
        # min variance s.t. ||B w_full||_1 <= h/m  and consistency equalities
        l1_cap = h / m
        ineq = {"type": "ineq",
                "fun": lambda wp: l1_cap - float(np.abs(B @ w_full(wp)).sum())}
        res = minimize(variance, x0=np.zeros(p), jac=var_grad,
                       constraints=(*cons_eq, ineq), method="SLSQP",
                       options={"ftol": 1e-12, "maxiter": 500})
        if not res.success:
            return np.inf
        return max(res.fun, 0.0)

    # mirror R's h-grid (read bounds from R source in Task 1); a robust default:
    h_grid = np.linspace(1e-6, max(8.0 * sd_post, 1e-3), h_points)
    var_h = np.array([min_variance_given_h(h) for h in h_grid])
    sd_h = np.sqrt(var_h)
    finite = np.isfinite(sd_h) & (sd_h > 0)
    if not finite.any():
        raise HonestDiDError("HONEST_FLCI_OPT_FAILED: no feasible h on the grid.")
    t_h = np.where(finite, h_grid / np.where(sd_h > 0, sd_h, 1.0), np.inf)
    cv = _folded_normal_quantile_monotone(t_h[finite], alpha=alpha)
    hl_candidates = sd_h[finite] * cv
    hl = float(hl_candidates.min())
    return {"half_length": hl, "lb": center - hl, "ub": center + hl}
```

KEY VALIDATION GATE: the 1e-6 match depends on mirroring R's **h-grid bounds + `numPoints`** (R reports the grid minimum, not the continuous optimum). If `test_flci_matches_r_oracle_over_m_grid` fails by more than 1e-6, replace `h_grid` bounds and `h_points` with the exact values from R's `.findOptimalFLCI_helper` (read in Task 1). Convexity guarantees `min_variance_given_h` matches R's per-h QP to optimizer tolerance, so any residual gap is the grid, not the QP. The `grid` (linear-trend) vector uses consecutive integer event times with the reference omitted, matching R's count-only `.create_A_SD`.

- [ ] **Step 4: Run to verify pass**

Run: `... -m pytest tests/test_honest_did_engine.py -k flci -v`
Expected: PASS (oracle + M=0 anchor). Iterate the h-grid per the note if the oracle test fails.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/honest_did.py tests/test_honest_did_engine.py
git commit -m "feat(honest-did): FLCI single-M (convex QP, R findOptimalFLCI port)"
```

---

## Task 5: Public entry `honest_sd`

M-grid loop + breakdown + guards, mirroring `honest_rm`'s shape (`{"results":[...], "breakdown":...}`) but with the `"M"` key.

**Files:**
- Modify: `backend/workbench/engine/honest_did.py`
- Test: `tests/test_honest_did_engine.py`

- [ ] **Step 1: Write the failing test**

```python
from workbench.engine.honest_did import honest_sd, HonestDiDError
import pytest

def test_honest_sd_shape_and_breakdown():
    beta, sigma, npre, npost = _load_inputs()
    l = np.full(npost, 1.0 / npost)
    s = float(np.sqrt(np.diag(sigma)).max())
    m_grid = [0.0, 0.5 * s, 1.0 * s, 1.5 * s, 2.0 * s]
    out = honest_sd(betahat=beta, sigma=sigma, num_pre=npre, num_post=npost,
                    l_vec=l, m_grid=m_grid, alpha=0.05)
    assert [r["M"] for r in out["results"]] == [float(m) for m in m_grid]
    assert all(np.isfinite(r["lb"]) and np.isfinite(r["ub"]) for r in out["results"])
    assert ("breakdown" in out)

def test_honest_sd_insufficient_pre_periods_raises():
    beta, sigma, _, _ = _load_inputs()
    with pytest.raises(HonestDiDError, match="HONEST_SD_INSUFFICIENT_PERIODS"):
        honest_sd(betahat=beta[:2], sigma=sigma[:2, :2], num_pre=1, num_post=1,
                  l_vec=np.array([1.0]), m_grid=[0.0, 1.0], alpha=0.05)
```

- [ ] **Step 2: Run to verify failure**

Run: `... -m pytest tests/test_honest_did_engine.py -k honest_sd -v`
Expected: FAIL with ImportError.

- [ ] **Step 3: Implement**

```python
def honest_sd(*, betahat, sigma, num_pre, num_post, l_vec, m_grid,
              alpha: float = 0.05, h_points: int = 100) -> dict:
    """Robust ΔSD (smoothness) confidence sets via FLCI across the M grid.

    Returns {"results": [{"M","lb","ub"}...], "breakdown": float|None}.
    breakdown = largest M whose FLCI still EXCLUDES 0; None if none do.
    Degrades via HonestDiDError on:
      HONEST_SD_INSUFFICIENT_PERIODS  (num_pre < 2: ΔSD non-identifiable; see spec §2.3)
      HONEST_NO_POST_PERIODS          (num_post < 1)
      HONEST_DEGENERATE_SIGMA         (non-finite / not positive-definite)
    """
    if num_pre < 2:
        raise HonestDiDError(
            "HONEST_SD_INSUFFICIENT_PERIODS: ΔSD needs >=2 pre-periods to "
            "annihilate constant+linear trends (identifiability)."
        )
    if num_post < 1:
        raise HonestDiDError("HONEST_NO_POST_PERIODS: no post-period to test.")
    betahat = np.asarray(betahat, float).reshape(-1)
    sigma = np.asarray(sigma, float)
    if not (np.isfinite(sigma).all() and np.isfinite(betahat).all()):
        raise HonestDiDError("HONEST_DEGENERATE_SIGMA: non-finite sigma/betahat.")
    sigma_sym = 0.5 * (sigma + sigma.T)
    if float(np.linalg.eigvalsh(sigma_sym).min()) <= 0.0:
        raise HonestDiDError("HONEST_DEGENERATE_SIGMA: sigma not positive-definite.")
    l_vec = np.asarray(l_vec, float).reshape(-1)

    results = []
    for M in m_grid:
        r = flci(betahat=betahat, sigma=sigma, num_pre=num_pre, num_post=num_post,
                 l_vec=l_vec, m=float(M), alpha=alpha, h_points=h_points)
        results.append({"M": float(M), "lb": float(r["lb"]), "ub": float(r["ub"])})

    excludes0 = [r["M"] for r in results
                 if (r["lb"] == r["lb"] and r["ub"] == r["ub"])
                 and (r["lb"] > 0.0 or r["ub"] < 0.0)]
    return {"results": results, "breakdown": (max(excludes0) if excludes0 else None)}
```

- [ ] **Step 4: Run to verify pass**

Run: `... -m pytest tests/test_honest_did_engine.py -k honest_sd -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/honest_did.py tests/test_honest_did_engine.py
git commit -m "feat(honest-did): honest_sd ΔSD entry (M-grid + breakdown + guards)"
```

---

## Task 6: Adapter reshape to `{rm, sd}` + frozen snapshot + status taxonomy

Rework `honest_did_from_cs_dynamic` to compute Σ/keep/event-times **once** (frozen snapshot), then run both `honest_rm` (existing) and `honest_sd` (new), returning the nested block with the `status`/`reason` taxonomy and the data-adaptive M-grid + clamp.

**Files:**
- Modify: `backend/workbench/engine/honest_did_adapter.py`
- Test: `tests/test_honest_did_adapter.py`

- [ ] **Step 1: Write the failing tests (nested shape + frozen Σ + SD guard)**

```python
import numpy as np
from workbench.engine.honest_did_adapter import honest_did_from_cs_dynamic

def _mk_agg():
    # reuse the adapter fixture builder already in this test module (cs dynamic
    # aggregation with labels [-3..3], component_if, etc.). Keep grid small.
    ...  # existing helper in tests/test_honest_did_adapter.py

def test_adapter_returns_nested_rm_and_sd(small_cs_dynamic, row_cluster, n_total):
    out = honest_did_from_cs_dynamic(
        small_cs_dynamic, row_cluster=row_cluster, n_total=n_total,
        mbar_grid=[0.0, 1.0], grid_points=150)
    assert "rm" in out and "sd" in out
    assert out["rm"]["status"] == "ok"
    assert out["sd"]["status"] == "ok" and out["sd"]["method"] == "FLCI"
    assert [r2["M"] for r2 in out["sd"]["post_average"]["results"]] == out["sd"]["m_grid"]
    # frozen snapshot: both tracks saw the SAME sigma
    assert "_debug_sigma" in out and out["rm"]["num_pre"] == out["sd"]["num_pre"]

def test_adapter_sd_scale_clamped_when_se_tiny(tiny_se_cs_dynamic, row_cluster, n_total):
    out = honest_did_from_cs_dynamic(
        tiny_se_cs_dynamic, row_cluster=row_cluster, n_total=n_total,
        mbar_grid=[0.0], grid_points=150)
    assert out["sd"]["scale"] >= 1e-8   # HONEST_SD_SCALE_FLOOR

def test_adapter_never_throws_on_shape_mismatch():
    out = honest_did_from_cs_dynamic(
        {"label": [0.0], "estimate": [1.0], "component_if": [[1.0]]},
        row_cluster=np.array([0, 1]), n_total=2, mbar_grid=[0.0])
    assert out["rm"]["status"] == "not_available"
    assert out["sd"]["status"] == "not_available"
```

(Use/extend the existing fixture helpers in `tests/test_honest_did_adapter.py`; do not invent a new dataset.)

- [ ] **Step 2: Run to verify failure**

Run: `... -m pytest tests/test_honest_did_adapter.py -k "nested or clamp or shape_mismatch" -v`
Expected: FAIL (`KeyError: 'rm'` / `'sd'`).

- [ ] **Step 3: Rewrite the adapter**

```python
from __future__ import annotations
import numpy as np
from .honest_did import honest_rm, honest_sd, HonestDiDError

HONEST_SD_M_MULT = [0.0, 0.5, 1.0, 1.5, 2.0]
HONEST_SD_SCALE_FLOOR = 1e-8

def _na(reason: str) -> dict:
    return {"status": "not_available", "reason": reason}

def _run_track(fn, *, betahat, sigma, num_pre, num_post, et, extra, **kw) -> dict:
    """Run one honest track (rm or sd) over post-average + per-event targets,
    mapping HonestDiDError -> status:not_available. ``extra`` merges static keys
    (e.g. method/m_grid/scale) into the ok payload."""
    try:
        l_avg = np.full(num_post, 1.0 / num_post)
        avg = fn(betahat=betahat, sigma=sigma, num_pre=num_pre,
                 num_post=num_post, l_vec=l_avg, **kw)
        per_event = []
        for j in range(num_post):
            lv = np.zeros(num_post); lv[j] = 1.0
            r = fn(betahat=betahat, sigma=sigma, num_pre=num_pre,
                   num_post=num_post, l_vec=lv, **kw)
            per_event.append({"event_time": et[num_pre + j], **r})
        return {"status": "ok", "reason": None, "num_pre": num_pre,
                "num_post": num_post, **extra,
                "post_average": avg, "per_event_time": per_event}
    except HonestDiDError as exc:
        return {"status": "not_available", "reason": str(exc),
                "num_pre": num_pre, "num_post": num_post}

def honest_did_from_cs_dynamic(agg_dynamic, *, row_cluster, n_total,
                               mbar_grid, alpha=0.05, grid_points=1000,
                               m_mult=None, scale_floor=HONEST_SD_SCALE_FLOOR) -> dict:
    """Run ΔRM (test-inversion) and ΔSD (FLCI) honest-DID from one frozen
    snapshot of the CS dynamic aggregation. Returns {"rm":..., "sd":..., _debug_*}.
    NEVER throws."""
    m_mult = HONEST_SD_M_MULT if m_mult is None else m_mult
    labels = [float(x) for x in agg_dynamic["label"]]
    beta = np.asarray(agg_dynamic["estimate"], dtype=float)
    CIF = np.asarray(agg_dynamic["component_if"], dtype=float)
    N = int(n_total)
    rc = np.asarray(row_cluster)

    if CIF.ndim != 2 or rc.shape[0] != CIF.shape[0] or CIF.shape[1] == 0:
        reason = "HONEST_BAD_INPUT: row_cluster/component_if shape mismatch."
        return {"rm": _na(reason), "sd": _na(reason)}

    # --- frozen snapshot: one Σ, one keep-order, one event-time vector ---
    uniq, inv = np.unique(rc, return_inverse=True)
    S = np.zeros((len(uniq), CIF.shape[1]))
    np.add.at(S, inv, CIF)
    Sigma_full = S.T @ S / (N ** 2)
    keep = [i for i, e in enumerate(labels) if abs(e + 1.0) > 1e-9]
    keep.sort(key=lambda i: (labels[i] >= 0, labels[i]))
    et = [labels[i] for i in keep]
    num_pre = sum(1 for e in et if e < 0)
    num_post = sum(1 for e in et if e >= 0)
    betahat = beta[keep]
    sigma = Sigma_full[np.ix_(keep, keep)]
    debug = {"_debug_keep_idx": keep, "_debug_event_times": et,
             "_debug_sigma": sigma.tolist()}

    # ΔRM track (unchanged numbers; just wrapped in the new taxonomy)
    rm = _run_track(honest_rm, betahat=betahat, sigma=sigma, num_pre=num_pre,
                    num_post=num_post, et=et,
                    extra={"mbar_grid": list(map(float, mbar_grid))},
                    mbar_grid=mbar_grid, alpha=alpha, grid_points=grid_points)

    # ΔSD track: data-adaptive M-grid with clamp, then FLCI
    diag = np.sqrt(np.clip(np.diag(sigma), 0.0, None)) if sigma.size else np.array([0.0])
    scale = float(diag.max()) if diag.size else 0.0
    if scale < scale_floor:
        scale = scale_floor
    m_grid = [float(mult) * scale for mult in m_mult]
    sd = _run_track(honest_sd, betahat=betahat, sigma=sigma, num_pre=num_pre,
                    num_post=num_post, et=et,
                    extra={"method": "FLCI", "m_grid": m_grid, "scale": scale},
                    m_grid=m_grid, alpha=alpha)

    return {"rm": rm, "sd": sd, **debug}
```

NOTE: `honest_sd`'s post-average/per-event results use the `"M"` key; `honest_rm`'s use `"Mbar"`. The `_run_track` helper is agnostic — it just forwards each track's dict.

- [ ] **Step 4: Run to verify pass**

Run: `... -m pytest tests/test_honest_did_adapter.py -v`
Expected: PASS (migrate any pre-existing adapter assertions that referenced the old flat keys `out["skipped"]` / `out["post_average"]` → `out["rm"]["status"]` / `out["rm"]["post_average"]`).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/honest_did_adapter.py tests/test_honest_did_adapter.py
git commit -m "feat(honest-did): adapter {rm,sd} nesting + frozen snapshot + ΔSD M-grid"
```

---

## Task 7: Runner wiring + migrate backend honest tests

Add SD constants, keep one `honest_did` flag emitting the nested block, recursively strip `_debug_`, and migrate every backend test that referenced the old flat shape.

**Files:**
- Modify: `backend/workbench/econometrics/runner.py:597-612`
- Modify: `tests/test_run_cs_did.py`, `tests/test_honest_did_wiring.py`, `tests/test_honest_did_adversarial.py`, `tests/test_honest_did_nan_safety.py`, `tests/test_honest_did_qa.py`, `tests/test_engine_golden.py`

- [ ] **Step 1: Update the runner block**

In `runner.py`, near the top with the other honest constants:

```python
HONEST_MBAR_GRID = [0.0, 0.5, 1.0, 1.5, 2.0]
HONEST_GRID_POINTS = 1000
HONEST_SD_M_MULT = [0.0, 0.5, 1.0, 1.5, 2.0]
HONEST_SD_SCALE_FLOOR = 1e-8
```

Replace the honest block (lines ~597-608) with:

```python
    result_honest = None
    if honest_did:
        from ..engine.honest_did_adapter import honest_did_from_cs_dynamic
        try:
            hd = honest_did_from_cs_dynamic(
                agg_by_kind["dynamic"], row_cluster=row_cluster, n_total=G,
                mbar_grid=HONEST_MBAR_GRID, alpha=alpha,
                grid_points=HONEST_GRID_POINTS,
                m_mult=HONEST_SD_M_MULT, scale_floor=HONEST_SD_SCALE_FLOOR)
        except Exception as exc:            # honest-DID must NEVER fail the run
            reason = f"HONEST_INTERNAL_ERROR: {exc}"
            hd = {"rm": {"status": "degraded", "reason": reason},
                  "sd": {"status": "degraded", "reason": reason}}
        result_honest = {k: v for k, v in hd.items() if not k.startswith("_debug_")}
```

(The `**({"honest_did": result_honest} ...)` return line is unchanged.)

- [ ] **Step 2: Migrate the backend honest tests**

Update each reference from the flat shape to the nested shape. Mapping:
- `art["honest_did"]["skipped"] is False` → `art["honest_did"]["rm"]["status"] == "ok"`
- `art["honest_did"]["skipped"] is True` + `["reason"]` → `["rm"]["status"] in ("not_available","degraded")` + `["rm"]["reason"]`
- `art["honest_did"]["post_average"]["results"]` → `art["honest_did"]["rm"]["post_average"]["results"]`
- `not any(k.startswith("_debug_") for k in art["honest_did"])` → still valid (debug stripped at top level); also assert no `_debug_` leaks into `rm`/`sd`.
- In `test_engine_golden.py:258-261` change the guard to assert both tracks:

```python
    hd = art["honest_did"]
    assert hd["rm"]["status"] == "ok" and "results" in hd["rm"]["post_average"]
    assert hd["sd"]["status"] == "ok" and hd["sd"]["method"] == "FLCI"
    assert "results" in hd["sd"]["post_average"]
    assert not any(k.startswith("_debug_") for k in hd)
```

Add at least one NEW assertion exercising the SD track end-to-end (post_average has finite/`null` lb/ub across `m_grid`).

- [ ] **Step 3: Run the migrated backend honest suite**

Run: `... -m pytest tests/test_run_cs_did.py tests/test_honest_did_wiring.py tests/test_honest_did_adversarial.py tests/test_honest_did_nan_safety.py tests/test_honest_did_qa.py tests/test_engine_golden.py -v`
Expected: PASS. Tests monkeypatch `runner.HONEST_MBAR_GRID`/`HONEST_GRID_POINTS` (and may set `HONEST_SD_M_MULT`) to small grids for speed — keep that pattern.

- [ ] **Step 4: Commit**

```bash
git add backend/workbench/econometrics/runner.py tests/test_run_cs_did.py tests/test_honest_did_wiring.py tests/test_honest_did_adversarial.py tests/test_honest_did_nan_safety.py tests/test_honest_did_qa.py tests/test_engine_golden.py
git commit -m "feat(honest-did): runner emits nested {rm,sd}; migrate backend honest tests"
```

---

## Task 8: Frontend — `{rm, sd}` types + three-state rendering

Restructure `HonestDidBlock` to `{rm, sd}` with the `status`/`reason` taxonomy, parameterize the sensitivity table over the param key (`Mbar` vs `M`), add the SD/FLCI panel, and render all three states. Migrate the FE tests.

**Files:**
- Modify: `frontend/src/runResult/CSDiagnosticsCard.tsx:37-92,223-290,410`
- Modify: `frontend/src/runResult/CSDiagnosticsCard.test.tsx`

- [ ] **Step 1: Update the failing FE test first**

Rewrite `CSDiagnosticsCard.test.tsx` honest cases to the nested shape:

```tsx
honest_did: {
  rm: { status: "ok", reason: null, num_pre: 2, num_post: 4,
        mbar_grid: [0, 1],
        post_average: { results: [{ Mbar: 0, lb: -0.1, ub: 0.2 }], breakdown: null },
        per_event_time: [{ event_time: 0, results: [{ Mbar: 0, lb: -0.1, ub: 0.2 }], breakdown: null }] },
  sd: { status: "ok", reason: null, method: "FLCI", num_pre: 2, num_post: 4,
        m_grid: [0, 0.02], scale: 0.02,
        post_average: { results: [{ M: 0, lb: -0.1, ub: 0.2 }], breakdown: null },
        per_event_time: [{ event_time: 0, results: [{ M: 0, lb: -0.1, ub: 0.2 }], breakdown: null }] },
},
```

Add cases asserting: `cs-honest-did-rm-panel` and `cs-honest-did-sd-panel` both render when `ok`; SD `status:"not_available"` renders `cs-honest-did-sd-unavailable` with the reason text; absent `honest_did` → neither panel.

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/runResult/CSDiagnosticsCard.test.tsx`
Expected: FAIL (type errors / missing labels).

- [ ] **Step 3: Update the component**

Replace the honest types and panel:

```tsx
interface HonestRow { Mbar?: number; M?: number; lb: number | null; ub: number | null; }
interface HonestTrack {
  status: "ok" | "degraded" | "not_available";
  reason: string | null;
  num_pre?: number; num_post?: number;
  mbar_grid?: number[]; m_grid?: number[]; scale?: number; method?: string;
  post_average?: { results: HonestRow[]; breakdown: number | null };
  per_event_time?: { event_time: number; results: HonestRow[]; breakdown: number | null }[];
}
interface HonestDidBlock { rm: HonestTrack; sd: HonestTrack; }
```

Parameterize the table over the param key:

```tsx
function HonestDidSensitivityTable({
  title, ariaLabel, paramKey, paramLabel, results, breakdown,
}: {
  title: string; ariaLabel: string;
  paramKey: "Mbar" | "M"; paramLabel: string;
  results: HonestRow[]; breakdown: number | null;
}) {
  // render rows reading r[paramKey]; header cell shows paramLabel (e.g. "M̄" or "M")
  // breakdown null -> "无突破"; lb/ub null -> "—"
}
```

Track renderer with three states:

```tsx
function HonestTrackPanel({ track, kind }: { track: HonestTrack; kind: "rm" | "sd" }) {
  const label = kind === "rm" ? "cs-honest-did-rm" : "cs-honest-did-sd";
  if (track.status === "not_available")
    return <div aria-label={`${label}-unavailable`} className="ios-warning">{track.reason}</div>;
  if (track.status === "degraded")
    return <div aria-label={`${label}-degraded`} className="ios-warning">{track.reason}</div>;
  const paramKey = kind === "rm" ? "Mbar" : "M";
  const paramLabel = kind === "rm" ? "M̄" : "M";
  return (
    <section aria-label={`${label}-panel`}>
      {/* heading + microcopy: rm = relative-magnitudes; sd = smoothness + FLCI */}
      {track.post_average && (
        <HonestDidSensitivityTable title="后期平均" ariaLabel={`${label}-post-average`}
          paramKey={paramKey} paramLabel={paramLabel}
          results={track.post_average.results} breakdown={track.post_average.breakdown} />
      )}
      {track.per_event_time?.map((pet) => (
        <HonestDidSensitivityTable key={pet.event_time} title={`事件 ${pet.event_time}`}
          ariaLabel={`${label}-event-${pet.event_time}`}
          paramKey={paramKey} paramLabel={paramLabel}
          results={pet.results} breakdown={pet.breakdown} />
      ))}
    </section>
  );
}

function HonestDidPanel({ honest }: { honest: HonestDidBlock }) {
  return (
    <section aria-label="cs-honest-did-panel">
      <HonestTrackPanel track={honest.rm} kind="rm" />
      <HonestTrackPanel track={honest.sd} kind="sd" />
    </section>
  );
}
```

Keep the render guard at line ~410: `{d.honest_did && <HonestDidPanel honest={d.honest_did} />}`.

- [ ] **Step 4: Run to verify pass + types**

Run: `cd frontend && npx vitest run src/runResult/CSDiagnosticsCard.test.tsx && npx tsc --noEmit`
Expected: PASS, 0 type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/runResult/CSDiagnosticsCard.tsx frontend/src/runResult/CSDiagnosticsCard.test.tsx
git commit -m "feat(honest-did): FE {rm,sd} three-state rendering + ΔSD/FLCI panel"
```

---

## Task 9: Golden structure guard + additive golden + nan-safety for SD

Ensure the golden still 0-drifts (numbers not frozen) but the structure guard pins the new `{rm, sd}` shape, and the SD FLCI path is nan-safe in the artifact.

**Files:**
- Modify: `tests/test_engine_golden.py` (if not fully covered in Task 7)
- Modify: `tests/test_honest_did_nan_safety.py`
- Test: `tests/golden/` (existing `cs_did_honest` golden file — verify unchanged)

- [ ] **Step 1: Add an SD nan-safety test**

```python
def test_sd_flci_nonfinite_serializes_to_null(tmp_path):
    # Force a degenerate FLCI (tiny grid + near-singular sigma) and assert the
    # serialized cs_did.json honest_did.sd contains JSON null (not NaN token) and
    # the file parses under strict json.loads.
    ...
```

(Mirror the existing ΔRM nan-safety test structure already in this file; assert on `art["honest_did"]["sd"]`.)

- [ ] **Step 2: Run the golden + nan-safety**

Run: `... -m pytest tests/test_engine_golden.py tests/test_honest_did_nan_safety.py -v`
Expected: PASS, golden 0-drift (the `_capture` freezes only status/artifacts/coef; the cs_did_honest golden file is byte-identical).

- [ ] **Step 3: Confirm full backend + golden 0-drift**

Run: `... -m pytest -q` (full suite via `.venv/bin/python -m pytest`)
Expected: all pass; golden 0-drift.

- [ ] **Step 4: Commit**

```bash
git add tests/test_engine_golden.py tests/test_honest_did_nan_safety.py
git commit -m "test(honest-did): ΔSD/FLCI structure guard + nan-safety"
```

---

## Task 10: Docs + release notes

**Files:**
- Modify: `docs/honest-did-howto.md`
- Create: `docs/v1.5.7.1-release-notes.md`

- [ ] **Step 1: Add a ΔSD/FLCI section to the howto**

Explain in plain terms (mirror the brainstorm framing): ΔSD = "trend may slope but not suddenly bend" (second differences bounded), FLCI = R's default for ΔSD (a minimum-length CI via convex optimization, no Monte Carlo), how to read the `{rm, sd}` panels, the breakdown M, and the data-adaptive M-scale caveat (M=1 is not cross-dataset comparable). State that ΔSD via test-inversion and user-chosen `l_vec` are deferred.

- [ ] **Step 2: Write the release notes**

`docs/v1.5.7.1-release-notes.md`: what shipped (ΔSD + FLCI, nested `{rm,sd}` contract with failure taxonomy), the math notes (L1 tight dual, p≥2 identifiability, z elimination, M=0 anchor), validation (R `findOptimalFLCI` oracle at 1e-6, no new R packages), determinism statement (no MC/bootstrap; golden freezes status/artifacts/coef only), and the deferrals (ΔSD test-inversion, `l_vec` → v1.5.8).

- [ ] **Step 3: Commit**

```bash
git add docs/honest-did-howto.md docs/v1.5.7.1-release-notes.md
git commit -m "docs(honest-did): ΔSD/FLCI howto + v1.5.7.1 release notes"
```

---

## Task 11: Final whole-feature adversarial review

Not a code-writing task — the v1.5.6.1 / v1.5.7 lesson: a dedicated final review (Reviewer + Test&QA roles) catches failure-path escapes the per-task reviews miss. Run before merging.

- [ ] **Step 1: Reviewer pass** — read every changed file as an adversary. Probe specifically:
  - FLCI vs R oracle margin at the **discriminating** M values (not just grid-saturated/M=0 points).
  - h-grid: does the reported `argmin` ever sit at a grid endpoint (grid too narrow → biased half-length)? Confirm the optimum is interior for the fixture.
  - SD `status:"not_available"` (num_pre=1) and `degraded` (forced internal error) both reach `cs_did.json` as strict-valid JSON and render in the FE.
  - Non-finite FLCI CI → `null` in JSON (strict `JSON.parse` survives, the whole CS card does not vanish — the exact v1.5.7 escape).
  - Frozen-snapshot: rm and sd read identical Σ (no recompute path introduced).
  - `_debug_` stripped from the shipped artifact at top level AND not leaked into `rm`/`sd`.
  - Determinism: 3× identical runs byte-equal on `status`/`artifacts`/`coef`.

- [ ] **Step 2: Test&QA pass** — prove the above with real runs (coarse grid). Add regression tests for any gap. Fill thin assertions (breakdown non-None path for SD, event_time labels, M=0 anchor).

- [ ] **Step 3: Full gate**

```bash
cd /Users/jiayuanren/项目规划/.worktrees/workbench-v1.5.7.1
./scripts/gate.sh
```
Expected: GATE PASSED — BE (≥989 + new) / golden 0-drift / FE (≥624 + new) / tsc 0.

- [ ] **Step 4: Finish the branch** — use superpowers:finishing-a-development-branch. `--no-ff` merge `workbench-v1.5.7.1` into `main` + annotated tag `v1.5.7.1`; verify the gated branch head vs the merged tree is an empty diff (`git diff <gated-head> <merge-commit> -- . ':!docs'` style EXIT=0 check). **Push requires explicit per-version authorization** — ask first. After ship, ask about worktree cache cleanup ([[feedback_version_cleanup]]).

---

## Self-review notes (coverage map)

- Spec §2.1 (ΔSD operator) → Task 2; §2.2–2.5 (estimator, consistency, L1 dual, z elimination, QP) → Task 4 (`_flci_bias_map` via `scipy.linalg.solve`, never inverse); §2.6 (folded-normal + monotone cache) → Task 3; §2.7 (entry + guards, M=0 anchor) → Tasks 4–5; §2.8 (determinism wording) → Tasks 9 (golden) + 10 (notes).
- Spec §3.1 (frozen snapshot) → Task 6 (`debug` computed once; both tracks read it); §3.2 (M-grid + clamp) → Task 6; §3.3 (one flag, runtime) → Task 7; §3.4 (`{rm,sd}` + taxonomy) → Tasks 6–7; §3.5 (FE three-state) → Task 8.
- Spec §4 (oracle 1e-6, M=0 anchor, golden, adversarial) → Tasks 1, 4, 9, 11.
- Param-key consistency: RM rows use `"Mbar"`, SD rows use `"M"` throughout (engine Task 5, adapter Task 6, runner Task 7, FE table `paramKey` Task 8). `status ∈ {ok, degraded, not_available}` consistent across Tasks 6/7/8.
- Open risk flagged in-task (not a placeholder): Task 2 reference-gap convention and Task 4 h-grid bounds must be reconciled against installed R source if the 1e-6 oracle test fails — both have explicit fallback instructions.
