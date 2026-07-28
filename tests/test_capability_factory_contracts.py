from __future__ import annotations

import importlib
import importlib.util
from dataclasses import FrozenInstanceError

import pytest


def _contracts():
    try:
        spec = importlib.util.find_spec("workbench.capability_factory.contracts")
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, "CF1 contracts module is not implemented"
    return importlib.import_module("workbench.capability_factory.contracts")


def test_requirement_is_immutable_and_digest_is_stable_for_mapping_order():
    contracts = _contracts()
    first = contracts.CapabilityRequirementRevision(
        requirement_id="requirement.alpha",
        revision=1,
        semantic_profile=contracts.SemanticProfile(
            profile_id="profile.alpha",
            revision=1,
            input_kinds=("scalar", "group"),
            operations=("fit", "summarize"),
            output_facets=("estimate", "diagnostic"),
            assumptions=("finite_inputs",),
            consumers={
                "report_projection": "report.v1",
                "diagnostic_adapter": None,
                "figure_provider": None,
                "compare_adapter": None,
            },
        ),
        requested_operations=("fit", "summarize"),
        requested_consumers=("report_projection",),
        input_schema={"value": "scalar", "group": "group"},
    )
    second = contracts.CapabilityRequirementRevision(
        requirement_id="requirement.alpha",
        revision=1,
        semantic_profile=first.semantic_profile,
        requested_operations=("fit", "summarize"),
        requested_consumers=("report_projection",),
        input_schema={"group": "group", "value": "scalar"},
    )

    assert first.content_digest == second.content_digest
    with pytest.raises(FrozenInstanceError):
        first.revision = 2
    with pytest.raises(TypeError):
        first.input_schema["new"] = "value"


def test_semantic_profile_rejects_unknown_consumer_and_unbounded_identifier():
    contracts = _contracts()
    with pytest.raises(contracts.ContractError, match="consumer"):
        contracts.SemanticProfile(
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
                "compare_adapter": "compare.v1",
                "made_up_consumer": "v1",
            },
        )

    with pytest.raises(contracts.ContractError, match="bounded"):
        contracts.SemanticProfile(
            profile_id="x" * 257,
            revision=1,
            input_kinds=("scalar",),
            operations=("fit",),
            output_facets=("estimate",),
            assumptions=(),
            consumers={},
        )


def test_implementation_requires_explicit_consumer_projection():
    contracts = _contracts()
    implementation = contracts.ImplementationRevision(
        implementation_id="implementation.alpha",
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
        artifact_ref="a" * 64,
    )
    assert implementation.consumer_support["diagnostic_adapter"] is None
    with pytest.raises(contracts.ContractError, match="consumer_support"):
        contracts.ImplementationRevision(
            implementation_id="implementation.beta",
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
            },
            artifact_ref="b" * 64,
        )


def test_resolution_policy_cannot_reorder_the_fixed_trust_ladder():
    contracts = _contracts()
    with pytest.raises(contracts.ContractError, match="fixed trust order"):
        contracts.ResolutionPolicySnapshot(
            policy_id="policy.alpha",
            revision=1,
            trust_order=(
                "authored_implementation",
                "native_pack",
                "registered_third_party",
                "generated_adapter",
            ),
            required_validity_domains=("implementation",),
        )
