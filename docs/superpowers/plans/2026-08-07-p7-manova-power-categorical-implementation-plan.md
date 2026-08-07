# P7 MANOVA, Power Analysis, and Categorical Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add standalone MANOVA, power-analysis, and Cramér's V/McNemar kernels with explicit contracts, fail-closed validation, and external numerical oracles.

**Architecture:** MANOVA extends the existing multivariate pack in a dedicated module. Power analysis and categorical tests each receive a separate contract and pack because their inputs and future Agent capabilities are different. No Agent, workflow, data-management, persistence, or frontend files are touched.

**Tech Stack:** Python 3, pandas, NumPy, SciPy, statsmodels, pytest, optional base R for test-only oracle checks; no new dependency.

---

### Task 1: MANOVA kernel

**Files:**
- Modify: `backend/workbench/contracts/model/multivariate.py`
- Create: `backend/workbench/engine/packs/multivariate/manova.py`
- Modify: `backend/workbench/engine/packs/multivariate/__init__.py`
- Test: `tests/test_manova_pack.py`

- [ ] Write red tests for one-factor MANOVA, explicit factor/covariate policy, deterministic repeated calls, all four multivariate tests, JSON-safe output, rank/df evidence, and non-finite/insufficient-design rejection.
- [ ] Run `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_manova_pack.py -q -p no:cacheprovider` and confirm the missing MANOVA symbol/operation failure.
- [ ] Implement quoted structured-term formula construction, complete-case preparation, statsmodels MANOVA execution, deterministic category policy, stable numeric parsing, and fail-closed validation.
- [ ] Add `multivariate.manova` to the closed contract and export only the kernel function/constants from the pack package.
- [ ] Re-run the focused test and commit the self-contained task.

### Task 2: Power-analysis kernel

**Files:**
- Create: `backend/workbench/contracts/model/power_analysis.py`
- Create: `backend/workbench/engine/packs/power_analysis/__init__.py`
- Create: `backend/workbench/engine/packs/power_analysis/solver.py`
- Test: `tests/test_power_analysis_pack.py`

- [ ] Write red tests for independent-t, one-way ANOVA, and two-proportion-z solve targets, exactly-one-unknown validation, explicit effect-size conventions, bounded sensitivity grids, deterministic output, and invalid range rejection.
- [ ] Run the focused test and confirm the missing pack/contract failure.
- [ ] Implement the design dispatch through statsmodels power solvers with explicit parameter validation, one-unknown solving, bounded sensitivity evaluation, and JSON-native provenance.
- [ ] Do not infer effect sizes, alpha, power, k-groups, ratio, or alternative; reject omitted values that are not the declared solve target.
- [ ] Re-run the focused test and commit the self-contained task.

### Task 3: Categorical test kernel

**Files:**
- Create: `backend/workbench/contracts/model/categorical.py`
- Create: `backend/workbench/engine/packs/categorical/__init__.py`
- Create: `backend/workbench/engine/packs/categorical/tests.py`
- Test: `tests/test_categorical_pack.py`

- [ ] Write red tests for Cramér's V with explicit correction, expected-count evidence, McNemar exact and asymptotic modes, paired-table validation, deterministic repeated calls, and no-discordance rejection.
- [ ] Run the focused test and confirm the missing pack/contract failure.
- [ ] Implement strict integer count-table validation, scipy chi-square/Cramér's V, statsmodels McNemar, stable method labels, and fail-closed degenerate cases.
- [ ] Keep correction/exactness policies in the result and never silently switch methods because a cell is small.
- [ ] Re-run the focused test and commit the self-contained task.

### Task 4: External Oracle acceptance

**Files:**
- Modify: `tests/test_manova_pack.py`
- Modify: `tests/test_power_analysis_pack.py`
- Modify: `tests/test_categorical_pack.py`

- [ ] Add a direct statsmodels MANOVA oracle using a fixed independently-written formula and compare all four statistics, degrees of freedom, F values, and p values.
- [ ] Add direct statsmodels power-oracle calls for each supported design and compare solved values at a declared tolerance.
- [ ] Add a base-R categorical oracle for chi-square/Cramér's V and McNemar when `Rscript` is available; skip only when the executable is absent.
- [ ] Verify that runtime imports never invoke R/subprocess and that oracle tests use fixed inputs, bounded timeouts, and argv-based execution.

### Task 5: Integration, review, and verification

**Files:**
- Modify: `task_plan.md`, `findings.md`, `progress.md`
- Review: all new contract, pack, test, design, and plan files

- [ ] Run the three focused suites and the existing P7 extension suite.
- [ ] Run adjacent Agent/workflow regression tests without modifying their files.
- [ ] Run `git diff --check`, inspect the full diff, and compare Claude-owned paths against the prior P7 baseline.
- [ ] Run formal FMS verification for `v1-8-8-p7-extensions` and record any failure/gap/review event through `scripts/devline_control.py`.
- [ ] Report Agent reachability, frontend, browser, full-gate, merge, push, and release status separately; do not claim them complete.
