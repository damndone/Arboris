"""How each registered operation reads to a person choosing it by hand.

The operation registry, workflow contracts and dedicated endpoints own what an
operation does and how it executes; this table owns only the words a person
sees when picking one: a title, one line on what it is for, and the group it
sits in. Groups follow the order a study usually moves in, from preparing data
to reporting. ``tests/test_operation_catalog.py`` fails when a registered
operation has no entry here, so a new capability arrives with its own words.
An operation added at runtime without an entry still appears, under "More",
with a title derived from its id and the first sentence of its summary.
"""

from __future__ import annotations

from typing import Mapping, NamedTuple

GROUPS: tuple[tuple[str, str], ...] = (
    ("prepare", "Prepare data"),
    ("explore", "Describe & explore"),
    ("test", "Compare & test"),
    ("model", "Estimate models"),
    ("check", "Check a model"),
    ("time_series", "Time series"),
    ("causal", "Causal designs"),
    ("multivariate", "Multivariate & scales"),
    ("survival", "Survival"),
    ("predict", "Prediction"),
    ("spatial", "Spatial"),
    ("plan", "Power & meta-analysis"),
    ("missing", "Missing data"),
    ("share", "Report & export"),
    ("advanced", "Advanced"),
)
FALLBACK_GROUP = ("more", "More")


class Presentation(NamedTuple):
    group: str
    title: str
    blurb: str


P = Presentation

