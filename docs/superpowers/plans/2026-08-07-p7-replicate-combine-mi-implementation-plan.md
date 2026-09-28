# P7 Replicate-and-Combine and MI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正 MICE 多重插补被压成单一完成数据集的推断错误，并建立供 Bootstrap、Permutation 与 Survey replicate 复用的安全复制/合并基础。

**Architecture:** `replicate_combine` 提供有界复制计划、执行证据和 typed combiner；`missing_data` 提供缺失诊断与 Rubin pooling；现有 MICE/EstimationStage 通过明确的 OLS adapter 使用多份完成数据并 fail closed 处理未支持模型族。Claude 的 Agent/P0/P1/P2 路径不在写集内。

**Tech Stack:** Python 3.11+, NumPy, pandas, SciPy, statsmodels, pytest, optional base R/R `mice` as external Oracles. No dependency installation.

---

## File map

- Create: `backend/workbench/contracts/model/replicate_combine.py` — versioned replicate plan/evidence envelope.
- Create: `backend/workbench/engine/replicate_combine/errors.py` — stable errors and reason codes.
- Create: `backend/workbench/engine/replicate_combine/types.py` — immutable plan, batch, provenance and failure-summary types.
- Create: `backend/workbench/engine/replicate_combine/runner.py` — bounded strategy execution over declared replicate adapters.
- Create: `backend/workbench/engine/replicate_combine/combiners.py` — shared validation plus typed combiner dispatch; Rubin math lives in the missing-data pack.
- Create: `backend/workbench/engine/replicate_combine/__init__.py` — narrow public surface.
- Create: `backend/workbench/contracts/model/missing_data.py` — missingness and Rubin result contracts.
- Create: `backend/workbench/engine/packs/missing_data/errors.py` — stable missing-data errors.
- Create: `backend/workbench/engine/packs/missing_data/diagnostics.py` — missingness profile and pattern evidence.
- Create: `backend/workbench/engine/packs/missing_data/rubin.py` — Rubin within/between/total variance and t-based interval/p-value pooling.
- Create: `backend/workbench/engine/packs/missing_data/__init__.py` — pack dispatch without Agent registration.
- Modify: `backend/workbench/imputation.py` — generate and persist exactly `m` MICE datasets with deterministic seed derivation and manifest.
- Modify: `backend/workbench/engine/stages/imputation.py` — expose all imputation handles and missingness evidence; never bind only the first as the model input for `m > 1`.
- Modify: `backend/workbench/engine/stages/estimation.py` — add an explicit OLS MI adapter and fail closed for unsupported model families.
- Modify: `backend/workbench/engine/stages/diagnostics.py`, `backend/workbench/engine/stages/recording.py`, `backend/workbench/orchestrator/_report_build.py`, `backend/workbench/report_view_model.py` — preserve pooled lineage and label per-imputation/unavailable diagnostics.
- Create: `tests/test_replicate_combine.py`, `tests/test_missing_data_pack.py` — contract, budget, digest, Rubin and missingness tests.
- Modify: `tests/test_imputation_mice.py`, `tests/test_imputation_summary_artifact.py`, `tests/test_engine_golden.py` — replace the current green assertion that `m=2` persists one dataset with the corrected multi-dataset/pooling behavior.
- Create: `docs/superpowers/specs/2026-08-07-p7-replicate-combine-mi-design.md` and this implementation plan.
- Modify: `task_plan.md`, `findings.md`, `progress.md` — durable task state and evidence.
- Do not modify: `backend/workbench/agent/**`, `frontend/src/workbench/agent/**`, OperationRegistry, orchestrator Agent seam, context tools, current P1/P2 integration files, or the existing `backend/workbench/survey/**` design engine.

## Task 1: Lock the real MICE regression before implementation

**Files:**

- Modify: `tests/test_imputation_mice.py`
- Create: `tests/test_missing_data_pack.py`

- [ ] **Step 1: Add the failing regression fixture.**

  Add a test that calls `run_mice_imputation(..., m=2, ...)` and requires two
  distinct persisted dataset artifacts, an imputation manifest listing both,
  `persisted_datasets == 2`, and `pooled_estimates` to remain false until the
  model stage actually pools results. Add a second test using two fixed model
  result lists with differing intercept estimates and assert that a future
  Rubin result has `total_variance > within_variance`.

