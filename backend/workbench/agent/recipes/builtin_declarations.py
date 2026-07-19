"""C1 does not register an executable LMM Agent recipe."""

from __future__ import annotations

from .registry import AgentRecipeDeclaration


BUILTIN_AGENT_RECIPE_DECLARATIONS: tuple[AgentRecipeDeclaration, ...] = ()
