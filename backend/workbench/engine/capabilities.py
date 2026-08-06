from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .imputation_registry import IMPUTATION_REGISTRY
from .registry import MODEL_REGISTRY


@dataclass(frozen=True)
class CapabilityDeclaration:
    """Metadata a future model pack may expose after its handler is registered."""

    model_type: str
    label: str
    group: str
    description: str
    requires: Sequence[str]
    params: Sequence[dict[str, object]]


def _v186_model_params(
    option_fields: Sequence[str], *, options_required: bool = False
) -> list[dict[str, object]]:
    return [
        {"key": "model_type", "kind": "select", "label": "Model", "role": "model"},
        {
            "key": "x",
            "kind": "columns",
            "label": "Regressors (X)",
            "required": True,
            "role": "x",
        },
        {
            "key": "model_options",
            "kind": "json",
            "label": "Model options",
            "required": options_required,
            "role": "model_options",
            "options": list(option_fields),
            "value": {},
        },
    ]


# The pack declaration supplies executable ownership; this table owns the
# stable public vocabulary shown to the Agent and model editor. Keeping the
# option fields here prevents a pack's display metadata from silently drifting
# away from the shared workflow contract.
V186_MODEL_CAPABILITY_METADATA: dict[str, dict[str, object]] = {
    "ordinal_logit": {
        "label": "Ordinal logit",
        "group": "Ordinal",
        "description": (
            "Ordered categorical outcome with logit or probit link, probabilities, "
            "odds ratios where applicable, marginal effects, and a parallel-lines diagnostic."
        ),
        "requires": ["ordered_outcome"],
        "model_options_fields": ["optimizer", "maxiter", "link", "outcome_order"],
        "model_options_required": [],
        "params": _v186_model_params(["optimizer", "maxiter", "link", "outcome_order"]),
    },
    "multinomial_logit": {
        "label": "Multinomial logit",
        "group": "Nominal",
        "description": (
            "Nominal categorical outcome with probabilities, relative-risk "
            "ratios, and marginal effects."
        ),
        "requires": ["nominal_outcome"],
        "model_options_fields": ["maxiter", "base_category"],
        "model_options_required": [],
        "params": _v186_model_params(["maxiter", "base_category"]),
    },
    "survival_cox": {
        "label": "Cox survival model",
        "group": "Survival",
        "description": (
            "Cox proportional-hazards model with Kaplan-Meier, log-rank, "
            "risk-set, censoring, and Schoenfeld evidence."
        ),
        "requires": ["survival_outcome", "event_column"],
        "model_options_fields": ["event_column", "group_column", "entry_column", "ties"],
        "model_options_required": ["event_column"],
        "params": _v186_model_params(
            ["event_column", "group_column", "entry_column", "ties"],
            options_required=True,
        ),
    },
    "quantile_regression": {
        "label": "Quantile regression",
        "group": "Quantile",
        "description": (
            "Multiple conditional quantiles with confidence intervals, optional "
            "bootstrap intervals, and cross-quantile comparisons."
        ),
        "requires": ["continuous_outcome"],
        "model_options_fields": ["quantiles", "bootstrap_reps", "random_state"],
        "model_options_required": [],
        "params": _v186_model_params(
            ["quantiles", "bootstrap_reps", "random_state"]
        ),
    },
}


_DECLARED_CAPABILITIES: dict[str, CapabilityDeclaration] = {}
_RESERVED_DECLARATION_MODEL_TYPES = frozenset({"auto", "glm", "poisson_rate"})


def register_capability_declaration(declaration: CapabilityDeclaration) -> None:
    """Register non-legacy capability metadata without mutating central lists.

    Legacy entries remain intentionally centralized for their current wire
    compatibility. New declarations are rejected if they would shadow one.
    """

    if declaration.model_type in _RESERVED_DECLARATION_MODEL_TYPES:
        raise ValueError(
            f"capability declaration uses reserved model type: "
            f"{declaration.model_type}"
        )
    if declaration.model_type in MODEL_UI_META:
        raise ValueError(
            f"capability declaration conflicts with legacy model type: "
            f"{declaration.model_type}"
        )
    if declaration.model_type in _DECLARED_CAPABILITIES:
        raise ValueError(
            f"duplicate capability declaration: {declaration.model_type}"
        )
    _DECLARED_CAPABILITIES[declaration.model_type] = declaration


def registered_declared_model_types() -> tuple[str, ...]:
    """Return future model types that have both declaration and handler.

    This is intentionally narrower than ``MODEL_REGISTRY``: core-only aliases
    remain internal unless a future pack explicitly declares public capability
    metadata for them.
    """

    from .packs.loader import bootstrap_builtin_packs

    bootstrap_builtin_packs()
    return tuple(
        key for key in sorted(_DECLARED_CAPABILITIES) if key in MODEL_REGISTRY
    )


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

_OLS_MODEL_PARAMS = _COMMON_MODEL_PARAMS + [
    {
        "key": "entity_col",
        "kind": "text",
        "label": "Cluster variable",
        "required": False,
        "role": "cluster",
    },
    {
        # The generic Agent envelope is a server-owned contract. Human OLS
        # users keep editing the visible top-level covariance select above;
        # the envelope exists so Notebook run projections can issue typed
        # model.rerun patches without inventing a second execution channel.
        "key": "model_options",
        "kind": "object",
        "label": "OLS model options",
        "required": False,
        "role": "model_options",
        "value": {},
    },
]