- [ ] **Step 2: Run the regression and observe the red state.**

  ```bash
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_imputation_mice.py tests/test_missing_data_pack.py -k 'multiple or persisted or rubin' -q -p no:cacheprovider
  ```

  Expected: the new expectations fail because the current implementation writes
  one dataset and has no Rubin combiner.

- [ ] **Step 3: Record the failure through the formal CLI.**

  Append a `FAILURE` event to `v1-8-8-p7-extensions` with the exact command,
  failed test names, and the root cause “m is metadata-only; between-imputation
  variance is not consumed”. Do not edit `events.jsonl` directly.

## Task 2: Build the shared replicate-and-combine foundation

**Files:**

- Create: `backend/workbench/contracts/model/replicate_combine.py`
- Create: `backend/workbench/engine/replicate_combine/errors.py`
- Create: `backend/workbench/engine/replicate_combine/types.py`
- Create: `backend/workbench/engine/replicate_combine/runner.py`
- Create: `backend/workbench/engine/replicate_combine/combiners.py`
- Create: `backend/workbench/engine/replicate_combine/__init__.py`
- Test: `tests/test_replicate_combine.py`

- [ ] **Step 1: Add contract and runner red tests.**

  Test exact versioned fields, declared kinds (`multiple_imputation`,
  `bootstrap`, `permutation`, `survey_replicate`), hard maximums, deterministic
  seed/provenance, failure counts, digest stability, no raw replicate values in
  output, and rejection of callback/formula/import fields from serialized
  requests.

- [ ] **Step 2: Run the focused tests and confirm imports/behavior fail.**

  ```bash
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_replicate_combine.py -q -p no:cacheprovider
  ```

- [ ] **Step 3: Implement the minimal typed foundation.**

  Use immutable dataclasses and a closed strategy registry. The runner accepts
  only registered strategy objects from Python code and a validated typed plan;
  the public contract contains IDs and policy values only. Bound requested
  replicates before allocation, preserve deterministic order, count failures by
  stable reason, and hash only bounded scalar evidence. Keep combine dispatch
  separate from generation so MI/Bootstrap/Permutation/Survey can use different
  mathematics without duplicating audit metadata.

- [ ] **Step 4: Run the foundation tests and commit.**

  ```bash
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_replicate_combine.py -q -p no:cacheprovider
  git add backend/workbench/contracts/model/replicate_combine.py backend/workbench/engine/replicate_combine tests/test_replicate_combine.py
  git commit -m "feat(p7): add replicate-and-combine foundation"
  ```

## Task 3: Implement missingness diagnostics and Rubin pooling

**Files:**

- Create: `backend/workbench/contracts/model/missing_data.py`
- Create: `backend/workbench/engine/packs/missing_data/errors.py`
- Create: `backend/workbench/engine/packs/missing_data/diagnostics.py`
- Create: `backend/workbench/engine/packs/missing_data/rubin.py`
- Create: `backend/workbench/engine/packs/missing_data/__init__.py`
- Modify: `tests/test_missing_data_pack.py`

- [ ] **Step 1: Add red tests for diagnostics and Rubin formulas.**

  Assert exact missing-rate/pattern counts, deterministic pattern ordering,
  explicit no-MCAR-claim semantics, `Qbar/Ubar/B/T`, total standard errors,
  fraction missing information, finite degrees of freedom, t-based intervals
  and p-values. Reject mismatched coefficient names, non-finite estimates,
  negative variances, `m < 2` for pooled mode, and zero/undefined degrees of
  freedom without replacing them by a normal approximation.

- [ ] **Step 2: Run the new tests and confirm red.**

  ```bash
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_missing_data_pack.py -q -p no:cacheprovider
  ```

- [ ] **Step 3: Implement the typed diagnostics and Rubin combiner.**

  Keep missingness evidence descriptive. Implement Rubin’s rules once in the
  pack and expose it through the common combiner protocol. For each coefficient,
  validate aligned estimates/variances, compute within/between/total variance,
  use explicit Rubin t semantics, and return status/reason/provenance fields.
  Do not round intermediate values or pool already-rounded p-values.

- [ ] **Step 4: Run focused tests and commit.**

  ```bash
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_missing_data_pack.py tests/test_replicate_combine.py -q -p no:cacheprovider
  git add backend/workbench/contracts/model/missing_data.py backend/workbench/engine/packs/missing_data tests/test_missing_data_pack.py
  git commit -m "feat(p7): add missingness evidence and Rubin pooling"
  ```

