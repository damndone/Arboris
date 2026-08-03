from __future__ import annotations

from ...capabilities import CapabilityDeclaration, register_capability_declaration
from ...pack import AnalysisPack, register_pack
from .runtime import model_handlers


def declare_pack() -> None:
    handler = model_handlers()["quantile_regression"]
    register_capability_declaration(CapabilityDeclaration(
        model_type="quantile_regression",
        label="Quantile regression",
        group="Robust / distributional",
        description="Multiple conditional quantiles with confidence intervals, optional bootstrap intervals, and cross-quantile comparisons.",
        requires=("continuous_outcome",),
        params=[
            {"key": "model_type", "kind": "select", "label": "Model", "role": "model"},
            {"key": "x", "kind": "columns", "label": "Regressors (X)", "required": True, "role": "x"},
            {"key": "model_options", "kind": "json", "label": "Quantile options", "value": {"quantiles": [0.25, 0.5, 0.75]}},
        ],
    ))
    register_pack(AnalysisPack(pack_id="v186-quantile-regression", model_handlers=[handler]))
