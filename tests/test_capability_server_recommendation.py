from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from test_notebook_capability_binding import _draft, _service_with_catalog
from tests.test_notebook_support import make_project
from workbench.agent.notebook.evidence import DataEvidencePackV1, EvidenceRecord
from workbench.agent.notebook.errors import OptionBatchInvalid
from workbench.canonical import sha256_canonical
from workbench.contracts.agent.notebook_option import EvidenceRef
from workbench.contracts.agent.notebook_option import RecommendationDecisionV11
from workbench.capability_factory.trace_contracts import CapabilityTraceEvent


def _evidence() -> DataEvidencePackV1:
    return DataEvidencePackV1(
        source_id="source.alpha",
        records=(
            EvidenceRecord(
                evidence_id="evidence.alpha",
                inspection_id="inspection.alpha",
                source_refs=("source.alpha",),
                protocol_version="inspection/v1",
                status="completed",
                result_hash="sha256:evidence-alpha",
            ),
        ),
    )


def test_server_stage_persists_complete_feasibility_before_v11_recommendation(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path, name="project.alpha")
    service, notebook, _binding, _catalog = _service_with_catalog(project)
    context = service.compile_context(notebook.notebook_id)
    drafts = (
        replace(
            _draft(capability_id="capability.registered", option_id="opt.alpha"),
            proposal=replace(_draft(capability_id="capability.registered", option_id="opt.alpha").proposal, proposal_id="proposal.alpha"),
            blocked_reason="agent_claim_must_not_become_server_fact",
        ),
        replace(
            _draft(capability_id="capability.registered", option_id="opt.beta", proposal_id="proposal.beta"),
            proposal=replace(
                _draft(capability_id="capability.registered", option_id="opt.beta").proposal,
                changes={"model_options": {"covariance": "classic"}},
            ),
            rank=2,
        ),
    )

    normalized, decision = service.derive_server_recommendation(
        notebook.notebook_id,
        context=context,
        drafts=drafts,
        batch_id="batch.server",
        evidence_pack=_evidence(),
    )

    assert isinstance(decision, RecommendationDecisionV11)
    assert decision.outcome == "insufficient_evidence"
    assert decision.recommended_option_id is None
    assert decision.feasibility_decision_ref is not None
    source = service.read_server_decision_registry(notebook.notebook_id).feasibility(
        decision.feasibility_decision_ref
    )
    assert source.candidate_option_ids == ("opt.alpha", "opt.beta")
    assert all(item.outcome == "feasible" for item in source.candidates)
    assert [draft.recommendation_decision_id for draft in normalized] == [
        decision.recommendation_decision_id,
        decision.recommendation_decision_id,
    ]
    assert all(draft.recommendation_status == "insufficient_evidence" for draft in normalized)


def test_single_server_validated_candidate_gets_v11_recommendation(tmp_path: Path) -> None:
    project = make_project(tmp_path, name="project.alpha")
    service, notebook, _binding, _catalog = _service_with_catalog(project)
    context = service.compile_context(notebook.notebook_id)

    normalized, decision = service.derive_server_recommendation(
        notebook.notebook_id,
        context=context,
        drafts=(_draft(capability_id="capability.registered", option_id="opt.alpha"),),
        batch_id="batch.single",
        evidence_pack=_evidence(),
    )

    assert decision.outcome == "recommended"
    assert decision.recommended_option_id == "opt.alpha"
    assert normalized[0].recommendation_decision_id == decision.recommendation_decision_id
    assert normalized[0].recommendation_status == "recommended"


