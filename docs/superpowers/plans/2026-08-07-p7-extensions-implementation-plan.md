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
