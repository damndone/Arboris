# P7 Extensions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add standalone clustering, discriminant, and time-series statistical kernels to the existing P7 worktree without touching Claude's Agent workflow seam.

**Architecture:** Extend the existing multivariate pack with focused clustering and discriminant modules, and create an independent time-series pack plus contract. Reuse the existing numeric/error/JSON boundary where semantics match, but keep time-series ordering and model options in its own contract. No operation registry, orchestrator, context tool, frontend, or persistence changes are allowed.

**Tech Stack:** Python 3, pandas, NumPy, SciPy, statsmodels, pytest; no new dependencies.

---

### Task 1: Formal same-worktree scope and shared result surface

**Files:**
- Modify: `backend/workbench/contracts/model/multivariate.py`
- Modify: `backend/workbench/engine/packs/multivariate/__init__.py`
- Create: `backend/workbench/contracts/model/time_series_pack.py`
- Create: `backend/workbench/engine/packs/time_series/__init__.py`
- Test: `tests/test_statistical_extensions.py`

- [x] Write failing tests for closed extension operation IDs, exact envelope fields, time-series option validation, and protected-path assumptions.
- [x] Run the extension tests and confirm missing-module failures.
- [x] Add only the new operation IDs and independent time-series result helpers; do not register them with Agent or model registries.
- [x] Run the contract tests and commit the shared surface.

### Task 2: Deterministic clustering

**Files:**
- Create: `backend/workbench/engine/packs/multivariate/clustering.py`
- Modify: `backend/workbench/engine/packs/multivariate/__init__.py`
- Test: `tests/test_statistical_extensions.py`

- [x] Write red tests for explicit standardization, deterministic fixed-k k-means, bounded candidate silhouette comparison, hierarchical linkage restrictions, and unsafe input rejection.
- [x] Run only clustering tests and confirm the missing-symbol failure.
- [x] Implement deterministic k-means with explicit seed/iteration/tolerance, a bounded silhouette calculation, and SciPy hierarchical clustering with declared linkage/metric constraints.
- [x] Return centers/labels/metrics only under declared output bounds and preserve the selection policy/provenance.
- [x] Run clustering tests and commit.

### Task 3: Safe LDA/QDA discriminant analysis

**Files:**
- Create: `backend/workbench/engine/packs/multivariate/discriminant.py`
- Modify: `backend/workbench/engine/packs/multivariate/__init__.py`
- Test: `tests/test_statistical_extensions.py`

- [x] Write red tests for LDA/QDA class ordering, empirical/declared priors, explicit covariance regularization, singular-matrix fail-closed behavior, and bounded holdout evaluation.
- [x] Run only discriminant tests and confirm the missing-symbol failure.
- [x] Implement real-valued Gaussian discriminant scoring with explicit priors and regularization; do not use a silent pseudoinverse fallback.
- [x] Return class-conditional parameters, predictions/metrics only when explicitly requested, and no raw rows.
- [x] Run discriminant tests and commit.

### Task 4: Time-series input and diagnostics

**Files:**
- Create: `backend/workbench/engine/packs/time_series/input.py`
- Create: `backend/workbench/engine/packs/time_series/diagnostics.py`
- Test: `tests/test_time_series_pack.py`

- [x] Write red tests for explicit time ordering, complete-case filtering, ACF/PACF lag bounds, ADF/KPSS option declarations, and no hidden frequency inference.
- [x] Run diagnostics tests and confirm missing-symbol failures.
- [x] Implement strict series preparation, ACF/PACF, ADF, and KPSS with exact options and bounded outputs.
- [x] Run diagnostics tests and commit.

### Task 5: Explicit ARIMA/SARIMA and VAR/Granger/IRF

**Files:**
- Create: `backend/workbench/engine/packs/time_series/models.py`
- Create: `backend/workbench/engine/packs/time_series/var.py`
- Modify: `backend/workbench/engine/packs/time_series/__init__.py`
- Test: `tests/test_time_series_models.py`

