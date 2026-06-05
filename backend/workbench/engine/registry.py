from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .context import ModelingContext, RunEnv


# A handler runs ONE model. Each handler builds its own kwargs from ctx
# (panel_ols needs entity/time, poisson needs exposure_col/poisson_x, etc.).
# Returns (model_id, primary_result_dict, primary_fitted_or_None).
HandlerFn = Callable[["ModelingContext", "RunEnv"], Tuple[str, dict[str, Any], Any]]


@dataclass
class ModelHandler:
    model_type: str            # registry key
    model_id: str              # default written model_id
    serves_y_types: tuple[str, ...]
    fit: HandlerFn


MODEL_REGISTRY: dict[str, ModelHandler] = {}
DEFAULT_BY_Y_TYPE: dict[str, str] = {}


def register_model(handler: ModelHandler) -> None:
    MODEL_REGISTRY[handler.model_type] = handler


def set_default(y_type: str, model_type: str) -> None:
    DEFAULT_BY_Y_TYPE[y_type] = model_type


def resolve(ctx) -> ModelHandler:
    """1.5.3.2 contract: explicit `requested_model_type` ALWAYS wins.

    Unknown explicit type => KeyError (caller surfaces structured failed,
    NEVER silent fallback). Auto falls back to the y_type default.
    `glm:<family>` collapses to the `glm` key (family comes from ctx).
    """
    req = ctx.requested_model_type
    if req and req != "auto":
        key = req.split(":", 1)[0] if req.startswith("glm:") else req
        return MODEL_REGISTRY[key]
    return MODEL_REGISTRY[DEFAULT_BY_Y_TYPE[ctx.y_type]]
