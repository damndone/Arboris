"""NotebookService consumes only server-owned capability bindings."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_capability_notebook_binding import (
    _admitted_records,
    _exploration_draft,
    _resolution,
    _validity,
)

from workbench.agent.context_compiler import (
    freshness_dependency_fingerprint,
    generation_context_hash,
)
from workbench.agent.notebook import NotebookService, OptionDraft, TypedProposal
from workbench.agent.notebook.errors import (
    OptionBatchInvalid,
    OptionExecutionGatewayUnavailable,
    OptionExecutionReceiptRequired,
    OptionRevisionStale,
    OptionValidationFailed,
)
from workbench.capability_factory.notebook_catalog import CapabilityBindingCatalog
from workbench.capability_factory.notebook_bridge import NotebookExecutionDispatch
from workbench.agent.notebook.recommendation import RecommendationValidator, candidate_cohort_hash
from workbench.contracts.agent.notebook_option import (
    ExpectedArtifact,
    FeasibilityCandidateDecision,
    FeasibilityDecision,
    NotebookOptionRevisionV11,
    NotebookOptionRevisionV12,
    RecommendationDecision,
    RecommendationDecisionV11,
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


def _server_decision(
    service: NotebookService,
    notebook,
    context,
    *,
    option_id: str = "opt_registered",
    decision_id: str | None = None,
    batch_id: str = "batch_registered",
) -> RecommendationDecisionV11:
    source = FeasibilityDecision(
        feasibility_decision_id=f"feasibility_{batch_id}",
        batch_id=batch_id,
        generation_context_hash=generation_context_hash(context),
        freshness_dependency_fingerprint=freshness_dependency_fingerprint(context),
        evidence_pack_hashes=("sha256:server-evidence",),
        candidate_option_ids=(option_id,),
        candidate_cohort_hash=candidate_cohort_hash((option_id,)),
        candidates=(
            FeasibilityCandidateDecision(
                option_id=option_id,
                protocol_id="feasibility.v1",
                protocol_version="feasibility/v1",
                inspection_refs=(f"inspection:{option_id}",),
                evidence_refs=(f"evidence:{option_id}",),
                outcome="feasible",
                reason_code="PASS",
            ),
        ),
        validator_revision="feasibility-validator/v1",
    )
    service.persist_server_decision(notebook.notebook_id, source)
    decision = RecommendationValidator().decide_v11(
        batch_id=batch_id,
        candidate_option_ids=(option_id,),
        generation_context_hash=source.generation_context_hash,
        freshness_dependency_fingerprint=source.freshness_dependency_fingerprint,
        evidence_pack_hashes=source.evidence_pack_hashes,
        decision_registry=service.read_server_decision_registry(notebook.notebook_id),
        feasibility_decision_ref=source.feasibility_decision_id,
    )
    if decision_id is not None:
        decision = replace(decision, recommendation_decision_id=decision_id)
    return decision


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
    decision = _server_decision(service, notebook, context)

    (revision,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[
            _draft(
                capability_id="capability.registered",
                decision_id=decision.recommendation_decision_id,
            )
        ],
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


def test_model_custom_proposal_is_canonicalized_to_server_binding_before_persistence(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path, name="project.alpha")
    binding, verifier = _binding_and_verifier()
    catalog = CapabilityBindingCatalog(verifier=verifier)
    catalog.register(
        "custom.adapter",
        binding,
        planner_projection={
            "key": "custom.adapter",
            "label": "Verified custom adapter",
            "model_type": "custom.adapter",
            "notebook_proposal_adapters": ["model.custom"],
            "params": [],
            "artifact_types": {"custom.result": "custom_json"},
        },
    )
    service = NotebookService(project, capability_bindings=catalog)
    notebook = service.create_notebook(
        title="Custom capability option",
        created_by="user_1",
        available_capabilities=["custom.adapter"],
    )
    context = service.compile_context(notebook.notebook_id)
    decision = _server_decision(
        service,
        notebook,
        context,
        option_id="opt_custom",
        decision_id="rec_custom",
        batch_id="batch_custom",
    )
    proposal = TypedProposal(
        proposal_id="proposal_custom",
        operation_id="model.custom",
        target={"dataset_source_id": "a" * 64},
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": context.context_id,
            "owner_resolution": "dataset_projection",
        },
        changes={
            "operation": "fit",
            "parameters": {"alpha": 0.1},
            "consumer_slots": ["report_projection"],
        },
    )
    (revision,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[
            OptionDraft(
                rank=1,
                rationale="the admitted custom adapter is the selected experimental path",
                proposal=proposal,
                expected_artifacts=(
                    ExpectedArtifact(
                        artifact_id="custom.result",
                        artifact_type="custom_json",
                        required=True,
                        count=1,
                    ),
                ),
                option_id="opt_custom",
                capability_id="custom.adapter",
                recommendation_decision_id=decision.recommendation_decision_id,
                recommendation_status=decision.outcome,
            )
        ],
        batch_id=decision.batch_id,
        recommendation_decision=decision,
    )

    stored = service.store.read_option(notebook.notebook_id, revision.option_id)
    persisted = stored.current_stored_revision.proposal
    assert revision.risk_level == "high"
    assert revision.execution_modes == (
        "materialize_only",
        "experimental_confirm_and_execute",
    )
    assert persisted.changes["capability_ref"] == binding.implementation_ref
    assert persisted.changes["binding_ref"] == binding.content_digest
    assert persisted.changes["operation"] == "fit"
    assert persisted.changes["consumer_slots"] == ["report_projection"]


def test_model_custom_materializes_a_dataset_bound_provenance_draft(tmp_path: Path) -> None:
    from workbench.lineage.upload_store import store_upload_bytes
    from workbench.contracts.agent.notebook_option import EvidenceRef

    project = make_project(tmp_path, name="project.alpha")
    upload_sha = store_upload_bytes(
        project,
        b"outcome,predictor\n1,2\n2,3\n",
        filename="custom.csv",
    )
    binding, verifier = _binding_and_verifier()
    binding = replace(binding, dependency_bundle_ref="a" * 64)
    catalog = CapabilityBindingCatalog(verifier=verifier)
    catalog.register(
        "custom.adapter",
        binding,
        planner_projection={
            "key": "custom.adapter",
            "label": "Verified custom adapter",
            "model_type": "custom.adapter",
            "notebook_proposal_adapters": ["model.custom"],
            "params": [],
            "artifact_types": {"custom.result": "custom_json"},
        },
    )
    service = NotebookService(project, capability_bindings=catalog)
    notebook = service.ensure_default_projection(
        dataset={
            "kind": "dataset",
            "upload_sha256": upload_sha,
            "filename": "custom.csv",
            "sheet_names": [],
        },
        created_by="ui",
    )
    context = service.compile_context(notebook.notebook_id)
    service.store.append_evidence_pack(
        notebook.notebook_id,
        {
            "evidence_pack_hash": "sha256:server-evidence",
            "records": [
                {
                    "evidence_id": "evidence:opt_custom",
                    "result_hash": "sha256:custom-result",
                    "observations": {"columns": [{"name": "outcome"}, {"name": "predictor"}]},
                }
            ],
        },
    )
    context = service.compile_context(notebook.notebook_id)
    decision = _server_decision(
        service,
        notebook,
        context,
        option_id="opt_custom_materialize",
        decision_id="rec_custom_materialize",
        batch_id="batch_custom_materialize",
    )
    proposal = TypedProposal(
        proposal_id="proposal_custom_materialize",
        operation_id="model.custom",
        target={"dataset_source_id": upload_sha},
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": context.context_id,
            "owner_resolution": "dataset_projection",
        },
        changes={"operation": "fit", "parameters": {"alpha": 0.1}},
    )
    (revision,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[
            OptionDraft(
                rank=1,
                rationale="the experimental adapter is explicitly selected for this dataset",
                proposal=proposal,
                expected_artifacts=(
                    ExpectedArtifact(
                        artifact_id="custom.result",
                        artifact_type="custom_json",
                        required=True,
                        count=1,
                    ),
                ),
                option_id="opt_custom_materialize",
                capability_id="custom.adapter",
                evidence_refs=(
                    EvidenceRef(
                        evidence_id="evidence:opt_custom",
                        result_hash="sha256:custom-result",
                        source_refs=(f"dataset_profile:{upload_sha}",),
                    ),
                ),
                comparative_claims=("evidence:opt_custom supports the adapter path",),
                recommendation_decision_id=decision.recommendation_decision_id,
                recommendation_status=decision.outcome,
            )
        ],
        batch_id=decision.batch_id,
        recommendation_decision=decision,
    )
    service.record_decision(notebook.notebook_id, revision.option_id, decision="selected", actor="ui")

    result = service.materialize_option(
        notebook.notebook_id,
        revision.option_id,
        context=service.compile_context(notebook.notebook_id),
    )
    model = next(node for node in result.draft.draft["graph"]["nodes"] if node["node_type"] == "model")
    assert model["model_type"] == "custom"
    assert model["params"]["capability_ref"] == binding.implementation_ref
    assert model["params"]["binding_ref"] == binding.content_digest
    assert result.draft.draft["notebook_provenance"]["capability_resolution_binding_ref"] == binding.content_digest

    captured: dict[str, object] = {}
    from workbench.capability_factory.notebook_bridge import NotebookExecutionDispatch

    class FakeGateway:
        def dispatch(self, **kwargs):
            captured.update(kwargs)
            authorization = kwargs["authorization"]
            return NotebookExecutionDispatch(
                authorization_id=authorization.authorization_id,
                run_intent_id=authorization.run_intent_id,
                status="unsupported",
            )

    service.execution_gateway = FakeGateway()
    dispatch = service.confirm_and_execute(
        notebook.notebook_id,
        revision.option_id,
        context=service.compile_context(notebook.notebook_id),
    )
    assert dispatch.status == "unsupported"
    assert captured["authorization"].bundle_ref == binding.dependency_bundle_ref


def test_catalog_rejects_mismatched_or_unbounded_planner_projection(tmp_path: Path) -> None:
    del tmp_path
    binding, verifier = _binding_and_verifier()
    catalog = CapabilityBindingCatalog(verifier=verifier)

    with pytest.raises(ValueError, match="key must match capability_id"):
        catalog.register(
            "custom.ols",
            binding,
            planner_projection={
                "key": "other.capability",
                "label": "wrong owner",
                "artifact_types": {"result": "custom_json"},
            },
        )

    with pytest.raises(ValueError, match="unsupported field"):
        catalog.register(
            "custom.ols",
            binding,
            planner_projection={
                "key": "custom.ols",
                "label": "wrong field",
                "artifact_types": {"result": "custom_json"},
                "entrypoint_ref": "secret-ref",
            },
        )

    with pytest.raises(ValueError, match="notebook_proposal_adapters is invalid"):
        catalog.register(
            "custom.ols",
            binding,
            planner_projection={
                "key": "custom.ols",
                "label": "unhashable adapter",
                "model_type": "ols",
                "notebook_proposal_adapters": [[]],
                "artifact_types": {"result": "custom_json"},
            },
        )

    with pytest.raises(ValueError, match="planner_projection.params.value must be scalar"):
        catalog.register(
            "custom.ols",
            binding,
            planner_projection={
                "key": "custom.ols",
                "label": "nested authority data",
                "model_type": "ols",
                "params": [
                    {
                        "key": "model_options",
                        "value": {"entrypoint_ref": "secret-ref"},
                    }
                ],
                "artifact_types": {"result": "custom_json"},
            },
        )

    restricted = replace(binding, allowed_operations=("inspect",))
    restricted_catalog = CapabilityBindingCatalog(verifier=lambda _candidate: None)
    restricted_catalog.register(
        "custom.restricted",
        restricted,
        planner_projection={
            "key": "custom.restricted",
            "label": "not fit-authorized",
            "model_type": "custom.restricted",
            "artifact_types": {"result": "custom_json"},
        },
    )
    with pytest.raises(ValueError, match="fit operation"):
        restricted_catalog.planner_projection("custom.restricted")

    consumer_restricted = replace(
        binding,
        allowed_consumers=("report_projection",),
    )
    consumer_catalog = CapabilityBindingCatalog(verifier=lambda _candidate: None)
    consumer_catalog.register(
        "custom.consumer_restricted",
        consumer_restricted,
        planner_projection={
            "key": "custom.consumer_restricted",
            "label": "not planner-authorized",
            "model_type": "custom.consumer_restricted",
            "artifact_types": {"result": "custom_json"},
        },
    )
    with pytest.raises(ValueError, match="notebook_option_planner consumer"):
        consumer_catalog.planner_projection("custom.consumer_restricted")


def test_catalog_publishes_custom_adapter_without_authority_internals(tmp_path: Path) -> None:
    del tmp_path
    binding, verifier = _binding_and_verifier()
    catalog = CapabilityBindingCatalog(verifier=verifier)
    catalog.register(
        "custom.adapter",
        binding,
        planner_projection={
            "key": "custom.adapter",
            "label": "Verified custom adapter",
            "model_type": "custom.adapter",
            "notebook_proposal_adapters": ["model.custom"],
            "params": [],
            "artifact_types": {"custom.result": "custom_json"},
        },
    )

    projection = catalog.planner_projection("custom.adapter")
    assert projection is not None
    assert projection["notebook_proposal_adapters"] == ["model.custom"]
    assert "entrypoint_ref" not in projection
    assert "binding_ref" not in projection


def test_custom_projection_artifact_types_reach_service_contract(tmp_path: Path) -> None:
    from workbench.capability_factory.notebook_binding import CapabilityResolutionBinding

    project = make_project(tmp_path, name="project.alpha")
    binding, verifier = _binding_and_verifier()
    catalog = CapabilityBindingCatalog(verifier=verifier)
    catalog.register(
        "custom.ols",
        binding,
        planner_projection={
            "key": "custom.ols",
            "label": "Verified custom OLS",
            "model_type": "ols",
            "params": [],
            "artifact_types": {"custom.ols.result": "custom_json"},
        },
    )
    service = NotebookService(project, capability_bindings=catalog)
    notebook = service.create_notebook(
        title="Custom projection",
        created_by="test",
        available_capabilities=["custom.ols"],
    )
    context = service.compile_context(notebook.notebook_id)
    draft = OptionDraft(
        rank=1,
        rationale="custom projection artifact is server declared",
        assumptions=("the admitted binding remains current",),
        proposal=TypedProposal(
            proposal_id="proposal_custom_projection",
            operation_id="model.genesis",
            target={"dataset_source_id": "a" * 64},
            preconditions={
                "context_version": "notebook-planning-context/v1",
                "context_fingerprint": context.context_id,
                "owner_resolution": "dataset_projection",
            },
            changes={
                "model_params": {
                    "model_type": "ols",
                    "y": "outcome",
                    "x": ["predictor"],
                }
            },
        ),
        expected_artifacts=(
            ExpectedArtifact(
                "custom.ols.result",
                "custom_json",
                required=True,
                count=1,
            ),
        ),
        capability_id="custom.ols",
        option_id="custom_projection_option",
    )

    _proposal, contract, _risk = service._prepare(notebook, context, draft)

    assert contract.expected[0].artifact_id == "custom.ols.result"
    assert isinstance(binding, CapabilityResolutionBinding)

    mismatched = replace(
        draft,
        proposal=replace(
            draft.proposal,
            proposal_id="proposal_mismatched_model_identity",
            changes={
                "model_params": {
                    "model_type": "logit",
                    "y": "outcome",
                    "x": ["predictor"],
                }
            },
        ),
    )
    with pytest.raises(OptionValidationFailed, match="model identity"):
        service._prepare(notebook, context, mismatched)


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
    first_decision = _server_decision(service, notebook, context)
    (first,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[
            _draft(
                capability_id="capability.registered",
                decision_id=first_decision.recommendation_decision_id,
            )
        ],
        batch_id=first_decision.batch_id,
        recommendation_decision=first_decision,
    )

    second_decision = _server_decision(
        service,
        notebook,
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
    decision = _server_decision(service, notebook, context)
    (revision,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
            drafts=[
                _draft(
                    capability_id="capability.registered",
                    decision_id=decision.recommendation_decision_id,
                )
            ],
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


def test_bound_v12_completion_rejects_client_owned_run_and_artifact_facts(
    tmp_path: Path,
) -> None:
    """CF4 completion must consume a trusted receipt, never HTTP callback facts."""

    project = make_project(tmp_path, name="project.alpha")
    service, notebook, _binding, _catalog = _service_with_catalog(project)
    context = service.compile_context(notebook.notebook_id)
    decision = _server_decision(
        service,
        notebook,
        context,
        option_id="opt_client_facts",
        decision_id="rec_client_facts",
        batch_id="batch_client_facts",
    )
    (revision,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[
            _draft(
                capability_id="capability.registered",
                option_id="opt_client_facts",
                proposal_id="proposal_client_facts",
                decision_id=decision.recommendation_decision_id,
            )
        ],
        batch_id=decision.batch_id,
        recommendation_decision=decision,
    )
    service.record_decision(
        notebook.notebook_id,
        revision.option_id,
        decision="selected",
        actor="user_1",
    )

    with pytest.raises(OptionExecutionReceiptRequired) as caught:
        service.complete_execution(
            notebook.notebook_id,
            revision.option_id,
            execution_status="succeeded",
            run_id="client-forged-run",
            produced_artifacts=[
                {
                    "artifact_id": "client-forged-artifact",
                    "artifact_type": "custom_json",
                    "count": 1,
                }
            ],
        )

    assert caught.value.code == "OPTION_EXECUTION_RECEIPT_REQUIRED"
    assert caught.value.details["reason"] == "capability_execution_receipt_required"
    view = service.option_view(notebook.notebook_id, revision.option_id)
    assert view.lifecycle_status == "selected"
    assert view.executions == ()
    assert view.last_execution is None


def test_confirm_and_execute_fails_closed_before_materialization_without_gateway(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path, name="project.alpha")
    service, notebook, _binding, _catalog = _service_with_catalog(project)
    context = service.compile_context(notebook.notebook_id)
    decision = _server_decision(
        service,
        notebook,
        context,
        option_id="opt_no_gateway",
        decision_id="rec_no_gateway",
        batch_id="batch_no_gateway",
    )
    (revision,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[
            _exploration_draft(
                capability_id="capability.registered",
                option_id="opt_no_gateway",
                proposal_id="proposal_no_gateway",
                decision_id=decision.recommendation_decision_id,
            )
        ],
        batch_id=decision.batch_id,
        recommendation_decision=decision,
    )
    service.record_decision(
        notebook.notebook_id,
        revision.option_id,
        decision="selected",
        actor="user_1",
    )

    with pytest.raises(OptionExecutionGatewayUnavailable) as caught:
        service.confirm_and_execute(
            notebook.notebook_id,
            revision.option_id,
            context=context,
        )

    assert caught.value.code == "OPTION_EXECUTION_GATEWAY_UNAVAILABLE"
    assert caught.value.details["reason"] == "trusted_execution_gateway_unavailable"
    view = service.option_view(notebook.notebook_id, revision.option_id)
    assert view.lifecycle_status == "selected"
    assert service.store.read_materialization(
        notebook.notebook_id, revision.option_id, revision.option_revision
    ) is None


def test_confirm_and_execute_builds_server_authorization_before_gateway_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path, name="project.alpha")
    service, notebook, binding, _catalog = _service_with_catalog(project)
    captured: dict[str, object] = {}

    class FakeGateway:
        def dispatch(self, **kwargs):
            captured.update(kwargs)
            authorization = kwargs["authorization"]
            return NotebookExecutionDispatch(
                authorization_id=authorization.authorization_id,
                run_intent_id=authorization.run_intent_id,
                status="dispatch_reserved",
                run_id="run_server_owned",
                attempt_id="attempt_server_owned",
                receipt_ref="a" * 64,
            )

    service.execution_gateway = FakeGateway()
    context = service.compile_context(notebook.notebook_id)
    decision = _server_decision(
        service,
        notebook,
        context,
        option_id="opt_gateway",
        decision_id="rec_gateway",
        batch_id="batch_gateway",
    )
    (revision,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=[
            _exploration_draft(
                capability_id="capability.registered",
                option_id="opt_gateway",
                proposal_id="proposal_gateway",
                decision_id=decision.recommendation_decision_id,
            )
        ],
        batch_id=decision.batch_id,
        recommendation_decision=decision,
    )
    service.record_decision(
        notebook.notebook_id,
        revision.option_id,
        decision="selected",
        actor="user_1",
    )

    materialization = SimpleNamespace(
        materialization_id="mat_server_owned",
        option_id=revision.option_id,
        option_revision=revision.option_revision,
        capability_resolution_binding_ref=binding.content_digest,
        draft_id="draft_server_owned",
        draft_hash="sha256:" + "d" * 64,
    )
    draft = SimpleNamespace(
        draft={"draft_id": "draft_server_owned", "graph": {"nodes": []}},
        draft_hash=materialization.draft_hash,
    )

    def fake_materialize(*_args, **_kwargs):
        return SimpleNamespace(materialization=materialization, draft=draft)

    monkeypatch.setattr(service, "materialize_option", fake_materialize)
    dispatch = service.confirm_and_execute(
        notebook.notebook_id,
        revision.option_id,
        context=context,
    )

    authorization = captured["authorization"]
    assert dispatch.status == "dispatch_reserved"
    assert authorization.materialization_id == "mat_server_owned"
    assert authorization.draft_id == "draft_server_owned"
    assert authorization.authorization_id.startswith("auth_")
    assert authorization.run_intent_id.startswith("intent_")
    assert authorization.idempotency_key.startswith("confirm-and-execute-")
    assert service.option_view(notebook.notebook_id, revision.option_id).lifecycle_status == (
        "selected"
    )


def test_bound_option_revalidation_rechecks_current_binding_before_prepare(
    tmp_path: Path,
) -> None:
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
    decision = _server_decision(service, notebook, context)
    (first,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
            drafts=[
                _draft(
                    capability_id="capability.registered",
                    decision_id=decision.recommendation_decision_id,
                )
            ],
        batch_id=decision.batch_id,
        recommendation_decision=decision,
    )

    http_style_revision = service.revalidate_option(
        notebook.notebook_id,
        first.option_id,
        context=context,
        draft=_draft(
            capability_id=None,
            option_id=first.option_id,
            proposal_id="proposal_http_style_revalidate",
        ),
    )
    assert (
        http_style_revision.capability_resolution_binding_ref
        == binding.content_digest
    )

    state["revoked"] = True
    with pytest.raises(OptionBatchInvalid) as caught:
        service.revalidate_option(
            notebook.notebook_id,
            first.option_id,
            context=context,
            draft=_draft(
                capability_id="capability.registered",
                option_id=first.option_id,
                proposal_id="proposal_revalidate",
            ),
        )

    assert caught.value.code == "OPTION_CAPABILITY_BINDING_UNAVAILABLE"


def test_service_rejects_bound_capability_without_fit_authorization(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path, name="project.alpha")
    binding, _verifier = _binding_and_verifier()
    restricted = replace(binding, allowed_operations=("inspect",))
    catalog = CapabilityBindingCatalog(verifier=lambda _candidate: None)
    catalog.register("capability.restricted", restricted)
    service = NotebookService(project, capability_bindings=catalog)
    notebook = service.create_notebook(
        title="Restricted capability",
        created_by="user_1",
        available_capabilities=["capability.restricted"],
    )
    context = service.compile_context(notebook.notebook_id)
    decision = _decision(context, option_id="opt_restricted")

    with pytest.raises(OptionBatchInvalid) as caught:
        service.propose_batch(
            notebook.notebook_id,
            context=context,
            drafts=[
                _draft(
                    capability_id="capability.restricted",
                    option_id="opt_restricted",
                )
            ],
            batch_id=decision.batch_id,
            recommendation_decision=decision,
        )

    assert caught.value.code == "OPTION_CAPABILITY_BINDING_UNAVAILABLE"
