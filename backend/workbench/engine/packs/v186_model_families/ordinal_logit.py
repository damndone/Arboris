from __future__ import annotations

from ...capabilities import CapabilityDeclaration, register_capability_declaration
from ...pack import AnalysisPack, register_pack
from .runtime import model_handlers


def declare_pack() -> None:
    handler = model_handlers()["ordinal_logit"]
    register_capability_declaration(CapabilityDeclaration(
        model_type="ordinal_logit",
        label="Ordinal logit",
        group="Ordinal",
        description="Ordered categorical outcome with logit/probit probabilities, odds ratios where applicable, marginal effects, and a parallel-lines diagnostic.",
        requires=("ordered_outcome",),
        params=[
            {"key": "model_type", "kind": "select", "label": "Model", "role": "model"},
            {"key": "x", "kind": "columns", "label": "Regressors (X)", "required": True, "role": "x"},
            {"key": "model_options", "kind": "json", "label": "Ordinal options", "value": {"link": "logit"}},
        ],
    ))
    register_pack(
        AnalysisPack(
            pack_id="v186-ordinal-logit",
            model_handlers=[handler],
            defaults_by_y_type={"ordinal": "ordinal_logit"},
        )
    )
