---
name: time-series-and-volatility
description: Guide ARIMA and ARMA-GARCH research using actual time order, transformations, original-fit innovations, separate training/production evidence, source-bound sensitivity and honest forecasting limits.
---

# Time series and volatility analysis

Fix the research question first: forecasting a series, evaluating volatility or assessing an association between trending series require different analyses. An unrelated univariate forecast cannot answer the M0 advertising/sales spurious-regression question. Preserve observation order, calendar/trading semantics, transformation, forecast target and estimand in the plan. Never fill gaps or infer an unstated calendar to make a method apply.

## ARIMA

Read actual ordered complete cases, initialization burn, original-fit coefficients/SE, convergence and AR/MA roots. The calibrated native diagnostics use fixed ADF(c,lag4,no autolag), KPSS(c,lag4), standardized one-step forecast innovations after initialization, Ljung–Box with ARMA degrees of freedom and ARCH LM with the declared ddof. Preserve approximate/bounded p-value labels. Short, constant, nonfinite or inadmissible cases are not passed tests. Irregular spacing, unresolved stationarity or remaining mean/variance dependence require applicable revision or partial completion. Do not search differencing/order to obtain non-rejection. VAR/VECM positive completion is not calibrated merely because the operations exist.

## ARMA-GARCH

The training-only parent and the all-available-observations production child are distinct results. Inspect the child's own native diagnostics/SE/convergence; never reuse training residuals as its evidence. Check standardized and squared innovations, native variance constraints and mean roots, actual transformation and declared initialization. The current residual policy uses .01 for GARCH adequacy; estimated-GARCH diagnostic p-values are asymptotic approximations. A normality rejection is distribution evidence, not an automatic failure of a nonnormal model.

Respect the original frozen training/validation boundary. In-sample classical replication is not independent forecasting evaluation. Plugin forecast intervals do not include parameter uncertainty and their nominal level does not prove actual coverage. Preserve validation sample size, failures, forecast metrics and uncertainty. Do not claim calibration from a tiny successful holdout.

## Sensitivity, completion and report

Obtain real, justified alternatives changing the point-estimation order, mean/variance specification, distribution or defensible sample. Horizon, confidence level, refit frequency or validation-window changes alone do not constitute a distinct full-sample point specification. A specification curve uses all model members frozen before that workflow executed; it retains failures and unavailable intervals, separates targets/scales, and is not formal preregistration or simultaneous inference.

Use time_series/garch completion playbooks with real source/evidence references and a source-bound report. Native computability, R/Stata numerical agreement and valid inference remain distinct. Keep the original M0 failures and scientific gaps visible; partial completion is preferable to false certification. Preserve both failed attempts, stop automatic attempts after the second, and explain concrete options without silent method substitution. Isolated review is bounded and has no execution authority; real model/judge/evaluation acceptance is a separate lane.
