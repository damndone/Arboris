# V1.5.3.1 Backend Analysis Expansion Design

Date: 2026-05-31

## 1. Purpose

V1.5.3.1 is a backend-only analysis expansion release. Its goal is to add mature statistical and machine-learning package support while keeping the workbench stable, debuggable, and easy to extend.

This release is separate from V1.5.3 frontend foundation hardening. It must not touch the V1.5.3 frontend state-machine work around F1/F2/F3/F5/F6/F7/F9.

The first principle is simple: support more methods, but do not automatically run everything. Default `auto` remains conservative. New capabilities run only when explicitly requested by `model_type`, CLI/API parameters, or project config.

## 2. Hard Boundaries

Allowed code areas:

- `pyproject.toml`
- `backend/workbench/econometrics/`
- `backend/workbench/statistical_tests.py`
- `backend/workbench/orchestrator.py`
- `backend/workbench/config.py`
- backend report/view-model code only when needed to surface new backend summaries
- backend tests under `tests/`
- backend/version docs under `docs/`

Forbidden code areas:

- `frontend/src/workbench/**`
- `frontend/src/lineage/**`
- `frontend/package.json`
- V1.5.3 frontend files for F1/F2/F3/F5/F6/F7/F9

Forbidden product scope:

- No new frontend UI.
- No AI chat endpoint.
- No rerun endpoint.
- No editable-ops endpoint.
- No command-palette behavior.
- No automatic causal interpretation.
- No automatic execution of all available models.

## 3. Dependency Strategy

Use core dependencies plus optional extras.

Core dependencies stay close to the current project:

- `statsmodels`
- `scipy`
- `pandas`

Optional extras:

```toml
[project.optional-dependencies]
panel = ["linearmodels>=6"]
ml = ["scikit-learn>=1.5"]
imbalanced = ["imbalanced-learn>=0.12"]
imputation = ["statsmodels>=0.14"]
```

`statsmodels.imputation.mice` is part of `statsmodels`, but MICE should still be treated as an explicit imputation capability. It must not run by default.

Do not add DoWhy or EconML in V1.5.3.1. Causal inference needs a separate design because it requires explicit treatment, outcome, confounders, identification assumptions, and refutation handling.

## 4. Architecture

Keep the structure simple. Do not introduce a large registry or adapter framework in this release.

Extend the existing backend in place:

```text
backend/workbench/econometrics/
├── runner.py          # existing model functions plus new explicit model functions
├── normalize.py       # normalize statsmodels/linearmodels-like outputs
├── diagnostics.py     # existing diagnostics plus small additions when required
├── specs.py           # extend ModelSpec for explicit advanced models
└── optional_deps.py   # new small helper for optional dependency checks
```

New functions should be plain and direct:

- `run_probit(...)`
- `run_negative_binomial(...)`
- `run_glm(...)`
- `run_panel_ols(...)`
- `run_iv_2sls(...)`
- `run_prediction_model(...)`
- `run_mice_imputation(...)`

The orchestrator should not become a model framework. It should:

1. Determine the requested model or preprocessing step.
2. Call the corresponding function.
3. Write lightweight artifacts.
4. Add clear warnings when a capability is unavailable or skipped.

## 5. Execution Model

Default `model_type=auto` keeps the current behavior:

- binary y -> Logit
- count y -> Poisson
- continuous y -> OLS with robust standard errors

V1.5.3.1 adds explicit model types:

- `probit`
- `negative_binomial`
- `glm`
- `panel_ols`
- `iv_2sls`
- `prediction_lasso`
- `prediction_ridge`
- `prediction_random_forest`

Optional preprocessing:

- `imputation=mice`

Auto mode may write recommendations, but it must not automatically run expensive or structurally different models. Examples:

- Poisson overdispersion -> recommend `negative_binomial`
- panel-like data -> recommend `panel_ols`
- explicit instrument fields present -> recommend `iv_2sls`
- user asks prediction mode -> recommend `prediction_*`

Recommendations should be written as metadata or warnings. They should not change execution.

## 6. Feature Scope

### 6.1 Statsmodels Models

Add:

- Probit for binary outcomes.
- Negative Binomial for overdispersed count outcomes.
- GLM foundation for selected families.

