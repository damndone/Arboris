from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Tuple, TYPE_CHECKING

from ..model_options import ModelOptionsContract

if TYPE_CHECKING:
    from .context import ModelingContext, RunEnv


# A handler runs ONE model. Each handler builds its own kwargs from ctx
# (panel_ols needs entity/time, poisson needs exposure_col/poisson_x, etc.).
# Returns (model_id, primary_result_dict, primary_fitted_or_None).
HandlerFn = Callable[["ModelingContext", "RunEnv"], Tuple[str, dict[str, Any], Any]]
# Validators must raise ModelOptionsValidationError for semantic rejections.
# Estimation also wraps ordinary ValueError/TypeError at this boundary so an
# invalid option can never fall through to the auto-model fallback path.
ModelOptionsValidator = Callable[[Mapping[str, Any]], None]

COEFFICIENT_RESULT_BINDING_KEY = "coefficient_table_v1"
ARTIFACT_RESULT_BINDING_KEY = "artifact_backed_v1"
TYPED_PACKET_RESULT_BINDING_KEY = "typed_packet_v1"


class ModelOptionsValidationError(ValueError):
    """A model-specific options contract rejected before fit execution."""

    def __init__(
        self,
        error_code: str,
        message: str,
        evidence: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.evidence = dict(evidence or {})


class ModelRegistryError(ValueError):
    """Raised when a model handler cannot be admitted to the registry."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        evidence: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
            self.evidence = dict(evidence or {})


@dataclass
class ModelHandler:
    model_type: str            # registry key
    model_id: str              # default written model_id
    serves_y_types: tuple[str, ...]
    fit: HandlerFn
    validate_model_options: ModelOptionsValidator | None = None
    model_options_contract: ModelOptionsContract | None = None
    # None is intentional: a future family is not admitted until its pack
    # declaration names a registered, typed result-binding strategy.
    result_binding_key: str | None = None
    # A family may emit a bounded set of result identities (for example OLS
    # emits ``ols``, ``ols_robust`` or ``ols_clustered``).  ``None`` means the
    # handler key itself is the only accepted result identity.
    accepted_result_model_types: tuple[str, ...] | None = None


MODEL_REGISTRY: dict[str, ModelHandler] = {}
DEFAULT_BY_Y_TYPE: dict[str, str] = {}


def register_model(handler: ModelHandler) -> None:
    if handler.result_binding_key is not None and (
        type(handler.result_binding_key) is not str or not handler.result_binding_key.strip()
    ):
        raise ModelRegistryError(
            f"model handler {handler.model_type!r} declares an invalid result-binding strategy"
        )
    if handler.accepted_result_model_types is not None and (
        type(handler.accepted_result_model_types) is not tuple
        or not handler.accepted_result_model_types
        or any(
            type(model_type) is not str or not model_type.strip()
            for model_type in handler.accepted_result_model_types
        )
        or len(set(handler.accepted_result_model_types)) != len(handler.accepted_result_model_types)
        or handler.model_type not in handler.accepted_result_model_types
    ):
        reason = (
            "must include handler model identity"
            if (
                type(handler.accepted_result_model_types) is tuple
                and handler.accepted_result_model_types
                and handler.model_type not in handler.accepted_result_model_types
            )
            else "declares invalid accepted result identities"
        )
        raise ModelRegistryError(f"model handler {handler.model_type!r} {reason}")
    existing = MODEL_REGISTRY.get(handler.model_type)
    if existing is not None:
        raise ModelRegistryError(
            f"model handler {handler.model_type!r} is already registered by "
            f"model_id {existing.model_id!r}; additive packs must use a new key"
        )
    MODEL_REGISTRY[handler.model_type] = handler


def require_result_binding_key(handler: ModelHandler) -> str:
    """Admit only handlers with an explicit, registered result strategy.

    The adapter registry is loaded lazily so model-pack declarations stay
    independent from the central registry module. This is a registration
    check, not a central allowlist: a new pack registers its adapter and then
    declares its opaque strategy key.
    """

    key = handler.result_binding_key

    def reject(reason: str) -> None:
        raise ModelRegistryError(
            f"model handler {handler.model_type!r} {reason}",
            code="MODEL_RESULT_INVALID",
            evidence={
                "model_type": handler.model_type,
                "result_binding_key": key if type(key) is str else None,
                "result_binding_key_type": type(key).__name__,
                "reason": reason,
            },
        )

    if key is None:
        reject("has no declared result-binding strategy")
    if type(key) is not str or not key.strip():
        reject("declares an invalid result-binding strategy")
    from .result_binding import is_result_binding_adapter_registered

    if not is_result_binding_adapter_registered(key):
        reject("declares an unregistered result-binding strategy")
    return key


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
