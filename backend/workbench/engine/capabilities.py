from __future__ import annotations

from .imputation_registry import IMPUTATION_REGISTRY
from .registry import MODEL_REGISTRY


MODEL_UI_META: dict[str, dict[str, object]] = {
    "ols": {
        "label": "OLS (linear)",
        "group": "Linear",
        "description": "Ordinary Least Squares with HC1 robust SE.",
    },
    "logit": {
        "label": "Logit",
        "group": "Binary",
        "description": "Logistic regression for binary outcomes.",
    },
    "probit": {
        "label": "Probit",
        "group": "Binary",
        "description": "Probit regression for binary outcomes.",
    },
    "poisson": {
        "label": "Poisson",
        "group": "Count",
        "description": "Poisson regression for count outcomes.",
    },
    "negative_binomial": {
        "label": "Negative Binomial",
        "group": "Count",
        "description": "For overdispersed count outcomes.",
    },
    "panel_ols": {
        "label": "Panel OLS",
        "group": "Panel",
        "description": "Fixed/random effects panel OLS.",
        "requires": ["entity_or_time"],
    },
    "iv_2sls": {
        "label": "IV / 2SLS",
        "group": "IV",
        "description": "Two-stage least squares with instrumental variables for endogenous regressors.",
        "requires": ["endog", "instruments"],
    },
    "did": {
        "label": "DID (Difference-in-Differences)",
        "group": "DID",
        "description": "Two-way fixed-effects DID with event study, parallel-trends test, and Goodman-Bacon decomposition.",
        "requires": ["entity", "time", "treatment_timing"],
    },
    "glm:binomial": {
        "label": "GLM - binomial",
        "group": "GLM",
        "description": "Generalized linear model with binomial family.",
    },
    "glm:poisson": {
        "label": "GLM - poisson",
        "group": "GLM",
        "description": "Generalized linear model with Poisson family.",
    },
    "glm:negative_binomial": {
        "label": "GLM - negative binomial",
        "group": "GLM",
        "description": "Generalized linear model with negative binomial family.",
    },
}

MODEL_UI_ORDER = [
    "ols",
    "logit",
    "probit",
    "poisson",
    "negative_binomial",
    "panel_ols",
    "iv_2sls",
    "did",
    "glm:binomial",
    "glm:poisson",
    "glm:negative_binomial",
]

# DESIGN NOTE: these UI lists are hardcoded rather than derived from registries
# to keep this task small and avoid coupling to prediction/imputation registry
# internals. Deliberate scope choice — not a registry-derivation.
PREDICTION_UI = [
    {"key": "prediction_lasso", "label": "Lasso", "description": "L1-regularized linear prediction."},
    {"key": "prediction_ridge", "label": "Ridge", "description": "L2-regularized linear prediction."},
    {"key": "prediction_random_forest", "label": "Random Forest", "description": "Tree-ensemble prediction."},
]

SAMPLING_UI = [
    {"key": "smote", "label": "SMOTE"},
    {"key": "oversample", "label": "Oversample"},
    {"key": "undersample", "label": "Undersample"},
]

COVARIANCE_UI = [
    {"key": "robust", "label": "Robust (default)"},
    {"key": "clustered", "label": "Clustered"},
    {"key": "unadjusted", "label": "Unadjusted"},
]


def build_capabilities() -> dict:
    """Build the UI capability manifest from registered backend handlers."""
    model_types = [{
        "key": "auto",
        "label": "Auto (infer from y)",
        "group": "auto",
        "description": "Pick the best model automatically based on y type.",
    }]

    exposed_keys = set(MODEL_REGISTRY)
    if "glm" in exposed_keys:
        exposed_keys.update({"glm:binomial", "glm:poisson", "glm:negative_binomial"})
    exposed_keys.discard("glm")
    exposed_keys.discard("poisson_rate")

    for key in MODEL_UI_ORDER:
        if key not in exposed_keys:
            continue
        entry = {"key": key, **MODEL_UI_META[key]}
        model_types.append(entry)

    imputation_methods = [
        {
            "key": method.key,
            "label": method.label,
            "description": method.description,
        }
        for method in sorted(IMPUTATION_REGISTRY.values(), key=lambda item: item.key)
    ]

    return {
        "schema_version": 2,
        "model_types": model_types,
        "imputation_methods": imputation_methods,
        "prediction_models": list(PREDICTION_UI),
        "sampling_methods": list(SAMPLING_UI),
        "covariance_options": list(COVARIANCE_UI),
    }
