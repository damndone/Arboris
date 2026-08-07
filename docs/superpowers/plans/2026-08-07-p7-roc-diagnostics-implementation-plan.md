# P7 ROC Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** Build a bounded, score-only ROC/classification diagnostics pack with an independent base-R Oracle.

**Architecture:** Separate target/score validation, curve construction, threshold diagnostics, and calibration. No model fitting or prediction-data access is introduced.

**Tech Stack:** Python 3.14, pandas, NumPy, SciPy, pytest, R base in tests only.

---

### Task 1: Contract and RED tests

**Files:** Create `backend/workbench/contracts/model/roc_diagnostics.py`; create `tests/test_roc_diagnostics_pack.py`.

- [ ] Write failing tests for explicit positive label, score semantics, probability bounds, unknown policies, output bounds, and envelope readback.
- [ ] Run the focused file and confirm the missing-module failure.
- [ ] Implement closed operations, stable errors, provenance, and bounded JSON fields.
- [ ] Re-run contract tests.

### Task 2: ROC/PR curves and threshold diagnostics

**Files:** Create `backend/workbench/engine/packs/roc_diagnostics/__init__.py`; modify the dedicated tests.

- [ ] Write failing fixed-input tests for tied scores, all ties, AUC, PR-AUC, threshold counts, and metric identities.
- [ ] Implement deterministic score sorting, explicit threshold policy, rank-based AUC, stepwise PR-AUC, and confusion metrics.
- [ ] Add base-R Oracle subprocess tests for AUC and selected thresholds.
- [ ] Add label-flip, non-finite, empty-class, and bound tests.

### Task 3: Probability diagnostics and calibration

- [ ] Write a failing test for Brier/log-loss and equal-width/quantile calibration bins.
- [ ] Implement probability-only validation, stable zero-probability log-loss handling, and bounded calibration output.
- [ ] Add Oracle comparisons for Brier/log-loss and test that arbitrary scores cannot silently enter probability metrics.
- [ ] Run the full dedicated suite and `git diff --check`.

### Task 4: Review and handoff

- [ ] Run adjacent P7 tests, request spec and quality reviews, fix/re-review issues, and record known limits.