PRESENTATION: Mapping[str, Presentation] = {
    # Prepare data
    "data.import": P("prepare", "Import a dataset", "Upload a CSV, Excel, Stata or SPSS file as a new source."),
    "metadata.edit": P("prepare", "Edit variable metadata", "Labels, value labels, measurement levels and missing-value codes."),
    "data.column.cast": P("prepare", "Change a column's type", "Convert one column to another type in a new dataset step."),
    "data.columns.cast": P("prepare", "Change several column types", "Convert several columns at once in one new dataset step."),
    "data.rename": P("prepare", "Rename columns", "Give columns new names; collisions are refused."),
    "data.recode": P("prepare", "Recode into a new variable", "Map values and ranges to new codes by ordered rules, like SPSS RECODE INTO."),
    "data.subset": P("prepare", "Filter rows and columns", "Keep the rows that meet conditions and the columns you name."),
    "data.dedupe": P("prepare", "Remove duplicate rows", "Drop repeated rows by a key, keeping the first or last."),
    "data.fill_missing": P("prepare", "Fill missing values", "Replace missing values column by column with a stated rule."),
    "data.aggregate": P("prepare", "Aggregate by groups", "Collapse rows to one per group with named summaries."),
    "data.merge": P("prepare", "Merge datasets", "Join another dataset on key columns."),
    "data.append": P("prepare", "Append datasets", "Stack another dataset's rows under this one."),
    "data.reshape": P("prepare", "Reshape wide or long", "Turn columns into rows or rows into columns."),
    "data.tsset": P("prepare", "Set the time index", "Declare the time or panel-time index and sort by it."),
    "data.lag": P("prepare", "Create lags", "Add lagged copies of columns along the time index."),
    "data.feature_recipe": P("prepare", "Create a feature", "Derive a new column from a registered recipe."),
    "statistical.derive_numeric": P("prepare", "Derive a numeric column", "Natural log of a column, or the product of two."),
    "statistical.derive_boolean": P("prepare", "Derive group indicators", "Flag rows above or below percentile thresholds."),
    # Describe & explore
    "statistical.explore": P("explore", "Explore the data", "Summaries, missing-value tables, frequency tables, correlations or scatter plots."),
    "statistical.derived_group_summarize": P("explore", "Summarize by derived group", "Describe columns within each derived group."),
    "nonparametric.robust_summary": P("explore", "Robust summary", "Median, trimmed and winsorized means for skewed data."),
    "missingness.profile": P("explore", "Missing-data profile", "Where values are missing and how patterns co-occur."),
    # Compare & test
    "test.t_tests": P("test", "t-test (two groups)", "Welch two-sample t-test of a numeric outcome across two groups."),
    "test.anova": P("test", "One-way ANOVA", "Compare a numeric outcome across three or more groups."),
    "test.chi_square": P("test", "Chi-square test", "Independence of two categorical variables."),
    "test.fisher_exact": P("test", "Fisher's exact test", "Independence in tables too sparse for chi-square."),
    "test.correlations": P("test", "Pearson correlations", "Correlation for every pair of numeric columns."),
    "test.rank_correlations": P("test", "Rank correlations", "Spearman and Kendall, for monotonic association."),
    "test.nonparametric": P("test", "Rank tests for groups", "Mann–Whitney U and Kruskal–Wallis, without assuming normality."),
    "test.evidence": P("test", "Effect sizes and follow-ups", "Effect sizes, post-hoc comparisons, variance tests, paired and one-sample tests."),
    "nonparametric.mann_whitney": P("test", "Mann–Whitney U", "Rank test of a difference between two independent groups."),
    "nonparametric.wilcoxon_signed_rank": P("test", "Wilcoxon signed-rank", "Rank test for paired measurements."),
    "nonparametric.kruskal_wallis": P("test", "Kruskal–Wallis", "Rank test across three or more independent groups."),
    "nonparametric.friedman": P("test", "Friedman test", "Rank test across repeated measurements of the same subjects."),
    "nonparametric.spearman": P("test", "Spearman correlation", "Rank correlation between two variables."),
    "nonparametric.kendall": P("test", "Kendall's tau", "Rank correlation robust to ties and small samples."),
    "categorical.cramers_v": P("test", "Cramér's V", "Strength of association between two categorical variables."),
    "categorical.mcnemar": P("test", "McNemar's test", "Change in a paired yes/no outcome."),
    "multiple_comparisons.games_howell": P("test", "Games–Howell comparisons", "Pairwise group comparisons without equal variances."),
    "multiple_comparisons.scheffe": P("test", "Scheffé comparisons", "Conservative pairwise comparisons after ANOVA."),
    "repeated_measures_anova.repeated_only": P("test", "Repeated-measures ANOVA", "Within-subject factors measured on the same subjects."),
    "repeated_measures_anova.mixed_design": P("test", "Mixed-design ANOVA", "Within-subject and between-subject factors together."),
    "resampling.bootstrap": P("test", "Bootstrap", "Confidence intervals by resampling the data."),
    "resampling.permutation": P("test", "Permutation test", "A p-value from the statistic's permutation distribution."),
    # Estimate models
    "model.draft": P("model", "New model", "Choose an outcome, predictors and estimator for a new analysis."),
    "model.genesis": P("model", "Estimate models", "Fit one or more models from the source table."),
    "model.auto": P("model", "Suggest a model", "Pick an estimator from the outcome's type."),
    "model.rerun": P("model", "Rerun with changes", "Change this model's settings and estimate it again."),
    "glm.beta": P("model", "Beta regression", "Outcomes that are proportions strictly between 0 and 1."),
    "glm.zero_inflated_poisson": P("model", "Zero-inflated Poisson", "Counts with more zeros than a Poisson allows."),
    "glm.zero_inflated_negative_binomial": P("model", "Zero-inflated negative binomial", "Overdispersed counts with excess zeros."),
    "glm.hurdle_poisson": P("model", "Hurdle Poisson", "Whether a count is zero, then how large it is."),
    "glm.hurdle_negative_binomial": P("model", "Hurdle negative binomial", "Hurdle model for overdispersed counts."),
    "iv.gmm": P("model", "IV by GMM", "Instrumental-variables estimation by generalized method of moments."),
    "model.time_series.arma_garch": P("model", "ARMA–GARCH", "Mean and volatility of a time series together."),
    "model.time_series.ets": P("model", "Exponential smoothing (ETS)", "Error, trend and seasonal smoothing for forecasting."),
    # Check a model
    "postestimation.wald": P("check", "Wald test", "Jointly test restrictions on a model's coefficients."),
    "postestimation.lincom": P("check", "Linear combination", "Estimate a sum or difference of coefficients with its standard error."),
    "postestimation.nlcom": P("check", "Nonlinear combination", "A smooth function of coefficients, by the delta method."),
    "postestimation.margins": P("check", "Marginal effects", "How the predicted outcome changes with each regressor."),
    "postestimation.lr": P("check", "Likelihood-ratio test", "Compare a restricted model with the fuller one it is nested in."),
    "model.joint_f_test": P("check", "Joint F-test", "Whether groups of OLS terms are jointly zero."),
    "model.white_test": P("check", "White test", "Heteroskedasticity in a completed OLS model."),
    "model.quadratic_stationary_point": P("check", "Turning point", "Where a linear-plus-squared effect peaks or bottoms out."),
    "model.compare": P("check", "Compare models", "Set two models side by side."),
    "diagnostics.breusch_pagan": P("check", "Breusch–Pagan test", "Heteroskedasticity linked to the regressors."),
    "diagnostics.white": P("check", "White test (standalone)", "General heteroskedasticity from a design you declare."),
    "diagnostics.breusch_godfrey": P("check", "Breusch–Godfrey test", "Serial correlation in regression residuals."),
    "diagnostics.reset": P("check", "RESET test", "Omitted nonlinearity in the functional form."),
    "diagnostics.vif": P("check", "Variance inflation (VIF)", "Collinearity among regressors."),
    "diagnostics.influence": P("check", "Influential observations", "Leverage, Cook's distance and other influence measures."),
    "iv.weak_instruments": P("check", "Weak-instrument tests", "Whether instruments are strong enough to trust IV estimates."),
    "roc.curve": P("check", "ROC curve", "Discrimination of a predicted score: ROC and AUC."),
    "roc.calibration": P("check", "Calibration", "Whether predicted probabilities match observed rates."),
    # Time series
    "time_series.acf": P("time_series", "Autocorrelation (ACF)", "Correlation of a series with its own lags."),
    "time_series.pacf": P("time_series", "Partial autocorrelation (PACF)", "Lag correlations net of shorter lags."),
    "time_series.adf": P("time_series", "ADF unit-root test", "Augmented Dickey–Fuller test for a unit root."),
    "time_series.kpss": P("time_series", "KPSS stationarity test", "Tests stationarity as the null, the reverse of ADF."),
    "time_series.arima": P("time_series", "ARIMA", "Autoregressive integrated moving-average model."),
    "time_series.var": P("time_series", "Vector autoregression (VAR)", "Several series explained by each other's lags."),
    "time_series.vecm": P("time_series", "Error-correction model (VECM)", "VAR for cointegrated series."),
    "time_series.cointegration": P("time_series", "Cointegration test", "Whether non-stationary series share a long-run relation."),
    "time_series.granger": P("time_series", "Granger causality", "Whether one series' past helps predict another."),
    "time_series.irf": P("time_series", "Impulse responses", "How a shock to one series moves the others over time."),
    # Causal designs
    "matching.att": P("causal", "Propensity-score matching", "Average effect on the treated by nearest-neighbour matching."),
    "matching.balance": P("causal", "Covariate balance", "How well treated and control groups match on covariates."),
    "synthetic_control.fit": P("causal", "Synthetic control", "Build a weighted control unit for one treated unit."),
    "synthetic_control.placebo": P("causal", "Synthetic-control placebos", "Rerun the fit on donor units to judge significance."),
    # Multivariate & scales
    "multivariate.pca": P("multivariate", "Principal components", "Summarize many correlated variables with a few components."),
    "multivariate.efa": P("multivariate", "Exploratory factor analysis", "Latent factors behind a set of items."),
    "multivariate.cronbach_alpha": P("multivariate", "Cronbach's alpha", "Internal consistency of a scale."),
    "multivariate.clustering": P("multivariate", "Cluster analysis", "Group observations by similarity."),
    "multivariate.discriminant": P("multivariate", "Discriminant analysis", "Which variables separate known groups."),
    "multivariate.manova": P("multivariate", "MANOVA", "Group differences on several outcomes at once."),
    "multivariate.correspondence": P("multivariate", "Correspondence analysis", "Map the association in a two-way table."),
    "multivariate.mca": P("multivariate", "Multiple correspondence", "Correspondence analysis for several categorical variables."),
    # Survival
    "survival.kaplan_meier": P("survival", "Kaplan–Meier curves", "Survival probability over time, by group."),
    "survival.log_rank": P("survival", "Log-rank test", "Whether survival curves differ between groups."),
    "survival.rmst": P("survival", "Restricted mean survival", "Average event-free time up to a chosen horizon."),
    # Prediction
    "prediction.prediction_lasso": P("predict", "Lasso prediction", "L1-penalized linear prediction, checked out of sample."),
    "prediction.prediction_ridge": P("predict", "Ridge prediction", "L2-penalized linear prediction, checked out of sample."),
    "prediction.prediction_random_forest": P("predict", "Random-forest prediction", "Tree-ensemble prediction, checked out of sample."),
    "resample.oversample": P("predict", "Oversample training data", "Repeat minority-class rows in the training split."),
    "resample.undersample": P("predict", "Undersample training data", "Drop majority-class rows in the training split."),
    "resample.smote": P("predict", "SMOTE", "Synthesize minority-class rows in the training split."),
    # Spatial
    "spatial.moran_i": P("spatial", "Moran's I", "Global spatial autocorrelation."),
    "spatial.geary_c": P("spatial", "Geary's C", "Spatial autocorrelation weighted toward local differences."),
    "spatial.getis_ord_g": P("spatial", "Getis–Ord G", "Clustering of high or low values."),
    # Power & meta-analysis
    "power_analysis.solve": P("plan", "Power analysis", "Solve for sample size, power, effect size or alpha."),
    "power_analysis.sensitivity_grid": P("plan", "Power sensitivity grid", "Power across a grid of sample and effect sizes."),
    "meta.effect_size": P("plan", "Study effect sizes", "Compute each study's effect size and its variance."),
    "meta.combine": P("plan", "Meta-analysis", "Pool study effects: fixed effect, DerSimonian–Laird or Paule–Mandel."),
    # Missing data
    "imputation.mice": P("missing", "Multiple imputation (MICE)", "Impute missing values by chained equations."),
    "missing_data.rubin_pool": P("missing", "Pool imputed results", "Combine estimates across imputations by Rubin's rules."),
    # Report & export
    "report.compose": P("share", "Compose a report", "Assemble completed steps into a report."),
    "table.export": P("share", "Export tables", "Selected result tables as an Excel workbook."),
    "data.export": P("share", "Export data", "Save the current dataset as a file."),
    "script.export": P("share", "Export a script", "Reproduce this analysis as a Stata, R or Python script."),
    # Advanced
    "graph.fork": P("advanced", "Branch from here", "Start a new branch from the selected step."),
    "operation.multi_step": P("advanced", "Multi-step workflow", "Run several steps under one confirmation."),
    "code.execute": P("advanced", "Run Python code", "Transform the dataset with sandboxed Python."),
    "model.custom": P("advanced", "Custom model", "Run an admitted custom model from a notebook."),
}


_GROUP_INDEX = {key: index for index, (key, _label) in enumerate(GROUPS)}
_GROUP_LABEL = dict(GROUPS)


def _first_sentence(text: str) -> str:
    line = " ".join(text.split())
    head, dot, _rest = line.partition(". ")
    return head + "." if dot else line


def present(operation_id: str, summary: str) -> dict[str, object]:
    """The catalog fields a person reads: title, one line, and group."""
    entry = PRESENTATION.get(operation_id)
    if entry is None:
        group, label = FALLBACK_GROUP
        return {
            "name": operation_id.replace(".", " ").replace("_", " ").capitalize(),
            "blurb": _first_sentence(summary),
            "group": group,
            "group_label": label,
            "group_order": len(GROUPS),
        }
    return {
        "name": entry.title,
        "blurb": entry.blurb,
        "group": entry.group,
        "group_label": _GROUP_LABEL[entry.group],
        "group_order": _GROUP_INDEX[entry.group],
    }