Initial GLM families:

- `binomial`
- `poisson`
- `negative_binomial`

Robust and clustered covariance should reuse mature package support where available. Clustered covariance must require an explicit cluster column.

### 6.2 Linearmodels Extra

Add when `.[panel]` is installed:

- `panel_ols`
- `iv_2sls`

`panel_ols` must require explicit entity and/or time fields. It should not guess fields beyond existing schema candidates unless the user explicitly accepts them through config or parameters.

`iv_2sls` must require:

- outcome
- exogenous variables
- endogenous variables
- instruments

If any of these are missing, skip with a clear structured error.

### 6.3 Statistical Tests

Extend `backend/workbench/statistical_tests.py` directly.

Add:

- Spearman correlation
- Kendall correlation
- Mann-Whitney U
- Kruskal-Wallis
- Fisher exact test
- multiple-testing correction using `statsmodels.stats.multitest`

Do not run tests over every dataset column by default. Continue using selected analysis columns and enforce pair limits.

### 6.4 Prediction Models

Add a small prediction-only path when `.[ml]` is installed:

- Lasso
- Ridge
- Random Forest
- train/test split
- cross-validation with bounded folds
- basic metrics

Prediction output must be isolated under:

```text
prediction_results/
```

Prediction results must not be interpreted as causal effects or regression inference.

### 6.5 Imbalanced-Learn Extra

When `.[imbalanced]` is installed, allow:

- SMOTE
- random oversampling
- random undersampling

These methods are prediction-only. They must not feed standard econometric inference models by default.

### 6.6 MICE Imputation

Add MICE as explicit preprocessing using `statsmodels.imputation.mice`.

Supported modes:

1. `impute-only`: write an imputed dataset and summary.
2. `impute-then-model`: only when the user explicitly requests both imputation and a model.

MICE must not overwrite `processed/cleaned_dataset.parquet`.

Artifacts:

```text
processed/imputed_dataset.parquet
imputation/mice_summary.json
imputation/mice_decisions.json
```

Default MICE limits:

- `m = 5`
- `max_iter = 10`
- explicit random seed
- numeric columns only in V1.5.3.1
- high-missing-rate columns skipped with warning

Do not pickle MICE objects. Do not save per-iteration full intermediate data.

Rubin's rules pooling for model estimates is not required in V1.5.3.1. If `impute-then-model` runs, the report must state exactly how estimates were produced.

## 7. Artifact Contract

New model results use the existing `model_results/` directory when they are inference models:

```text
model_results/probit_1.json
model_results/negative_binomial_1.json
model_results/glm_1.json
model_results/panel_ols_1.json
model_results/iv_2sls_1.json
```

Prediction models use:

```text
prediction_results/{model_id}.json
```

Imputation uses:

```text
imputation/mice_summary.json
imputation/mice_decisions.json
processed/imputed_dataset.parquet
```

Each result artifact must include:

- `schema_version`
- `model_id`
- `model_type`
- `engine`
- `nobs`
- `input_columns`
- `status`
- `warnings`
- model-specific result fields

Large arrays are not stored by default. For fitted values, residuals, predictions, or fold-level output, store summaries and at most a small preview.

## 8. Error And Warning Contract

Errors must be structured and localizable.

Required fields:

- `error_code`
- `step`
- `engine`
- `model_type`
- `model_id`
- `message`
- `details`

Examples:

- `OPTIONAL_DEPENDENCY_MISSING`
- `PANEL_FIELDS_MISSING`
- `IV_SPEC_INCOMPLETE`
- `MODEL_SIZE_LIMIT_EXCEEDED`
- `MICE_UNSUPPORTED_COLUMN`
- `PREDICTION_EXTRA_MISSING`

Missing extras should not produce vague import errors. They should produce a direct message such as:

```text
Install the panel extra to use panel_ols: pip install -e ".[panel]"
```

## 9. Runtime And Memory Guardrails

V1.5.3.1 must prefer predictable runtime over maximum automation.

Required limits:

