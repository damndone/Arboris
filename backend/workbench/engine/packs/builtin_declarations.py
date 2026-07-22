"""Integration-owned declarations for built-in executable model packs."""

from __future__ import annotations

from .loader import PackDeclaration


BUILTIN_PACK_DECLARATIONS: tuple[PackDeclaration, ...] = (
    PackDeclaration(
        module="workbench.engine.packs.linear_mixed_effects.declaration",
        model_type="linear_mixed_effects",
    ),
    PackDeclaration(
        module="workbench.engine.packs.arma_garch.declaration",
        model_type="time_series.arma_garch",
    ),
)
