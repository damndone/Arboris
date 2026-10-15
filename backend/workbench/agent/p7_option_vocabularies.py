"""The allowed values of each frozen-pack option that takes a closed vocabulary.

Every set here is the one the pack's kernel validates the option against, and
is imported from the pack's contract module, where the kernel imports it too:
there is one copy of each vocabulary. The workflow registry merges these into
the operations' request schemas, so the served catalog offers a choice instead
of a free text box and a wrong spelling is refused before the kernel runs.

Options that name something in the data (a column, a unit) are open and are
listed in ``OPEN_STRING_OPTIONS`` instead. ``tests/test_p7_option_vocabularies.py``
fails when a string option of a frozen pack is in neither place.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from workbench.contracts.model.iv_gmm import GMM_COVARIANCE_METHODS, GMM_ESTIMATORS
from workbench.contracts.model.matching import (
    MATCHING_COMMON_SUPPORT_POLICIES,
    MATCHING_GEOMETRY_POLICIES,
    MATCHING_MISSING_POLICIES,
    MATCHING_SUPPORT_DISTANCE_POLICIES,
    MATCHING_TIE_POLICIES,
    MATCHING_UNMATCHED_POLICIES,
)
from workbench.contracts.model.meta_analysis import (
    META_ANALYSIS_CI_METHODS,
    META_ANALYSIS_COMBINE_METHODS,
    META_ANALYSIS_EFFECT_MEASURES,
)
from workbench.contracts.model.model_diagnostics import MODEL_DIAGNOSTICS_TIME_ORDERS
from workbench.contracts.model.multivariate import (
    CLUSTERING_ALGORITHMS,
    CLUSTERING_LINKAGES,
    CLUSTERING_METRICS,
    CLUSTERING_SELECTIONS,
    CLUSTERING_STANDARDIZATIONS,
    DISCRIMINANT_EVALUATIONS,
    DISCRIMINANT_METHODS,
    DISCRIMINANT_PRIOR_POLICIES,
    EFA_EXTRACTIONS,
    EFA_ROTATIONS,
    MCA_MISSING_POLICIES,
    MULTIVARIATE_MISSING_POLICIES,
    PCA_COMPONENT_SELECTIONS,
    PCA_MATRICES,
)
from workbench.contracts.model.nonparametric import (
    FRIEDMAN_METHODS,
    KENDALL_VARIANTS,
    KRUSKAL_WALLIS_METHODS,
    MANN_WHITNEY_METHODS,
    NONPARAMETRIC_ALTERNATIVES,
    NONPARAMETRIC_MISSING_POLICIES,
    WILCOXON_METHODS,
    WILCOXON_ZERO_METHODS,
)
from workbench.contracts.model.power_analysis import POWER_ANALYSIS_DESIGNS, POWER_ANALYSIS_SOLVE_TARGETS
from workbench.contracts.model.repeated_measures_anova import REPEATED_MEASURES_ANOVA_CORRECTIONS
from workbench.contracts.model.resampling import (
    BOOTSTRAP_INTERVAL_METHODS,
    BOOTSTRAP_STATISTICS,
    PERMUTATION_ALTERNATIVES,
    PERMUTATION_STATISTICS,
)
from workbench.contracts.model.roc_diagnostics import (
    ROC_CALIBRATION_METHODS,
    ROC_MISSING_POLICIES,
    ROC_SCORE_SEMANTICS,
    ROC_THRESHOLD_POLICIES,
)
from workbench.contracts.model.survival_analysis import (
    SURVIVAL_ANALYSIS_CI_METHODS,
    SURVIVAL_ANALYSIS_TIE_POLICIES,
)
from workbench.contracts.model.time_series_pack import (
    ADF_AUTOLAGS,
    ADF_REGRESSIONS,
    ARIMA_TRENDS,
    COINTEGRATION_METHODS,
    ENGLE_GRANGER_TRENDS,
    GRANGER_TESTS,
    IRF_CI_METHODS,
    KPSS_REGRESSIONS,
    PACF_METHODS,
    STABILITY_POLICIES,
    TIME_ORDER_POLICIES,
    VAR_TRENDS,
    VECM_DETERMINISTICS,
)


def _values(vocabulary: Iterable[str]) -> tuple[str, ...]:
    """A stable order for the served enum: as declared for tuples, sorted for sets."""
    return tuple(vocabulary) if isinstance(vocabulary, tuple) else tuple(sorted(vocabulary))


def _each(operation_ids: Iterable[str], options: Mapping[str, Iterable[str]]) -> dict[str, dict[str, tuple[str, ...]]]:
    return {operation_id: {name: _values(values) for name, values in options.items()} for operation_id in operation_ids}


_DIAGNOSTICS = ("diagnostics.breusch_pagan", "diagnostics.white", "diagnostics.reset", "diagnostics.vif", "diagnostics.influence")

OPTION_VOCABULARIES: dict[str, dict[str, tuple[str, ...]]] = {
    **_each(("diagnostics.breusch_godfrey",), {"time_order": MODEL_DIAGNOSTICS_TIME_ORDERS}),
    **_each(("iv.gmm",), {"estimator": GMM_ESTIMATORS, "covariance_method": GMM_COVARIANCE_METHODS}),
    **_each(("matching.att",), {
        "matching_geometry_policy": MATCHING_GEOMETRY_POLICIES,
        "support_distance_policy": MATCHING_SUPPORT_DISTANCE_POLICIES,
        "tie_policy": MATCHING_TIE_POLICIES,
        "common_support_policy": MATCHING_COMMON_SUPPORT_POLICIES,
        "unmatched_policy": MATCHING_UNMATCHED_POLICIES,
        "missing_policy": MATCHING_MISSING_POLICIES,
    }),
    **_each(("matching.balance",), {"missing_policy": MATCHING_MISSING_POLICIES}),
    **_each(("meta.combine",), {
        "effect_measure": META_ANALYSIS_EFFECT_MEASURES,
        "method": META_ANALYSIS_COMBINE_METHODS,
        "ci_method": META_ANALYSIS_CI_METHODS,
    }),
    **_each(("meta.effect_size",), {"effect_measure": META_ANALYSIS_EFFECT_MEASURES}),
    **_each(("multivariate.clustering",), {
        "algorithm": CLUSTERING_ALGORITHMS,
        "standardization": CLUSTERING_STANDARDIZATIONS,
        "selection": CLUSTERING_SELECTIONS,
        "linkage": CLUSTERING_LINKAGES,
        "metric": CLUSTERING_METRICS,
        "missing_policy": MULTIVARIATE_MISSING_POLICIES,
    }),
    **_each(("multivariate.discriminant",), {
        "method": DISCRIMINANT_METHODS,
        "prior_policy": DISCRIMINANT_PRIOR_POLICIES,
        "evaluation": DISCRIMINANT_EVALUATIONS,
        "missing_policy": MULTIVARIATE_MISSING_POLICIES,
    }),
    **_each(("multivariate.efa",), {
        "extraction": EFA_EXTRACTIONS,
        "rotation": EFA_ROTATIONS,
        "missing_policy": MULTIVARIATE_MISSING_POLICIES,
    }),
    **_each(("multivariate.pca",), {
        "matrix": PCA_MATRICES,
        "component_selection": PCA_COMPONENT_SELECTIONS,
        "missing_policy": MULTIVARIATE_MISSING_POLICIES,
    }),
    **_each(("multivariate.cronbach_alpha", "multivariate.manova"), {"missing_policy": MULTIVARIATE_MISSING_POLICIES}),
    **_each(("multivariate.mca",), {"missing_policy": MCA_MISSING_POLICIES}),
    **_each(("nonparametric.mann_whitney",), {
        "alternative": NONPARAMETRIC_ALTERNATIVES,
        "method": MANN_WHITNEY_METHODS,
        "missing_policy": NONPARAMETRIC_MISSING_POLICIES,
    }),
    **_each(("nonparametric.wilcoxon_signed_rank",), {
        "alternative": NONPARAMETRIC_ALTERNATIVES,
        "method": WILCOXON_METHODS,
        "zero_method": WILCOXON_ZERO_METHODS,
        "missing_policy": NONPARAMETRIC_MISSING_POLICIES,
    }),
    **_each(("nonparametric.kruskal_wallis",), {
        "method": KRUSKAL_WALLIS_METHODS,
        "missing_policy": NONPARAMETRIC_MISSING_POLICIES,
    }),
    **_each(("nonparametric.friedman",), {"method": FRIEDMAN_METHODS}),
    **_each(("nonparametric.kendall",), {"variant": KENDALL_VARIANTS, "missing_policy": NONPARAMETRIC_MISSING_POLICIES}),
    **_each(("nonparametric.spearman", "nonparametric.robust_summary"), {"missing_policy": NONPARAMETRIC_MISSING_POLICIES}),
    **_each(("power_analysis.solve", "power_analysis.sensitivity_grid"), {
        "design": POWER_ANALYSIS_DESIGNS,
        "solve_for": POWER_ANALYSIS_SOLVE_TARGETS,
    }),
    **_each(("repeated_measures_anova.repeated_only", "repeated_measures_anova.mixed_design"), {
        "correction": REPEATED_MEASURES_ANOVA_CORRECTIONS,
    }),
    **_each(("resampling.bootstrap",), {"statistic_id": BOOTSTRAP_STATISTICS, "interval_method": BOOTSTRAP_INTERVAL_METHODS}),
    **_each(("resampling.permutation",), {"statistic_id": PERMUTATION_STATISTICS, "alternative": PERMUTATION_ALTERNATIVES}),
    **_each(("roc.curve",), {
        "score_semantics": ROC_SCORE_SEMANTICS,
        "threshold_policy": ROC_THRESHOLD_POLICIES,
        "missing_policy": ROC_MISSING_POLICIES,
    }),
    **_each(("roc.calibration",), {
        "score_semantics": ROC_SCORE_SEMANTICS,
        "calibration_method": ROC_CALIBRATION_METHODS,
        "missing_policy": ROC_MISSING_POLICIES,
    }),
    **_each(("survival.kaplan_meier", "survival.rmst"), {"ci_method": SURVIVAL_ANALYSIS_CI_METHODS}),
    **_each(("survival.log_rank",), {"tie_policy": SURVIVAL_ANALYSIS_TIE_POLICIES}),
    **_each(("time_series.acf",), {"time_order": TIME_ORDER_POLICIES}),
    **_each(("time_series.pacf",), {"time_order": TIME_ORDER_POLICIES, "method": PACF_METHODS}),
    **_each(("time_series.adf",), {"time_order": TIME_ORDER_POLICIES, "regression": ADF_REGRESSIONS, "autolag": ADF_AUTOLAGS}),
    **_each(("time_series.kpss",), {"time_order": TIME_ORDER_POLICIES, "regression": KPSS_REGRESSIONS}),
    **_each(("time_series.arima",), {"time_order": TIME_ORDER_POLICIES, "trend": ARIMA_TRENDS}),
    **_each(("time_series.var",), {"time_order": TIME_ORDER_POLICIES, "trend": VAR_TRENDS, "stability_policy": STABILITY_POLICIES}),
    **_each(("time_series.irf",), {
        "time_order": TIME_ORDER_POLICIES,
        "trend": VAR_TRENDS,
        "ci_method": IRF_CI_METHODS,
        "stability_policy": STABILITY_POLICIES,
    }),
    # Engle-Granger validates trend; Johansen does not read it.
    **_each(("time_series.cointegration",), {
        "time_order": TIME_ORDER_POLICIES,
        "method": COINTEGRATION_METHODS,
        "trend": ENGLE_GRANGER_TRENDS,
    }),
    **_each(("time_series.granger",), {"time_order": TIME_ORDER_POLICIES, "test": GRANGER_TESTS}),
    **_each(("time_series.vecm",), {"time_order": TIME_ORDER_POLICIES, "deterministic": VECM_DETERMINISTICS}),
}

#: String options whose value names something in the data, not a policy.
OPEN_STRING_OPTIONS: dict[str, frozenset[str]] = {
    **{operation_id: frozenset({"intercept_column"}) for operation_id in (*_DIAGNOSTICS, "diagnostics.breusch_godfrey")},
    "synthetic_control.fit": frozenset({"treated_unit"}),
    "synthetic_control.placebo": frozenset({"treated_unit"}),
}

__all__ = ["OPEN_STRING_OPTIONS", "OPTION_VOCABULARIES"]
