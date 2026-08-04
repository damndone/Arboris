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
    PackDeclaration(
        module="workbench.engine.packs.ets.declaration",
        model_type="time_series.ets",
    ),
    PackDeclaration(
        module="workbench.engine.packs.v186_model_families.ordinal_logit",
        model_type="ordinal_logit",
    ),
    PackDeclaration(
        module="workbench.engine.packs.v186_model_families.multinomial_logit",
        model_type="multinomial_logit",
    ),
    PackDeclaration(
        module="workbench.engine.packs.v186_model_families.survival_cox",
        model_type="survival_cox",
    ),
    PackDeclaration(
        module="workbench.engine.packs.v186_model_families.quantile_regression",
        model_type="quantile_regression",
    ),
)