- [x] Write red tests for explicit ARIMA/SARIMA orders, bounded forecasts, VAR lag/trend validation, Granger direction semantics, and finite IRF horizons.
- [x] Run model tests and confirm missing-symbol failures.
- [x] Implement statsmodels-backed explicit ARIMA/SARIMA fitting and VAR/Granger/IRF evidence without autonomous order selection or causal claims.
- [x] Normalize summaries into JSON-safe bounded packets with estimator/version provenance.
- [x] Run model tests and commit.

### Task 6: Full local verification and handoff

**Files:**
- Test: `tests/test_statistical_extensions.py`, `tests/test_time_series_pack.py`, `tests/test_time_series_models.py`
- Review: all new pack/contract/docs files

- [x] Run all new tests plus adjacent Agent regression tests and `git diff --check`.
- [x] Verify Claude-owned P0/P1/P2 paths have no diff from the baseline.
- [x] Verify the formal event stream and Context Pack.
- [x] Record that Agent reachability, UI, browser acceptance, full gate, and release remain future work.

---

## Phase 2: evidence-complete extensions

### Task 7: Cointegration and VECM

**Files:**
- Create: `backend/workbench/engine/packs/time_series/cointegration.py`
- Modify: `backend/workbench/engine/packs/time_series/__init__.py`
- Modify: `backend/workbench/contracts/model/time_series_pack.py`
- Test: `tests/test_time_series_models.py`

- [x] Write red tests for Engle-Granger pair restrictions, Johansen rank evidence, rank-zero rejection, explicit VECM policy, bounded forecasts, and JSON-safe packets.
- [x] Run only the new cointegration/VECM tests and confirm missing-symbol failures.
- [x] Implement direct statsmodels-backed Engle-Granger/Johansen evidence with explicit deterministic and lag policies; derive rank sequentially from critical values.
- [x] Implement VECM using the derived Johansen trace rank; reject rank zero instead of fabricating an equilibrium model.
- [x] Run the focused time-series model tests and commit.

### Task 8: VAR stability and IRF confidence bands

**Files:**
- Modify: `backend/workbench/engine/packs/time_series/var.py`
- Modify: `tests/test_time_series_models.py`

- [x] Write red tests for stable/unstable companion evidence, explicit unstable-fit policy, and IRF asymptotic confidence bands with a declared confidence level/method.
- [x] Run the new VAR tests and confirm the current result is missing stability/band evidence.
- [x] Add companion eigenvalue/modulus evidence and fail-closed default stability policy to VAR.
- [x] Add asymptotic-normal IRF lower/upper bands from statsmodels standard errors; label the method and never call it bootstrap.
- [x] Run focused and existing time-series model tests and commit.

### Task 9: Correspondence analysis and MCA

**Files:**
- Create: `backend/workbench/engine/packs/multivariate/correspondence.py`
- Modify: `backend/workbench/engine/packs/multivariate/__init__.py`
- Modify: `backend/workbench/contracts/model/multivariate.py`
- Test: `tests/test_statistical_extensions.py`

- [x] Write red tests for CA masses/coordinates/inertia, MCA indicator construction, deterministic category ordering, and unsafe table/missing-category rejection.
- [x] Run only CA/MCA tests and confirm missing-symbol failures.
- [x] Implement one bounded SVD-based CA core reused by CA and explicitly labelled indicator-CA MCA.
- [x] Return coordinates/contributions/inertia as JSON-safe evidence without raw input rows or hidden category coercion.
- [x] Run focused multivariate tests and commit.

### Task 10: External numerical oracle

**Files:**
- Modify: `tests/test_time_series_models.py`
- Modify: `tests/test_statistical_extensions.py`

- [x] Write oracle tests that compare direct statsmodels reference outputs and a base-R SVD reference for a fixed CA table; skip only when the external executable is unavailable.
- [x] Run oracle tests and record exact skip/pass state; an unavailable oracle is not reported as a numerical pass.
- [x] Add no runtime dependency on R or shell execution; keep all oracle calls inside tests with fixed inputs and argv-based subprocess invocation.
- [x] Run the complete extension suite, adjacent Agent tests, protected-path diff, `git diff --check`, and formal FMS verification.
- [x] Record the remaining Agent/UI/browser/full-gate limits and commit the verification update.