- Do not run advanced models in `auto` mode.
- Do not run prediction models unless explicitly requested.
- Do not run imputation unless explicitly requested.
- Do not run causal methods.
- Limit pairwise statistical tests by number of selected columns.
- Limit CV folds; default 5.
- Random Forest default should be conservative; no grid search.
- MICE defaults to `m=5`, `max_iter=10`.
- Do not save pickled model objects.
- Do not save large dense design matrices.
- Do not save complete residual/fitted/prediction arrays for large datasets.

Each skipped capability should explain why it was skipped.

## 10. Graph And Lineage Safety

Do not add complex graph relationships in V1.5.3.1.

Allowed lineage pattern:

```text
cleaned_dataset -> model_result:<model_id>
cleaned_dataset -> diagnostics:<model_id>
cleaned_dataset -> prediction_result:<model_id>
cleaned_dataset -> imputed_dataset
imputed_dataset -> model_result:<model_id>
```

Do not create cross-linked model comparison graphs, causal graphs, or multi-model dependency meshes in this release. The graph should continue to render if new artifacts are unknown to the frontend.

## 11. Config And CLI/API Surface

Extend existing backend inputs minimally.

CLI/API:

- expand accepted `model_type` values
- optionally accept imputation settings where existing plumbing allows it

Config example:

```yaml
analysis:
  model_type: panel_ols
  entity: firm_id
  time: year
  covariance: clustered
  cluster: firm_id

imputation:
  method: mice
  m: 5
  max_iter: 10
  random_seed: 42

prediction:
  enabled: true
  model_type: random_forest
  cv_folds: 5
```

If a field is not wired in V1.5.3.1, do not pretend it is supported. Keep the accepted surface small and tested.

## 12. Testing Strategy

Tests must prove both success and safe failure.

Core tests:

- Existing OLS/Logit/Poisson auto behavior remains unchanged.
- `model_type=probit` writes a Probit result.
- `model_type=negative_binomial` writes a Negative Binomial result.
- GLM writes a normalized result for supported families.
- Missing optional extra returns a structured warning/error.
- Statistical test extensions write finite values or skip invalid pairs.
- Multiple-testing correction is present when test families have p-values.

Panel extra tests:

- `panel_ols` runs when `linearmodels` is installed.
- missing entity/time fields produce `PANEL_FIELDS_MISSING`.
- `iv_2sls` runs on a small valid fixture.
- incomplete IV spec produces `IV_SPEC_INCOMPLETE`.

ML extra tests:

- Lasso/Ridge/RandomForest write prediction artifacts.
- CV folds are bounded.
- prediction artifacts do not enter inference claim paths.

Imputation tests:

- MICE impute-only writes imputed dataset and summary.
- high-missing-rate or unsupported columns are skipped with warnings.
- cleaned dataset is not overwritten.
- no pickle files are produced.

Regression tests:

- Full backend test suite still passes.
- No frontend tests are required for V1.5.3.1 because no frontend code changes are allowed.

## 13. Implementation Order

1. Add optional dependency helper and extras metadata.
   - Verify: missing extras produce clear messages.

2. Add statsmodels models: Probit, Negative Binomial, GLM.
   - Verify: small fixtures produce normalized model artifacts.

3. Extend statistical tests.
   - Verify: finite outputs, pair limits, correction metadata.

4. Add linearmodels panel/IV functions behind `.[panel]`.
   - Verify: installed and missing-extra paths.

5. Add MICE explicit preprocessing.
   - Verify: imputed artifacts, no overwrite, bounded output.

6. Add sklearn prediction path behind `.[ml]`.
   - Verify: isolated `prediction_results` artifacts.

7. Add imbalanced-learn prediction-only sampling behind `.[imbalanced]`.
   - Verify: cannot silently feed inference models.

8. Update docs and release notes.
   - Verify: scope and install commands are clear.

## 14. Definition Of Done

- No frontend files changed.
- Default `auto` behavior remains OLS/Logit/Poisson.
- New methods run only by explicit request or config.
- Missing extras produce structured, actionable errors.
- No model pickles or large hidden caches are written.
- New artifacts are lightweight and registered.
- Graph lineage remains simple and backward-compatible.
- Backend tests cover success, skip, and missing-extra paths.
- Full backend test suite passes.
