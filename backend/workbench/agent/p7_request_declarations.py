"""The request schema of each P7 operation: its bindings, options and their shapes.

Data only. p7_pack_registry owns the schema type and checks these cover every declared operation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from workbench.contracts.model.glm_extensions import GLM_EXTENSION_OPERATION_IDS
from workbench.contracts.model.multiple_comparisons import MULTIPLE_COMPARISONS_OPERATION_IDS
from workbench.contracts.model.repeated_measures_anova import REPEATED_MEASURES_ANOVA_OPERATION_IDS
from workbench.contracts.model.spatial_statistics import SPATIAL_STATISTICS_OPERATION_IDS


def declare_request_schemas(register: Callable[..., None], request_schema: Callable[..., Any]) -> None:
    register(
        ("categorical.cramers_v",),
        request_schema(
            ("row", "column"),
            required_options=("correction",),
            option_shapes={"correction": "boolean"},
        ),
    )
    register(
        ("categorical.mcnemar",),
        request_schema(
            ("row", "column"),
            required_options=("exact", "correction"),
            option_shapes={"exact": "boolean", "correction": "boolean"},
        ),
    )
    register(
        GLM_EXTENSION_OPERATION_IDS,
        request_schema(
            ("outcome", "predictors"),
            binding_shapes={"outcome": "column", "predictors": "columns"},
            option_shapes={"maxiter": "integer"},
        ),
    )
    register(
        ("iv.gmm",),
        request_schema(
            ("outcome", "exog", "endog", "instruments"),
            binding_shapes={
                "outcome": "column",
                "exog": "columns",
                "endog": "columns",
                "instruments": "columns",
            },
            option_shapes={
                "estimator": "string",
                "covariance_method": "string",
                "center_moments": "boolean",
                "confidence_level": "number",
                "intercept": "boolean",
                "intercept_column": "string",
            },
        ),
    )
    register(
        ("iv.weak_instruments",),
        request_schema(
            ("outcome", "exog", "endog", "instruments"),
            binding_shapes={
                "outcome": "column",
                "exog": "columns",
                "endog": "columns",
                "instruments": "columns",
            },
            option_shapes={"intercept": "boolean", "intercept_column": "string"},
        ),
    )
    register(
        ("treatment_effects.estimate",),
        request_schema(
            ("treatment", "outcome", "covariates"),
            binding_shapes={"treatment": "column", "outcome": "column", "covariates": "columns"},
            required_options=("estimand",),
            option_shapes={
                "estimand": "string",
                "method": "string",
                "trim": "number",
                "bootstrap_replications": "integer",
                "seed": "integer",
            },
        ),
    )
    register(
        ("matching.att",),
        request_schema(
            ("treatment", "outcome", "covariates"),
            binding_shapes={
                "treatment": "column",
                "outcome": "column",
                "id": "column",
                "covariates": "columns",
            },
            required_options=(
                "propensity_policy",
                "matching_geometry_policy",
                "support_distance_policy",
                "ratio",
                "caliper",
                "replacement",
                "tie_policy",
                "common_support_policy",
                "unmatched_policy",
                "balance_threshold",
                "missing_policy",
            ),
            option_shapes={
                "propensity_policy": "object",
                "matching_geometry_policy": "string",
                "support_distance_policy": "string",
                "ratio": "integer",
                "caliper": "number",
                "replacement": "boolean",
                "tie_policy": "string",
                "common_support_policy": "string",
                "unmatched_policy": "string",
                "balance_threshold": "number",
                "missing_policy": "string",
            },
        ),
    )
    register(
        ("matching.balance",),
        request_schema(
            ("treatment", "covariates"),
            binding_shapes={
                "treatment": "column",
                "id": "column",
                "covariates": "columns",
            },
            required_options=("balance_threshold", "missing_policy"),
            option_shapes={
                "balance_threshold": "number",
                "missing_policy": "string",
                "matched_pairs": "array",
            },
        ),
    )
    register(
        ("meta.combine",),
        request_schema(
            ("study_id", "effect", "variance"),
            required_options=("effect_measure", "method"),
            option_shapes={
                "effect_measure": "string",
                "method": "string",
                "alpha": "number",
                "ci_method": "string",
                "use_t": "boolean",
                "leave_one_out": "boolean",
                "max_leave_one_out": "integer",
                "continuity_correction": "number",
                "zero_correction": "number",
            },
        ),
    )
    register(
        ("meta.effect_size",),
        request_schema(
            ("study_id", "effect", "variance"),
            required_options=("effect_measure",),
            option_shapes={
                "effect_measure": "string",
                "alpha": "number",
                "continuity_correction": "number",
                "zero_correction": "number",
            },
        ),
    )
    register(
        ("missingness.profile",),
        request_schema(),
    )
    register(
        ("missing_data.rubin_pool",),
        request_schema(
            required_options=("model_results",),
            option_shapes={
                "model_results": "array",
                "alpha": "number",
                "null_value": "number",
                "complete_data_degrees_of_freedom": "number",
            },
        ),
    )
    register(
        ("diagnostics.vif",),
        request_schema(
            ("design",),
            binding_shapes={"design": "columns"},
            option_shapes={
                "intercept": "boolean",
                "intercept_column": "nullable_string",
                "model_metadata": "object",
                "max_output_rows": "integer",
            },
        ),
    )
    register(
        ("diagnostics.breusch_pagan", "diagnostics.white"),
        request_schema(
            ("response", "design"),
            binding_shapes={"response": "column", "design": "columns"},
            option_shapes={
                "intercept": "boolean",
                "intercept_column": "nullable_string",
                "model_metadata": "object",
            },
        ),
    )
    register(
        ("diagnostics.breusch_godfrey",),
        request_schema(
            ("response", "design"),
            binding_shapes={"response": "column", "design": "columns"},
            required_options=("lag", "time_order"),
            option_shapes={
                "intercept": "boolean",
                "intercept_column": "nullable_string",
                "model_metadata": "object",
                "lag": "integer",
                "time_order": "string",
            },
        ),
    )
    register(
        ("diagnostics.reset",),
        request_schema(
            ("response", "design"),
            binding_shapes={"response": "column", "design": "columns"},
            required_options=("reset_powers",),
            option_shapes={
                "intercept": "boolean",
                "intercept_column": "nullable_string",
                "model_metadata": "object",
                "reset_powers": "array",
            },
        ),
    )
    register(
        ("diagnostics.influence",),
        request_schema(
            ("response", "design"),
            binding_shapes={"response": "column", "design": "columns"},
            option_shapes={
                "intercept": "boolean",
                "intercept_column": "nullable_string",
                "model_metadata": "object",
                "max_output_rows": "integer",
            },
        ),
    )
    register(
        MULTIPLE_COMPARISONS_OPERATION_IDS,
        request_schema(
            ("group", "value"),
            option_shapes={"alpha": "number"},
        ),
    )
    register(
        ("multivariate.pca",),
        request_schema(
            ("columns",),
            binding_shapes={"columns": "columns"},
            option_shapes={
                "matrix": "string",
                "component_selection": "string",
                "n_components": "integer",
                "variance_threshold": "number",
                "include_scores": "boolean",
                "max_score_rows": "integer",
                "missing_policy": "string",
            },
        ),
    )
    register(
        ("multivariate.efa",),
        request_schema(
            ("columns",),
            binding_shapes={"columns": "columns"},
            required_options=(
                "n_factors",
                "extraction",
                "rotation",
                "kmo_threshold",
                "bartlett_alpha",
            ),
            option_shapes={
                "n_factors": "integer",
                "extraction": "string",
                "rotation": "string",
                "kmo_threshold": "number",
                "bartlett_alpha": "number",
                "missing_policy": "string",
            },
        ),
    )
    register(
        ("multivariate.cronbach_alpha",),
        request_schema(
            ("columns",),
            binding_shapes={"columns": "columns"},
            option_shapes={
                "reverse_scored": "array",
                "reverse_bounds": "object",
                "missing_policy": "string",
            },
        ),
    )
    register(
        ("multivariate.clustering",),
        request_schema(
            ("columns",),
            binding_shapes={"columns": "columns"},
            required_options=("algorithm", "standardization", "selection"),
            option_shapes={
                "algorithm": "string",
                "standardization": "string",
                "selection": "string",
                "n_clusters": "integer",
                "candidate_ks": "array",
                "random_state": "integer",
                "linkage": "string",
                "metric": "string",
                "max_iter": "integer",
                "tol": "number",
                "include_assignments": "boolean",
                "max_assignment_rows": "integer",
                "missing_policy": "string",
            },
        ),
    )
    register(
        ("multivariate.mca",),
        request_schema(
            ("columns",),
            binding_shapes={"columns": "columns"},
            option_shapes={
                "n_dimensions": "integer",
                "missing_policy": "string",
            },
        ),
    )
    register(
        ("multivariate.discriminant",),
        request_schema(
            ("features", "target"),
            binding_shapes={"features": "columns", "target": "column"},
            required_options=("method", "prior_policy", "regularization", "evaluation"),
            option_shapes={
                "method": "string",
                "prior_policy": "string",
                "regularization": "number",
                "evaluation": "string",
                "priors": "object",
                "test_size": "number",
                "random_state": "integer",
                "include_predictions": "boolean",
                "max_prediction_rows": "integer",
                "missing_policy": "string",
            },
        ),
    )
    register(
        ("multivariate.correspondence",),
        request_schema(
            ("row", "column"),
            option_shapes={"n_dimensions": "integer"},
        ),
    )
    register(
        ("multivariate.manova",),
        request_schema(
            ("responses", "factors"),
            optional_bindings=("covariates",),
            binding_shapes={
                "responses": "columns",
                "factors": "columns",
                "covariates": "columns",
            },
            required_options=("interaction_terms", "intercept", "missing_policy"),
            option_shapes={
                "interaction_terms": "array",
                "intercept": "boolean",
                "missing_policy": "string",
                "max_retained_positions": "integer",
            },
        ),
    )
    register(
        ("nonparametric.mann_whitney",),
        request_schema(
            ("x", "y"),
            option_shapes={
                "alternative": "string",
                "method": "string",
                "missing_policy": "string",
                "n_resamples": "integer",
                "seed": "integer",
                "alpha": "number",
            },
        ),
    )
    register(
        ("nonparametric.wilcoxon_signed_rank",),
        request_schema(
            ("x", "y"),
            option_shapes={
                "alternative": "string",
                "method": "string",
                "zero_method": "string",
                "missing_policy": "string",
                "alpha": "number",
            },
        ),
    )
    register(
        ("nonparametric.spearman",),
        request_schema(
            ("x", "y"),
            option_shapes={"missing_policy": "string", "alpha": "number"},
        ),
    )
    register(
        ("nonparametric.kendall",),
        request_schema(
            ("x", "y"),
            option_shapes={
                "variant": "string",
                "missing_policy": "string",
                "alpha": "number",
            },
        ),
    )
    register(
        ("nonparametric.kruskal_wallis",),
        request_schema(
            ("group", "value"),
            option_shapes={
                "method": "string",
                "missing_policy": "string",
                "alpha": "number",
            },
        ),
    )
    register(
        ("nonparametric.friedman",),
        request_schema(
            ("columns",),
            binding_shapes={"columns": "columns"},
            option_shapes={"method": "string", "alpha": "number"},
        ),
    )
    register(
        ("nonparametric.robust_summary",),
        request_schema(
            ("values",),
            option_shapes={
                "trim_fraction": "number",
                "winsor_fraction": "number",
                "missing_policy": "string",
                "alpha": "number",
            },
        ),
    )
    register(
        ("power_analysis.solve",),
        request_schema(
            required_options=("design", "solve_for"),
            option_shapes={"design": "string", "solve_for": "string"},
        ),
    )
    register(
        ("power_analysis.sensitivity_grid",),
        request_schema(
            required_options=("design", "solve_for", "axes"),
            option_shapes={"design": "string", "solve_for": "string", "axes": "object"},
        ),
    )
    register(
        REPEATED_MEASURES_ANOVA_OPERATION_IDS,
        request_schema(
            ("response", "subject", "within"),
            optional_bindings=("between",),
            binding_shapes={
                "response": "column",
                "subject": "column",
                "within": "column_or_columns",
                "between": "column",
            },
            option_shapes={"correction": "string"},
        ),
    )
    register(
        ("resampling.bootstrap",),
        request_schema(
            ("values",),
            required_options=("statistic_id", "n_resamples", "seed", "confidence_level", "interval_method"),
            option_shapes={
                "statistic_id": "string",
                "n_resamples": "integer",
                "seed": "integer",
                "confidence_level": "number",
                "interval_method": "string",
            },
        ),
    )
    register(
        ("resampling.permutation",),
        request_schema(
            ("left", "right"),
            required_options=("statistic_id", "n_resamples", "seed", "alternative"),
            option_shapes={
                "statistic_id": "string",
                "n_resamples": "integer",
                "seed": "integer",
                "alternative": "string",
            },
        ),
    )
    register(
        ("roc.curve",),
        request_schema(
            ("truth", "scores"),
            required_options=("positive_label",),
            option_shapes={
                "positive_label": "any",
                "score_semantics": "string",
                "threshold_policy": "string",
                "quantile_grid_size": "integer",
                "max_thresholds": "integer",
                "missing_policy": "string",
                "constraint_policy": "object",
                "cost_policy": "object",
            },
        ),
    )
    register(
        ("roc.calibration",),
        request_schema(
            ("truth", "scores"),
            required_options=("positive_label", "score_semantics", "calibration_method", "n_bins"),
            option_shapes={
                "positive_label": "any",
                "score_semantics": "string",
                "calibration_method": "string",
                "n_bins": "integer",
                "max_bins": "integer",
                "missing_policy": "string",
            },
        ),
    )
    register(
        SPATIAL_STATISTICS_OPERATION_IDS,
        request_schema(
            ("values", "weights"),
            binding_shapes={"values": "column", "weights": "columns"},
            required_options=("weight_policy", "permutation_policy"),
            option_shapes={"weight_policy": "object", "permutation_policy": "object"},
        ),
    )
    register(
        ("survival.kaplan_meier",),
        request_schema(
            ("duration", "event"),
            optional_bindings=("entry", "group"),
            binding_shapes={
                "duration": "column",
                "event": "column",
                "entry": "column",
                "group": "column",
            },
            option_shapes={
                "ci_method": "string",
                "confidence_level": "number",
                "tau": "number",
            },
        ),
    )
    register(
        ("survival.log_rank",),
        request_schema(
            ("duration", "event"),
            optional_bindings=("entry", "group"),
            binding_shapes={
                "duration": "column",
                "event": "column",
                "entry": "column",
                "group": "column",
            },
            option_shapes={"tie_policy": "string"},
        ),
    )
    register(
        ("survival.rmst",),
        request_schema(
            ("duration", "event"),
            optional_bindings=("entry", "group"),
            binding_shapes={
                "duration": "column",
                "event": "column",
                "entry": "column",
                "group": "column",
            },
            option_shapes={
                "ci_method": "string",
                "confidence_level": "number",
                "tau": "number",
            },
        ),
    )
    register(
        ("synthetic_control.fit",),
        request_schema(
            ("outcomes",),
            binding_shapes={"outcomes": "columns"},
            required_options=("treated_unit", "pre_periods", "post_periods"),
            option_shapes={
                "unit_column": "string",
                "time_column": "string",
                "treated_unit": "string",
                "donor_pool": "array",
                "periods": "array",
                "pre_periods": "array",
                "post_periods": "array",
                "solver_policy": "object",
                "tolerance_policy": "object",
            },
        ),
    )
    register(
        ("synthetic_control.placebo",),
        request_schema(
            ("outcomes",),
            binding_shapes={"outcomes": "columns"},
            required_options=(
                "treated_unit",
                "pre_periods",
                "post_periods",
                "placebo_policy",
            ),
            option_shapes={
                "unit_column": "string",
                "time_column": "string",
                "treated_unit": "string",
                "donor_pool": "array",
                "periods": "array",
                "pre_periods": "array",
                "post_periods": "array",
                "placebo_policy": "object",
                "solver_policy": "object",
                "tolerance_policy": "object",
            },
        ),
    )
    register(
        ("time_series.acf",),
        request_schema(
            ("time", "value"),
            binding_shapes={"time": "column", "value": "column"},
            required_options=("time_order", "nlags"),
            option_shapes={
                "time_order": "string",
                "nlags": "integer",
                "confidence_level": "number",
                "adjusted": "boolean",
            },
        ),
    )
    register(
        ("time_series.pacf",),
        request_schema(
            ("time", "value"),
            binding_shapes={"time": "column", "value": "column"},
            required_options=("time_order", "nlags"),
            option_shapes={
                "time_order": "string",
                "nlags": "integer",
                "confidence_level": "number",
                "method": "string",
            },
        ),
    )
    register(
        ("time_series.adf",),
        request_schema(
            ("time", "value"),
            binding_shapes={"time": "column", "value": "column"},
            required_options=("time_order",),
            option_shapes={
                "time_order": "string",
                "regression": "string",
                "autolag": "string",
                "max_lag": "integer",
            },
        ),
    )
    register(
        ("time_series.kpss",),
        request_schema(
            ("time", "value"),
            binding_shapes={"time": "column", "value": "column"},
            required_options=("time_order",),
            option_shapes={
                "time_order": "string",
                "regression": "string",
                "nlags": "any",
            },
        ),
    )
    register(
        ("time_series.arima",),
        request_schema(
            ("time", "value"),
            binding_shapes={"time": "column", "value": "column"},
            required_options=("time_order", "order"),
            option_shapes={
                "time_order": "string",
                "order": "array",
                "seasonal_order": "array",
                "trend": "string",
                "forecast_horizon": "integer",
                "confidence_level": "number",
            },
        ),
    )
    register(
        ("time_series.var",),
        request_schema(
            ("time", "values"),
            binding_shapes={"time": "column", "values": "columns"},
            required_options=("time_order", "lags"),
            option_shapes={
                "time_order": "string",
                "lags": "integer",
                "trend": "string",
                "forecast_horizon": "integer",
                "confidence_level": "number",
                "stability_policy": "string",
            },
        ),
    )
    register(
        ("time_series.irf",),
        request_schema(
            ("time", "values"),
            binding_shapes={"time": "column", "values": "columns"},
            required_options=("time_order", "lags"),
            option_shapes={
                "time_order": "string",
                "lags": "integer",
                "trend": "string",
                "horizon": "integer",
                "orthogonalized": "boolean",
                "confidence_level": "number",
                "ci_method": "string",
                "stability_policy": "string",
            },
        ),
    )
    register(
        ("time_series.cointegration",),
        request_schema(
            ("time", "values"),
            binding_shapes={"time": "column", "values": "columns"},
            required_options=("time_order", "method"),
            option_shapes={
                "time_order": "string",
                "method": "string",
                "confidence_level": "number",
                "max_lag": "integer",
                "trend": "string",
                "det_order": "integer",
                "k_ar_diff": "integer",
            },
        ),
    )
    register(
        ("time_series.vecm",),
        request_schema(
            ("time", "values"),
            binding_shapes={"time": "column", "values": "columns"},
            required_options=("time_order", "deterministic"),
            option_shapes={
                "time_order": "string",
                "det_order": "integer",
                "k_ar_diff": "integer",
                "deterministic": "string",
                "forecast_horizon": "integer",
                "confidence_level": "number",
            },
        ),
    )
    register(
        ("time_series.granger",),
        request_schema(
            ("time", "cause", "effect"),
            required_options=("time_order", "max_lag"),
            option_shapes={"time_order": "string", "max_lag": "integer", "test": "string"},
        ),
    )
