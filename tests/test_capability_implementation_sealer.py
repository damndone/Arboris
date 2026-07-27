from __future__ import annotations

from dataclasses import replace

import pytest


def _implementation():
    from workbench.capability_factory.contracts import ImplementationRevision

    return ImplementationRevision(
        implementation_id="implementation.alpha",
        revision=1,
        profile_id="profile.alpha",
        profile_revision=1,
        profile_digest="a" * 64,
        input_schema_digest="b" * 64,
        source_kind="authored_implementation",
        trust_tier="authored_implementation",
        operations=("fit",),
        consumer_support={
            "report_projection": None,
            "diagnostic_adapter": None,
            "figure_provider": None,
            "compare_adapter": None,
        },
        artifact_ref="c" * 64,
    )


def test_sealer_binds_exact_adapter_candidate_and_runtime_refs():
    from workbench.capability_factory.adapter_contract import AdapterContract
    from workbench.capability_factory.candidate_store import CapabilityCandidate
    from workbench.capability_factory.implementation_sealer import ImplementationSealer

    implementation = _implementation()
    adapter = AdapterContract.from_implementation(
        implementation=implementation,
        adapter_id="adapter.alpha",
        revision=1,
        entrypoint_ref="d" * 64,
        operations=("fit",),
        consumer_support={
            "report_projection": None,
            "diagnostic_adapter": None,
            "figure_provider": None,
            "compare_adapter": None,
        },
    )
    candidate = CapabilityCandidate(
        candidate_id="candidate.alpha",
        capability_kind="model",
        source_kind="authored_implementation",
        implementation_ref=implementation.content_digest,
        source_ref="e" * 64,
        author_lineage_ref="f" * 64,
        risk_level="high",
    )
    sealed = ImplementationSealer().seal(
        candidate=candidate,
        adapter=adapter,
        dependency_bundle_ref="1" * 64,
        runtime_policy_ref="2" * 64,
        environment_ref="3" * 64,
        source_ref="4" * 64,
        code_ref="5" * 64,
        manifest_ref="6" * 64,
    )
    assert sealed.adapter_ref == adapter.content_digest
    assert sealed.candidate_ref == candidate.content_digest
    assert sealed.bundle_ref == sealed.content_digest


def test_sealer_rejects_adapter_from_another_implementation():
    from workbench.capability_factory.adapter_contract import AdapterContract
    from workbench.capability_factory.candidate_store import CapabilityCandidate
    from workbench.capability_factory.implementation_sealer import ImplementationSealer, SealingError

    implementation = _implementation()
    other = replace(implementation, implementation_id="implementation.other", artifact_ref="7" * 64)
    adapter = AdapterContract.from_implementation(
        implementation=other,
        adapter_id="adapter.other",
        revision=1,
        entrypoint_ref="8" * 64,
        operations=("fit",),
        consumer_support={
            "report_projection": None,
            "diagnostic_adapter": None,
            "figure_provider": None,
            "compare_adapter": None,
        },
    )
    candidate = CapabilityCandidate(
        candidate_id="candidate.alpha",
        capability_kind="model",
        source_kind="authored_implementation",
        implementation_ref=implementation.content_digest,
        source_ref="9" * 64,
        author_lineage_ref="a" * 64,
        risk_level="high",
    )
    with pytest.raises(SealingError, match="implementation"):
        ImplementationSealer().seal(
            candidate=candidate,
            adapter=adapter,
            dependency_bundle_ref="1" * 64,
            runtime_policy_ref="2" * 64,
            environment_ref="3" * 64,
            source_ref="4" * 64,
            code_ref="5" * 64,
            manifest_ref="6" * 64,
        )
