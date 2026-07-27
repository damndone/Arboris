from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest


def _implementation():
    from workbench.capability_factory.contracts import (
        CapabilityRequirementRevision,
        ImplementationRevision,
        SemanticProfile,
    )

    profile = SemanticProfile(
        profile_id="profile.generic",
        revision=1,
        input_kinds=("table", "numeric"),
        operations=("fit", "predict", "summarize"),
        output_facets=("parameters", "uncertainty", "predictions"),
        assumptions=("finite_inputs",),
        consumers={
            "report_projection": "report.generic.v1",
            "diagnostic_adapter": "diagnostic.generic.v1",
            "figure_provider": None,
            "compare_adapter": None,
        },
    )
    requirement = CapabilityRequirementRevision(
        requirement_id="requirement.generic",
        revision=1,
        semantic_profile=profile,
        requested_operations=("fit", "summarize"),
        requested_consumers=("report_projection",),
        input_schema={"response": "numeric", "features": "table"},
    )
    return ImplementationRevision(
        implementation_id="implementation.generic",
        revision=1,
        profile_id=profile.profile_id,
        profile_revision=profile.revision,
        profile_digest=profile.content_digest,
        input_schema_digest=requirement.input_schema_digest,
        source_kind="generated_adapter",
        trust_tier="generated_adapter",
        operations=("fit", "predict", "summarize"),
        consumer_support={
            "report_projection": "report.generic.v1",
            "diagnostic_adapter": "diagnostic.generic.v1",
            "figure_provider": None,
            "compare_adapter": None,
        },
        artifact_ref="a" * 64,
    )


def _consumer_support():
    return {
        "report_projection": "adapter.report.v1",
        "diagnostic_adapter": None,
        "figure_provider": None,
        "compare_adapter": None,
    }


def test_adapter_contract_binds_profile_schema_operations_and_consumers_explicitly():
    from workbench.capability_factory.adapter_contract import AdapterContract

    implementation = _implementation()
    adapter = AdapterContract.from_implementation(
        implementation=implementation,
        adapter_id="adapter.generic",
        revision=1,
        entrypoint_ref="b" * 64,
        operations=("fit", "summarize"),
        consumer_support=_consumer_support(),
    )

    assert adapter.implementation_ref == implementation.content_digest
    assert adapter.profile_digest == implementation.profile_digest
    assert adapter.input_schema_digest == implementation.input_schema_digest
    assert adapter.operations == ("fit", "summarize")
    assert adapter.consumer_support["diagnostic_adapter"] is None
    adapter.validate_against(implementation)
    with pytest.raises(FrozenInstanceError):
        adapter.revision = 2


def test_adapter_contract_rejects_mismatched_bindings_and_missing_consumer_slots():
    from workbench.capability_factory.adapter_contract import AdapterContract, AdapterContractError

    implementation = _implementation()
    with pytest.raises(AdapterContractError, match="profile"):
        AdapterContract(
            adapter_id="adapter.generic",
            revision=1,
            implementation_ref=implementation.content_digest,
            profile_id="profile.other",
            profile_revision=implementation.profile_revision,
            profile_digest=implementation.profile_digest,
            input_schema_digest=implementation.input_schema_digest,
            source_kind=implementation.source_kind,
            trust_tier=implementation.trust_tier,
            operations=("fit",),
            consumer_support=_consumer_support(),
            entrypoint_ref="b" * 64,
        ).validate_against(implementation)

    with pytest.raises(AdapterContractError, match="consumer_support"):
        AdapterContract.from_implementation(
            implementation=implementation,
            adapter_id="adapter.incomplete",
            revision=1,
            entrypoint_ref="b" * 64,
            operations=("fit",),
            consumer_support={
                "report_projection": "adapter.report.v1",
                "diagnostic_adapter": None,
                "figure_provider": None,
            },
        )


def test_adapter_contract_cannot_claim_an_undeclared_operation_or_consumer():
    from workbench.capability_factory.adapter_contract import AdapterContract, AdapterContractError

    implementation = _implementation()
    with pytest.raises(AdapterContractError, match="operations"):
        AdapterContract.from_implementation(
            implementation=implementation,
            adapter_id="adapter.invalid-operation",
            revision=1,
            entrypoint_ref="b" * 64,
            operations=("fit", "diagnose"),
            consumer_support=_consumer_support(),
        )

    unsupported = dict(_consumer_support())
    unsupported["figure_provider"] = "adapter.figure.v1"
    implementation_without_figure = _implementation()
    with pytest.raises(AdapterContractError, match="figure_provider"):
        AdapterContract.from_implementation(
            implementation=implementation_without_figure,
            adapter_id="adapter.invalid-consumer",
            revision=1,
            entrypoint_ref="b" * 64,
            operations=("fit",),
            consumer_support=unsupported,
        )


