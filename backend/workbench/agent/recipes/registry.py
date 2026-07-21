"""Fail-closed registry for future model-specific Agent recipes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


BuildPacket = Callable[[Mapping[str, Any]], dict[str, Any]]


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


def _option_vocabulary_builders() -> dict[str, BuildVocabulary]:
    from .arma_garch_vocabulary import build_arma_garch_option_vocabulary
    from ...contracts.model.arma_garch import ARMA_GARCH_PACK_ID

    return {ARMA_GARCH_PACK_ID: build_arma_garch_option_vocabulary}


def build_option_vocabulary(op_type: str) -> dict[str, Any] | None:
    """Return a pack's Agent-facing option vocabulary, or None if it declares none.

    Silence is the correct answer for packs whose editable schema already names
    every field: inventing a vocabulary there would be a second, drifting source
    of truth. Returning None keeps the platform free of per-pack branches.
    """

    builder = _option_vocabulary_builders().get(op_type)
    return builder() if builder is not None else None


PatchValidator = Callable[..., dict[str, Any]]


def _patch_validators() -> dict[str, PatchValidator]:
    from .arma_garch import validate_arma_garch_model_options_patch
    from ...contracts.model.arma_garch import ARMA_GARCH_PACK_ID

    return {ARMA_GARCH_PACK_ID: validate_arma_garch_model_options_patch}


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
