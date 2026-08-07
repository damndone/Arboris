# P7 Repeated-Measures ANOVA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** Build a standalone, contract-validated repeated-measures and one-between-factor mixed ANOVA kernel.

**Architecture:** Keep the pack independent from LMM and the automatic statistical-test stage. Use statsmodels for repeated-only, an explicit balanced error-layer calculation for mixed design, and R base as an external Oracle.

**Tech Stack:** Python 3.14, pandas, NumPy, SciPy, statsmodels, pytest, R base `aov` in tests only.

---

### Task 1: Contract and RED tests

**Files:** Create `backend/workbench/contracts/model/repeated_measures_anova.py`; create `tests/test_repeated_measures_anova_pack.py`.

- [ ] Add failing tests for operation IDs, required explicit columns, duplicate-cell rejection, incomplete-balance rejection, between-label consistency, and JSON-safe result envelope.
- [ ] Run `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_repeated_measures_anova_pack.py -q -p no:cacheprovider`; confirm failure is the missing contract/module.
- [ ] Implement closed operation IDs, versioned envelope, explicit correction/design policies, bounded fields, and stable error codes.
- [ ] Re-run the focused contract tests and confirm green.

### Task 2: Repeated-only kernel

**Files:** Create `backend/workbench/engine/packs/repeated_measures_anova/__init__.py`; modify the dedicated test file only.

- [ ] Write failing numerical tests for a balanced two-level within design and a multi-level sphericity case.
- [ ] Implement long-table validation and the `AnovaRM` path with explicit correction metadata and JSON projection.
- [ ] Add direct `statsmodels.AnovaRM` comparison tests and fail-closed tests for non-finite/duplicate/incomplete data.
- [ ] Run the focused repeated-only tests and inspect every statistic.

### Task 3: Mixed-design kernel

**Files:** Modify `backend/workbench/engine/packs/repeated_measures_anova/__init__.py`; modify the dedicated test file.

- [ ] Write a failing mixed-design test with one between factor and one within factor, including expected subject×within error degrees of freedom.
- [ ] Implement balanced error-layer projections without pseudoinverse fallback; expose the selected error layer in every effect row.
- [ ] Add R base `aov` Oracle subprocess tests using fixed input and compare SS/df/F/p within declared tolerance.
- [ ] Add tests that reject multiple between factors, inconsistent subject labels, and unbalanced cells.
- [ ] Run all repeated-measures tests and `git diff --check`.

### Task 4: Review and handoff

- [ ] Run the full dedicated suite and adjacent P7 statistical tests.
- [ ] Request spec-compliance review, then code-quality review; fix and re-review every Important/Critical issue.
- [ ] Record numerical Oracle and known limits in `findings.md`/`progress.md`.
