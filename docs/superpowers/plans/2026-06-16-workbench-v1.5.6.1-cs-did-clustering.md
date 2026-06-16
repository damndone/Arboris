# cs_did Variable-Clustering Completion (v1.5.6.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one-way variable-clustering in the Callaway-Sant'Anna estimator (`cs_did`) correct and oracle-validated — entity-level influence functions aggregated by cluster in BOTH the analytical SE and the multiplier bootstrap — removing the v1.5.6 `CS_CLUSTERING_DEFERRED` guard.

**Architecture:** Single row convention. The influence function (IF) is entity-level `(N, K)` everywhere; clustering is a `rowsum` applied ONLY at the two variance steps (analytical `_se` in `cs_aggregate.py` and the multiplier bootstrap in `cs_inference.py`). The grouping source of truth is `bundle.aux["row_cluster"]`. Validation uses a deterministic cluster-robust-variance (CRVE) oracle built in R from the already-1e-8-validated influence functions.

**Tech Stack:** Python (NumPy/SciPy/statsmodels/pandas), pytest, R 4.6.0 (`did` 2.5.0 / `DRDID` 1.3.0, `~/.R/Makevars` `CC=clang -std=gnu17`), React/TypeScript + vitest. Zero new deps.

**Spec:** `docs/superpowers/specs/2026-06-16-workbench-v1.5.6.1-cs-did-clustering-design.md`

**Per-task discipline:** TDD (red → green) + two-stage review (spec-conformance, then quality) per [[feedback_review_workflow]]. Commit after each green task. Full suite via `.venv/bin/python -m pytest` (never bare). Push to main needs explicit per-version authorization.

**Key math note (resolved):** the cluster-robust SE is `sqrt(Σ_c S_c²) / N` where `S_c = Σ_{i∈c} ψ_i` and **N = number of entities** (NOT n_clusters). This is forced by the unclustered identity: when each entity is its own cluster, `S_c = ψ_i` and the formula must reduce exactly to the existing 1e-10-validated unclustered SE `sqrt(Σ ψ_i²)/N`. The clustered oracle is built with this same `n=N` convention and emits `n` explicitly so the assertion is self-documenting.

---

## File Structure

Backend (modify):
- `backend/workbench/engine/cs_attgt.py` — drop the deferral guard + the cluster-collapse; IF stays `(N,K)`; resolve `row_cluster` with validation; delete dead `cluster_influence`.
- `backend/workbench/engine/cs_inference.py` — `multiplier_bootstrap(..., clusters=None)`; rowsum to clusters, per-cluster multipliers.
- `backend/workbench/engine/cs_aggregate.py` — confirm `_se` clustered branch (n=N); no formula change expected, add a guard comment.
- `backend/workbench/econometrics/runner.py` — `run_cs_did` passes `row_cluster` to the bootstrap, honest `metadata` (`n_units`/`n_clusters`/`cluster_level`).

Tests (create/modify):
- `tests/fixtures/cs_did/panel.csv` — add `cluster` column.
- `tests/fixtures/cs_did/generate_fixtures.R` — emit `aggte_clustered.json`.
- `tests/fixtures/cs_did/aggte_clustered.json` — new oracle (generated).
- `tests/test_cs_inference.py` — clustered bootstrap behaviors.
- `tests/test_cs_did_clustering.py` — NEW: point-invariance + clustered-SE-vs-oracle.
- `tests/test_cs_did_hardening.py` — bad cluster inputs → structured errors.
- `tests/test_run_cs_did.py` — clustered run + metadata.
- `tests/test_engine_golden.py` + `tests/golden/cs_did_clustered.json` — additive clustered golden.

Frontend (modify):
- `frontend/src/runForm/CSControls.tsx` (+ `.test.tsx`) — restore cluster-var selector.
- `frontend/src/runForm/RunForm.tsx` — thread `clusterVar`.
- `frontend/src/api.ts` — append `cs_cluster_var`.
- `frontend/src/runResult/CSDiagnosticsCard.tsx` — show `cluster_level` + `n_clusters`.

Docs: `docs/cs-did-howto.md`, `docs/v1.5.6.1-release-notes.md`.

---

## Task 0: Worktree + environment + baseline gate

**Files:** none (environment only).

- [ ] **Step 1: Create the isolated worktree off main**

```bash
cd /Users/jiayuanren/项目规划
git worktree add -b workbench-v1.5.6.1 .worktrees/workbench-v1.5.6.1 main
cd .worktrees/workbench-v1.5.6.1
git log --oneline -1   # expect the v1.5.6.1 spec commit on top of 3b8dce2
```

- [ ] **Step 2: Build the backend venv (full extras) + frontend deps**

```bash
~/.local/bin/python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev,panel,ml,imbalanced,imputation]"
cd frontend && npm install && cd ..
```

- [ ] **Step 3: Verify R toolchain (oracle generation needs it)**

```bash
/opt/homebrew/bin/Rscript -e 'library(did); library(DRDID); cat("R OK\n")'
# If R packages need reinstall: ~/.R/Makevars MUST contain  CC=clang -std=gnu17
```

Expected: `R OK`.

- [ ] **Step 4: Baseline gate — everything green BEFORE any change**

```bash
.venv/bin/python -m pytest -q
cd frontend && npx vitest run && npx tsc --noEmit && cd ..
```

Expected: BE 908 passed, golden/invariants/snapshot 18 0-drift, FE 617 passed, tsc 0 errors. Record the numbers; they are the no-drift reference.

- [ ] **Step 5: Commit (marker only, if anything generated)**

No code change. Proceed to Task 1.

---

## Task 1: Clustered R oracle (fixture + generator)

