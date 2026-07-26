from __future__ import annotations

import pytest


def _adapter_and_bundle():
    from workbench.capability_factory.adapter_contract import AdapterContract
    from workbench.capability_factory.contracts import (
        CapabilityRequirementRevision,
        ImplementationRevision,
        SemanticProfile,
    )
    from workbench.capability_factory.validation_contract import (
        ValidationBundle,
        ValidationCase,
        ValidationEvidence,
    )

    profile = SemanticProfile(
        profile_id="profile.control",
        revision=1,
        input_kinds=("table",),
        operations=("fit",),
        output_facets=("parameters",),
        assumptions=(),
        consumers={
            "report_projection": "report.generic.v1",
            "diagnostic_adapter": None,
            "figure_provider": None,
            "compare_adapter": None,
        },
    )
    requirement = CapabilityRequirementRevision(
        requirement_id="requirement.control",
        revision=1,
        semantic_profile=profile,
        requested_operations=("fit",),
        requested_consumers=("report_projection",),
        input_schema={"value": "table"},
    )
    implementation = ImplementationRevision(
        implementation_id="implementation.control",
        revision=1,
        profile_id=profile.profile_id,
        profile_revision=profile.revision,
        profile_digest=profile.content_digest,
        input_schema_digest=requirement.input_schema_digest,
        source_kind="generated_adapter",
        trust_tier="generated_adapter",
        operations=("fit",),
        consumer_support={
            "report_projection": "report.generic.v1",
            "diagnostic_adapter": None,
            "figure_provider": None,
            "compare_adapter": None,
        },
        artifact_ref="a" * 64,
    )
    adapter = AdapterContract.from_implementation(
        implementation=implementation,
        adapter_id="adapter.control",
        revision=1,
        entrypoint_ref="b" * 64,
        operations=("fit",),
        consumer_support={
            "report_projection": "adapter.report.v1",
            "diagnostic_adapter": None,
            "figure_provider": None,
            "compare_adapter": None,
        },
    )
    case = ValidationCase(
        case_id="case.control.1",
        fixture_ref="c" * 64,
        fixture_visibility="author_visible",
    )
    bundle = ValidationBundle(
        bundle_id="bundle.control",
        revision=1,
        adapter_ref=adapter.content_digest,
        cases=(case,),
    ).append_evidence(
        ValidationEvidence(
            evidence_id="evidence.control.1",
            case_ref=case.content_digest,
            tier="E1",
            status="passed",
            observed_ref="d" * 64,
        )
    )
    return adapter, bundle


def test_adapter_proposal_is_high_risk_control_data_without_execution():
    from workbench.agent.adapter_control import AdapterProposalControl

    adapter, bundle = _adapter_and_bundle()
    proposal = AdapterProposalControl().create_proposal(
        adapter=adapter,
        validation_bundle=bundle,
        proposal_id="proposal.adapter.1",
    )

    assert proposal.status == "pending_confirmation"
    assert proposal.operation_id == "capability.adapter.propose"
    assert proposal.risk_level == "high"
    assert proposal.execution_allowed is False
    assert proposal.source_eligible is False
    with pytest.raises(ValueError):
        proposal.risk_binding()

    confirmed = AdapterProposalControl().confirm(
        proposal,
        confirmation_ref="e" * 64,
    )
    binding = confirmed.risk_binding()
    assert binding["adapter_ref"] == adapter.content_digest
    assert binding["validation_bundle_ref"] == bundle.content_digest


def test_adapter_proposal_lifecycle_reuses_existing_stores_and_stays_unregistered(
    tmp_path,
):
    from workbench.agent.adapter_control import AdapterProposalControl
    from workbench.agent.operations import OperationRegistry, UnknownOperationError

    control = AdapterProposalControl()
    adapter, bundle = _adapter_and_bundle()
    proposal = control.create_proposal(
        adapter=adapter,
        validation_bundle=bundle,
        proposal_id="proposal.adapter.durable",
    )
    revision = control.persist_proposal(
        proposal,
        root=tmp_path,
        session_id="session-adapter",
        chain_id="chain-adapter",
        active_head_run_id="run-1",
    )
    receipt = control.authorize_persisted_proposal(
        proposal,
        root=tmp_path,
        revision=revision.revision,
        fingerprint=revision.fingerprint,
        actor_type="human_ui",
        current_context_fingerprint=proposal.content_digest,
        current_active_head_run_id="run-1",
    )

    assert receipt.confirmation.status == "confirmed"
    assert receipt.risk_authorization.status == "issued"
    assert receipt.execution_allowed is False
    with pytest.raises(UnknownOperationError):
        OperationRegistry().require("capability.adapter.propose", "v1")


def test_adapter_proposal_rejects_a_bundle_for_another_adapter():
    from dataclasses import replace

    from workbench.agent.adapter_control import AdapterControlError, AdapterProposalControl

    adapter, bundle = _adapter_and_bundle()
    mismatched = replace(bundle, adapter_ref="f" * 64)
    with pytest.raises(AdapterControlError, match="adapter"):
        AdapterProposalControl().create_proposal(
            adapter=adapter,
            validation_bundle=mismatched,
            proposal_id="proposal.adapter.mismatch",
        )
