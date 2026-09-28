"""Shared contracts for the v1.8.6 foundation and v1.8.9 classification seam."""

from .contracts import (
    AvailabilitySpecV1,
    ContractError,
    FeatureRecipeV1,
    SampleSpecV1,
    SamplingSpecV1,
    SplitPlanV1,
    StructureSpecV1,
)
from .schema import (
    CLASSIFICATION_GRAPH_SCHEMA,
    CLASSIFICATION_PACKET_SCHEMA,
    PayloadContractError,
    PayloadSchemaRegistry,
    build_classification_packet,
    classification_content_hash,
    validate_classification_packet,
)


def __getattr__(name: str):
    """Load artifact-backed helpers lazily to keep ``artifacts`` acyclic.

    ``workbench.artifacts`` imports the packet schema registry.  Eagerly
    importing consumer/persistence/graph modules here would make those
    modules import ``workbench.artifacts`` while it is still initializing.
    The public names remain importable, but the dependency is resolved only
    when a caller asks for the helper.
    """

    if name in {"project_classification_evidence", "read_classification_evidence_from_run_root"}:
        from .consumer_projection import project_classification_evidence, read_classification_evidence_from_run_root

        return {
            "project_classification_evidence": project_classification_evidence,
            "read_classification_evidence_from_run_root": read_classification_evidence_from_run_root,
        }[name]
    if name in {"build_classification_graph", "persist_classification_graph"}:
        from .graph_persistence import build_classification_graph, persist_classification_graph

        return {"build_classification_graph": build_classification_graph, "persist_classification_graph": persist_classification_graph}[name]
    if name == "persist_classification_evidence_packet":
        from .persistence import persist_classification_evidence_packet

        return persist_classification_evidence_packet
    if name in {
        "ClassificationPreprocessingStepV1",
        "ClassificationDiagnosticsPlanV1",
        "ClassificationSplitProfileV1",
        "ClassificationSplitSpecV1",
        "ClassificationTaskSpecV1",
        "DecisionPolicyV1",
        "FeatureAvailabilityContractV1",
        "FeatureAvailabilityV1",
        "LabelDefinitionV1",
        "StageCapabilityV1",
        "validate_weight_support",
    }:
        from . import classification_contracts

        return getattr(classification_contracts, name)
    if name in {"ClassificationSplitManifestV1", "InformationIntervalV1", "build_classification_split_manifest"}:
        from . import split_kernel

        return getattr(split_kernel, name)
    if name in {"ClassificationFoldPreprocessingV1", "ClassificationFittedPreprocessorV1"}:
        from . import preprocessing

        return getattr(preprocessing, name)
    if name in {"adapter_registry", "get_classification_adapter"}:
        from . import classification_adapters

        return getattr(classification_adapters, name)
    if name in {"classification_metric_bundle", "compute_calibration_bins", "select_threshold_from_oof", "threshold_curve"}:
        from . import classification_metrics

        return getattr(classification_metrics, name)
    if name in {"HoldoutSealV1", "run_classification_protocol"}:
        from . import classification_protocol

        return getattr(classification_protocol, name)
    raise AttributeError(name)

__all__ = [
    "AvailabilitySpecV1",
    "CLASSIFICATION_GRAPH_SCHEMA",
    "CLASSIFICATION_PACKET_SCHEMA",
    "ContractError",
    "ClassificationFittedPreprocessorV1",
    "ClassificationFoldPreprocessingV1",
    "ClassificationPreprocessingStepV1",
    "ClassificationDiagnosticsPlanV1",
    "ClassificationSplitManifestV1",
    "ClassificationSplitProfileV1",
    "ClassificationSplitSpecV1",
    "ClassificationTaskSpecV1",
    "DecisionPolicyV1",
    "FeatureRecipeV1",
    "FeatureAvailabilityContractV1",
    "FeatureAvailabilityV1",
    "HoldoutSealV1",
    "InformationIntervalV1",
    "LabelDefinitionV1",
    "PayloadContractError",
    "PayloadSchemaRegistry",
    "build_classification_graph",
    "build_classification_packet",
    "classification_content_hash",
    "persist_classification_evidence_packet",
    "persist_classification_graph",
    "project_classification_evidence",
    "read_classification_evidence_from_run_root",
    "adapter_registry",
    "build_classification_split_manifest",
    "classification_metric_bundle",
    "compute_calibration_bins",
    "get_classification_adapter",
    "run_classification_protocol",
    "SampleSpecV1",
    "select_threshold_from_oof",
    "SamplingSpecV1",
    "StageCapabilityV1",
    "SplitPlanV1",
    "StructureSpecV1",
    "threshold_curve",
    "validate_weight_support",
    "validate_classification_packet",
]
