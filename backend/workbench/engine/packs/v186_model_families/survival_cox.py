from __future__ import annotations

from ...capabilities import CapabilityDeclaration, register_capability_declaration
from ...pack import AnalysisPack, register_pack
from .runtime import model_handlers


def declare_pack() -> None:
    handler = model_handlers()["survival_cox"]
    register_capability_declaration(CapabilityDeclaration(
        model_type="survival_cox",
        label="Survival / Cox",
        group="Survival",
        description="Cox proportional hazards with Kaplan–Meier, log-rank, risk-set, censoring, and Schoenfeld evidence.",
        requires=("event_column",),
        params=[
            {"key": "model_type", "kind": "select", "label": "Model", "role": "model"},
            {"key": "x", "kind": "columns", "label": "Covariates (X)", "required": True, "role": "x"},
            {"key": "model_options", "kind": "json", "label": "Survival options", "value": {}},
        ],
    ))
    register_pack(AnalysisPack(pack_id="v186-survival-cox", model_handlers=[handler]))
