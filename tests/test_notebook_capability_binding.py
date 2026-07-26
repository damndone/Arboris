"""NotebookService consumes only server-owned capability bindings."""

from __future__ import annotations

from pathlib import Path

import pytest

from test_capability_notebook_binding import _admitted_records, _resolution, _validity

from workbench.agent.context_compiler import (
    freshness_dependency_fingerprint,
    generation_context_hash,
)
from workbench.agent.notebook import NotebookService, OptionDraft, TypedProposal
from workbench.agent.notebook.errors import OptionBatchInvalid, OptionRevisionStale
from workbench.capability_factory.notebook_catalog import CapabilityBindingCatalog
from workbench.contracts.agent.notebook_option import (
    ExpectedArtifact,
    NotebookOptionRevisionV11,
    NotebookOptionRevisionV12,
    RecommendationDecision,
)

from tests.test_notebook_support import make_project, model_rerun_proposal


def _binding_and_verifier():
    from workbench.capability_factory.notebook_binding import CapabilityResolutionBinding

    controller, adapter, bundle, assessment, admission = _admitted_records()
    validity = _validity()
    resolution = _resolution(adapter, validity)
    binding = CapabilityResolutionBinding.from_records(
        admission_controller=controller,
        resolution_binding=resolution,
        adapter=adapter,
        validation_bundle=bundle,
        assessment=assessment,
        admission=admission,
        current_validity=validity,
    )

    def verify(candidate: CapabilityResolutionBinding) -> None:
        candidate.assert_current(
            admission_controller=controller,
            adapter=adapter,
            validation_bundle=bundle,
            assessment=assessment,
            current_validity=validity,
            runtime_policy_ref=admission.runtime_policy_ref,
            scope_kind=admission.scope_kind,
            scope_ref=admission.scope_ref,
        )

    return binding, verify


def _decision(
    context,
    *,
    option_id: str = "opt_registered",
    decision_id: str = "rec_registered",
    batch_id: str = "batch_registered",
) -> RecommendationDecision:
    return RecommendationDecision(
        recommendation_decision_id=decision_id,
        batch_id=batch_id,
        generation_context_hash=generation_context_hash(context),
        freshness_dependency_fingerprint=freshness_dependency_fingerprint(context),
        evidence_pack_hashes=(),
        comparison_protocol_refs=(),
        candidate_option_ids=(option_id,),
        outcome="recommended",
        recommended_option_id=option_id,
        reason_refs=("evidence:registered",),
    )


