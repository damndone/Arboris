# P7 Meta-analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** Implement transparent study-level fixed/random meta-analysis and effect-size conversion with statsmodels/R Oracle checks.

**Architecture:** A pure solver owns validation, effect-scale conversion, combine methods, heterogeneity, prediction intervals, and optional leave-one-out. No source retrieval or model-family wiring.

**Tech Stack:** Python 3.14, NumPy, pandas, SciPy, statsmodels reference calls, pytest, R base in tests only.

---

### Task 1: Contract and RED tests

**Files:** Create `backend/workbench/contracts/model/meta_analysis.py`; create `tests/test_meta_analysis_pack.py`.

- [ ] Write failing tests for study count, positive variance, explicit effect scale/method, alpha bounds, and envelope digest/readback.
- [ ] Run the focused file and confirm the missing-module failure.
- [ ] Implement closed contract fields, stable errors, method metadata, bounded payloads, and optional effect conversion declarations.
- [ ] Re-run contract tests.

### Task 2: Effect-size conversion

**Files:** Create `backend/workbench/engine/packs/meta_analysis/__init__.py`; modify the dedicated tests.

- [ ] Write failing tests for direct effect/variance, mean-difference, standardized mean difference, log risk ratio, and log odds ratio conversion.
- [ ] Implement each converter as a separate named strategy with explicit required fields; reject incomplete or mixed scales.
- [ ] Compare supported conversions to statsmodels helpers where available and R base formulas for fixed fixtures.
- [ ] Add overflow/non-finite and zero-cell continuity-correction tests.

### Task 3: Combine and influence evidence

- [ ] Write failing tests for fixed effects, DerSimonian–Laird, Paule–Mandel, Q/I²/tau², prediction interval, and leave-one-out.
- [ ] Implement transparent formulas and preserve method/CI semantics; never silently pick a winner.
- [ ] Add direct `statsmodels.combine_effects` Oracle tests and an R base Oracle for fixed/DL fixtures.
- [ ] Bound study and output counts; run the complete dedicated suite and `git diff --check`.

### Task 4: Review and handoff

- [ ] Run adjacent P7 tests, request spec and quality reviews, fix/re-review issues, and record tolerances/limits.