## Task 4: Generate `m` MICE datasets and preserve lineage

**Files:**

- Modify: `backend/workbench/imputation.py`
- Modify: `backend/workbench/engine/stages/imputation.py`
- Modify: `tests/test_imputation_mice.py`, `tests/test_imputation_summary_artifact.py`

- [ ] **Step 1: Add red tests for dataset count, seeds, and handles.**

  Require `m` persisted datasets with distinct artifact IDs and a manifest that
  binds each dataset to its derived seed. Require the cleaned artifact to stay
  byte-identical, missingness diagnostics to bind to the same selected columns,
  and `m=1` to be explicitly labelled `single_imputation`. Require an `m>1`
  request to expose all handles to the next stage rather than only
  `imputed_dataset`.

- [ ] **Step 2: Run the existing MICE tests plus new expectations.**

  ```bash
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_imputation_mice.py tests/test_imputation_summary_artifact.py -q -p no:cacheprovider
  ```

- [ ] **Step 3: Implement deterministic multi-dataset generation.**

  Derive `m` seeds from the declared base seed, instantiate an independent
  `MICEData` per replicate, preserve/restore global NumPy state around each
  third-party call, and persist only validated finite completed frames. Write a
  bounded manifest and register every dataset plus the manifest. Keep a single
  dataset only for explicit `m=1`; do not create a compatibility alias that a
  downstream estimator could mistake for a pooled input.

- [ ] **Step 4: Run tests and commit the persistence slice.**

  ```bash
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_imputation_mice.py tests/test_imputation_summary_artifact.py -q -p no:cacheprovider
  git add backend/workbench/imputation.py backend/workbench/engine/stages/imputation.py tests/test_imputation_mice.py tests/test_imputation_summary_artifact.py
  git commit -m "fix(p7): persist all declared MICE datasets"
  ```

## Task 5: Pool ordinary OLS results and fail closed elsewhere

**Files:**

- Modify: `backend/workbench/engine/stages/estimation.py`
- Modify: `backend/workbench/engine/stages/diagnostics.py`
- Modify: `backend/workbench/engine/stages/recording.py`
- Modify: `backend/workbench/orchestrator/_report_build.py`, `backend/workbench/report_view_model.py`
- Modify: `tests/test_imputation_mice.py`, `tests/test_engine_golden.py`

- [ ] **Step 1: Add a failing end-to-end OLS pooling test.**

  Run a deterministic missing-data OLS workflow with `imputation_m=2` and
  assert that the model result records all imputed dataset inputs, includes a
  pooled coefficient block, and has total intercept variance greater than or
  equal to the within-imputation variance when the estimates differ. Assert
  that `m>1` with an explicitly unsupported model type returns a structured
  failure and never writes a usable first-imputation model result.

- [ ] **Step 2: Run the regression and confirm it fails.**

  ```bash
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_imputation_mice.py tests/test_engine_golden.py -k 'pool or imputation' -q -p no:cacheprovider
  ```

- [ ] **Step 3: Implement the OLS MI adapter.**

  Clone the modeling context and data handle per imputation, call the existing
  OLS handler, extract unrounded coefficient estimates and complete-data
  variances, and pass them to `rubin_pool`. Write one pooled result whose
  `inputs` lists every imputed artifact. Keep the model family and coefficient
  names identical. Set `_fitted_models` empty or explicitly per-imputation for
  diagnostics that cannot be pooled; never let the first fitted object supply
  pooled coefficient/SE claims. Add a stable unsupported-family error before any
  first-replicate fallback.

- [ ] **Step 4: Make downstream reports honest.**

  Preserve pooled model evidence and lineage. Label diagnostic artifacts as
  `per_imputation` or `unavailable` when no valid pooled diagnostic exists, show
  `m`, within/between/total variance and pooling method in the report, and remove
  the old “one persisted imputed dataset” wording. Keep prediction’s fold-local
  preprocessing path separate; it is not an inferential MI pool.

