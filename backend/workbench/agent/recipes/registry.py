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