_DID_MODEL_PARAMS = [
    {"key": "model_type", "kind": "select", "label": "Model", "role": "model"},
    {
        "key": "x",
        "kind": "columns",
        "label": "Covariates (optional)",
        "required": False,
        "role": "x",
    },
    {"key": "entity_col", "kind": "columns", "label": "Entity", "required": True, "role": "entity"},
    {"key": "time_col", "kind": "columns", "label": "Time", "required": True, "role": "time"},
]

_COHORT_DID_MODEL_PARAMS = _DID_MODEL_PARAMS + [
    {
        "key": "cohort_col",
        "kind": "columns",
        "label": "First treated period",
        "required": True,
        "role": "cohort",
    },
]

_SWITCHING_DID_MODEL_PARAMS = _DID_MODEL_PARAMS + [
    {
        "key": "treatment_path_col",
        "kind": "columns",
        "label": "Treatment path",
        "required": True,
        "role": "treatment_path",
    },
]

_MODEL_PARAMS: dict[str, list[dict]] = {
    "ols": _OLS_MODEL_PARAMS,
    "logit": _COMMON_MODEL_PARAMS,
    "probit": _COMMON_MODEL_PARAMS,
    "poisson": _COMMON_MODEL_PARAMS,
    "negative_binomial": _COMMON_MODEL_PARAMS,
    "panel_ols": _COMMON_MODEL_PARAMS + [
        {"key": "entity_col", "kind": "columns", "label": "Entity", "required": False, "role": "entity"},
        {"key": "time_col", "kind": "columns", "label": "Time", "required": False, "role": "time"},
        {
            "key": "model_options",
            "kind": "object",
            "label": "Panel OLS model options",
            "required": False,
            "role": "model_options",
            "value": {},
        },
    ],
    "iv_2sls": _COMMON_MODEL_PARAMS + [
        {"key": "iv_endog", "kind": "columns", "label": "Endogenous", "required": True, "role": "endog"},
        {"key": "iv_instruments", "kind": "columns", "label": "Instruments", "required": True, "role": "instruments"},
    ],
    "did": _COMMON_MODEL_PARAMS,
    "cs_did": _COHORT_DID_MODEL_PARAMS,
    "sa_did": _COHORT_DID_MODEL_PARAMS,
    "dcdh": _SWITCHING_DID_MODEL_PARAMS,
    "glm:binomial": _COMMON_MODEL_PARAMS,
    "glm:poisson": _COMMON_MODEL_PARAMS,
    "glm:negative_binomial": _COMMON_MODEL_PARAMS,
}


def build_capabilities() -> dict:
    """Build the UI capability manifest from registered backend handlers."""
    # A process can query /capabilities before the first estimation. Future
    # declarations must therefore get the same idempotent pack bootstrap as
    # estimation itself rather than depend on a prior run having imported it.
    from .packs.loader import bootstrap_builtin_packs

    bootstrap_builtin_packs()
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

    # New model packs contribute metadata declaratively. A declaration alone is
    # never enough to expose a selectable model: the real handler must be
    # present, otherwise the UI could offer a model the engine cannot resolve.
    for key in registered_declared_model_types():
        declaration = _DECLARED_CAPABILITIES[key]
        metadata = V186_MODEL_CAPABILITY_METADATA.get(key)
        if metadata is not None:
            entry = {
                "key": key,
                "label": metadata["label"],
                "group": metadata["group"],
                "description": metadata["description"],
                "schema_id": f"{key}@v1",
                "params": [dict(param) for param in metadata["params"]],
            }
            requires = metadata.get("requires")
            if requires:
                entry["requires"] = list(requires)
            model_types.append(entry)
            continue
        entry: dict[str, object] = {
            "key": declaration.model_type,
            "label": declaration.label,
            "group": declaration.group,
            "description": declaration.description,
            "schema_id": f"{declaration.model_type}@v1",
            "params": [dict(param) for param in declaration.params],
        }
        if declaration.requires:
            entry["requires"] = list(declaration.requires)
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
        "survey_design": _survey_design_capability(),
    }


def _survey_design_capability() -> dict:
    """What composes with what, stated so a caller can derive it.

    Published as capabilities rather than left implicit so an agent can work out
    which variance channel a given estimator can use instead of carrying a
    hard-coded list that silently rots as families are added.
    """
    from ..survey.design import LONELY_PSU_POLICIES, REPLICATE_TYPES
    from ..survey.estimator import VARIANCE_METHOD_REQUIREMENTS

    return {
        "variance_methods": sorted(VARIANCE_METHOD_REQUIREMENTS),
        "variance_method_requirements": {
            method: sorted(caps) for method, caps in VARIANCE_METHOD_REQUIREMENTS.items()
        },
        "replicate_types": list(REPLICATE_TYPES),
        "lonely_psu_policies": list(LONELY_PSU_POLICIES),
        "design_fields": [
            "survey_strata_col", "survey_psu_col", "survey_fpc_col",
            "survey_replicate_weights", "survey_replicate_type",
            "survey_lonely_psu", "survey_weight_frame", "survey_subpop",
        ],
    }