**Files:**
- Modify: `tests/fixtures/cs_did/panel.csv` (add `cluster` column)
- Modify: `tests/fixtures/cs_did/generate_fixtures.R`
- Create (generated): `tests/fixtures/cs_did/aggte_clustered.json`
- Test: `tests/test_cs_did_clustering.py` (oracle-shape sanity only in this task)

- [ ] **Step 1: Add a `cluster` column to panel.csv**

Write a one-off Python snippet (run once, then delete) that assigns each of the 60 units to one of 20 clusters of 3, **crossing cohorts** so within-cluster correlation differs from entity clustering:

```python
import pandas as pd
d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
units = sorted(d["unit"].unique())                 # 60 units
# stride assignment: unit i -> cluster (i % 20). Because cohorts cycle on a
# different period (first_treat in {0,3,4,5}), i%20 mixes cohorts within a cluster.
cl = {u: (k % 20) for k, u in enumerate(units)}
d["cluster"] = d["unit"].map(cl)
d.to_csv("tests/fixtures/cs_did/panel.csv", index=False)
print(d.groupby("cluster")["first_treat"].nunique().describe())  # expect clusters spanning >1 cohort
```

Run it; confirm clusters span multiple cohorts (max nunique > 1). The new column is the LAST column — verify the existing oracle tests still read `unit/period/first_treat/x1/y` by name (they do; `pd.read_csv` is name-keyed).

- [ ] **Step 2: Verify the three existing oracles are 0-drift with the new column**

```bash
.venv/bin/python -m pytest tests/test_cs_did_oracle.py -q
```

Expected: PASS unchanged (the `cluster` column is never read by point/IF/aggte oracles).

- [ ] **Step 3: Extend generate_fixtures.R to emit the deterministic clustered CRVE**

Append to `tests/fixtures/cs_did/generate_fixtures.R` (after the existing `aggte_out` block):

```r
# ---- Clustered CRVE oracle (deterministic, built from inf functions) ----
# did forces bstrap=TRUE with clustervars, so there is no native analytical
# clustered SE. We build a deterministic cluster-robust SE from the SAME
# influence functions did exposes (already 1e-8-validated unclustered):
#   S_c = sum_{i in c} psi_i ;  se = sqrt(sum_c S_c^2) / N   (N = #entities).
# Unclustered identity: each entity its own cluster => reduces to did's getSE.
cluster_of_unit <- unique(d[, c("unit", "cluster")])
cluster_of_unit <- cluster_of_unit[order(cluster_of_unit$unit), ]
emit_clustered <- function(method) {
  r <- att_gt(yname = "y", tname = "period", idname = "unit", gname = "first_treat",
              xformla = ~x1, data = d, est_method = method,
              control_group = "nevertreated", base_period = "varying",
              anticipation = 0, bstrap = FALSE, cband = FALSE)
  N <- length(r$DIDparams$data[!duplicated(r$DIDparams$data$unit), "unit"])
  # entity order did uses for inffunc rows:
  ids <- unique(r$DIDparams$data$unit)
  cl  <- cluster_of_unit$cluster[match(ids, cluster_of_unit$unit)]
  crve <- function(inf) {                       # inf: length-N entity IF
    S <- rowsum(inf, cl)                         # (n_clusters,)
    sqrt(sum(S^2)) / N
  }
  agg <- function(type) {
    a <- aggte(r, type = type, bstrap = FALSE)
    overall_if <- a$inf.function$overall.inf.func
    egt_if     <- a$inf.function$egt.inf.func    # matrix (N x n_labels) or NULL
    se_egt <- if (is.null(egt_if)) NULL else apply(egt_if, 2, crve)
    list(overall = a$overall.att,
         overall_se = if (is.null(overall_if)) NULL else crve(overall_if),
         egt = a$egt, se_egt = se_egt)
  }
  list(n = N, n_clusters = length(unique(cl)),
       simple = agg("simple"), dynamic = agg("dynamic"),
       group = agg("group"), calendar = agg("calendar"))
}
clustered_out <- list()
for (m in c("dr", "ipw", "reg")) clustered_out[[m]] <- emit_clustered(m)
write_json(clustered_out, "tests/fixtures/cs_did/aggte_clustered.json",
           digits = 12, auto_unbox = TRUE, null = "null")
```

- [ ] **Step 4: Run the generator and inspect the oracle**

```bash
/opt/homebrew/bin/Rscript tests/fixtures/cs_did/generate_fixtures.R
.venv/bin/python -c "import json; o=json.load(open('tests/fixtures/cs_did/aggte_clustered.json')); print(o['dr']['n'], o['dr']['n_clusters'], o['dr']['dynamic']['overall_se'])"
```

Expected: `n=60`, `n_clusters=20`, a finite `overall_se` that DIFFERS from the unclustered `aggte.json` dynamic overall_se (clustering moved it).

- [ ] **Step 5: Sanity test for the oracle shape**

Create `tests/test_cs_did_clustering.py`:

```python
import json
import numpy as np
import pandas as pd
import pytest

CLUSTERED = json.load(open("tests/fixtures/cs_did/aggte_clustered.json"))
UNCLUSTERED = json.load(open("tests/fixtures/cs_did/aggte.json"))


def test_clustered_oracle_present_and_differs():
    for m in ("dr", "ipw", "reg"):
        assert CLUSTERED[m]["n"] == 60 and CLUSTERED[m]["n_clusters"] == 20
        c = CLUSTERED[m]["dynamic"]["overall_se"]
        u = UNCLUSTERED[m]["dynamic"]["overall_se"]
        assert c is not None and abs(c - u) > 1e-6  # clustering changed the SE
```

- [ ] **Step 6: Run the test**

