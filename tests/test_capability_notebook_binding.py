from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from test_capability_admission_contract import _adapter, _bundle


def _validity():
    from workbench.capability_factory.freshness import ValidityCursor, ValidityCursorSnapshot

    return ValidityCursorSnapshot(
        cursors={
            "registry": ValidityCursor(
                domain="registry",
                sequence=1,
                state_digest="a" * 64,
                authority_ref="b" * 64,
                valid_until=datetime(2030, 1, 1, tzinfo=timezone.utc),
            )
        },
        observed_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
    )


def _resolution(adapter, current_validity=None):
    from workbench.capability_factory.contracts import ResolutionBinding

    current_validity = current_validity or _validity()
    return ResolutionBinding(
        requirement_digest="1" * 64,
        policy_digest="2" * 64,
        candidate_set_digest="3" * 64,
        selection_digest="4" * 64,
        implementation_ref=adapter.implementation_ref,
        validity_cursor_digest=current_validity.content_digest,
    )


def _admitted_records():
    from workbench.capability_factory.admission_contract import CapabilityAdmissionController

    adapter = _adapter()
    bundle = _bundle(adapter, independent=True, case_count=2)
    controller = CapabilityAdmissionController()
    assessment = controller.assess(
        adapter=adapter,
        validation_bundle=bundle,
        assessment_id="assessment.binding",
        assessment_rule_ref="6" * 64,
    )
    proposed = controller.propose(
        adapter=adapter,
        validation_bundle=bundle,
        assessment=assessment,
        admission_id="admission.binding",
        runtime_policy_ref="7" * 64,
        scope_kind="project",
        scope_ref="project.alpha",
        minimum_evidence_tier="E2",
        allowed_operations=("fit",),
        allowed_consumers=("report_projection",),
    )
    admitted = controller.admit(
        proposed.admission_id,
        approver_ref="human_ui",
        approval_ref="8" * 64,
    )
    return controller, adapter, bundle, assessment, admitted


def test_resolution_binding_pins_resolution_adapter_evidence_admission_and_policy():
    from workbench.capability_factory.notebook_binding import CapabilityResolutionBinding

    controller, adapter, bundle, assessment, admission = _admitted_records()
    current_validity = _validity()
    binding = CapabilityResolutionBinding.from_records(
        admission_controller=controller,
        resolution_binding=_resolution(adapter, current_validity),
        adapter=adapter,
        validation_bundle=bundle,
        assessment=assessment,
        admission=admission,
        current_validity=current_validity,
    )

    assert binding.resolution_binding_ref == _resolution(adapter, current_validity).content_digest
    assert binding.implementation_ref == adapter.implementation_ref
    assert binding.adapter_ref == adapter.content_digest
    assert binding.validation_bundle_ref == bundle.content_digest
    assert binding.assessment_ref == assessment.content_digest
    assert binding.admission_ref == admission.content_digest
    assert binding.runtime_policy_ref == admission.runtime_policy_ref
    assert binding.execution_allowed is False


def test_resolution_binding_freshness_verifier_rejects_revoked_current_admission():
    from workbench.capability_factory.notebook_binding import CapabilityResolutionBinding

    controller, adapter, bundle, assessment, admission = _admitted_records()
    current_validity = _validity()
    binding = CapabilityResolutionBinding.from_records(
        admission_controller=controller,
        resolution_binding=_resolution(adapter, current_validity),
        adapter=adapter,
        validation_bundle=bundle,
        assessment=assessment,
        admission=admission,
        current_validity=current_validity,
    )
    binding.assert_current(
        admission_controller=controller,
        adapter=adapter,
        validation_bundle=bundle,
        assessment=assessment,
        current_validity=current_validity,
        runtime_policy_ref="7" * 64,
        scope_kind="project",
        scope_ref="project.alpha",
    )
    with pytest.raises(ValueError, match="validity cursor"):
        binding.assert_current(
            admission_controller=controller,
            adapter=adapter,
            validation_bundle=bundle,
            assessment=assessment,
            current_validity=replace(
                current_validity,
                observed_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
            ),
            runtime_policy_ref="7" * 64,
            scope_kind="project",
            scope_ref="project.alpha",
        )
    controller.expire(admission.admission_id, reason_ref="9" * 64)
    with pytest.raises(ValueError, match="current"):
        binding.assert_current(
            admission_controller=controller,
            adapter=adapter,
            validation_bundle=bundle,
            assessment=assessment,
            current_validity=current_validity,
            runtime_policy_ref="7" * 64,
            scope_kind="project",
            scope_ref="project.alpha",
        )


