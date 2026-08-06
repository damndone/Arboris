from __future__ import annotations

from ...capabilities import CapabilityDeclaration, register_capability_declaration
from ...pack import AnalysisPack, register_pack
from .runtime import model_handlers


def declare_pack() -> None:
    register_capability_declaration(CapabilityDeclaration(
        model_type="anova",
        label="ANOVA / ANCOVA",
        group="ANOVA",
        description=(
            "Factorial analysis of variance with optional covariates. Declares its "
            "sums-of-squares type explicitly: SPSS reports Type III and R's aov "
            "reports Type I, and on an unbalanced design they disagree."
        ),
        requires=(),
        params=[
            {"key": "model_type", "kind": "select", "label": "Model", "role": "model"},
            {"key": "x", "kind": "columns", "label": "Factors and covariates", "required": True, "role": "x"},
            {
                "key": "model_options", "kind": "json", "label": "ANOVA options",
                "value": {"sums_of_squares": 3, "categorical": [], "interactions": []},
            },
        ],
    ))
    register_pack(
        AnalysisPack(pack_id="v187-anova", model_handlers=list(model_handlers().values()))
    )
