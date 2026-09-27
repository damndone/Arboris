# Coming from Stata or SPSS

Everything below can be asked of the Agent in plain language ("run a Welch
t-test of wage by female"). The Arboris column gives the capability id, which
is also what appears in proposals, the analysis ledger and the
[capability reference](../reference/capabilities.md).

## Data management

| Stata | SPSS | Arboris |
|---|---|---|
| `use`, `import delimited`, `import excel` | File › Open | Import a `.dta`, `.sav`, `.csv` or `.xlsx` ([Getting started](01-getting-started.md)); labels and missing codes come with it |
| `describe`, `codebook` | Variable View, `DISPLAY DICTIONARY` | Variable view |
| `browse`, `list` | Data View | Data view; or ask the Agent to show rows |
| `label variable`, `label define`, `label values` | `VARIABLE LABELS`, `VALUE LABELS` | Variable view, or `metadata.edit` |
| `mvdecode`, missing codes | `MISSING VALUES` | Variable view › Missing, or `metadata.edit` |
| measurement level | `VARIABLE LEVEL` | Variable view › Measure |
| `keep if`, `drop if`, `keep varlist` | `SELECT IF`, `FILTER` | `data.subset` |
| `recode x (...), generate(y)` | `RECODE ... INTO` | `data.recode` (always into a new variable) |
| `generate`, `replace` | `COMPUTE` | `statistical.derive_numeric`; for anything else, `code.execute` (sandboxed Python) |
| `rename` | `RENAME VARIABLES` | `data.rename` |
| `destring`, `tostring` | `ALTER TYPE` | `data.column.cast`, `data.columns.cast` |
| `collapse` | `AGGREGATE` | `data.aggregate` |
| `merge` | `MATCH FILES` | `data.merge` |
| `append` | `ADD FILES` | `data.append` |
| `reshape long/wide` | `VARSTOCASES`, `CASESTOVARS` | `data.reshape` |
| `duplicates drop` | Identify Duplicate Cases | `data.dedupe` (never done automatically) |
| missing-value fill | Replace Missing Values | `data.fill_missing` |
| `tsset`, `xtset` | Define Dates | `data.tsset` |
| `L.x` | `LAG` | `data.lag` |
| `mi impute chained` | Multiple Imputation | `imputation.mice`; pooled with `missing_data.rubin_pool` |
| `save`, `export delimited`, `export excel` | `SAVE OUTFILE`, Export | Export: SPSS, Stata 13 / 14–18 / 15–18 large, CSV, Excel ([Working with data](02-data.md)) |

Every data change creates a new dataset; the original is kept.

## Descriptive statistics

| Stata | SPSS | Arboris |
|---|---|---|
| `summarize` | `DESCRIPTIVES` | `statistical.explore` › summarize |
| `summarize, detail` | `EXAMINE`, `FREQUENCIES /STATISTICS` | summarize_detail — Stata's percentile definition, variance, skewness, kurtosis, 4 smallest and largest |
| `tabulate` | `FREQUENCIES` | tabulate |
| `misstable summarize` | Missing Value Analysis | misstable; `missingness.profile` |
| `by g: summarize` | `SPLIT FILE`, `MEANS` | any of the above with *group by* |
| `correlate`, `pwcorr` | `CORRELATIONS` | corr; `test.correlations` |
| `alpha` | `RELIABILITY` | `multivariate.cronbach_alpha` |

## Tests

| Stata | SPSS | Arboris |
|---|---|---|
| `ttest y, by(g) unequal` | `T-TEST GROUPS` | `test.t_tests` (Welch) |
| paired, one-sample `ttest` | `T-TEST PAIRS`, one-sample | `test.evidence` |
| `tabulate a b, chi2` | `CROSSTABS /STATISTICS=CHISQ` | `test.chi_square`; `test.fisher_exact` for sparse tables; `categorical.cramers_v`, `categorical.mcnemar` |
| `oneway` | `ONEWAY` | `test.anova`; post hoc `multiple_comparisons.games_howell`, `.scheffe` |
| `anova` (factorial) | `UNIANOVA` | `model.anova` (declares its sums-of-squares type) |
| `ranksum`, `kwallis` | `NPAR TESTS /M-W`, `/K-W` | `test.nonparametric`; `nonparametric.mann_whitney`, `.kruskal_wallis` |
| `signrank`, `friedman` | `NPAR TESTS /WILCOXON`, `/FRIEDMAN` | `nonparametric.wilcoxon_signed_rank`, `.friedman` |
| `spearman`, `ktau` | `NONPAR CORR` | `test.rank_correlations` |
| repeated-measures `anova` | `GLM` repeated measures | `repeated_measures_anova.*` |
| `manova` | `GLM` multivariate | `multivariate.manova` |
| `bootstrap`, `permute` | Bootstrap | `resampling.bootstrap`, `.permutation` |
| `power` | Power Analysis | `power_analysis.solve`, `.sensitivity_grid` |

## Models

| Stata | SPSS | Arboris |
|---|---|---|
| `regress`, `regress, vce(robust)` | `REGRESSION` | `model.ols` — conventional or HC1 robust errors |
| `logit`, `probit` | `LOGISTIC REGRESSION`, `PROBIT` | `model.logit`, `model.probit` |
| `poisson`, `nbreg`, `glm` | `GENLIN` | `model.poisson`, `model.negative_binomial`, `model.glm:*` |
| `zip`, `zinb`, hurdle, beta regression | `GENLIN` | `glm.zero_inflated_*`, `glm.hurdle_*`, `glm.beta` |
| `mlogit` | `NOMREG` | `model.multinomial_logit` |
| `ologit`, `oprobit` | `PLUM` | `model.ordinal_logit` |
| `qreg`, `sqreg` | `QUANTILE REGRESSION` | `model.quantile_regression` |
| `xtreg, fe` / `re` | — | `model.panel_ols` |
| `mixed` | `MIXED` | `model.linear_mixed_effects` |
| `ivregress 2sls` / `gmm`, `estat firststage` | `2SLS` | `model.iv_2sls`, `iv.gmm`, `iv.weak_instruments` |
| `svy: regress`, `svy: logit` | Complex Samples | declare the survey design (weight, strata, PSU, FPC or replicate weights) when setting up the model |
| `stcox`, `sts graph`, `sts test` | `COXREG`, `KM` | `model.survival_cox`, `survival.kaplan_meier`, `survival.log_rank`, `survival.rmst` |
| `didregress`, `xtdidregress` | — | `model.did` (TWFE, event study, parallel trends, Goodman-Bacon) |
| `csdid`, `eventstudyinteract`, `did_multiplegt_dyn`, `honestdid` | — | `model.cs_did`, `model.sa_did`, `model.dcdh`; HonestDiD sensitivity is an option of the DiD models |
| `teffects psmatch` | PS matching | `matching.att`, `matching.balance` |
| `synth` | — | `synthetic_control.fit`, `.placebo` |
| `meta` | Meta Analysis | `meta.effect_size`, `meta.combine` |
| `pca`, `factor`, `cluster`, `discrim`, `ca`, `mca` | `FACTOR`, `CLUSTER`, `DISCRIMINANT`, `CORRESPONDENCE` | `multivariate.pca`, `.efa`, `.clustering`, `.discriminant`, `.correspondence`, `.mca` |
| `lasso`, ridge, random forest | — | `prediction.*` (out-of-sample protocol; never read as causal) |

## After estimation

| Stata | SPSS | Arboris |
|---|---|---|
| `test x1 x2` | — | `model.joint_f_test` |
| `estat hettest`, `estat imtest, white` | — | `diagnostics.breusch_pagan`, `diagnostics.white`, `model.white_test` |
| `estat ovtest` | — | `diagnostics.reset` |
| `estat vif` | Collinearity diagnostics | `diagnostics.vif` |
| `estat bgodfrey` | — | `diagnostics.breusch_godfrey` |
| `predict, cooksd` / `dfbeta` | Influence statistics | `diagnostics.influence` |
| `nlcom -_b[x]/(2*_b[x2])` | — | `model.quadratic_stationary_point` |
| `margins, dydx(*)` | — | average marginal effects, reported with logit, probit, Poisson, multinomial and ordinal models |
| `lroc`, `estat gof` | ROC Curve | `roc.curve`, `roc.calibration` |

## Time series

| Stata | Arboris |
|---|---|
| `corrgram`, `ac`, `pac` | `time_series.acf`, `.pacf` |
| `dfuller`, `kpss` | `time_series.adf`, `.kpss` |
| `arima` | `time_series.arima` |
| `arch` (GARCH) | `model.time_series.arma_garch` |
| exponential smoothing | `model.time_series.ets` |
| `var`, `vec`, `irf`, `vargranger`, `vecrank` | `time_series.var`, `.vecm`, `.irf`, `.granger`, `.cointegration` |

## Spatial

Moran's I, Geary's C and Getis–Ord G: `spatial.moran_i`, `.geary_c`, `.getis_ord_g`.