```bash
.venv/bin/python -m pytest tests/test_cs_did_clustering.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/cs_did/panel.csv tests/fixtures/cs_did/generate_fixtures.R \
        tests/fixtures/cs_did/aggte_clustered.json tests/test_cs_did_clustering.py
git commit -m "test(cs_did): clustered CRVE oracle from R inf-funcs + cluster column"
```

---

## Task 2: `multiplier_bootstrap` per-cluster multipliers

**Files:**
- Modify: `backend/workbench/engine/cs_inference.py`
- Test: `tests/test_cs_inference.py`

- [ ] **Step 1: Write failing tests for the `clusters=` argument**

Append to `tests/test_cs_inference.py`:

```python
def test_clusters_none_is_unchanged():
    psi = _if()
    a = multiplier_bootstrap(psi, B=500, alpha=0.05, seed=3)
    b = multiplier_bootstrap(psi, B=500, alpha=0.05, seed=3, clusters=None)
    assert np.array_equal(a["se"], b["se"])
    assert a["uniform_crit"] == b["uniform_crit"]


def test_distinct_clusters_equal_entity_identity():
    # each row its own cluster => identical to unclustered (rowsum is identity)
    psi = _if()                                   # (80, 5)
    distinct = np.arange(psi.shape[0])
    a = multiplier_bootstrap(psi, B=500, alpha=0.05, seed=9)
    b = multiplier_bootstrap(psi, B=500, alpha=0.05, seed=9, clusters=distinct)
    assert np.allclose(a["se"], b["se"])
    assert np.allclose(a["uniform_band"], b["uniform_band"])


def test_clustered_se_matches_rowsum_crve():
    # se under clustering = sqrt(sum_c S_c^2)/N  (N = #rows, not #clusters)
    psi = _if()                                   # (80, 5)
    clusters = np.arange(psi.shape[0]) % 16       # 16 clusters of 5
    r = multiplier_bootstrap(psi, B=200, alpha=0.05, seed=4, clusters=clusters)
    import pandas as pd
    S = pd.DataFrame(psi).groupby(clusters).sum().to_numpy()   # (16, 5)
    expected = np.sqrt((S ** 2).sum(axis=0)) / psi.shape[0]
    assert np.allclose(r["se"], expected, atol=1e-12)
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_cs_inference.py -k "clusters or clustered" -q
```

Expected: FAIL (`multiplier_bootstrap() got an unexpected keyword argument 'clusters'`).

- [ ] **Step 3: Implement `clusters=` in `multiplier_bootstrap`**

In `backend/workbench/engine/cs_inference.py`, change the signature and add the rowsum-to-cluster collapse BEFORE the existing math. The collapsed matrix `Psi_c` then flows through the identical Mammen/sup-t code, with the SE divisor kept at the ENTITY count `N` (the math note):

```python
def multiplier_bootstrap(if_matrix, *, B=1000, alpha=0.05, seed=20260615,
                         estimates=None, clusters=None):
    """Callaway-Sant'Anna multiplier (wild) bootstrap.

    if_matrix : (N, K) ENTITY-row IF, mean-zero columns.
    clusters  : optional (N,) cluster id per entity row. When given, the IF is
        summed within clusters (R's rowsum) before drawing one Mammen multiplier
        per CLUSTER; the analytical/robust scale divisor stays N (entities), so
        the unclustered case (each entity its own cluster) is the exact identity.
    estimates : optional (K,) point estimates; CIs are centered on them.
    """
    if B < 1:
        raise ValueError("CS_BAD_BOOTSTRAP_B: B must be >= 1")
    Psi_entity = np.asarray(if_matrix, dtype=float)
    N, K = Psi_entity.shape
    if clusters is None:
        Psi = Psi_entity
    else:
        clusters = np.asarray(clusters)
        if clusters.shape[0] != N:
            raise ValueError("CS_CLUSTER_LEN_MISMATCH: clusters length != IF rows")
        uniq, inv = np.unique(clusters, return_inverse=True)
        Psi = np.zeros((len(uniq), K))
        np.add.at(Psi, inv, Psi_entity)            # rowsum within cluster
    G = Psi.shape[0]                               # rows to draw multipliers over
    if estimates is None:
        estimates = np.zeros(K)
    estimates = np.asarray(estimates, dtype=float)
    # analytical/robust SE uses the ENTITY count N (cluster-robust CRVE convention)
    se = np.sqrt((Psi ** 2).sum(axis=0)) / N
    rng = np.random.default_rng(seed)
    k1 = (1 - np.sqrt(5)) / 2
    k2 = (1 + np.sqrt(5)) / 2
    p = (np.sqrt(5) + 1) / (2 * np.sqrt(5))
    V = np.where(rng.random((B, G)) < p, k1, k2)        # (B, G) one per cluster
    R = (V @ Psi) / N                                   # (B, K)  divisor N
    q75, q25 = np.quantile(R, 0.75, axis=0), np.quantile(R, 0.25, axis=0)
    sigma = (q75 - q25) / (stats.norm.ppf(0.75) - stats.norm.ppf(0.25))
    sigma = np.where(sigma > 0, sigma, se)
    z = stats.norm.ppf(1 - alpha / 2)
    pointwise_ci = np.column_stack([estimates - z * se, estimates + z * se])
    good = sigma > 0
    if good.any():
        tstat = np.max(np.abs(R[:, good]) / sigma[good], axis=1)
        uniform_crit = float(np.quantile(tstat, 1 - alpha))
    else:
        uniform_crit = float(z)
    uniform_band = np.column_stack([estimates - uniform_crit * se,
                                    estimates + uniform_crit * se])
    return {"se": se, "pointwise_ci": pointwise_ci, "uniform_band": uniform_band,
            "uniform_crit": uniform_crit, "band_type": "simultaneous", "B": B,
            "alpha": alpha, "seed": seed}
```

