from __future__ import annotations

from pathlib import Path

import pytest

from test_notebook_capability_binding import _binding_and_verifier
from tests.test_notebook_support import make_project
from workbench.agent.notebook import NotebookService, OptionDraft, TypedProposal
from workbench.agent.notebook.evidence import DataEvidencePackV1, EvidenceRecord
from workbench.agent.notebook.errors import OptionRevisionStale
from workbench.agent.notebook.materialization import NotebookOptionMaterializer
from workbench.agent.trace import TraceWriter
from workbench.capability_factory.notebook_catalog import CapabilityBindingCatalog
from workbench.contracts.agent.notebook_option import (
    EvidenceRef,
    ExpectedArtifact,
    OptionMaterialization,
    OptionMaterializationV11,
)
from workbench.lineage.upload_store import store_upload_bytes


def _legacy_materialization() -> OptionMaterialization:
    return OptionMaterialization(
        materialization_id="mat_native_1",
        option_id="opt_native_1",
        option_revision=1,
        proposal_id="proposal_native_1",
        proposal_revision=1,
        freshness_dependency_fingerprint="fresh1:native",
        generation_context_id="context_native_1",
        draft_id="draft_native_1",
        draft_hash="sha256:" + "a" * 64,
        draft_execution_mode="genesis",
        source_run_id=None,
        source_model_node_id=None,
        source_op_node_id=None,
        source_node_hash=None,
        source_forest_node_key=None,
        source_context_fingerprint=None,
        dataset_upload_sha256="upload_native_1",
        run_family_id="family_native_1",
    )


def test_materialization_v11_round_trips_binding_without_granting_execution() -> None:
    legacy = _legacy_materialization()
    assert OptionMaterialization.from_dict(legacy.to_dict()) == legacy

    bound = OptionMaterializationV11(
        **{**legacy.to_dict(), "contract_version": "1.1"},
        capability_resolution_binding_ref="b" * 64,
    )
    payload = bound.to_dict()

    assert payload["contract_version"] == "1.1"
    assert OptionMaterialization.from_dict(payload) == bound
    assert payload["capability_resolution_binding_ref"] == "b" * 64


def test_trace_accepts_only_immutable_binding_identity_for_option_events(
    tmp_path: Path,
) -> None:
    writer = TraceWriter(
        tmp_path,
        scope={
            "project_id": "project.alpha",
            "notebook_id": "notebook.alpha",
            "run_family_id": "family.alpha",
        },
        versions={
            "app_commit": "commit",
            "model_id": "model",
            "prompt_version": "prompt",
            "vocabulary_version": "vocabulary",
            "context_profile": "notebook/v1",
        },
    )

    writer.emit(
        "option.revision.created",
        payload={
            "option_id": "opt.alpha",
            "option_revision": 1,
            "generation_context_hash": "sha256:" + "c" * 64,
            "freshness_dependency_fingerprint": "fresh1:" + "d" * 64,
            "capability_resolution_binding_ref": "e" * 64,
        },
    )

    with pytest.raises(ValueError, match="unexpected payload"):
        writer.emit(
            "option.revision.created",
            payload={
                "option_id": "opt.beta",
                "option_revision": 1,
                "generation_context_hash": "sha256:" + "c" * 64,
                "freshness_dependency_fingerprint": "fresh1:" + "d" * 64,
                "capability_resolution_binding_ref": "e" * 64,
                "execution_grant": True,
            },
        )


def test_bound_materialization_replays_with_binding_in_draft_and_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            "notebook_proposal_adapters": ["model.genesis"],
            "params": [],
            "artifact_types": {"custom.ols.result": "custom_json"},
        },
    )
    service = NotebookService(project, capability_bindings=catalog)
    upload_sha = store_upload_bytes(
        project, b"outcome,predictor\n1,2\n2,3\n", filename="data.csv"
    )
    notebook = service.ensure_default_projection(
        dataset={
            "kind": "dataset",
            "upload_sha256": upload_sha,
            "filename": "data.csv",
            "sheet_names": [],
        },
        created_by="test",
        available_capabilities=["custom.ols"],
    )
    context = service.compile_context(notebook.notebook_id)
    evidence = DataEvidencePackV1(
        source_id=f"dataset:{upload_sha}",
        records=(
            EvidenceRecord(
                evidence_id="evidence.profile",
                inspection_id="profile.v1",
                source_refs=(f"dataset_profile:{upload_sha}",),
                protocol_version="profile/v1",
                status="completed",
                result_hash="sha256:profile-result",
            ),
        ),
    )
    proposal = TypedProposal(
        proposal_id="proposal.custom.ols",
        operation_id="model.genesis",
        target={"dataset_source_id": upload_sha},
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
    )
    draft = OptionDraft(
        rank=1,
        rationale="The server-admitted capability matches the dataset contract.",
        proposal=proposal,
        expected_artifacts=(
            ExpectedArtifact(
                "custom.ols.result", "custom_json", required=True, count=1
            ),
        ),
        option_id="opt.custom.ols",
        capability_id="custom.ols",
        evidence_refs=(
            EvidenceRef(
                evidence_id="evidence.profile",
                result_hash="sha256:profile-result",
                source_refs=(f"dataset_profile:{upload_sha}",),
            ),
        ),
    )
    service.store.append_evidence_pack(notebook.notebook_id, evidence.to_dict())
    context = service.compile_context(notebook.notebook_id)
    normalized, decision = service.derive_server_recommendation(
        notebook.notebook_id,
        context=context,
        drafts=(draft,),
        batch_id="batch.custom.ols",
        evidence_pack=evidence,
    )
    (revision,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=normalized,
        batch_id=decision.batch_id,
        recommendation_decision=decision,
    )
    service.record_decision(
        notebook.notebook_id, revision.option_id, decision="selected", actor="user"
    )
    trace = TraceWriter(
        project,
        scope={
            "project_id": project.name,
            "notebook_id": notebook.notebook_id,
            "run_family_id": notebook.run_family_id,
        },
        versions={
            "app_commit": "commit",
            "model_id": "model",
            "prompt_version": "prompt",
            "vocabulary_version": "vocabulary",
            "context_profile": "notebook/v1",
        },
    )

    result = service.materialize_option(
        notebook.notebook_id,
        revision.option_id,
        context=service.compile_context(notebook.notebook_id),
        trace=trace,
    )

    assert isinstance(result.materialization, OptionMaterializationV11)
    assert (
        result.materialization.capability_resolution_binding_ref
        == binding.content_digest
    )
    assert (
        result.draft.draft["notebook_provenance"]["capability_resolution_binding_ref"]
        == binding.content_digest
    )
    lifecycle_events = [
        event
        for event in TraceWriter.replay(project, trace.trace_id)
        if event["event_type"] == "option.lifecycle.changed/v1"
    ]
    assert lifecycle_events
    assert all(
        event["payload"]["capability_resolution_binding_ref"] == binding.content_digest
        for event in lifecycle_events
    )

    replay = service.materialize_option(
        notebook.notebook_id,
        revision.option_id,
        context=service.compile_context(notebook.notebook_id),
    )
    assert replay.materialization == result.materialization
    assert replay.draft.draft["notebook_provenance"][
        "capability_resolution_binding_ref"
    ] == binding.content_digest

    monkeypatch.setattr(
        catalog,
        "_verifier",
        lambda _candidate: (_ for _ in ()).throw(ValueError("binding revoked")),
    )
    with pytest.raises(OptionRevisionStale, match="currently usable"):
        NotebookOptionMaterializer(service).materialize(
            notebook.notebook_id,
            revision.option_id,
            context=service.compile_context(notebook.notebook_id),
        )
