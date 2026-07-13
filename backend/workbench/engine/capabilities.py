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
    "cs_did": {
        "label": "Callaway-Sant'Anna DID",
        "group": "DID",
        "description": "Heterogeneity-robust group-time ATT(g,t) with event-study, group, and calendar aggregations and simultaneous confidence bands. Eliminates the staggered-adoption bias of TWFE DID.",
        "requires": ["entity", "time", "treatment_timing"],
    },
    "sa_did": {
        "label": "Sun-Abraham DID",
        "group": "DID",
        "description": "Interaction-weighted event-study estimator (Sun & Abraham 2021). Heterogeneity-robust dynamic ATT using clean-control cohorts, immune to the contamination of TWFE event-study leads/lags under staggered adoption.",
        "requires": ["entity", "time", "treatment_timing"],
    },
    "dcdh": {
        "label": "de Chaisemartin-D'Haultfoeuille DID",
        "group": "DID",
        "description": "Dynamic DID for binary NON-ABSORBING (switching) treatment using not-yet-switched controls (de Chaisemartin & D'Haultfoeuille). Handles treatments that turn on and off, which Callaway-Sant'Anna and Sun-Abraham cannot. Event study with native placebo pre-trend tests.",
        "requires": ["entity", "time", "treatment_path"],
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
    "cs_did",
    "sa_did",
    "dcdh",
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
    {"key": "robust", "label": "Robust (default)", "default": True},
    {"key": "clustered", "label": "Clustered"},
    {"key": "unadjusted", "label": "Unadjusted"},
]

# U3 (v1.6.11): the default covariance is declared explicitly on the option, so
# reordering COVARIANCE_UI can never silently change the default standard error.
# This single value drives both the exposed `default` flag and the model param's
# `value` below; the frontend reads the flagged option (never `options[0]`).
_COVARIANCE_DEFAULT = next(o["key"] for o in COVARIANCE_UI if o.get("default"))

# v1.6.0 — per-op editable schemas (mirror the FE EditableControl). Structural only:
# key (POST /runs form-param name), kind, options, required, role, value. NO business
# rules (those stay in the pipeline). Only fields the backend genuinely consumes.
_COMMON_MODEL_PARAMS = [
    {"key": "model_type", "kind": "select", "label": "Model", "role": "model"},
    {"key": "x", "kind": "columns", "label": "Regressors (X)", "required": True, "role": "x"},
    {"key": "covariance", "kind": "select", "label": "Covariance", "required": False,
     "options": [o["key"] for o in COVARIANCE_UI], "value": _COVARIANCE_DEFAULT},
]

_MODEL_PARAMS: dict[str, list[dict]] = {
    "ols": _COMMON_MODEL_PARAMS,
    "logit": _COMMON_MODEL_PARAMS,
    "probit": _COMMON_MODEL_PARAMS,
    "poisson": _COMMON_MODEL_PARAMS,
    "negative_binomial": _COMMON_MODEL_PARAMS,
    "panel_ols": _COMMON_MODEL_PARAMS + [
        {"key": "entity_col", "kind": "columns", "label": "Entity", "required": False, "role": "entity"},
        {"key": "time_col", "kind": "columns", "label": "Time", "required": False, "role": "time"},
    ],
    "iv_2sls": _COMMON_MODEL_PARAMS + [
        {"key": "iv_endog", "kind": "columns", "label": "Endogenous", "required": True, "role": "endog"},
        {"key": "iv_instruments", "kind": "columns", "label": "Instruments", "required": True, "role": "instruments"},
    ],
    "did": _COMMON_MODEL_PARAMS,
    "cs_did": _COMMON_MODEL_PARAMS,
    "sa_did": _COMMON_MODEL_PARAMS,
    "dcdh": _COMMON_MODEL_PARAMS,
    "glm:binomial": _COMMON_MODEL_PARAMS,
    "glm:poisson": _COMMON_MODEL_PARAMS,
    "glm:negative_binomial": _COMMON_MODEL_PARAMS,
}


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
        entry["schema_id"] = f"{key}@v1"
        entry["params"] = _MODEL_PARAMS.get(key, list(_COMMON_MODEL_PARAMS))
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
        "schema_version": 3,
        "editable_stages": ["model"],
        "model_types": model_types,
        "imputation_methods": imputation_methods,
        "prediction_models": list(PREDICTION_UI),
        "sampling_methods": list(SAMPLING_UI),
        "covariance_options": list(COVARIANCE_UI),
    }
