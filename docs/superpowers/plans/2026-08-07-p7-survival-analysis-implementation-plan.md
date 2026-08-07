# P7 Survival Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** Add Kaplan–Meier, log-rank, and RMST as an independent survival kernel with R Oracle validation.

**Architecture:** A pure pandas/NumPy/SciPy pack consumes explicit duration/event/entry/group columns. The existing Cox family remains untouched; future Agent adapters can map typed specs later.

**Tech Stack:** Python 3.14, pandas, NumPy, SciPy, pytest, R `survival` in tests only.

---

### Task 1: Contract and RED tests

**Files:** Create `backend/workbench/contracts/model/survival_analysis.py`; create `tests/test_survival_analysis_pack.py`.

- [ ] Write failing tests for operation IDs, event/duration/entry validation, explicit RMST tau, group limits, and versioned envelopes.
- [ ] Run the focused test file and confirm the expected missing-module failure.
- [ ] Implement closed policies, stable error codes, bounded result fields, and JSON-safe readback validation.
- [ ] Re-run contract tests.

### Task 2: Kaplan–Meier and RMST

**Files:** Create `backend/workbench/engine/packs/survival_analysis/__init__.py`; modify the dedicated tests.

- [ ] Write failing tests for one-group KM, censoring, delayed entry, Greenwood/log-log intervals, median, and RMST.
- [ ] Implement risk-set construction with explicit tie handling; reject invalid or non-finite inputs before computation.
- [ ] Add R `survfit` Oracle tests and compare event tables, survival, CI, median, and RMST.
- [ ] Add all-censored/no-event and tau-out-of-support tests.

### Task 3: Log-rank

- [ ] Write a failing two-group and multi-group log-rank test.
- [ ] Implement tied-time observed/expected accumulation and covariance with df = groups−1.
- [ ] Add R `survdiff` Oracle coverage and a no-discordance/degenerate-group rejection.
- [ ] Run the complete dedicated survival suite and `git diff --check`.

### Task 4: Review and handoff

- [ ] Request spec-compliance review, then code-quality review; resolve all Important/Critical findings.
- [ ] Record Oracle tolerance, tie semantics, and known non-goals in tracking files.
