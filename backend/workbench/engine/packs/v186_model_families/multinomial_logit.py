from __future__ import annotations

from ...capabilities import CapabilityDeclaration, register_capability_declaration
from ...pack import AnalysisPack, register_pack
from .runtime import model_handlers


def declare_pack() -> None:
    handler = model_handlers()["multinomial_logit"]
    register_capability_declaration(CapabilityDeclaration(
        model_type="multinomial_logit",
        label="Multinomial logit",
        group="Nominal",
        description="Nominal categorical outcome with probabilities, relative-risk ratios, and marginal effects.",
        requires=("nominal_outcome",),
        params=[
            {"key": "model_type", "kind": "select", "label": "Model", "role": "model"},
            {"key": "x", "kind": "columns", "label": "Regressors (X)", "required": True, "role": "x"},
            {"key": "model_options", "kind": "json", "label": "Multinomial options", "value": {}},
        ],
    ))
    register_pack(AnalysisPack(pack_id="v186-multinomial-logit", model_handlers=[handler]))