NOTE: previously `se` and `R` divided by `G` (rows). With `clusters=None`, `G == N`, so the divisor is identical → unclustered golden 0-drift. The change to `N` only matters when clustered.

- [ ] **Step 4: Run the new + existing inference tests**

```bash
.venv/bin/python -m pytest tests/test_cs_inference.py -q
```

Expected: ALL pass (new clustered tests + the existing unclustered ones unchanged).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/cs_inference.py tests/test_cs_inference.py
git commit -m "feat(cs_did): per-cluster multiplier bootstrap (entity-row IF, rowsum at variance step)"
```

---

## Task 3: `estimate_att_gt` — IF always entity-level + cluster validation

**Files:**
- Modify: `backend/workbench/engine/cs_attgt.py`
- Test: `tests/test_cs_attgt.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cs_attgt.py` (reuse its existing `_panel`/normalize helpers; if absent, build `norm` via `normalize_did_input` as in `test_cs_did_oracle.py`):

```python
import numpy as np, pandas as pd, pytest
from workbench.engine.did_spec import normalize_did_input
from workbench.engine.cs_attgt import estimate_att_gt, CSSpecError


def _norm(extra=None):
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    if extra:
        d = extra(d)
    return normalize_did_input(d, mode="cohort", entity="unit", time="period",
                               y="y", cohort="first_treat")


def test_clustered_if_is_entity_level():
    b = estimate_att_gt(_norm(), control_group="never", est_method="dr",
        base_period="varying", anticipation=0, covariates=["x1"], cluster_var="cluster")
    # IF rows = entities (60), NOT clusters (20)
    assert b.influence_func.shape[0] == 60
    assert b.aux["row_cluster"].shape[0] == 60
    assert len(np.unique(b.aux["row_cluster"])) == 20


def test_unclustered_row_cluster_is_entity():
    b = estimate_att_gt(_norm(), control_group="never", est_method="dr",
        base_period="varying", anticipation=0, covariates=["x1"], cluster_var=None)
    assert b.influence_func.shape[0] == 60
    assert len(np.unique(b.aux["row_cluster"])) == 60


def test_missing_cluster_col_raises():
    with pytest.raises(CSSpecError, match="CS_CLUSTER_COL_MISSING"):
        estimate_att_gt(_norm(), control_group="never", est_method="dr",
            base_period="varying", anticipation=0, covariates=["x1"], cluster_var="nope")


def test_single_cluster_raises():
    setone = lambda d: d.assign(cluster=0)
    with pytest.raises(CSSpecError, match="CS_CLUSTER_SINGLE"):
        estimate_att_gt(_norm(setone), control_group="never", est_method="dr",
            base_period="varying", anticipation=0, covariates=["x1"], cluster_var="cluster")


def test_nan_cluster_raises():
    setnan = lambda d: d.assign(cluster=d["cluster"].where(d["unit"] != d["unit"].iloc[0]))
    with pytest.raises(CSSpecError, match="CS_CLUSTER_COL_NAN"):
        estimate_att_gt(_norm(setnan), control_group="never", est_method="dr",
            base_period="varying", anticipation=0, covariates=["x1"], cluster_var="cluster")
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_cs_attgt.py -k cluster -q
```

Expected: FAIL — current code raises `CS_CLUSTERING_DEFERRED` for the first two and the error-path matches don't fire.

- [ ] **Step 3: Remove the deferral guard + the cluster-collapse; add validation**

In `backend/workbench/engine/cs_attgt.py`:

(a) DELETE the deferral block (lines ~331–342, the `if cluster_var: raise CSSpecError("CS_CLUSTERING_DEFERRED...")`).

(b) After `frame, entity, time, y = norm.frame, ...` and `units_all` is computed, resolve+validate the cluster assignment once:

```python
    # Resolve per-entity cluster id (entity-default when cluster_var falsy).
    if cluster_var:
        if cluster_var not in frame.columns:
            raise CSSpecError(f"CS_CLUSTER_COL_MISSING: '{cluster_var}' is not a column.")
        cl_by_unit = frame.drop_duplicates(entity).set_index(entity)[cluster_var]
        cl = cl_by_unit.loc[units_all]
        if cl.isna().any():
            raise CSSpecError("CS_CLUSTER_COL_NAN: cluster column has missing values.")
        cl = cl.to_numpy()
        if len(np.unique(cl)) < 2:
            raise CSSpecError("CS_CLUSTER_SINGLE: need >= 2 clusters for cluster-robust SE.")
        row_cluster = np.asarray(cl)
    else:
        row_cluster = np.asarray(units_all)
```

(c) REPLACE the old cluster-collapse block (lines ~401–411, `if cluster_var: ... cif = ...; else: cluster_ids = units_all; cif = obs_if`) so the IF is NEVER collapsed:

```python
    # Single row convention: influence_func stays ENTITY-level (N, K). Clustering
    # is applied only at the variance steps (cs_aggregate._se, cs_inference) via
    # aux["row_cluster"]. cluster_ids is descriptive only.
    cif = obs_if
    cluster_ids = np.unique(row_cluster)
```

(d) DELETE the now-dead module-level `cluster_influence` helper (lines ~193–199).

(e) The `aux = {...}` assignment near the end: drop the old `if cluster_var: row_cluster = np.asarray(cl) else ...` (now computed above) and just reference the resolved `row_cluster`:

```python
    aux = {"n_total": int(G), "row_cohort": row_cohort, "row_cluster": row_cluster}
