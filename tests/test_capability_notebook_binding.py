from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from test_capability_admission_contract import _adapter, _bundle
from tests.test_notebook_support import make_project


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
        allowed_consumers=("report_projection", "notebook_option_planner"),
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

def test_notebook_option_v12_round_trips_and_keeps_execution_grant_closed():
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

    confirmable = replace(
        option,
        execution_modes=("materialize_only", "confirm_and_execute"),
    )
    assert NotebookOptionRevision.from_dict(confirmable.to_dict()) == confirmable
    assert confirmable.execution_allowed is False

    with pytest.raises(ValueError, match="execution_modes"):
        replace(option, execution_modes=("confirm_and_execute",))


def _exploration_draft(
    *,
    capability_id: str,
    option_id: str = "opt_exploration",
    proposal_id: str = "proposal_exploration",
    decision_id: str = "rec_exploration",
):
    from workbench.agent.notebook import OptionDraft, TypedProposal
    from workbench.contracts.agent.notebook_option import ExpectedArtifact

    return OptionDraft(
        rank=1,
        rationale="read-only exploration is explicitly user-confirmable",
        assumptions=("the current source remains unchanged",),
        proposal=TypedProposal.from_dict(
            {
                "proposal_id": proposal_id,
                "proposal_revision": 1,
                "operation_id": "statistical.explore",
                "operation_version": "v1",
                "target": {
                    "run_id": "run.exploration",
                    "node_ref": "node.source",
                    "artifact_id": "artifact.raw",
                    "workflow_id": "workflow.exploration",
                    "step_id": "step.summary",
                },
                "preconditions": {
                    "source_fingerprint": "source-fingerprint",
                    "dependency_fingerprints": [],
                },
                "changes": {"operation": "summarize"},
                "evidence_refs": [],
                "expected_effect": ["read-only summary"],
                "risks": [],
            }
        ),
        expected_artifacts=(
            ExpectedArtifact(
                artifact_id="ts.parameters",
                artifact_type="time_series_json",
                required=True,
                count=1,
            ),
        ),
        option_id=option_id,
        capability_id=capability_id,
        recommendation_decision_id=decision_id,
        recommendation_status="recommended",
    )


def _execution_authorization_for(revision, binding, *, notebook_id: str):
    from workbench.capability_factory.execution_authorization import (
        OptionExecutionAuthorization,
    )
    from workbench.custom_capability.canonical import domain_digest

    now = datetime.now(timezone.utc)
    return OptionExecutionAuthorization(
        authorization_id="auth_exploration_1",
        notebook_id=notebook_id,
        option_id=revision.option_id,
        option_revision=revision.option_revision,
        binding_revision=1,
        capability_resolution_binding_ref=binding.content_digest,
        materialization_id="materialization_exploration_1",
        draft_id="draft_exploration_1",
        draft_hash="sha256:" + "d" * 64,
        run_intent_id="run_intent_exploration_1",
        capability_ref=binding.implementation_ref,
        bundle_ref=binding.validation_bundle_ref,
        evidence_ref=binding.assessment_ref,
        admission_ref=binding.admission_ref,
        runtime_policy_ref=binding.runtime_policy_ref,
        freshness_cursor_ref=binding.validity_cursor_ref,
        input_graph_fingerprint=revision.generation_context_hash,
        freshness_dependency_fingerprint=revision.freshness_dependency_fingerprint,
        operation_id="fit",
        execution_mode="confirm_and_execute",
        risk_level=revision.risk_level,
        artifact_contract_ref=domain_digest(
            "workbench.notebook.artifact_contract/v1",
            revision.artifact_contract.to_dict(),
        ),
        consumer_projection_ref=domain_digest(
            "workbench.capability_factory.consumer_projection/v1",
            {"allowed_consumers": list(binding.allowed_consumers)},
        ),
        idempotency_key="confirm-exploration-1",
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )


def test_low_risk_confirmation_binds_a_receipt_without_execution(tmp_path):
    from test_notebook_capability_binding import _server_decision, _service_with_catalog
    from workbench.capability_factory.execution_authorization import (
        OptionExecutionAuthorizationStore,
    )

    project = make_project(tmp_path, name="project.alpha")
    service, notebook, binding, _catalog = _service_with_catalog(project)
    context = service.compile_context(notebook.notebook_id)
    decision = _server_decision(
        service,
        notebook,
        context,
        option_id="opt_exploration",
        decision_id="rec_exploration",
        batch_id="batch_exploration",
    )
    (revision,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[_exploration_draft(capability_id="capability.registered")],
        batch_id=decision.batch_id,
        recommendation_decision=decision,
    )
    assert revision.risk_level == "low"
    assert revision.execution_modes == ("materialize_only", "confirm_and_execute")

    service.record_decision(
        notebook.notebook_id,
        revision.option_id,
        decision="selected",
        actor="user_1",
    )
    authorization = _execution_authorization_for(
        revision,
        binding,
        notebook_id=notebook.notebook_id,
    )

    persisted = service.authorize_option_execution(
        notebook.notebook_id,
        revision.option_id,
        context=context,
        authorization=authorization,
    )

    assert persisted == authorization
    view = service.option_view(notebook.notebook_id, revision.option_id)
    assert view.lifecycle_status == "selected"
    assert view.executions == ()
    assert OptionExecutionAuthorizationStore(project).read(
        authorization.authorization_id
    ) == authorization


def test_confirmation_rejects_receipt_with_stale_binding(tmp_path):
    from test_notebook_capability_binding import _server_decision, _service_with_catalog

    project = make_project(tmp_path, name="project.alpha")
    service, notebook, binding, _catalog = _service_with_catalog(project)
    context = service.compile_context(notebook.notebook_id)
    decision = _server_decision(
        service,
        notebook,
        context,
        option_id="opt_exploration",
        decision_id="rec_exploration",
        batch_id="batch_exploration",
    )
    (revision,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[_exploration_draft(capability_id="capability.registered")],
        batch_id=decision.batch_id,
        recommendation_decision=decision,
    )
    service.record_decision(
        notebook.notebook_id,
        revision.option_id,
        decision="selected",
        actor="user_1",
    )
    authorization = _execution_authorization_for(
        revision,
        binding,
        notebook_id=notebook.notebook_id,
    )
    stale = replace(authorization, capability_resolution_binding_ref="0" * 64)

    from workbench.agent.notebook.errors import OptionRevisionStale

    with pytest.raises(OptionRevisionStale, match="authorization binding"):
        service.authorize_option_execution(
            notebook.notebook_id,
            revision.option_id,
            context=context,
            authorization=stale,
        )


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