def test_server_recommendation_uses_only_referenced_completed_evidence(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path, name="project.alpha")
    service, notebook, _binding, _catalog = _service_with_catalog(project)
    context = service.compile_context(notebook.notebook_id)
    partial = EvidenceRecord(
        evidence_id="evidence.sample",
        inspection_id="sample.v1",
        source_refs=("source.alpha",),
        protocol_version="sample/v1",
        status="partial",
        omissions=({"section": "sample.columns", "reason": "sample_column_cap"},),
    )
    full_pack = DataEvidencePackV1(
        source_id="source.alpha",
        records=(*_evidence().records, partial),
    )

    draft = replace(
        _draft(capability_id="capability.registered", option_id="opt.alpha"),
        evidence_refs=(
            EvidenceRef(
                evidence_id="evidence.alpha",
                result_hash=_evidence().records[0].result_hash,
                source_refs=("source.alpha",),
            ),
        ),
    )

    _normalized, decision = service.derive_server_recommendation(
        notebook.notebook_id,
        context=context,
        drafts=(draft,),
        batch_id="batch.partial-limitation",
        evidence_pack=full_pack,
    )

    assert decision.outcome == "recommended"
    assert decision.evidence_pack_hashes == (_evidence().evidence_pack_hash,)
    assert (
        service.store.read_evidence_pack(
            notebook.notebook_id, full_pack.evidence_pack_hash
        )
        is not None
    )


def test_server_recommendation_rejects_a_referenced_partial_record(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path, name="project.alpha")
    service, notebook, _binding, _catalog = _service_with_catalog(project)
    context = service.compile_context(notebook.notebook_id)
    partial = EvidenceRecord(
        evidence_id="evidence.sample",
        inspection_id="sample.v1",
        source_refs=("source.alpha",),
        protocol_version="sample/v1",
        status="partial",
        result_hash="sha256:partial",
        omissions=({"section": "sample.columns", "reason": "sample_column_cap"},),
    )
    draft = replace(
        _draft(capability_id="capability.registered", option_id="opt.alpha"),
        evidence_refs=(
            EvidenceRef(
                evidence_id=partial.evidence_id,
                result_hash=partial.result_hash,
                source_refs=partial.source_refs,
            ),
        ),
    )

    with pytest.raises(OptionBatchInvalid) as error:
        service.derive_server_recommendation(
            notebook.notebook_id,
            context=context,
            drafts=(draft,),
            batch_id="batch.partial-reference",
            evidence_pack=DataEvidencePackV1(
                source_id="source.alpha",
                records=(*_evidence().records, partial),
            ),
        )

    assert error.value.code == "OPTION_SERVER_FEASIBILITY_INCOMPLETE"


def test_server_feasibility_emits_a_bounded_capability_trace_event(tmp_path: Path) -> None:
    project = make_project(tmp_path, name="project.alpha")
    service, notebook, _binding, _catalog = _service_with_catalog(project)
    events: list[CapabilityTraceEvent] = []

    context = service.compile_context(notebook.notebook_id)
    _normalized, decision = service.derive_server_recommendation(
        notebook.notebook_id,
        context=context,
        drafts=(_draft(capability_id="capability.registered", option_id="opt.alpha"),),
        batch_id="batch.trace",
        evidence_pack=_evidence(),
        capability_trace_sink=events.append,
    )

    assert len(events) == 1
    event = events[0]
    assert event.event_type == "option.feasibility.decided"
    assert event.payload["decision_ref"] == sha256_canonical(decision.to_dict())
    assert event.payload["candidate_cohort_ref"] == decision.candidate_cohort_hash
    assert event.payload["outcome"] == decision.outcome


def test_server_stage_rejects_uncovered_candidate_evidence_before_source_write(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path, name="project.alpha")
    service, notebook, _binding, _catalog = _service_with_catalog(project)
    context = service.compile_context(notebook.notebook_id)
    draft = replace(
        _draft(capability_id="capability.registered", option_id="opt.alpha"),
        evidence_refs=(
            EvidenceRef(
                evidence_id="evidence.missing",
                result_hash="sha256:missing",
                source_refs=("source.alpha",),
            ),
        ),
    )

    with pytest.raises(OptionBatchInvalid) as error:
        service.derive_server_recommendation(
            notebook.notebook_id,
            context=context,
            drafts=(draft,),
            batch_id="batch.invalid-evidence",
            evidence_pack=_evidence(),
        )

    assert error.value.code == "OPTION_SERVER_EVIDENCE_BINDING_INVALID"
    assert service.read_server_decision_registry(notebook.notebook_id).get(
        "feasibility_batch.invalid-evidence"
    ) is None
    assert service.store.read_evidence_pack(
        notebook.notebook_id, _evidence().evidence_pack_hash
    ) is None