```

Keep `vcov_config["cluster_level"]` as-is (`"entity"` when unclustered, else the column name).

- [ ] **Step 4: Run the new tests + the full cs_attgt + oracle suites**

```bash
.venv/bin/python -m pytest tests/test_cs_attgt.py tests/test_cs_did_oracle.py -q
```

Expected: ALL pass (unclustered oracles 0-drift; clustered shape + error tests green).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/cs_attgt.py tests/test_cs_attgt.py
git commit -m "feat(cs_did): entity-level IF + cluster validation; drop deferral guard & collapse"
```

---

## Task 4: Confirm `_se` clustered branch matches the oracle (1e-8/1e-10)

**Files:**
- Modify: `backend/workbench/engine/cs_aggregate.py` (comment only, unless oracle disagrees)
- Test: `tests/test_cs_did_clustering.py`

- [ ] **Step 1: Write the failing oracle-match test**

Append to `tests/test_cs_did_clustering.py`:

```python
from workbench.engine.did_spec import normalize_did_input
from workbench.engine.cs_attgt import estimate_att_gt
from workbench.engine.cs_aggregate import aggregate


def _bundle_clustered(method):
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    norm = normalize_did_input(d, mode="cohort", entity="unit", time="period",
        y="y", cohort="first_treat")
    return estimate_att_gt(norm, control_group="never", est_method=method,
        base_period="varying", anticipation=0, covariates=["x1"], cluster_var="cluster")


@pytest.mark.parametrize("method", ["dr", "ipw", "reg"])
def test_clustered_se_matches_R_crve(method):
    ref = CLUSTERED[method]
    b = _bundle_clustered(method)
    # dynamic: per-event-time SE (se_egt) + overall_se
    out = aggregate(b, "dynamic")
    if ref["dynamic"]["overall_se"] is not None:
        assert abs(out["overall_se"] - ref["dynamic"]["overall_se"]) < 1e-8
    # align our labels to R's egt order
    if ref["dynamic"]["se_egt"] is not None:
        our = {lab: se for lab, se in zip(out["label"], out["se"])}
        for e, se_r in zip(ref["dynamic"]["egt"], ref["dynamic"]["se_egt"]):
            assert abs(our[float(e)] - se_r) < 1e-8, f"e={e} ours={our[float(e)]} R={se_r}"


@pytest.mark.parametrize("kind", ["simple", "group", "calendar"])
def test_clustered_overall_se_matches_R(kind):
    ref = CLUSTERED["dr"][kind]
    b = _bundle_clustered("dr")
    out = aggregate(b, kind)
    if ref["overall_se"] is not None:
        assert abs(out["overall_se"] - ref["overall_se"]) < 1e-8


def test_point_estimates_cluster_invariant():
    # clustering must not move any point estimate
    bu = _bundle_clustered("dr")                       # clustered
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    norm = normalize_did_input(d, mode="cohort", entity="unit", time="period",
        y="y", cohort="first_treat")
    bc = estimate_att_gt(norm, control_group="never", est_method="dr",
        base_period="varying", anticipation=0, covariates=["x1"], cluster_var=None)
    assert np.allclose(np.nan_to_num(bu.estimates), np.nan_to_num(bc.estimates), atol=1e-12)
    for kind in ("simple", "dynamic", "group", "calendar"):
        ou, oc = aggregate(bu, kind), aggregate(bc, kind)
        if ou["overall"] is not None:
            assert abs(ou["overall"] - oc["overall"]) < 1e-12
```

- [ ] **Step 2: Run to verify (expect PASS if n=N is correct, else FAIL)**

```bash
.venv/bin/python -m pytest tests/test_cs_did_clustering.py -q
```

Expected: PASS. `_se` already computes `sqrt(Σ_c S_c²)/n` with `n=n_total=N` and clusters via `row_cluster` — the oracle uses the same n=N. If any assertion FAILS, the discrepancy is the `n` convention: inspect `aggte_clustered.json`'s `n`/`n_clusters` and adjust `_se`'s `n` accordingly (this is the one oracle-decided knob — change ONLY the divisor, never weaken the 1e-8 tolerance).

- [ ] **Step 3: Pin the convention with a comment**

In `cs_aggregate.py:_se`, replace the stale "UNVALIDATED: variable-clustering deferred" comment (line ~90) with:

```python
        # Cluster-robust CRVE: S_c = sum_{i in c} if_i, se = sqrt(sum_c S_c^2)/N
        # with N = entity count (NOT n_clusters) — forced by the unclustered
        # identity and validated to 1e-8 vs the R-built oracle (aggte_clustered.json).
        clustered = np.array([entity_if[row_cluster == c].sum() for c in uniq])
```

Also update the stale comment at `_attach_influence` (line ~191) to drop "UNVALIDATED/deferred".

- [ ] **Step 4: Re-run + full aggregate suite**

```bash
.venv/bin/python -m pytest tests/test_cs_did_clustering.py tests/test_cs_did_oracle.py -q
```

Expected: PASS, oracles 0-drift.

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/engine/cs_aggregate.py tests/test_cs_did_clustering.py
git commit -m "test(cs_did): validate clustered analytical SE vs R CRVE oracle (1e-8)"
```

---

## Task 5: `run_cs_did` end-to-end clustering + honest metadata

**Files:**
- Modify: `backend/workbench/econometrics/runner.py`
- Test: `tests/test_run_cs_did.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_run_cs_did.py` (mirror its `_norm` helper; add a `cluster` column variant):

```python
def _norm_cluster():
    import pandas as pd
    from workbench.engine.did_spec import normalize_did_input
    d = pd.read_csv("tests/fixtures/cs_did/panel.csv")
    return normalize_did_input(d, mode="cohort", entity="unit", time="period",
        y="y", cohort="first_treat")