- [ ] **Step 5: Run focused workflow tests and commit.**

  ```bash
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_imputation_mice.py tests/test_engine_golden.py tests/test_engine_increment_fork.py -q -p no:cacheprovider
  git add backend/workbench/engine/stages/estimation.py backend/workbench/engine/stages/diagnostics.py backend/workbench/engine/stages/recording.py backend/workbench/orchestrator/_report_build.py backend/workbench/report_view_model.py tests/test_imputation_mice.py tests/test_engine_golden.py
  git commit -m "fix(p7): pool ordinary model estimates across MICE datasets"
  ```

## Task 6: Independent Oracle and Stage 12 gate

**Files:**

- Modify: `tests/test_missing_data_pack.py`, `tests/test_imputation_mice.py`, `tests/test_engine_golden.py`
- Modify: `task_plan.md`, `findings.md`, `progress.md`

- [ ] **Step 1: Add independent numerical Oracle checks.**

  Compare Rubin `Qbar/Ubar/B/T` and t intervals against an independent direct
  Python/R implementation. If R `mice` is installed, add an optional fixed-input
  `mice::pool` comparison; otherwise keep the direct formula Oracle mandatory.
  Include the known intercept-SE fixture where ignoring between-imputation
  variance produces the visibly smaller wrong SE.

- [ ] **Step 2: Run the Oracle and focused regression suites.**

  ```bash
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_replicate_combine.py tests/test_missing_data_pack.py tests/test_imputation_mice.py tests/test_imputation_summary_artifact.py -q -p no:cacheprovider
  ```

- [ ] **Step 3: Run adjacent P7 and existing survey/IV/post-hoc regressions.**

  ```bash
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv/bin/python -m pytest tests/test_multivariate_pack.py tests/test_time_series_pack.py tests/test_time_series_models.py tests/test_manova_pack.py tests/test_power_analysis_pack.py tests/test_categorical_pack.py tests/test_repeated_measures_anova_pack.py tests/test_survival_analysis_pack.py tests/test_roc_diagnostics_pack.py tests/test_meta_analysis_pack.py tests/test_engine_iv.py tests/test_iv_diagnostics.py tests/test_iv_spec.py tests/test_survey_design_engine_v187.py tests/test_survey_design_composition_v187.py tests/test_statistical_tests_v186.py tests/test_statistical_tests_extended.py -q -p no:cacheprovider
  git diff --check
  ```

- [ ] **Step 4: Verify safety, protected paths, and formal FMS.**

  Run Python compilation, runtime R/shell scan, compare the diff against
  Claude-owned paths, and execute:

  ```bash
  PYTHONPATH=backend .venv/bin/python scripts/devline_control.py verify --line v1-8-8-p7-extensions
  ```

  Append every material failure, review, gate, and state change through the
  formal CLI. Do not claim Agent reachability, browser acceptance, full gate,
  merge, push, or release.

- [ ] **Step 5: Commit the verified Stage 12 evidence.**

  ```bash
  git add tests/test_replicate_combine.py tests/test_missing_data_pack.py tests/test_imputation_mice.py tests/test_imputation_summary_artifact.py tests/test_engine_golden.py task_plan.md findings.md progress.md docs/superpowers/specs/2026-08-07-p7-replicate-combine-mi-design.md docs/superpowers/plans/2026-08-07-p7-replicate-combine-mi-implementation-plan.md
  git commit -m "test(p7): verify replicate combine and MI pooling"
  ```

## Later stages, after Stage 12 is green

- Stage 13: Bootstrap/permutation consumer pack using the shared replicate
  plan and distribution/null combiners.
- Stage 14: GMM only; reuse existing IV/2SLS and diagnostics, adding GMM
  estimation plus explicit weak-instrument diagnostics and Oracle coverage.
- Stage 15: Scheffé and Games--Howell plus a new multiple-comparison contract;
  reuse existing Tukey/Bonferroni/multipletests semantics instead of duplicating
  them.
- Stage 16: Survey-aware adapters for new packs, beginning with weighted PCA and
  design-corrected post-hoc; consume the existing v1.8.7 SurveyDesign and
  replicate engine without changing its mathematical core.
- Stage 17: Cross-pack regression, protected-path, formal, and final handoff
  verification.

## Review protocol

After each task, dispatch a fresh spec-compliance reviewer and then a separate
code-quality reviewer. Resolve all Critical/Important findings and re-run the
affected tests before moving forward. Request a final review after Stage 12,
then write the next stage's own design before implementation.

