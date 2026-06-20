"""Model-type mapping extracted from orchestrator (V1.5.4.5, behavior-frozen).

Verbatim move. Consumed by ytype/estimation/diagnostics stages + the core
driver's exception handler via the workbench.orchestrator.* namespace.

新模型类型的映射改这里：_MODEL_TYPE_MAP / _SUPPORTED_GLM_FAMILIES /
_PREDICTION_MODEL_TYPES 三张表 + 对应翻译函数都在本文件。
"""
from __future__ import annotations

from typing import Any

from ._errors import WorkflowValidationError

# ---------------------------------------------------------------------------
# Per-model-type metadata used to build structured failure details.
# ---------------------------------------------------------------------------
_MODEL_METADATA: dict[str, dict[str, str]] = {
    "ols":               {"model_id": "ols_1",               "engine": "statsmodels"},
    "logit":             {"model_id": "logit_1",             "engine": "statsmodels"},
    "probit":            {"model_id": "probit_1",            "engine": "statsmodels"},
    "poisson":           {"model_id": "poisson_1",           "engine": "statsmodels"},
    "negative_binomial": {"model_id": "negative_binomial_1", "engine": "statsmodels"},
    "panel_ols":         {"model_id": "panel_ols_1",         "engine": "linearmodels"},
    "cs_did":            {"model_id": "cs_did_1",            "engine": "workbench"},
    "sa_did":            {"model_id": "sa_did_1",            "engine": "workbench"},
    "prediction_lasso":          {"model_id": "prediction_lasso_1",          "engine": "scikit-learn"},
    "prediction_ridge":          {"model_id": "prediction_ridge_1",          "engine": "scikit-learn"},
    "prediction_random_forest":  {"model_id": "prediction_random_forest_1",  "engine": "scikit-learn"},
}

# Maximum length of root_cause string in failure evidence to avoid
# leaking verbose stack traces into errors.json.
_ROOT_CAUSE_MAX_LENGTH = 300


def _model_id_for_type(model_type: str) -> str:
    """Return the canonical model_id for a given model_type string."""
    meta = _MODEL_METADATA.get(model_type)
    if meta is not None:
        return meta["model_id"]
    if model_type.startswith("glm:"):
        return "glm_1"
    return f"{model_type}_1"


def _engine_for_type(model_type: str) -> str:
    """Return the engine string for a given model_type."""
    meta = _MODEL_METADATA.get(model_type)
    if meta is not None:
        return meta["engine"]
    if model_type.startswith("glm:"):
        return "statsmodels"
    return "unknown"


def _model_failure_details(
    *,
    model_type: str,
    y: str,
    x: list[str],
    root_cause: str,
    step: str = "estimation",
) -> dict[str, Any]:
    """Build a consistent evidence dict for model-failure issues.

    Every ``MODEL_FIT_FAILED``, ``UNSUPPORTED_MODEL_TYPE``, etc. issue
    must include at least ``model_type``, ``model_id``, ``engine``,
    ``step``, ``y``, ``x``, and ``root_cause`` so that downstream
    consumers (diagnostic summary, report view-model) can render the
    failure without guessing context.
    """
    return {
        "model_type": model_type,
        "model_id": _model_id_for_type(model_type),
        "engine": _engine_for_type(model_type),
        "step": step,
        "y": y,
        "x": list(x),
        "root_cause": root_cause[:_ROOT_CAUSE_MAX_LENGTH],
    }


_MODEL_TYPE_MAP = {
    "ols": "continuous",
    "logit": "binary",
    "probit": "binary",
    "poisson": "count",
    "negative_binomial": "count",
    "panel_ols": "continuous",
    "iv_2sls": "continuous",
    "did": "continuous",
    "cs_did": "continuous",
    "sa_did": "continuous",
}
_SUPPORTED_GLM_FAMILIES = {"binomial", "poisson", "negative_binomial"}
_PREDICTION_MODEL_TYPES = {
    "prediction_lasso",
    "prediction_ridge",
    "prediction_random_forest",
}


def _map_model_type(model_type: str) -> str | None:
    return _MODEL_TYPE_MAP.get(model_type)


def _validate_requested_model_type(model_type: str) -> str | None:
    if model_type == "auto" or model_type in _MODEL_TYPE_MAP or model_type in _PREDICTION_MODEL_TYPES:
        return None
    if not model_type.startswith("glm:"):
        raise WorkflowValidationError(
            "UNSUPPORTED_MODEL_TYPE",
            f"Unsupported model type: {model_type}",
            {
                "model_type": model_type,
                "supported_types": sorted(
                    list(_MODEL_TYPE_MAP.keys())
                    + list(_PREDICTION_MODEL_TYPES)
                    + ["glm:<family>"]
                ),
            },
        )
    family_name = model_type.split(":", 1)[1]
    if family_name not in _SUPPORTED_GLM_FAMILIES:
        raise WorkflowValidationError(
            "UNSUPPORTED_GLM_FAMILY",
            f"Unsupported GLM family: {family_name}",
            {
                "model_type": model_type,
                "glm_family": family_name,
                "supported_families": sorted(_SUPPORTED_GLM_FAMILIES),
            },
        )
    return family_name