def test_run_cs_did_clustered_metadata():
    res = run_cs_did(_norm_cluster(), covariates=["x1"], control_group="never",
        est_method="dr", base_period="varying", anticipation=0,
        cluster_var="cluster", seed=20260615)
    m = res["metadata"]
    assert m["n_units"] == 60          # entities, never overwritten
    assert m["n_clusters"] == 20
    assert m["cluster_level"] == "cluster"


def test_run_cs_did_entity_metadata():
    res = run_cs_did(_norm_cluster(), covariates=["x1"], control_group="never",
        est_method="dr", base_period="varying", anticipation=0,
        cluster_var=None, seed=20260615)
    m = res["metadata"]
    assert m["n_units"] == 60 and m["n_clusters"] == 60
    assert m["cluster_level"] == "entity"


def test_run_cs_did_clustered_runs_and_bands_present():
    res = run_cs_did(_norm_cluster(), covariates=["x1"], control_group="never",
        est_method="dr", base_period="varying", anticipation=0,
        cluster_var="cluster", seed=1)
    dyn = res["aggregations"]["dynamic"]
    assert dyn["overall_uniform_band"] is not None
    assert len(dyn["uniform_band"]) == len(dyn["estimate"])
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_run_cs_did.py -k "clustered or entity_metadata" -q
```

Expected: FAIL (`KeyError: 'n_clusters'`; clustered run currently raises `CS_CLUSTERING_DEFERRED`).

- [ ] **Step 3: Pass `row_cluster` into the bootstrap + honest metadata**

In `backend/workbench/econometrics/runner.py`, inside `run_cs_did`:

(a) After `bundle = estimate_att_gt(...)`, capture the cluster vector:

```python
    G = bundle.influence_func.shape[0]
    row_cluster = bundle.aux["row_cluster"]
    n_clusters = int(np.unique(row_cluster).size)
```

(b) In the overall-band call, pass `clusters=row_cluster` and keep the reshape (now safe, `G==N`):

```python
        if agg["overall"] is not None and agg["overall_if"] is not None:
            ob = multiplier_bootstrap(np.asarray(agg["overall_if"]).reshape(G, 1),
                B=B, alpha=alpha, seed=seed, estimates=np.array([agg["overall"]]),
                clusters=row_cluster)
```

(c) In the per-label band call, pass `clusters=row_cluster`:

```python
            lb = multiplier_bootstrap(agg["component_if"], B=B, alpha=alpha, seed=seed,
                estimates=np.asarray(agg["estimate"], dtype=float), clusters=row_cluster)
```

(d) In the `metadata` dict, add the honest cluster fields (cluster_level from the bundle's `vcov_config`):

```python
    metadata = {"control_group": control_group, "est_method": est_method,
        "base_period": base_period, "anticipation": anticipation,
        "covariates": list(covariates), "cluster_var": cluster_var,
        "n_units": int(G), "n_clusters": n_clusters,
        "cluster_level": bundle.vcov_config.get("cluster_level", "entity"),
        "n_cohorts": len(cohorts),
        "n_valid_cells": int(sum(1 for m in bundle.cell_metadata if m["valid"])),
        "n_cells": len(bundle.cell_metadata), "B": B, "alpha": alpha, "seed": seed,
        "confidence_level": 1 - alpha, "band_type": "simultaneous"}
```

- [ ] **Step 4: Run the run_cs_did suite**

```bash
.venv/bin/python -m pytest tests/test_run_cs_did.py -q
```

Expected: ALL pass (clustered + unclustered, metadata fields present).

- [ ] **Step 5: Commit**

```bash
git add backend/workbench/econometrics/runner.py tests/test_run_cs_did.py
git commit -m "feat(cs_did): run_cs_did clustered bootstrap + n_clusters/cluster_level metadata"
```

---

## Task 6: End-to-end wiring + hardening (bad cluster inputs → MODEL_FIT_FAILED)

**Files:**
- Test: `tests/test_cs_did_hardening.py`, `tests/test_cs_did_wiring.py`

- [ ] **Step 1: Write failing wiring + hardening tests**

Append to `tests/test_cs_did_hardening.py` (follow its existing run-workflow harness; check the file for the `create_project`/`run_workflow` helper it already uses and reuse it):

```python
def test_clustered_cs_did_completes_end_to_end(tmp_path):
    # a full workflow run with cs_cluster_var set must COMPLETE (not deferred)
    import pandas as pd, numpy as np
    rng = np.random.default_rng(5)
    rows = []
    for i in range(40):
        cohort = [0, 2019, 2020, 2021][i % 4]
        x1, fe = float(rng.normal()), float(rng.normal())
        for year in range(2017, 2023):
            d = 1 if (cohort and year >= cohort) else 0
            y = fe + 0.1*(year-2017) + 0.3*x1 + 2.0*d + 0.05*rng.normal()
            rows.append({"id": f"u{i:02d}", "year": year, "first_treat": cohort,
                         "x1": round(x1,6), "y": round(y,6), "grp": i % 8})
    snap = _run_cs(tmp_path, pd.DataFrame(rows), cs_cluster_var="grp")  # helper in this file
    assert snap["status"] == "completed"
    assert snap["artifacts"]["cs_did"]["metadata"]["cluster_level"] == "grp"


def test_bad_cluster_col_is_structured_failure(tmp_path):
    import pandas as pd, numpy as np
    rng = np.random.default_rng(6)
    rows = []
    for i in range(40):
        cohort = [0, 2019, 2020, 2021][i % 4]
        x1, fe = float(rng.normal()), float(rng.normal())
        for year in range(2017, 2023):
            d = 1 if (cohort and year >= cohort) else 0
            rows.append({"id": f"u{i:02d}", "year": year, "first_treat": cohort,
                         "x1": round(x1,6), "y": round(fe+2.0*d,6)})
    snap = _run_cs(tmp_path, pd.DataFrame(rows), cs_cluster_var="does_not_exist")
    assert snap["status"] == "failed"
    # must be structured MODEL_FIT_FAILED, not WORKFLOW_FAILED
    assert "CS_CLUSTER_COL_MISSING" in str(snap)
