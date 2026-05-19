"""Factory helpers that produce ready-made DecisionPoint instances for the six
V1.4.0 audit-trail triggers, per V1.4 spec §5.3.

These are the canonical shapes; the orchestrator constructs and passes them
to GraphRecorder.record_*. Keeping them here avoids cluttering orchestrator.py
with verbose DecisionPoint construction.
"""
from __future__ import annotations

from .graph_model import (
    AutoChosenReason,
    Contestability,
    DecisionPoint,
)


def model_type_auto_select(*, selected: str, y_unique: int, y_dtype: str) -> DecisionPoint:
    return DecisionPoint(
        decision_id="model_type_auto_select",
        selected=selected,
        candidates=("ols", "logit", "poisson"),
        source="data_driven_default",
        contestability=Contestability.derive(
            assumption_checks_needed=("variable_role_inference",),
            warnings=("Auto-selected based on y dtype and unique-value count; verify domain fit.",),
        ),
        reason=AutoChosenReason(
            reason_type="data_driven_default",
            explanation=f"y has {y_unique} unique values; selected '{selected}'.",
            chosen_params={"y_unique": y_unique, "y_dtype": y_dtype},
        ),
    )


def categorical_auto_dummy(
    *, variable: str, n_unique: int, reference_level: str
) -> DecisionPoint:
    return DecisionPoint(
        decision_id="categorical_auto_dummy",
        selected="dummy_encode",
        candidates=("dummy_encode", "leave_as_continuous", "drop"),
        source="data_driven_default",
        contestability=Contestability.derive(
            assumption_checks_needed=("categorical_candidate",),
            warnings=("Column had ≤ threshold unique values; may be ordinal rather than categorical.",),
        ),
        reason=AutoChosenReason(
            reason_type="data_driven_default",
            explanation=f"Column '{variable}' has {n_unique} unique non-null values; dummy-encoded.",
            chosen_params={
                "variable": variable,
                "n_unique": n_unique,
                "reference_level": reference_level,
            },
        ),
    )


def ols_default_robust_se(*, variant: str = "HC1") -> DecisionPoint:
    return DecisionPoint(
        decision_id="ols_default_robust_se",
        selected=variant,
        candidates=(),
        source="system_default",
        contestability=Contestability.derive(
            assumption_checks_needed=("breusch_pagan", "white_test"),
            warnings=("Robust SE is hardcoded default. Confirm heteroskedasticity or revisit.",),
        ),
        reason=AutoChosenReason(
            reason_type="system_default",
            explanation="OLS pipeline always applies HC1; not data-driven.",
            chosen_params={"se_type": "robust", "variant": variant},
        ),
    )


def auto_coerce_to_numeric(
    *, variable: str, conversion_rate: float, sample_unconvertible: tuple[str, ...] = (),
) -> DecisionPoint:
    return DecisionPoint(
        decision_id="auto_coerce_to_numeric",
        selected="numeric",
        candidates=("numeric", "leave_as_string", "treat_as_categorical"),
        source="data_driven_default",
        contestability=Contestability.derive(
            assumption_checks_needed=("variable_role_inference",),
            warnings=("Coerced object-dtype column to numeric. Verify column is continuous (vs. ordinal-as-integer).",),
        ),
        reason=AutoChosenReason(
            reason_type="data_driven_default",
            explanation=f"Column '{variable}' was object dtype; coerced to numeric.",
            chosen_params={
                "variable": variable,
                "conversion_rate": conversion_rate,
                "sample_unconvertible": list(sample_unconvertible),
            },
        ),
    )


_MISSING_VALUE_CANDIDATES = (
    "drop_rows_with_missing_required_fields",
    "mean_imputation",
    "median_imputation",
    "group_median_imputation",
    "mode_imputation",
    "missing_as_category",
    "forward_fill",
    "backward_fill",
    "linear_interpolation",
    "spline_interpolation",
    "moving_average_imputation",
    "knn_imputation",
    "regression_imputation",
    "random_forest_imputation",
    "multiple_imputation",
    "kalman_smoothing",
    "matrix_completion",
    "model_native_missing_handling",
)


def handle_missing_values(*, variables: list[str]) -> DecisionPoint:
    return DecisionPoint(
        decision_id="handle_missing_values",
        selected="drop_rows_with_missing_required_fields",
        candidates=_MISSING_VALUE_CANDIDATES,
        source="system_default",
        contestability=Contestability.derive(
            assumption_checks_needed=("missingness_mechanism_audit",),
            warnings=(
                "Listwise deletion assumes MCAR. May bias estimates under MAR/MNAR.",
                "Consider per-variable strategy for time series / panel / causal contexts.",
            ),
        ),
        reason=AutoChosenReason(
            reason_type="system_default",
            explanation="Pipeline drops rows with any missing value in y or x. No per-column strategy.",
            chosen_params_schema="MissingValueStrategy.v1",
            chosen_params={
                "method": "drop_rows_with_missing_required_fields",
                "variables": list(variables),
                "scope": "dataset",
                "group_by": [],
                "time_variable": None,
                "max_gap": None,
                "add_missing_indicator": False,
            },
        ),
    )


def variable_silently_dropped(
    *,
    variable: str,
    drop_reason: str,
    n_unique_after_cleaning: int | None = None,
) -> DecisionPoint:
    """drop_reason is one of: zero_variance / all_missing / perfect_collinearity."""
    return DecisionPoint(
        decision_id="variable_silently_dropped",
        selected="drop_variable",
        candidates=("drop_variable", "drop_rows", "impute", "user_review"),
        source="data_driven_default",
        contestability=Contestability.derive(
            is_contestable=True,
            assumption_checks_needed=(),
            warnings=("Variable was dropped before model fit; downstream interpretation must acknowledge.",),
        ),
        reason=AutoChosenReason(
            reason_type="data_driven_default",
            explanation=f"Variable '{variable}' was dropped due to {drop_reason}.",
            chosen_params={
                "variable": variable,
                "drop_reason": drop_reason,
                "n_unique_after_cleaning": n_unique_after_cleaning,
            },
        ),
    )