def _draft(
    *,
    capability_id: str,
    option_id: str = "opt_registered",
    proposal_id: str = "proposal_registered",
    decision_id: str = "rec_registered",
) -> OptionDraft:
    return OptionDraft(
        rank=1,
        rationale="server-owned capability binding is available",
        assumptions=("the admitted capability remains current",),
        proposal=TypedProposal.from_dict(model_rerun_proposal(proposal_id)),
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


def _service_with_catalog(tmp_path: Path):
    binding, verifier = _binding_and_verifier()
    catalog = CapabilityBindingCatalog(verifier=verifier)
    catalog.register("capability.registered", binding)
    service = NotebookService(tmp_path, capability_bindings=catalog)
    notebook = service.create_notebook(
        title="Capability options",
        created_by="user_1",
        available_capabilities=["capability.registered"],
    )
    return service, notebook, binding, catalog


def test_registered_capability_generates_a_materialize_only_v12_option(tmp_path: Path) -> None:
    project = make_project(tmp_path, name="project.alpha")
    service, notebook, binding, _catalog = _service_with_catalog(project)
    context = service.compile_context(notebook.notebook_id)
    decision = _decision(context)

    (revision,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[_draft(capability_id="capability.registered")],
        batch_id=decision.batch_id,
        recommendation_decision=decision,
    )

    assert isinstance(revision, NotebookOptionRevisionV12)
    assert revision.capability_resolution_binding_ref == binding.content_digest
    assert revision.execution_modes == ("materialize_only",)
    assert revision.execution_allowed is False
    assert isinstance(
        service.option_view(notebook.notebook_id, revision.option_id).current_revision,
        NotebookOptionRevisionV12,
    )


def test_unregistered_capability_keeps_the_existing_v11_path(tmp_path: Path) -> None:
    project = make_project(tmp_path, name="project.alpha")
    service, notebook, _binding, _catalog = _service_with_catalog(project)
    context = service.compile_context(notebook.notebook_id)
    draft = _draft(capability_id="capability.native", option_id="opt_native")
    decision = _decision(context, option_id="opt_native")
    draft = OptionDraft(**{**draft.__dict__, "recommendation_decision_id": decision.recommendation_decision_id})

    (revision,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[draft],
        batch_id=decision.batch_id,
        recommendation_decision=decision,
    )

    assert isinstance(revision, NotebookOptionRevisionV11)
    assert not isinstance(revision, NotebookOptionRevisionV12)


def test_registered_capability_requires_a_recommendation_decision_before_writes(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path, name="project.alpha")
    service, notebook, _binding, _catalog = _service_with_catalog(project)
    context = service.compile_context(notebook.notebook_id)

    with pytest.raises(OptionBatchInvalid) as caught:
        service.propose_batch(
            notebook.notebook_id,
            context=context,
            drafts=[_draft(capability_id="capability.registered", option_id="opt_blocked")],
        )

    assert caught.value.code == "OPTION_CAPABILITY_BINDING_DECISION_REQUIRED"
    assert service.store.option_ids(notebook.notebook_id) == []


def test_binding_verifier_failure_is_fail_closed_and_atomic(tmp_path: Path) -> None:
    project = make_project(tmp_path, name="project.alpha")
    binding, verifier = _binding_and_verifier()
    state = {"revoked": False}

    def current_verifier(candidate):
        if state["revoked"]:
            raise ValueError("admission is no longer current")
        verifier(candidate)

    catalog = CapabilityBindingCatalog(verifier=current_verifier)
    catalog.register("capability.registered", binding)
    service = NotebookService(project, capability_bindings=catalog)
    notebook = service.create_notebook(
        title="Capability options",
        created_by="user_1",
        available_capabilities=["capability.registered"],
    )
    context = service.compile_context(notebook.notebook_id)
    decision = _decision(context)
    state["revoked"] = True

    with pytest.raises(OptionBatchInvalid) as caught:
        service.propose_batch(
            notebook.notebook_id,
            context=context,
            drafts=[_draft(capability_id="capability.registered")],
            batch_id=decision.batch_id,
            recommendation_decision=decision,
        )

    assert caught.value.code == "OPTION_CAPABILITY_BINDING_UNAVAILABLE"
    assert service.store.option_ids(notebook.notebook_id) == []


def test_bound_option_revalidation_cannot_silently_downgrade_to_v11(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path, name="project.alpha")
    service, notebook, binding, _catalog = _service_with_catalog(project)
    context = service.compile_context(notebook.notebook_id)
    first_decision = _decision(context)
    (first,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[_draft(capability_id="capability.registered")],
        batch_id=first_decision.batch_id,
        recommendation_decision=first_decision,
    )

    second_decision = _decision(
        context,
        option_id=first.option_id,
        decision_id="rec_replan",
        batch_id="batch_replan",
    )
    with pytest.raises(OptionBatchInvalid) as caught:
        service.propose_batch(
            notebook.notebook_id,
            context=context,
            drafts=[
                _draft(
                    capability_id="capability.native",
                    option_id=first.option_id,
                    proposal_id="proposal_replan",
                    decision_id=second_decision.recommendation_decision_id,
                )
            ],
            batch_id=second_decision.batch_id,
            recommendation_decision=second_decision,
            revalidate_existing=True,
        )

    assert caught.value.code == "OPTION_CAPABILITY_BINDING_REVALIDATION_MISMATCH"
    view = service.option_view(notebook.notebook_id, first.option_id)
    assert len(view.revisions) == 1
    assert isinstance(view.current_revision, NotebookOptionRevisionV12)
    assert view.current_revision.capability_resolution_binding_ref == binding.content_digest


def test_current_binding_is_rechecked_before_execution_callback(tmp_path: Path) -> None:
    project = make_project(tmp_path, name="project.alpha")
    binding, verifier = _binding_and_verifier()
    state = {"revoked": False}

    def current_verifier(candidate):
        if state["revoked"]:
            raise ValueError("admission is no longer current")
        verifier(candidate)

    catalog = CapabilityBindingCatalog(verifier=current_verifier)
    catalog.register("capability.registered", binding)
    service = NotebookService(project, capability_bindings=catalog)
    notebook = service.create_notebook(
        title="Capability options",
        created_by="user_1",
        available_capabilities=["capability.registered"],
    )
    context = service.compile_context(notebook.notebook_id)
    decision = _decision(context)
    (revision,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[_draft(capability_id="capability.registered")],
        batch_id=decision.batch_id,
        recommendation_decision=decision,
    )
    state["revoked"] = True

    with pytest.raises(OptionRevisionStale, match="binding"):
        service.complete_execution(
            notebook.notebook_id,
            revision.option_id,
            execution_status="succeeded",
            produced_artifacts=(),
        )