```

If `test_cs_did_hardening.py` has no `_run_cs` helper, add one mirroring `test_engine_golden.py:_run` (it accepts `model_type="cs_did"`, `did_mode="cohort"`, `did_cohort_col`, `cs_*` kwargs) and capture the run snapshot the same way `_capture` does.

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_cs_did_hardening.py -k "clustered or bad_cluster" -q
```

Expected: the completion test FAILS today (deferred → failed status); the bad-col test may already pass via the new validation.

- [ ] **Step 3: Confirm green (no new impl expected — wiring already exists)**

The api → `_run_workflow` → `run_cs_did` path already threads `cs_cluster_var` (api.py:336). With Tasks 3+5 done, the completion test should pass. If `_run_cs` reveals a missing thread between `_run_workflow` and `run_cs_did`, add the pass-through there (grep `cs_control_group` in the estimation/runner dispatch to find the call site and add `cluster_var=cs_cluster_var` beside it).

```bash
.venv/bin/python -m pytest tests/test_cs_did_hardening.py tests/test_cs_did_wiring.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_cs_did_hardening.py tests/test_cs_did_wiring.py
git commit -m "test(cs_did): end-to-end clustered run completes; bad cluster col -> structured failure"
```

---

## Task 7: Frontend — restore cluster selector + show cluster diagnostics

**Files:**
- Modify: `frontend/src/runForm/CSControls.tsx`, `frontend/src/runForm/CSControls.test.tsx`
- Modify: `frontend/src/runForm/RunForm.tsx`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/runResult/CSDiagnosticsCard.tsx`

- [ ] **Step 1: Update the failing CSControls test (selector now PRESENT)**

In `frontend/src/runForm/CSControls.test.tsx`, replace the v1.5.6 "removed" assertion (lines ~19–20) with a presence + change test, and pass a `columns` prop:

```tsx
it("renders the cluster-var selector and reports changes", () => {
  const onChange = vi.fn();
  render(<CSControls value={baseValue} columns={["unit", "region", "x1"]} onChange={onChange} />);
  const sel = screen.getByLabelText("cs-cluster-var") as HTMLSelectElement;
  expect(sel).toBeInTheDocument();
  fireEvent.change(sel, { target: { value: "region" } });
  expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ clusterVar: "region" }));
});
```

(`baseValue` must now include `clusterVar: ""`. Update any existing render calls in this file to pass `columns={[]}`.)

- [ ] **Step 2: Run to verify it fails**

```bash
cd frontend && npx vitest run src/runForm/CSControls.test.tsx; cd ..
```

Expected: FAIL (no `cs-cluster-var` element; `clusterVar` not on `CSValue`).

- [ ] **Step 3: Add `clusterVar` to `CSValue` + render the optional selector**

In `frontend/src/runForm/CSControls.tsx`:

```tsx
export interface CSValue {
  controlGroup: "never" | "not_yet";
  estMethod: "dr" | "ipw" | "reg";
  basePeriod: "varying" | "universal";
  anticipation: number;
  clusterVar: string;          // "" = cluster by entity (default)
}