def test_resolution_binding_rejects_unadmitted_or_mismatched_records():
    from workbench.capability_factory.notebook_binding import CapabilityResolutionBinding

    controller, adapter, bundle, assessment, admission = _admitted_records()
    current_validity = _validity()
    resolution = _resolution(adapter, current_validity)
    with pytest.raises(ValueError, match="admitted"):
        CapabilityResolutionBinding.from_records(
            admission_controller=controller,
            resolution_binding=resolution,
            adapter=adapter,
            validation_bundle=bundle,
            assessment=assessment,
            admission=replace(admission, status="expired", approver_ref=None, approval_ref=None, reason_ref="9" * 64),
            current_validity=current_validity,
        )

    with pytest.raises(ValueError, match="implementation"):
        CapabilityResolutionBinding.from_records(
            admission_controller=controller,
            resolution_binding=replace(resolution, implementation_ref="a" * 64),
            adapter=adapter,
            validation_bundle=bundle,
            assessment=assessment,
            admission=admission,
            current_validity=current_validity,
        )

    with pytest.raises(ValueError, match="current"):
        forged_admission = replace(admission, approval_ref="9" * 64)
        CapabilityResolutionBinding.from_records(
            admission_controller=controller,
            resolution_binding=resolution,
            adapter=adapter,
            validation_bundle=bundle,
            assessment=assessment,
            admission=forged_admission,
            current_validity=current_validity,
        )

    experimental_bundle = _bundle(adapter, independent=False)
    experimental = controller.assess(
        adapter=adapter,
        validation_bundle=experimental_bundle,
        assessment_id="assessment.binding.experimental",
        assessment_rule_ref="a" * 64,
    )
    forged = replace(
        admission,
        validation_bundle_ref=experimental_bundle.content_digest,
        assessment_ref=experimental.content_digest,
        minimum_evidence_tier="E2",
    )
    controller._admissions[admission.admission_id][-1] = forged
    with pytest.raises(ValueError, match="evidence tier"):
        CapabilityResolutionBinding.from_records(
            admission_controller=controller,
            resolution_binding=resolution,
            adapter=adapter,
            validation_bundle=experimental_bundle,
            assessment=experimental,
            admission=forged,
            current_validity=current_validity,
        )

def test_notebook_option_v12_round_trips_and_only_exposes_materialize_only():
    from workbench.capability_factory.notebook_binding import CapabilityResolutionBinding
    from workbench.contracts.agent.notebook_option import (
        ArtifactContract,
        ExpectedArtifact,
        NotebookOptionRevision,
        NotebookOptionRevisionV12,
    )

    controller, adapter, bundle, assessment, admission = _admitted_records()
    current_validity = _validity()
    binding = CapabilityResolutionBinding.from_records(
        admission_controller=controller,
        resolution_binding=_resolution(adapter, current_validity),
        adapter=adapter,
        validation_bundle=bundle,
        assessment=assessment,
        admission=admission,
        current_validity=current_validity,
    )
    option = NotebookOptionRevisionV12(
        option_id="option.custom.1",
        option_revision=1,
        notebook_id="notebook.1",
        run_family_id="run-family:1",
        generation_context_id="context.1",
        generation_context_hash="sha256:" + "a" * 64,
        freshness_dependency_fingerprint="fresh1:" + "b" * 64,
        typed_proposal_id="proposal.custom.1",
        typed_proposal_revision=1,
        artifact_contract=ArtifactContract(
            expected=(ExpectedArtifact("artifact.custom", "custom_json"),)
        ),
        rationale="typed capability proposal",
        assumptions=("input contract is satisfied",),
        risk_level="medium",
        lifecycle_status="proposed",
        freshness_status="fresh",
        validation_status="valid",
        rank=1,
        batch_id="batch.custom.1",
        created_at="2026-07-26T15:00:00Z",
        evidence_refs=(),
        comparative_claims=(),
        recommendation_decision_id="recommendation.custom.1",
        recommendation_status="insufficient_evidence",
        capability_resolution_binding_ref=binding.content_digest,
        execution_modes=("materialize_only",),
    )

    payload = option.to_dict()
    assert payload["contract_version"] == "1.2"
    assert NotebookOptionRevision.from_dict(payload) == option
    assert option.execution_allowed is False

    with pytest.raises(ValueError, match="execution_modes"):
        replace(option, execution_modes=("confirm_and_execute",))


def test_notebook_option_v11_fixture_still_uses_the_legacy_contract():
    import json
    from pathlib import Path

    from workbench.contracts.agent.notebook_option import (
        NotebookOptionRevision,
        NotebookOptionRevisionV11,
    )

    fixture = Path("tests/fixtures/contracts/v181/notebook_option_revision_v11.json")
    parsed = NotebookOptionRevision.from_dict(json.loads(fixture.read_text()))
    assert isinstance(parsed, NotebookOptionRevisionV11)
    assert parsed.contract_version == "1.1"
