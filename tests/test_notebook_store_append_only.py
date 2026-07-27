"""Gate 4 — persistence is append-only and crash-recoverable (spec §8, §3.6).

The point of these tests is the negative: no byte previously written is ever
changed. A revision counter that increments over overwritten content (§3.8) is
indistinguishable from this one at the API level and useless at the disk level,
so the assertions look at the file.
"""
from __future__ import annotations

import fcntl
import json
from dataclasses import replace
import multiprocessing
from pathlib import Path

import pytest

from workbench.agent.notebook import NotebookService, OptionDraft, TypedProposal
from workbench.agent.notebook.errors import OptionBatchInvalid
from workbench.agent.notebook.recommendation import (
    ComparisonDecisionRecord,
    RecommendationValidator,
    ServerDecisionRegistry,
    candidate_cohort_hash,
)
from workbench.agent.notebook.store import NotebookStore
from workbench.agent.trace import TraceWriter
from workbench.agent.notebook.vocabulary import DECLARED_ARTIFACT_TYPES
from workbench.contracts.agent.notebook_option import (
    ExpectedArtifact,
    FeasibilityCandidateDecision,
    FeasibilityDecision,
    RecommendationDecisionV11,
)
from workbench.agent.context_compiler import (
    freshness_dependency_fingerprint,
    generation_context_hash,
)

from tests.test_notebook_support import make_project, model_rerun_proposal

_REQUIRED = (
    ExpectedArtifact(
        artifact_id="ts.parameters", artifact_type="time_series_json", required=True, count=1
    ),
)


def _draft(proposal_id: str, covariance: str, option_id: str | None = None) -> OptionDraft:
    return OptionDraft(
        rank=1,
        rationale=covariance,
        proposal=TypedProposal.from_dict(
            model_rerun_proposal(proposal_id, covariance=covariance)
        ),
        expected_artifacts=_REQUIRED,
        option_id=option_id,
    )


def _option_log(project: Path, notebook_id: str, option_id: str) -> Path:
    return project / "notebooks" / notebook_id / "options" / f"{option_id}.jsonl"


def _server_feasibility_decision() -> FeasibilityDecision:
    candidates = (
        FeasibilityCandidateDecision(
            option_id="opt_ets",
            protocol_id="feasibility.v1",
            protocol_version="feasibility/v1",
            inspection_refs=("inspection:opt_ets",),
            evidence_refs=("evidence:opt_ets",),
            outcome="feasible",
            reason_code="PASS",
        ),
        FeasibilityCandidateDecision(
            option_id="opt_arma",
            protocol_id="feasibility.v1",
            protocol_version="feasibility/v1",
            inspection_refs=("inspection:opt_arma",),
            evidence_refs=("evidence:opt_arma",),
            outcome="blocked",
            reason_code="INPUT_CONTRACT_INVALID",
        ),
    )
    option_ids = tuple(item.option_id for item in candidates)
    return FeasibilityDecision(
        feasibility_decision_id="feasibility_1",
        batch_id="batch_1",
        generation_context_hash="sha256:context",
        freshness_dependency_fingerprint="fresh1:fingerprint",
        evidence_pack_hashes=("sha256:evidence",),
        candidate_option_ids=option_ids,
        candidate_cohort_hash=candidate_cohort_hash(option_ids),
        candidates=candidates,
        validator_revision="feasibility-validator/v1",
    )


def _server_comparison_decision() -> ComparisonDecisionRecord:
    option_ids = ("opt_ets", "opt_arma")
    return ComparisonDecisionRecord(
        comparison_decision_id="comparison_1",
        batch_id="batch_1",
        generation_context_hash="sha256:context",
        freshness_dependency_fingerprint="fresh1:fingerprint",
        evidence_pack_hashes=("sha256:evidence",),
        candidate_option_ids=option_ids,
        candidate_cohort_hash=candidate_cohort_hash(option_ids),
        outcome="recommended",
        recommended_option_id="opt_ets",
        protocol_ref="comparison.v1",
    )


