"""Explicit engine declaration for the linear mixed-effects pack."""

from __future__ import annotations

from workbench.contracts.model.linear_mixed_effects import (
    LMM_CONTRACT_VERSION,
    LMM_MODEL_TYPE,
    LmmModelInput,
)
from workbench.engine.pack import AnalysisPack, register_pack
from workbench.engine.capabilities import CapabilityDeclaration, register_capability_declaration
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
    register_capability_declaration(
        CapabilityDeclaration(
            model_type=LMM_MODEL_TYPE,
            label="Linear Mixed Effects",
            group="Panel",
            description="Repeated-measures linear mixed model with explicit subject, time, and group roles.",
            requires=("subject", "time", "group"),
            # v1.8.7. This was `()`, and an empty parameter list is what made
            # LMM an island: the form drove it through hard-coded controls, a
            # rerun rejected every field as unknown, and no Agent could name it.
            # The five inputs travel in `model_options`, which is where the LMM
            # contract has always read them -- declaring them here changes no
            # execution path, only who can see them.
            params=(
                {"key": "model_type", "kind": "select", "label": "Model", "role": "model"},
                {
                    "key": "x",
                    "kind": "columns",
                    "label": "Regressors (X)",
                    "required": False,
                    "role": "x",
                },
                {
                    "key": "model_options",
                    "kind": "json",
                    "label": "Repeated-measures options",
                    "required": True,
                    "role": "model_options",
                    "options": [
                        "subject_id", "time", "group", "fit_method", "random_slope",
                    ],
                    "value": {},
                },
            ),
        )
    )
