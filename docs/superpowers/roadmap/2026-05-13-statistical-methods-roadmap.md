# Statistical Methods Roadmap

Date: 2026-05-13
Owner: Workbench project
Status: Informational. Not a binding commitment; reordering is expected as priorities evolve.

## 1. Purpose

This document inventories the statistical methods that Workbench currently supports, those that are partially supported, and those that are missing. It groups methods into seven canonical categories and ranks them within each category by typical usage frequency in applied econometrics / social-science work (the project's primary domain). It also documents how the V1.4 lineage-graph data model is designed to accommodate all of these methods without future schema migrations.

This roadmap is the reference point when:
- Choosing what to ship in V1.5+ feature versions.
- Evaluating whether a proposed change requires schema migration.
- Onboarding contributors who need to know "what's in" versus "what's planned".

## 2. Categories

1. Regression models (§3)
2. Hypothesis tests (§4)
3. Causal inference (§5)
4. Machine learning (§6)
5. Dimensionality reduction & structure discovery (§7)
6. Time series (§8)
7. Survival analysis (§9)

Status symbols used throughout:
- ✅ = implemented and exercised by tests
- ⚠️ = partially implemented (e.g. one variant of a family, or one statistic of a battery)
- ❌ = not implemented

## 3. Regression Models

Ranked by frequency of use in applied econometric work.

| # | Method | Status | Implementation reference |
|---|---|---|---|
| 1 | OLS | ✅ | `backend/workbench/econometrics/runner.py:run_ols` (HC1 robust SE default) |
| 2 | Logit | ✅ | `runner.py:run_logit` |
| 3 | Poisson | ✅ | `runner.py:run_poisson` |
| 4 | Probit | ❌ | Trivial addition once `run_probit` is written |
| 5 | Negative Binomial | ❌ | Poisson overdispersion alternative |
| 6 | Ordered Logit / Probit | ❌ | For ordered categorical outcomes |
| 7 | Multinomial Logit | ❌ | For unordered multi-class outcomes |
| 8 | Tobit / Heckman | ❌ | Censored / selection-corrected models |
| 9 | Quantile Regression | ❌ | Beyond conditional mean |
| 10 | Ridge / Lasso / Elastic Net | ❌ | Regularization (variable selection / collinearity) |
| 11 | GLM (unified interface) | ❌ | Umbrella covering OLS / Logit / Poisson / NB |
| 12 | Robust regression (M-estimator) | ❌ | Outlier-robust fitting; distinct from robust SE |

### 3a. Panel Data subcategory

| # | Method | Status | Notes |
|---|---|---|---|
| 1 | Two-way fixed effects (LSDV) | ⚠️ | `runner.py:run_fixed_effects` uses dummy-variable approach, not within-transformation |
| 2 | Within-transformation FE | ❌ | Prefer `linearmodels.PanelOLS`; more efficient |
| 3 | Random Effects | ❌ | |
| 4 | Hausman test | ❌ | RE vs FE selection |
| 5 | Clustered SE (panel-aware) | ❌ | Zero-cost once V1.4 schema decoupling lands |
| 6 | First Differences | ❌ | |
| 7 | Pooled OLS | ❌ | Baseline |
| 8 | Between estimator | ❌ | |
| 9 | Arellano-Bond / dynamic panel | ❌ | Advanced |

## 4. Hypothesis Tests

| # | Method | Status | Notes |
|---|---|---|---|
| 1 | Welch t-test | ✅ | `statistical_tests.py:_welch_t_test` |
| 2 | One-way ANOVA | ✅ | `statistical_tests.py:_anova` |
| 3 | Chi-square (independence) | ✅ | `statistical_tests.py:_chi_square` |
| 4 | F-test (joint significance) | ⚠️ | Internal to OLS; no standalone API |
| 5 | Levene / Bartlett (variance equality) | ❌ | Prerequisite for choosing t-test variant |
| 6 | Shapiro-Wilk / KS (normality) | ❌ | |
| 7 | Mann-Whitney U | ❌ | Nonparametric two-sample |
| 8 | Wilcoxon signed-rank | ❌ | Nonparametric paired |
| 9 | Kruskal-Wallis | ❌ | Nonparametric one-way ANOVA |
| 10 | Breusch-Pagan / White (heteroskedasticity) | ❌ | Informs SE choice |
| 11 | Durbin-Watson (first-order autocorrelation) | ❌ | |
| 12 | VIF (multicollinearity) | ❌ | |
| 13 | RESET (specification) | ❌ | |
| 14 | Hausman (FE vs RE) | ❌ | Cross-listed in §3a |
| 15 | Wald / LR / Score (nested models) | ❌ | |

## 5. Causal Inference

| # | Method | Status | Notes |
|---|---|---|---|
| 1 | Difference-in-Differences (two-period) | ❌ | |
| 2 | Event Study (dynamic DID) | ❌ | Parallel-trends visualization |
| 3 | IV / 2SLS | ❌ | |
| 4 | Sharp RDD | ❌ | |
| 5 | Fuzzy RDD | ❌ | |
| 6 | Propensity Score Matching | ❌ | |
| 7 | Synthetic Control | ❌ | |
| 8 | Mediation Analysis | ❌ | |
| 9 | Doubly Robust Estimation | ❌ | |
| 10 | Heterogeneous Treatment Effects (CATE) | ❌ | |
| 11 | Causal Forest / GRF | ❌ | ML × causal |
| 12 | Modern DID (Callaway-Sant'Anna / Borusyak / de Chaisemartin) | ❌ | Staggered-treatment-bias corrections |

## 6. Machine Learning

| # | Method / Capability | Status | Notes |
|---|---|---|---|
| 1 | Random Forest | ❌ | Highest practical adoption |
| 2 | Gradient Boosting (XGBoost / LightGBM) | ❌ | |
| 3 | Decision Tree (single) | ❌ | Interpretable baseline |
| 4 | Cross-validation framework | ❌ | Infrastructure, not a single method |
| 5 | Feature importance / SHAP | ❌ | |
| 6 | KNN | ❌ | |
| 7 | SVM | ❌ | |
| 8 | Naive Bayes | ❌ | |
| 9 | Neural Network (basic MLP) | ❌ | |
| 10 | Ensemble (Stacking / Voting) | ❌ | |
| 11 | Classification metrics (ROC-AUC / PR / Confusion Matrix) | ⚠️ | Tracked as V1.2.5 known gap |

## 7. Dimensionality Reduction & Structure Discovery

| # | Method | Status | Notes |
|---|---|---|---|
| 1 | PCA | ❌ | Most-used reduction |
| 2 | K-means | ❌ | Most-used clustering |
| 3 | Hierarchical Clustering | ❌ | |
| 4 | Factor Analysis (EFA) | ❌ | Common in psychometrics / social science |
| 5 | LDA (Linear Discriminant Analysis) | ❌ | Supervised reduction |
| 6 | DBSCAN | ❌ | Density-based |
| 7 | t-SNE / UMAP | ❌ | Visualization-focused |
| 8 | ICA | ❌ | |
| 9 | CFA (Confirmatory FA) | ❌ | Usually paired with SEM |

## 8. Time Series

| # | Method | Status | Notes |
|---|---|---|---|
| 1 | Stationarity tests (ADF / KPSS / PP) | ❌ | Prerequisite for almost all time-series modeling |
| 2 | ACF / PACF | ⚠️ | Only lag-1 autocorrelation is computed |
| 3 | ARIMA / SARIMA | ❌ | Most-used univariate model |
| 4 | Seasonal decomposition (STL / classical) | ❌ | |
| 5 | Granger causality | ❌ | |
| 6 | VAR (Vector Autoregression) | ❌ | Multivariate |
| 7 | Cointegration (Engle-Granger / Johansen) | ❌ | |
| 8 | VECM | ❌ | Post-cointegration modeling |
| 9 | GARCH / ARCH (volatility) | ❌ | Financial applications |
| 10 | Holt-Winters / Exponential smoothing | ❌ | Simple forecasting |
| 11 | State Space / Kalman Filter | ❌ | Advanced |
| 12 | Prophet | ❌ | Industry adoption |

## 9. Survival Analysis

| # | Method | Status | Notes |
|---|---|---|---|
| 1 | Kaplan-Meier | ❌ | Most-basic survival curve |
| 2 | Cox Proportional Hazards | ❌ | Most-used regression |
| 3 | Log-rank test | ❌ | Two-group survival comparison |
| 4 | Parametric survival (Weibull / Exponential / Lognormal) | ❌ | |
| 5 | AFT (Accelerated Failure Time) | ❌ | Cox alternative |
| 6 | Time-varying covariates | ❌ | |
| 7 | Competing Risks | ❌ | |
| 8 | Frailty models | ❌ | Advanced |

## 10. Summary

- ✅ Fully supported: 6 items (OLS, Logit, Poisson, t-test, ANOVA, chi-square)
- ⚠️ Partial: ~6 items (FE, correlation Pearson-only, F-test, ACF lag-1 only, classification metrics, multi-resolution figure coverage)
- ❌ Missing: ~80 items across the 7 categories

The project's strong base in regression and three classical tests covers the bulk of weekly applied work but leaves most advanced econometrics (causal inference, panel-data refinements, time-series) and all of ML / dimensionality reduction / survival analysis unaddressed.

## 11. How V1.4's Lineage Graph Accommodates Future Methods

V1.4 (the next major version) introduces the artifact lineage graph as a substrate that the methods above will plug into. Five schema decisions were made specifically to ensure that adding any method from §3–§9 does not require migrating the graph data model.

### 11.1 `NodeKind` is small and method-agnostic

```python
class NodeKind(str, Enum):
    DATASET_STAGE = "dataset_stage"
    VARIABLE      = "variable"
    MODEL         = "model"
    TEST          = "test"
    PLOT          = "plot"
    REPORT        = "report"
```

Method identity (OLS vs Logit vs DID vs ARIMA vs Cox PH) lives in node payload, never in `NodeKind`. Adding a new method does not introduce a new `NodeKind`.

### 11.2 `estimator` and `covariance_type` are independent fields on `MODEL` nodes

```python
estimator: str           # ols / logit / probit / poisson / panel_ols_within / did / iv_2sls / arima / cox_ph / ...
covariance_type: str     # homo / hc0 / hc1 / hc3 / cluster_robust / newey_west / driscoll_kraay / bootstrap / ...
cluster_var: str | None  # populated when covariance_type == "cluster_robust"
```

This decoupling unblocks clustered SE, Newey-West, panel-aware clustering, and bootstrap SE without schema migration. It is part of V1.4 P0.

### 11.3 `TEST` nodes use a single standardized schema

```python
test_kind: str           # welch_t / anova_one_way / chi_square / adf / kpss / hausman / parallel_trends / log_rank / ...
statistic: float
p_value: float | None
df: float | tuple[int, ...] | None
critical_values: dict[str, float] | None
null_hypothesis: str
decision: Literal["reject_null", "fail_to_reject", "inconclusive"]
```

All 15 items in §4, all stationarity tests in §8, the Hausman test in §3a, the log-rank test in §9, the parallel-trends test in §5 — all use this same schema. The frontend renders any test node identically; adding a test never changes the UI.

### 11.4 Multi-output operations use multiple outgoing edges

DAG nodes naturally support fan-out. An Event-Study `MODEL` node produces a coefficient `MODEL`, a dynamic-effects `PLOT`, and a parallel-trends `TEST` — three outgoing edges, three downstream nodes. An ARIMA fit produces a forecast `PLOT`, a residual-diagnostics `TEST`, and AIC/BIC `MODEL` metadata. A Cox-PH fit produces a Kaplan-Meier `PLOT` and proportional-hazards `TEST`. No schema change required for any of these.

### 11.5 `VARIABLE` node roles are a list, not a single value

```python
roles: list[str]
```

Available role tags expand over time:
- Existing: `dependent`, `regressor`, `treatment`, `proxy`, `id`, `time`, `categorical`
- Causal additions: `treatment_assignment`, `period_of_treatment`, `control_group`, `instrument`, `cutoff_variable`
- Panel additions: `entity_id`, `time_invariant_covariate`
- Time-series additions: `lag_eligible`, `seasonal`, `trend`
- Survival additions: `time_to_event`, `censoring_indicator`

A single variable may carry multiple roles simultaneously (e.g. `regressor` + `treatment_assignment` + `entity_id`). Adding a new role is a single-line registration; no schema migration.

## 12. Proposed V1.5+ Rollout Order

This is an informational sequencing suggestion, not a binding commitment. Each version below would be brainstormed and spec'd separately.

| Version | Theme | Contents |
|---|---|---|
| **V1.5.0** | Regression patch pack | Probit, Negative Binomial, Clustered SE (schema-ready in V1.4), proper Panel: within-FE + RE + Hausman |
| **V1.5.1** | Test patch pack | Levene, Shapiro-Wilk, Mann-Whitney, Kruskal-Wallis, Breusch-Pagan, Durbin-Watson, VIF |
| **V1.5.2** | Multiverse analysis UI | Surface V1.4's `decision_point` data; specification-curve plot |
| **V1.6.0** | Time-series basics | ADF / KPSS, full ACF / PACF, ARIMA, seasonal decomposition |
| **V1.6.1** | AI integration — phase 1 | Node annotations + suggested forks (V1.4 hooks) |
| **V1.7.0** | Causal inference I | DID, Event Study |
| **V1.7.1** | Causal inference II | IV / 2SLS, RDD (sharp + fuzzy) |
| **V1.7.2** | Causal inference III | Propensity-score matching, synthetic control, modern DID estimators |
| **V1.8.x** | Machine learning | Random Forest, XGBoost, cross-validation framework, SHAP, classification metrics |
| **V1.9.x** | Dimensionality & clustering | PCA, K-means, hierarchical clustering |
| **V2.0.x** | Time-series advanced | VAR, VECM, cointegration, GARCH |
| **V2.1.x** | Survival analysis | Kaplan-Meier, Cox PH, log-rank |

## 13. Maintenance

When a new method is implemented, mark its row ✅ and add the implementation reference. When a method's status changes from ❌ to ⚠️ (partial), keep the row and update the notes column with what's missing. Do not delete rows; the inventory's value is partly historical.

When the project's domain emphasis shifts (e.g. heavier ML focus, or pivot toward time series), revisit §3–§9 ordering. The 7-category structure is intended to be stable; the within-category ranking can move.

When a method's V1.4-style graph representation requires a new field (a counterexample to §11.1–§11.5), that's a signal that the substrate needs an extension — escalate as a substrate-level design change rather than a method-level patch.
