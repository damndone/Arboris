"""Public declaration for the v1.8.1 ETS Model Pack.

Central loading stays Integration-owned: this module only exposes
`declare_pack()` for a thin `PackDeclaration` entry.
"""

from __future__ import annotations

from workbench.contracts.model.ets import ETS_CONTRACT_VERSION, ETS_MODEL_TYPE
from workbench.engine.capabilities import (
    CapabilityDeclaration,
    register_capability_declaration,
)
from workbench.engine.pack import AnalysisPack, register_pack
from workbench.engine.registry import ModelHandler
from workbench.model_options import ModelOptionsContract

from .input import ETSModelOptions
from .runner import MODEL_ID, fit_from_context


def declare_pack() -> None:
    """Register exactly one new handler and its selectable capability."""

    register_pack(
        AnalysisPack(
            pack_id=ETS_MODEL_TYPE,
            model_handlers=[
                ModelHandler(
                    model_type=ETS_MODEL_TYPE,
                    model_id=MODEL_ID,
                    serves_y_types=("continuous",),
                    fit=fit_from_context,
                    validate_model_options=ETSModelOptions.from_dict,
                    model_options_contract=ModelOptionsContract(
                        producer_version=f"{ETS_MODEL_TYPE}@{ETS_CONTRACT_VERSION}",
                        input_contract_version=ETS_CONTRACT_VERSION,
                    ),
                )
            ],
        )
    )
    register_capability_declaration(
        CapabilityDeclaration(
            model_type=ETS_MODEL_TYPE,
            label="ETS Exponential Smoothing",
            group="Time Series",
            description=(
                "Error/trend/seasonal exponential smoothing of the conditional "
                "mean, fitted by maximum likelihood on one evenly spaced series."
            ),
            requires=("time", "value"),
            params=(
                {
                    "key": "model_type",
                    "kind": "select",
                    "label": "Model",
                    "role": "model",
                },
                {
                    "key": "model_options",
                    "kind": "json",
                    "label": "ETS specification",
                    "required": True,
                    "role": "model_options",
                },
            ),
        )
    )


__all__ = ["declare_pack"]
