"""Shared contracts for the v1.8.6 predictive research foundation."""

from .contracts import (
    AvailabilitySpecV1,
    ContractError,
    FeatureRecipeV1,
    SampleSpecV1,
    SamplingSpecV1,
    SplitPlanV1,
    StructureSpecV1,
)
from .schema import PayloadContractError, PayloadSchemaRegistry
from .classification_contracts import (
    ClassificationClarificationV1,
    ClassificationTaskSpecV1,
    DecisionPolicyV1,
    FeatureAvailabilityContractV1,
    LabelDefinitionV1,
    StageCapabilityV1,
    build_classification_clarification,
)

__all__ = [
    "AvailabilitySpecV1",
    "ClassificationClarificationV1",
    "ClassificationTaskSpecV1",
    "ContractError",
    "DecisionPolicyV1",
    "FeatureAvailabilityContractV1",
    "FeatureRecipeV1",
    "LabelDefinitionV1",
    "PayloadContractError",
    "PayloadSchemaRegistry",
    "SampleSpecV1",
    "SamplingSpecV1",
    "SplitPlanV1",
    "StructureSpecV1",
    "StageCapabilityV1",
    "build_classification_clarification",
]
