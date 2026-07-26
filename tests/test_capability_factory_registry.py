from __future__ import annotations

import importlib

import pytest

from workbench.capability_factory.contracts import ImplementationRevision


def _registry():
    try:
        return importlib.import_module("workbench.capability_factory.registry")
    except ModuleNotFoundError as error:
        pytest.fail(f"CF1 registry module is not implemented: {error}")


def _implementation(artifact_ref: str = "a" * 64):
    return ImplementationRevision(
        implementation_id="implementation.alpha",
        revision=1,
        profile_id="profile.alpha",
        profile_revision=1,
        profile_digest="c" * 64,
        input_schema_digest="d" * 64,
        source_kind="registered_third_party",
        trust_tier="registered_third_party",
        operations=("fit",),
        consumer_support={
            "report_projection": "report.v1",
            "diagnostic_adapter": None,
            "figure_provider": None,
            "compare_adapter": None,
        },
        artifact_ref=artifact_ref,
    )


def test_registry_is_content_addressed_and_duplicate_revision_cannot_be_replaced():
    registry_module = _registry()
    registry = registry_module.CapabilityRegistry()
    implementation = _implementation()

    first = registry.register(
        implementation,
        validity_refs={"implementation": "a" * 64},
    )
    second = registry.register(
        implementation,
        validity_refs={"implementation": "a" * 64},
    )

    assert first.implementation_ref == second.implementation_ref
    assert registry.get(first.implementation_ref) == implementation
    with pytest.raises(registry_module.RegistryError, match="immutable"):
        registry.register(
            _implementation("b" * 64),
            validity_refs={"implementation": "a" * 64},
        )


def test_untrusted_registration_cannot_self_declare_native_source():
    registry_module = _registry()
    registry = registry_module.CapabilityRegistry()
    native = ImplementationRevision(
        implementation_id="implementation.native-fake",
        revision=1,
        profile_id="profile.alpha",
        profile_revision=1,
        profile_digest="c" * 64,
        input_schema_digest="d" * 64,
        source_kind="native_pack",
        trust_tier="native_pack",
        operations=("fit",),
        consumer_support={
            "report_projection": "report.v1",
            "diagnostic_adapter": None,
            "figure_provider": None,
            "compare_adapter": None,
        },
        artifact_ref="c" * 64,
    )

    with pytest.raises(registry_module.RegistryError, match="trusted native"):
        registry.register(native, validity_refs={"implementation": "a" * 64})


def test_registry_returns_candidates_without_executing_or_mutating_implementations():
    registry_module = _registry()
    contracts = importlib.import_module("workbench.capability_factory.contracts")
    registry = registry_module.CapabilityRegistry()
    implementation = _implementation()
    registry.register(implementation, validity_refs={"implementation": "a" * 64})
    requirement = contracts.CapabilityRequirementRevision(
        requirement_id="requirement.alpha",
        revision=1,
        semantic_profile=contracts.SemanticProfile(
            profile_id="profile.alpha",
            revision=1,
            input_kinds=("scalar",),
            operations=("fit",),
            output_facets=("estimate",),
            assumptions=(),
            consumers={
                "report_projection": "report.v1",
                "diagnostic_adapter": None,
                "figure_provider": None,
                "compare_adapter": None,
            },
        ),
        requested_operations=("fit",),
        requested_consumers=("report_projection",),
        input_schema={"value": "scalar"},
    )

    candidates = registry.candidate_set(requirement)

    assert len(candidates.candidates) == 1
    assert candidates.candidates[0].implementation is implementation


def test_native_projector_exposes_read_only_registered_engine_handlers():
    import workbench.engine.stages.estimation  # noqa: F401

    native = importlib.import_module("workbench.capability_factory.native")

    projections = native.NativePackProjector().project()

    assert projections
    assert all(item.implementation.source_kind == "native_pack" for item in projections)
    assert len({item.implementation.implementation_id for item in projections}) == len(projections)
    assert all(item.implementation.consumer_support for item in projections)
