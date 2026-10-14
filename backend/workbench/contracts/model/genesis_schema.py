"""Shared Genesis parameter declaration without numerical execution imports."""
from __future__ import annotations

from typing import Any

from .family import MODEL_FAMILY_CONTRACTS


def _workflow_executable_family_sentence() -> str:
    """The families an Agent may name, derived from the registry."""
    families = sorted(key for key in MODEL_FAMILY_CONTRACTS if key != "auto")
    return (
        "Registered workflow-executable model family: "
        + ", ".join(families)
        + ". Every branch in one step uses this same family."
    )


def _multiple_imputation_sentence() -> str:
    """Read off the pooling registry, so the offer cannot outgrow the validation."""
    from ...combinators.multiple_imputation import MAX_IMPUTATIONS, MIN_IMPUTATIONS, validated_text

    return (
        f"Optional m ({MIN_IMPUTATIONS}-{MAX_IMPUTATIONS}) for multiple imputation: missing values in "
        "the outcome and predictors are imputed m times by chained equations (MICE), the model is "
        "fitted to each completed dataset, and the estimates are pooled by Rubin's rules with "
        f"Barnard-Rubin degrees of freedom. Offered for: {validated_text()}. Refused with a "
        "sampling design. Pooled results report no R-squared or residual diagnostics, and joint "
        "tests on them are not available yet."
    )


def _by_group_sentence() -> str:
    """Read off the by-group registry, so the offer cannot outgrow the invariance test."""
    from ...combinators.by_group import BY_GROUP_OPEN, MAX_GROUPS

    families = ", ".join(sorted(name for name in BY_GROUP_OPEN if "." not in name))
    return (
        "Optional grouping column: the model is estimated separately within each group (a "
        f"missing value is a group of its own; at most {MAX_GROUPS} groups; under a sampling "
        "design each group is a domain of the full design). Each group gets its own result; a "
        "group below the check library's sample minimum is listed as not estimable. The run also "
        "tests whether the groups' coefficients differ (Wald on the fully interacted pooled "
        f"model): cite that test before saying groups differ. Offered for: {families}."
    )


def _genesis_survey_fields() -> dict[str, str]:
    """The sampling-design declarations, described where they are declared.

    A first run must be able to state a design: reachable only on a rerun means
    the analysis has to be built by hand before an Agent can touch it, which is
    the opposite of driving the workbench from one sentence.
    """
    from ...survey.fields import DESIGN_FIELD_SPECS

    described = {
        spec["key"]: (
            f"{spec['label']}."
            + (f" One of: {', '.join(spec['options'])}." if spec.get("options") else "")
        )
        for spec in DESIGN_FIELD_SPECS
    }
    described["sampling_weight"] = (
        "Column holding the sampling weight. A survey design requires one, and a "
        "sampling weight without a declared design is refused -- give both or neither."
    )
    return described



def model_genesis_parameters() -> dict[str, Any]:
    """Build the live metadata consumed by workflow admission and CLI help."""
    return dict(
        summary="Estimate one or more models from the source table.",
        fields={
            # Read off the registry, never typed out: this sentence is the only
            # place an Agent learns which families exist, and a hand-written
            # list goes stale the first time one is added. `anova` shipped in
            # v1.8.7 while this text still named the previous eighteen, so a
            # request for a factorial ANOVA had nowhere to land -- and nothing
            # failed, because prose does not fail.
            "model_family": _workflow_executable_family_sentence(),
            "covariance": (
                "Default covariance for every branch. panel_ols and did cluster by entity when "
                "omitted (CR1, t(G-1), as Stata's xtreg, fe vce(robust)); to cluster at the level "
                "where treatment was assigned, name that column in model_options.cluster. robust "
                "(not clustered) is inconsistent with a fixed number of periods; offer it only to "
                "reproduce earlier work."
            ),
            "model_options": (
                "Family-owned JSON options. Only the selected model family's declared "
                "option fields are accepted; do not copy options from another family."
            ),
            "entity_col": (
                "Panel entity column. panel_ols requires entity_col or time_col; "
                "clustered panel covariance requires entity_col."
            ),
            "time_col": "Optional panel time column for time fixed effects.",
            "cohort_col": "First-treatment period for cs_did or sa_did (0 for never treated).",
            "treatment_path_col": "Binary treatment path for dcdh, which may switch on and off.",
            "iv_endog": "Non-empty endogenous-regressor column list for iv_2sls.",
            "iv_instruments": "Non-empty instrument column list for iv_2sls; must not overlap endog or predictors.",
            "did_mode": "TWFE DID treatment definition: cohort, two_by_two, or status.",
            "did_cohort_col": "First-treatment period for did_mode cohort (0 for never treated).",
            "did_treat_col": "Treatment-group indicator for did_mode two_by_two.",
            "did_post_col": "Post-period indicator for did_mode two_by_two.",
            "did_status_col": "Absorbing treatment-status indicator for did_mode status.",
            **_genesis_survey_fields(),
            "labels": (
                "Column metadata. `measurement_level` maps column names to "
                "nominal / ordinal / scale / count and decides how each column is "
                "modelled -- an integer rating left undeclared is analysed as a "
                "count. Declare every column in one step rather than one at a time."
            ),
            "branches": (
                "List of {branch_id, outcome, predictors[, categorical]"
                "[, polynomials][, covariance]}; one estimated model per entry. "
                "Entries in `predictors` enter LINEARLY, exactly as the column "
                "stands — listing a categorical code column there estimates a "
                "linear effect on the code, which is a different model. Use "
                "`categorical` for dummy expansion and `polynomials` for powers. "
                "Interaction terms cannot be expressed; say so rather than "
                "approximating one."
            ),
            "categorical": (
                "Per branch: list of column names to expand into dummy "
                "indicators. One level is dropped as the reference category to "
                "avoid perfect collinearity with the intercept; the lowest "
                "sorted level is the reference. A column listed here must NOT "
                "also appear in `predictors`."
            ),
            "polynomials": (
                "Per branch: list of {column, degree}. degree 2 adds the square, "
                "3 adds square and cube, and so on; generated columns are named "
                "{column}_pow2, {column}_pow3. The linear term is not added "
                "implicitly — list the column in `predictors` as well when the "
                "model should contain it."
            ),
            "context_columns": "Extra columns to carry into the model context.",
            "multiple_imputations": _multiple_imputation_sentence(),
            "by_group": _by_group_sentence(),
        },
        required=("model_family", "branches"),
        field_types={
            "model_family": "string",
            "covariance": "string",
            "model_options": "object",
            "entity_col": "string",
            "time_col": "string",
            "cohort_col": "string",
            "treatment_path_col": "string",
            "iv_endog": "list",
            "iv_instruments": "list",
            "did_mode": "string",
            "did_cohort_col": "string",
            "did_treat_col": "string",
            "did_post_col": "string",
            "did_status_col": "string",
            "branches": "list",
            "categorical": "list",
            "polynomials": "list",
            "context_columns": "list",
            "multiple_imputations": "integer",
            "by_group": "string",
        },
        field_schemas={},
        field_enums={},
    )
