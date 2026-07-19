"""Explicit engine declaration for the linear mixed-effects pack."""

from __future__ import annotations

from workbench.contracts.model.linear_mixed_effects import (
    LMM_CONTRACT_VERSION,
    LMM_MODEL_TYPE,
    LmmModelInput,
)
from workbench.engine.pack import AnalysisPack, register_pack
from workbench.engine.registry import ModelHandler
from workbench.model_options import ModelOptionsContract

from .runner import fit_from_context


def declare_pack() -> None:
    """Register only the LMM handler; central loading remains Integration-owned."""

    register_pack(
        AnalysisPack(
            pack_id=LMM_MODEL_TYPE,
            model_handlers=[
                ModelHandler(
                    model_type=LMM_MODEL_TYPE,
                    model_id="linear_mixed_effects_1",
                    serves_y_types=("continuous",),
                    fit=fit_from_context,
                    validate_model_options=LmmModelInput.from_dict,
                    model_options_contract=ModelOptionsContract(
                        producer_version="linear_mixed_effects@1.0",
                        input_contract_version=LMM_CONTRACT_VERSION,
                    ),
                )
            ],
        )
    )