def _append_jsonl_child(path: str, started: object, finished: object) -> None:
    from workbench.agent.storage import append_jsonl_atomic

    started.set()  # type: ignore[attr-defined]
    append_jsonl_atomic(Path(path), {"worker": "child"})
    finished.set()  # type: ignore[attr-defined]


def test_append_jsonl_atomic_serializes_writers_across_processes(tmp_path: Path) -> None:
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("process-lock test requires fork")
    path = tmp_path / "records.jsonl"
    path.write_text('{"worker":"seed"}\n', encoding="utf-8")
    lock_path = path.with_name(f".{path.name}.lock")
    context = multiprocessing.get_context("fork")
    started = context.Event()
    finished = context.Event()
    child = context.Process(
        target=_append_jsonl_child,
        args=(str(path), started, finished),
    )

    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        child.start()
        assert started.wait(timeout=5)
        assert not finished.wait(timeout=0.25)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    child.join(timeout=5)
    assert child.exitcode == 0
    assert finished.is_set()
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [record["worker"] for record in records] == ["seed", "child"]


def test_server_decisions_survive_store_restart_without_duplicate_records(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="Decision store", created_by="u")
    feasibility = _server_feasibility_decision()
    comparison = _server_comparison_decision()
    store = NotebookStore(project)

    store.append_server_decision(notebook.notebook_id, feasibility)
    store.append_server_decision(notebook.notebook_id, feasibility)
    store.append_server_decision(notebook.notebook_id, comparison)

    reopened = NotebookStore(project)
    registry = reopened.read_server_decision_registry(notebook.notebook_id)
    assert isinstance(registry, ServerDecisionRegistry)
    assert registry.feasibility(feasibility.feasibility_decision_id) == feasibility
    assert registry.comparison(comparison.comparison_decision_id) == comparison

    records = [
        json.loads(line)
        for line in (project / "notebooks" / notebook.notebook_id / "notebook.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert [record["record_type"] for record in records].count("feasibility_decision") == 1
    assert [record["record_type"] for record in records].count("comparison_decision") == 1


def test_server_decision_persistence_rejects_conflicting_reuse_of_a_reference(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="Decision conflict", created_by="u")
    store = NotebookStore(project)
    decision = _server_feasibility_decision()
    store.append_server_decision(notebook.notebook_id, decision)

    conflict = replace(decision, batch_id="batch_other")
    with pytest.raises(ValueError, match="conflicting server decision"):
        store.append_server_decision(notebook.notebook_id, conflict)

    assert (
        store.read_server_decision_registry(notebook.notebook_id).feasibility(
            decision.feasibility_decision_id
        )
        == decision
    )


def test_persisted_server_registry_drives_v11_recommendation_service_lifecycle(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="V11 lifecycle", created_by="u")
    context = service.compile_context(notebook.notebook_id)
    source = replace(
        _server_feasibility_decision(),
        batch_id="batch_v11_service",
        generation_context_hash=generation_context_hash(context),
        freshness_dependency_fingerprint=freshness_dependency_fingerprint(context),
    )
    service.persist_server_decision(notebook.notebook_id, source)
    decision = RecommendationValidator().decide_v11(
        batch_id=source.batch_id,
        candidate_option_ids=source.candidate_option_ids,
        generation_context_hash=source.generation_context_hash,
        freshness_dependency_fingerprint=source.freshness_dependency_fingerprint,
        evidence_pack_hashes=source.evidence_pack_hashes,
        decision_registry=service.read_server_decision_registry(notebook.notebook_id),
        feasibility_decision_ref=source.feasibility_decision_id,
    )
    assert isinstance(decision, RecommendationDecisionV11)
    drafts = [
        replace(_draft("p_ets", "robust", option_id="opt_ets"),
                recommendation_decision_id=decision.recommendation_decision_id,
                recommendation_status=decision.outcome),
        replace(_draft("p_arma", "clustered", option_id="opt_arma"),
                rank=2,
                recommendation_decision_id=decision.recommendation_decision_id,
                recommendation_status=decision.outcome),
    ]

    revisions = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=drafts,
        batch_id=decision.batch_id,
        recommendation_decision=decision,
    )

    assert len(revisions) == 2
    assert service.store.read_decision(notebook.notebook_id, decision.batch_id) == decision
    reopened = NotebookService(project)
    assert reopened.store.read_decision(notebook.notebook_id, decision.batch_id) == decision


def test_v11_recommendation_without_persisted_source_fails_before_any_write(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="V11 fail closed", created_by="u")
    context = service.compile_context(notebook.notebook_id)
    source = replace(
        _server_feasibility_decision(),
        batch_id="batch_v11_unpersisted",
        generation_context_hash=generation_context_hash(context),
        freshness_dependency_fingerprint=freshness_dependency_fingerprint(context),
    )
    in_memory_registry = ServerDecisionRegistry()
    in_memory_registry.register_feasibility(source)
    decision = RecommendationValidator().decide_v11(
        batch_id=source.batch_id,
        candidate_option_ids=source.candidate_option_ids,
        generation_context_hash=source.generation_context_hash,
        freshness_dependency_fingerprint=source.freshness_dependency_fingerprint,
        evidence_pack_hashes=source.evidence_pack_hashes,
        decision_registry=in_memory_registry,
        feasibility_decision_ref=source.feasibility_decision_id,
    )
    drafts = [
        replace(_draft("p_ets", "robust", option_id="opt_ets"),
                recommendation_decision_id=decision.recommendation_decision_id,
                recommendation_status=decision.outcome),
        replace(_draft("p_arma", "clustered", option_id="opt_arma"),
                rank=2,
                recommendation_decision_id=decision.recommendation_decision_id,
                recommendation_status=decision.outcome),
    ]

    with pytest.raises(OptionBatchInvalid) as caught:
        service.propose_batch(
            notebook.notebook_id,
            context=context,
            drafts=drafts,
            batch_id=decision.batch_id,
            recommendation_decision=decision,
        )

    assert caught.value.code == "OPTION_RECOMMENDATION_DECISION_UNAVAILABLE"
    assert service.store.option_ids(notebook.notebook_id) == []
    assert service.store.read_decision(notebook.notebook_id, decision.batch_id) is None


def test_store_rejects_direct_v11_recommendation_without_persisted_source(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="V11 store boundary", created_by="u")
    context = service.compile_context(notebook.notebook_id)
    source = replace(
        _server_feasibility_decision(),
        batch_id="batch_v11_store_boundary",
        generation_context_hash=generation_context_hash(context),
        freshness_dependency_fingerprint=freshness_dependency_fingerprint(context),
    )
    registry = ServerDecisionRegistry()
    registry.register_feasibility(source)
    decision = RecommendationValidator().decide_v11(
        batch_id=source.batch_id,
        candidate_option_ids=source.candidate_option_ids,
        generation_context_hash=source.generation_context_hash,
        freshness_dependency_fingerprint=source.freshness_dependency_fingerprint,
        evidence_pack_hashes=source.evidence_pack_hashes,
        decision_registry=registry,
        feasibility_decision_ref=source.feasibility_decision_id,
    )

    with pytest.raises(ValueError, match="not backed"):
        service.store.append_decision(notebook.notebook_id, decision)

    assert service.store.read_decision(notebook.notebook_id, decision.batch_id) is None


def test_the_option_log_only_ever_grows(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="n", created_by="u")
    (option,) = service.propose_batch(
        notebook.notebook_id,
        context=service.compile_context(notebook.notebook_id),
        drafts=[_draft("p1", "robust")],
    )
    path = _option_log(project, notebook.notebook_id, option.option_id)
    prefix = path.read_bytes()

    service.record_decision(
        notebook.notebook_id, option.option_id, decision="deferred", actor="u"
    )
    service.set_focus(notebook.notebook_id, user_focus={"selected_text_hash": "sha256:zzz"})
    service.revalidate_option(
        notebook.notebook_id,
        option.option_id,
        context=service.compile_context(notebook.notebook_id),
        draft=_draft("p2", "clustered", option_id=option.option_id),
    )

    after = path.read_bytes()
    assert after.startswith(prefix)
    assert len(after) > len(prefix)

    records = [json.loads(line) for line in after.decode("utf-8").splitlines() if line.strip()]
    assert [r["record_type"] for r in records] == [
        "option",
        "revision",
        "lifecycle",
        "lifecycle",
        "revision",
    ]
    revisions = [r for r in records if r["record_type"] == "revision"]
    assert [r["option_revision"] for r in revisions] == [1, 2]
    # Revision 1 still names its own proposal, not revision 2's.
    assert revisions[0]["typed_proposal"]["proposal_id"] == "p1"
    assert revisions[0]["typed_proposal"]["changes"]["model_options"]["covariance"] == "robust"
    assert revisions[1]["typed_proposal"]["changes"]["model_options"]["covariance"] == (
        "clustered"
    )
    assert revisions[1]["revision"]["supersedes_option_revision"] == 1
    # Lifecycle survived the new revision: deferred + stale + valid is legal (§3.4).
    assert service.option_view(
        notebook.notebook_id, option.option_id
    ).lifecycle_status == "deferred"


def test_a_notebook_and_its_options_survive_a_process_restart(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    first = NotebookService(project)
    notebook = first.create_notebook(title="Restart", created_by="u")
    (option,) = first.propose_batch(
        notebook.notebook_id,
        context=first.compile_context(notebook.notebook_id),
        drafts=[_draft("p1", "robust")],
    )

    reopened = NotebookService(project)
    view = reopened.option_view(notebook.notebook_id, option.option_id)

    assert reopened.get_notebook(notebook.notebook_id).title == "Restart"
    assert view.current_revision.to_dict() == option.to_dict()
    assert view.current_stored_revision.proposal.proposal_id == "p1"
    assert view.lifecycle_status == "proposed"
    assert [n.notebook_id for n in reopened.list_notebooks()] == [notebook.notebook_id]


def test_first_persisted_trace_adopts_richest_legacy_notebook_trace(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="Trace migration", created_by="u")
    legacy = TraceWriter(
        project,
        scope={
            "project_id": project.name,
            "notebook_id": notebook.notebook_id,
            "run_family_id": notebook.run_family_id,
        },
        versions={
            "app_commit": "test",
            "model_id": "test",
            "prompt_version": "test",
            "vocabulary_version": "test",
            "context_profile": "test",
        },
    )
    other = TraceWriter(
        project,
        scope=legacy.scope,
        versions=legacy.versions,
    )
    # TraceWriter validates event payloads; context.compiled is the smallest
    # real event and is enough to distinguish the richer historical trace.
    for index in range(2):
        legacy.emit(
            "context.compiled",
            payload={
                "context_id": f"ctx_{index}",
                "generation_context_hash": f"sha256:{index}",
                "freshness_dependency_fingerprint": f"fresh:{index}",
                "compiled_context_blob_ref": f"blob:{index}",
                "omitted_sections": [],
                "content_chars": 10 + index,
            },
        )
    other.emit(
        "context.compiled",
        payload={
            "context_id": "ctx_other",
            "generation_context_hash": "sha256:other",
            "freshness_dependency_fingerprint": "fresh:other",
            "compiled_context_blob_ref": "blob:other",
            "omitted_sections": [],
            "content_chars": 12,
        },
    )

    trace_id = NotebookStore(project).ensure_trace_id(notebook.notebook_id)

    assert trace_id == legacy.trace_id
    assert NotebookStore(project).get_notebook(notebook.notebook_id).trace_id == trace_id


def test_the_published_vocabulary_matches_the_packs_required_artifacts() -> None:
    """§5.4 — the vocabulary is a promise about what the system really produces.

    Imports the pack's own list rather than restating it: if a pack adds or
    renames a logical artifact, this fails instead of letting the notebook layer
    quietly promise something that no longer exists.
    """
    from workbench.engine.packs.arma_garch.runner import _REQUIRED_LOGICAL_ARTIFACTS

    assert set(DECLARED_ARTIFACT_TYPES) == set(_REQUIRED_LOGICAL_ARTIFACTS)
    assert DECLARED_ARTIFACT_TYPES["ts.artifact_manifest"] == "time_series_manifest"
    assert DECLARED_ARTIFACT_TYPES["ts.parameters"] == "time_series_json"
