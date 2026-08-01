"""Fail-closed registry for future model-specific Agent recipes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


BuildPacket = Callable[[Mapping[str, Any]], dict[str, Any]]
PublicProjectionBuilder = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class PublicProjectionDeclaration:
    """One server-owned, bounded public result projection."""

    recipe_id: str
    projection_id: str
    owner: str
    build: PublicProjectionBuilder


def _build_ets_projection(
    payload: Mapping[str, Any], *, artifact_id: str | None, artifact_sha256: str | None
) -> dict[str, Any]:
    from .ets import build_ets_public_result_view

    if not isinstance(artifact_id, str) or not isinstance(artifact_sha256, str):
        return {"available": False, "reason_code": "ETS_PUBLIC_RESULT_UNAVAILABLE"}
    return build_ets_public_result_view(
        payload,
        artifact_id=artifact_id,
        artifact_sha256=artifact_sha256,
    )


def _build_arma_garch_projection(
    payload: Mapping[str, Any], *, artifact_id: str | None, artifact_sha256: str | None
) -> dict[str, Any]:
    from .arma_garch import build_arma_garch_public_result_view

    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, Mapping):
        return {
            "available": False,
            "reason": "ARMA_GARCH_PUBLIC_ARTIFACTS_UNAVAILABLE",
        }
    return build_arma_garch_public_result_view(artifacts)


_PUBLIC_PROJECTIONS: Mapping[str, PublicProjectionDeclaration] = MappingProxyType(
    {
        "time_series.ets": PublicProjectionDeclaration(
            recipe_id="time_series.ets",
            projection_id="forecast_summary",
            owner="time_series.ets",
            build=_build_ets_projection,
        ),
        "time_series.arma_garch": PublicProjectionDeclaration(
            recipe_id="time_series.arma_garch",
            projection_id="time_series_manifest",
            owner="time_series.arma_garch",
            build=_build_arma_garch_projection,
        ),
    }
)


def resolve_public_result_projection(recipe_id: str) -> PublicProjectionDeclaration:
    try:
        return _PUBLIC_PROJECTIONS[recipe_id]
    except (KeyError, TypeError) as exc:
        raise KeyError(f"no public projection for {recipe_id!r}") from exc


def build_public_result_projection(
    recipe_id: str,
    payload: Mapping[str, Any],
    *,
    artifact_id: str | None = None,
    artifact_sha256: str | None = None,
) -> dict[str, Any]:
    """Build one bounded projection without model-type dispatch at the caller."""

    declaration = resolve_public_result_projection(recipe_id)
    return declaration.build(
        payload,
        artifact_id=artifact_id,
        artifact_sha256=artifact_sha256,
    )


@dataclass(frozen=True)
class AgentRecipeDeclaration:
    recipe_id: str
    model_type: str
    build: BuildPacket


class AgentRecipeRegistry:
    def __init__(self) -> None:
        self._items: dict[str, AgentRecipeDeclaration] = {}

    def register(self, declaration: AgentRecipeDeclaration) -> None:
        if declaration.recipe_id in self._items:
            raise ValueError(f"duplicate agent recipe: {declaration.recipe_id}")
        self._items[declaration.recipe_id] = declaration

    def resolve(self, recipe_id: str) -> AgentRecipeDeclaration:
        try:
            return self._items[recipe_id]
        except KeyError as exc:
            raise KeyError(f"no agent recipe: {recipe_id}") from exc


BuildVocabulary = Callable[[], dict[str, Any]]


def _build_ols_option_vocabulary() -> dict[str, Any]:
    from ...contracts.model.ols import OLS_COVARIANCE_VALUES

    return {
        "version": "ols-model-options/v1",
        "fields": {
            "covariance": {
                "path": "covariance",
                "type": "enum",
                "allowed_values": list(OLS_COVARIANCE_VALUES),
                "description": "OLS standard-error covariance estimator.",
            }
        },
        "cross_field_rules": [
            "clustered covariance requires the source model's entity_col cluster field.",
        ],
        "patch_shape_example": {"covariance": "unadjusted"},
        "prohibited_claims": [
            "Do not claim clustered covariance was used unless the source model has an entity_col.",
            "Do not translate covariance into a different estimator label.",
        ],
    }


def _option_vocabulary_builders() -> dict[str, BuildVocabulary]:
    from .arma_garch_vocabulary import build_arma_garch_option_vocabulary
    from ...contracts.model.arma_garch import ARMA_GARCH_PACK_ID

    return {
        ARMA_GARCH_PACK_ID: build_arma_garch_option_vocabulary,
        "ols": _build_ols_option_vocabulary,
    }


def build_option_vocabulary(op_type: str) -> dict[str, Any] | None:
    """Return a pack's Agent-facing option vocabulary, or None if it declares none.

    Silence is the correct answer for packs whose editable schema already names
    every field: inventing a vocabulary there would be a second, drifting source
    of truth. Returning None keeps the platform free of per-pack branches.
    """

    builder = _option_vocabulary_builders().get(op_type)
    return builder() if builder is not None else None


PatchValidator = Callable[..., dict[str, Any]]


def _validate_ols_model_options_patch(
    *, current_contract: Mapping[str, object], patch: Mapping[str, object]
) -> dict[str, object]:
    from ...contracts.model.ols import validate_ols_model_options
    from ...model_options import merge_model_options

    merged = merge_model_options(current_contract, patch)
    validate_ols_model_options(merged)
    return merged


def _patch_validators() -> dict[str, PatchValidator]:
    from .arma_garch import validate_arma_garch_model_options_patch
    from ...contracts.model.arma_garch import ARMA_GARCH_PACK_ID

    return {
        ARMA_GARCH_PACK_ID: validate_arma_garch_model_options_patch,
        "ols": _validate_ols_model_options_patch,
    }


def validate_model_options_patch(
    op_type: str,
    *,
    current_contract: Mapping[str, Any],
    patch: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Judge a model_options patch against the pack that owns it.

    Returns the contract the patch would produce, or None when the pack
    declares no validator. Packs raise their own structured errors, which the
    caller surfaces rather than reinterprets.
    """

    validator = _patch_validators().get(op_type)
    if validator is None:
        return None
    return validator(current_contract=current_contract, patch=patch)