def test_adapter_candidate_factory_emits_typed_candidate_and_empty_validation_bundle(tmp_path):
    from workbench.capability_factory.adapter_contract import (
        AdapterCandidateFactory,
        AdapterSourceGenerator,
    )
    from workbench.capability_factory.validation_contract import ValidationCase

    implementation = _implementation()
    source = AdapterSourceGenerator().generate(
        implementation=implementation,
        provider=lambda _context: "def adapter():\n    return None\n",
        output_root=tmp_path / "source",
    )
    generated = AdapterCandidateFactory().generate(
        implementation=implementation,
        adapter_id="adapter.generated",
        adapter_revision=1,
        entrypoint_ref=source.entrypoint_ref,
        operations=("fit", "summarize"),
        consumer_support=_consumer_support(),
        candidate_id="candidate.generated",
        capability_kind="model",
        source_ref=source.source_ref,
        author_lineage_ref="d" * 64,
        validation_bundle_id="validation.generated",
        validation_cases=(
            ValidationCase(
                case_id="case.generated.1",
                fixture_ref="e" * 64,
                fixture_visibility="author_visible",
            ),
        ),
        source_artifact=source,
    )

    assert generated.candidate.source_kind == "generated_adapter"
    assert generated.candidate.status == "submitted"
    assert generated.validation_bundle.evidence == ()
    assert generated.validation_bundle.adapter_ref == generated.adapter.content_digest


def test_adapter_candidate_factory_rejects_a_fabricated_source_reference():
    from workbench.capability_factory.adapter_contract import AdapterCandidateFactory, AdapterContractError
    from workbench.capability_factory.validation_contract import ValidationCase

    implementation = _implementation()
    with pytest.raises(AdapterContractError, match="source_artifact is required"):
        AdapterCandidateFactory().generate(
            implementation=implementation,
            adapter_id="adapter.unbound-source",
            adapter_revision=1,
            entrypoint_ref="b" * 64,
            operations=("fit",),
            consumer_support=_consumer_support(),
            candidate_id="candidate.unbound-source",
            capability_kind="model",
            source_ref="c" * 64,
            author_lineage_ref="d" * 64,
            validation_bundle_id="validation.unbound-source",
            validation_cases=(
                ValidationCase(
                    case_id="case.unbound-source",
                    fixture_ref="e" * 64,
                    fixture_visibility="author_visible",
                ),
            ),
        )


def test_adapter_candidate_factory_binds_generated_source_and_entrypoint(tmp_path):
    from workbench.capability_factory.adapter_contract import (
        AdapterCandidateFactory,
        AdapterSourceGenerator,
    )

    from workbench.capability_factory.validation_contract import ValidationCase

    implementation = _implementation()
    source = AdapterSourceGenerator().generate(
        implementation=implementation,
        provider=lambda _context: "def adapter():\n    return None\n",
        output_root=tmp_path / "source",
    )
    cases = (
        ValidationCase(
            case_id="case.bound-source",
            fixture_ref="8" * 64,
            fixture_visibility="author_visible",
        ),
    )
    generated = AdapterCandidateFactory().generate(
        implementation=implementation,
        adapter_id="adapter.bound-source",
        adapter_revision=1,
        entrypoint_ref=source.entrypoint_ref,
        operations=("fit",),
        consumer_support=_consumer_support(),
        candidate_id="candidate.bound-source",
        capability_kind="custom.model",
        source_ref=source.source_ref,
        author_lineage_ref="9" * 64,
        validation_bundle_id="validation.bound-source",
        validation_cases=cases,
        source_artifact=source,
    )

    assert generated.candidate.source_ref == source.source_ref
    assert generated.adapter.entrypoint_ref == source.entrypoint_ref
    assert generated.execution_allowed is False


def test_adapter_source_generator_stores_bounded_agent_output_without_executing_it(tmp_path):
    from workbench.capability_factory.adapter_contract import AdapterSourceGenerator

    implementation = _implementation()
    seen = []

    def provider(context):
        seen.append(context)
        return "def fit(input_bundle, parameters):\n    return None\n"

    artifact = AdapterSourceGenerator().generate(
        implementation=implementation,
        provider=provider,
        output_root=tmp_path,
    )

    assert artifact.path.read_text(encoding="utf-8").startswith("def fit")
    assert artifact.path.name == f"{artifact.source_ref}.py"
    assert artifact.source_ref != artifact.entrypoint_ref
    assert seen == [
        {
            "profile_ref": implementation.profile_digest,
            "input_schema_ref": implementation.input_schema_digest,
            "operations": list(implementation.operations),
            "implementation_ref": implementation.content_digest,
        }
    ]