export function CSControls(props: {
  value: CSValue;
  columns: string[];
  onChange: (v: CSValue) => void;
}) {
  const { value, columns, onChange } = props;
  const set = (patch: Partial<CSValue>) => onChange({ ...value, ...patch });
  // ... existing fields unchanged ...
```

Add, after the anticipation field, before the closing `</div>`:

```tsx
      <label className="ios-field">
        <span>聚类变量 (cluster, 选填)</span>
        <select
          aria-label="cs-cluster-var"
          value={value.clusterVar}
          onChange={(e) => set({ clusterVar: e.target.value })}
        >
          <option value="">按实体 (entity, 默认)</option>
          {columns.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </label>
```

- [ ] **Step 4: Thread `clusterVar` through RunForm + api.ts**

In `frontend/src/runForm/RunForm.tsx`: add `clusterVar: ""` to the `csValue` initial state (line ~80); pass `columns={columnNames}` to `<CSControls>` (line ~426); add to the post payload (line ~265 block):

```tsx
          csClusterVar: isCsDid ? csValue.clusterVar : undefined,
```

In `frontend/src/api.ts` (after the `csAnticipation` append, line ~378) add the field to `RunExtraParams` type and the append:

```ts
  if (extra?.csClusterVar) form.append("cs_cluster_var", extra.csClusterVar);
```

(Add `csClusterVar?: string;` to the `RunExtraParams` interface where `csAnticipation?` is declared.)

- [ ] **Step 5: Show cluster diagnostics in CSDiagnosticsCard**

In `frontend/src/runResult/CSDiagnosticsCard.tsx`, where metadata is rendered, add a degraded-safe line (cluster_level/n_clusters may be absent on old artifacts):

```tsx
{metadata.cluster_level && (
  <div className="cs-meta-row">
    <span>聚类层级</span>
    <span>
      {metadata.cluster_level === "entity"
        ? "实体 (entity)"
        : `${metadata.cluster_level} · ${metadata.n_clusters ?? "?"} 簇`}
      （cluster-robust SE）
    </span>
  </div>
)}
```

(Match the card's existing row markup/classnames; if its metadata type is explicit, add `cluster_level?: string; n_clusters?: number;`.)

- [ ] **Step 6: Run the frontend gate**

```bash
cd frontend && npx vitest run && npx tsc --noEmit; cd ..
```

Expected: all vitest pass, tsc 0 errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/runForm/CSControls.tsx frontend/src/runForm/CSControls.test.tsx \
        frontend/src/runForm/RunForm.tsx frontend/src/api.ts \
        frontend/src/runResult/CSDiagnosticsCard.tsx
git commit -m "feat(cs_did): restore cluster-var selector + cluster-robust diagnostics (FE)"
```

---

## Task 8: Additive clustered golden + docs + final gate

**Files:**
- Modify: `tests/test_engine_golden.py`
- Create (generated): `tests/golden/cs_did_clustered.json`
- Modify: `docs/cs-did-howto.md`
- Create: `docs/v1.5.6.1-release-notes.md`

- [ ] **Step 1: Add an additive clustered golden test**

In `tests/test_engine_golden.py`, after `test_golden_cs_did_staggered`, add a clustered variant (a `cluster` column + `cs_cluster_var="cluster"`):

```python
def test_golden_cs_did_clustered(tmp_path):
    import numpy as np
    rng = np.random.default_rng(11)
    rows = []
    for i in range(40):
        ent = f"u{i:02d}"
        cohort = [0, 2019, 2020, 2021][i % 4]
        x1 = round(float(rng.normal()), 6)
        fe = round(float(rng.normal()), 6)
        for year in range(2017, 2023):
            d = 1 if (cohort and year >= cohort) else 0
            y = round(fe + 0.1*(year-2017) + 0.3*x1 + 2.0*d + 0.05*rng.normal(), 6)
            rows.append({"id": ent, "year": year, "first_treat": cohort,
                         "x1": x1, "y": y, "cl": i % 10})   # 10 clusters of 4
    run_root, _ = _run(tmp_path, pd.DataFrame(rows), y="y", x=["x1"], model_type="cs_did",
                       entity_col="id", time_col="year", did_mode="cohort",
                       did_cohort_col="first_treat", cs_control_group="never",
                       cs_est_method="dr", cs_base_period="varying", cs_cluster_var="cl")
    snap = _capture(run_root)
    assert snap["status"] == "completed"
    assert snap["artifacts"]["cs_did"]["metadata"]["cluster_level"] == "cl"
    _assert_or_write_golden("cs_did_clustered", snap)
```

If `_run` does not yet forward `cs_cluster_var`, add it to that helper's kwargs and to its `_run_workflow` call (mirror the existing `cs_control_group` forwarding).

- [ ] **Step 2: Generate the golden, then re-run to prove it is frozen**

```bash
.venv/bin/python -m pytest tests/test_engine_golden.py::test_golden_cs_did_clustered -q   # writes golden
.venv/bin/python -m pytest tests/test_engine_golden.py -q                                  # 0-drift now
```

Expected: first run writes `tests/golden/cs_did_clustered.json`; second run all golden tests pass with 0 drift (existing 18 + 1 new = 19).

- [ ] **Step 3: Document clustering in the how-to + release notes**

Add a "Clustering" section to `docs/cs-did-howto.md`: leave the cluster field empty to cluster by entity (default); pick a column for one-way variable clustering; SE/bands become cluster-robust; the point estimates are unchanged; two-way clustering is not yet supported.

Create `docs/v1.5.6.1-release-notes.md` summarizing: dormant clustering path completed; single row convention; deterministic CRVE oracle; restored UI selector; honest `n_units`/`n_clusters`/`cluster_level`; gate numbers.

- [ ] **Step 4: Full gate**

```bash
.venv/bin/python -m pytest -q
cd frontend && npx vitest run && npx tsc --noEmit && cd ..
./scripts/gate.sh
```

Expected: BE 908 + new tests passed, golden/invariants/snapshot 19 (0-drift), FE 617 + new passed, tsc 0, `GATE PASSED`.

- [ ] **Step 5: Commit**

```bash
git add tests/test_engine_golden.py tests/golden/cs_did_clustered.json \
        docs/cs-did-howto.md docs/v1.5.6.1-release-notes.md
git commit -m "test(cs_did): additive clustered golden + clustering docs/release notes"
```

---

## Final: whole-feature adversarial review (before merge)

- [ ] Run a whole-branch adversarial review (the v1.5.5.1 lesson) focused on FAILURE PATHS and the new clustering math: confirm no bad cluster input escapes to `WORKFLOW_FAILED`; confirm the unclustered path is byte-identical golden 0-drift; confirm the clustered SE matches the oracle to 1e-8 for dr/ipw/reg across all four aggregations; confirm `metadata.n_units` is never the cluster count.
- [ ] Fix anything found; re-run the full gate.
- [ ] Present finishing options (merge `--no-ff` + tag `v1.5.6.1`, verify gated-branch-head vs merged-tree empty diff). Push to main requires explicit per-version authorization.

---

## Self-Review (completed by author)

- **Spec coverage:** §3.1① → Task 3; §3.1② → Task 4; §3.1③ → Task 2; §3.1④ → Task 5; §4 oracle → Task 1+4; §5 errors → Task 3+6; §6 frontend → Task 7; §7 golden → Task 8; §9 gate → Task 8 + Final; §10 Layer-3 hook → carried in spec. All covered.
- **Placeholder scan:** no TBD/TODO; every code step has concrete code; the one oracle-decided knob (`n` in `_se`) is explicit with both the expected value (N) and the fallback procedure.
- **Type consistency:** `clusters=` (cs_inference) ↔ `row_cluster`/`bundle.aux["row_cluster"]` (cs_attgt/runner); `CSValue.clusterVar` ↔ `csClusterVar` (RunForm) ↔ `cs_cluster_var` (api) consistent end to end; `cluster_level`/`n_clusters` consistent across runner metadata, golden assert, and FE card.
