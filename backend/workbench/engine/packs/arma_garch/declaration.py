"""Public declaration for the v1.8 ARMA-GARCH Model Pack."""

from __future__ import annotations

from typing import get_args, get_type_hints

from workbench.contracts.model.arma_garch import (
    ARMA_GARCH_CONTRACT_VERSION,
    ARMA_GARCH_PACK_ID,
    ArmaGarchAnalysisContract,
    ValidationOptions,
    normalize_arma_garch_model_options,
)
from workbench.engine.capabilities import (
    CapabilityDeclaration,
    register_capability_declaration,
)
from workbench.engine.pack import AnalysisPack, register_pack
from workbench.engine.registry import ModelHandler
from workbench.model_options import ModelOptionsContract

from .runner import fit_from_context


def declare_pack() -> None:
    """Register one public handler and its selectable capability metadata."""

    register_pack(
        AnalysisPack(
            pack_id=ARMA_GARCH_PACK_ID,
            model_handlers=[
                ModelHandler(
                    model_type=ARMA_GARCH_PACK_ID,
                    model_id="arma_garch_1",
                    serves_y_types=("continuous",),
                    fit=fit_from_context,
                    validate_model_options=ArmaGarchAnalysisContract.from_dict,
                    model_options_contract=ModelOptionsContract(
                        producer_version="time_series.arma_garch@1.0",
                        input_contract_version=ARMA_GARCH_CONTRACT_VERSION,
                        normalize_payload=normalize_arma_garch_model_options,
                    ),
                )
            ],
        )
    )
    register_capability_declaration(
        CapabilityDeclaration(
            model_type=ARMA_GARCH_PACK_ID,
            label="ARMA-GARCH Volatility Workbench",
            group="Time Series",
            description=(
                "One-series ARMA mean and ARCH/GARCH volatility analysis with "
                "a confirmed transform, train/validation or classical full-sample replication, and prefix-only rolling forecasts."
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
                    "label": "ARMA-GARCH analysis contract",
                    "required": True,
                    "role": "model_options",
                    "evaluation_modes": list(get_args(get_type_hints(ValidationOptions)["evaluation_mode"])),
                },
            ),
        )
    )


__all__ = ["declare_pack"]
