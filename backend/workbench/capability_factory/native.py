"""Read-only projection of registered native Analysis Pack handlers."""

from __future__ import annotations

from dataclasses import dataclass

from ..custom_capability.canonical import domain_digest
from ..engine.registry import MODEL_REGISTRY
from .contracts import ImplementationRevision, SemanticProfile


@dataclass(frozen=True, slots=True)
class NativePackProjection:
    profile: SemanticProfile
    implementation: ImplementationRevision


class NativePackProjector:
    """Derive CF1 records from engine registry truth without copying handlers."""

    def project(self) -> tuple[NativePackProjection, ...]:
        result: list[NativePackProjection] = []
        for model_type, handler in sorted(MODEL_REGISTRY.items()):
            profile_id = f"engine.{model_type}"
            profile = SemanticProfile(
                profile_id=profile_id,
                revision=1,
                input_kinds=handler.serves_y_types or ("unspecified",),
                operations=("fit",),
                output_facets=("primary_result",),
                assumptions=(),
                consumers={
                    "report_projection": None,
                    "diagnostic_adapter": None,
                    "figure_provider": None,
                    "compare_adapter": None,
                },
            )
            artifact_ref = domain_digest(
                "workbench.capability_factory.native_pack/v1",
                {"model_type": model_type, "model_id": handler.model_id},
            )
            implementation = ImplementationRevision(
                implementation_id=f"native.{model_type}",
                revision=1,
                profile_id=profile_id,
                profile_revision=profile.revision,
                profile_digest=profile.content_digest,
                input_schema_digest=domain_digest(
                    "workbench.capability_factory.input_schema/v1",
                    {"input_kinds": list(profile.input_kinds)},
                ),
                source_kind="native_pack",
                trust_tier="native_pack",
                operations=("fit",),
                consumer_support=dict(profile.consumers),
                artifact_ref=artifact_ref,
            )
            result.append(NativePackProjection(profile=profile, implementation=implementation))
        return tuple(result)


__all__ = ["NativePackProjection", "NativePackProjector"]
