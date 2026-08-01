from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from workbench.agent.context_compiler import (
    attach_domain_memory_projection,
    compile_notebook_planning_context,
    freshness_dependency_fingerprint,
    generation_context_hash,
    notebook_planning_workbench_context,
)
from workbench.agent.notebook.memory_defaults import (
    MemoryDefaultApplicationError,
    apply_memory_defaults,
    validate_memory_default_sources,
)
from workbench.agent.notebook import NotebookService, OptionDraft
from workbench.agent.notebook.errors import OptionRevisionStale
from workbench.agent.notebook.proposal import TypedProposal
from workbench.contracts.agent.notebook_option import (
    EvidenceRef,
    ExpectedArtifact,
    MemoryDefaultSource,
    NotebookOptionRevisionV11,
    NotebookOptionRevisionV13,
    RecommendationDecision,
)
from workbench.domain_memory.candidate_store import MemoryCandidateStore
from workbench.domain_memory.contracts import (
    DomainMemoryApprovalRecord,
    DomainMemoryContentRevision,
    DomainMemoryValidityRecord,
    MemoryVerifier,
    SourceSummaryRef,
)
from workbench.domain_memory.preflight import collect_domain_memory_preflight
from workbench.domain_memory.redaction import build_redacted_summary_snapshot
from workbench.domain_memory.service import DomainMemoryService
from workbench.domain_memory.scope import MemoryScope
from workbench.domain_memory.source_access import (
    SourceAccessBinding,
    SourceAccessValidityRecord,
)
from workbench.domain_memory.store import DomainMemoryStore
from workbench.http.notebook_routes import _domain_memory_projection
from tests.test_notebook_support import make_project


def _context(tmp_path: Path):
    return compile_notebook_planning_context(
        tmp_path,
        notebook_id="notebook-1",
        run_family_id="family-1",
        active_head_run_id=None,
        analysis_contract={"question": "bounded"},
        user_focus={"section": "model"},
    )


def _memory_projection(*entries: dict[str, object]) -> dict[str, object]:
    return {
        "contract_version": "domain-memory-context-input/v2",
        "retrieval_ref": "retrieval-1",
        "scope_ref": "scope-1",
        "outcome": "used" if entries else "empty",
        "reason": "approved hint",
        "entries": list(entries),
        "omissions": [],
        "bounded": True,
        "preference_ref": "preference-1",
        "memory_authority": "non_authoritative",
    }


def _memory_hint(
    *,
    memory_id: str = "memory-1",
    revision: int = 1,
    apply_mode: str = "suggest_default",
    target_ref: str = "model.genesis.ols.covariance.unadjusted",
) -> dict[str, object]:
    return {
        "memory_id": memory_id,
        "revision": revision,
        "content_hash": "a" * 64,
        "memory_kind": "project_domain_fact",
        "domain_tags": ["domain-a"],
        "compact_lesson": "The approved analysis convention uses unadjusted covariance.",
        "recommended_effect_kind": "assumption_check_hint",
        "recommended_target_refs": [target_ref],
        "source_summary_refs": ["summary-1"],
        "match_reason": ["goal"],
        "apply_mode": apply_mode,
        "apply_mode_reason": "verifier_current" if apply_mode == "suggest_default" else "declared_inform_only",
        "memory_source": {"memory_id": memory_id, "revision": revision},
        "memory_authority": "non_authoritative_hint",
    }


def _ols_genesis_proposal() -> TypedProposal:
    return TypedProposal(
        proposal_id="proposal-1",
        operation_id="model.genesis",
        target={"dataset_source_id": "upload-1"},
        preconditions={"context_version": "node-operation-context/v1"},
        changes={"model_params": {"model_type": "ols", "y": "outcome", "x": ["exposure"]}},
    )


def _approved_memory_store(
    tmp_path: Path,
    *,
    verifier: MemoryVerifier | None,
    last_validated_at: str | None,
    expires_at: str | None,
) -> DomainMemoryStore:
    scope = MemoryScope("ns-memory", "profile-memory", "user-memory", None, "private", "user")
    store = DomainMemoryStore(tmp_path / "approved-memory", scope)
    snapshot = build_redacted_summary_snapshot(
        summary_text="Reviewed domain-memory source.",
        source_ref="source-memory",
        source_kind="trace_summary",
        redaction_subject="subject-memory",
    )
    binding = SourceAccessBinding(
        "binding-memory",
        scope,
        snapshot.summary_snapshot_ref,
        snapshot.summary_snapshot_hash,
        snapshot.summary_schema_version,
        snapshot.redaction_assessment_ref,
        snapshot.redaction_subject_hash,
        snapshot.source_kind,
        snapshot.source_ref,
        scope.namespace_id,
        scope.profile_id,
        scope.owner_id,
        scope.organization_id,
        "grant-memory",
        None,
    )
    store.append_binding(binding)
    store.append_source_validity(
        SourceAccessValidityRecord(
            "binding-memory", 1, 1, "valid", "2026-08-01T00:00:00Z", "granted", "acl-v1", ("acl-memory",)
        )
    )
    content = DomainMemoryContentRevision(
        "memory-preflight",
        1,
        scope,
        ("domain-memory",),
        "project_domain_fact",
        ({"predicate_id": "goal", "operator": "exists", "value": None},),
        "The approved convention is current only while its verifier remains current.",
        "assumption_check_hint",
        ("model.genesis.ols.covariance.robust",),
        (
            SourceSummaryRef(
                "project-memory",
                snapshot.summary_snapshot_ref,
                snapshot.summary_snapshot_hash,
                snapshot.summary_schema_version,
                "binding-memory",
            ),
        ),
        "independently_reviewed",
        "2026-08-10T00:00:00Z",
        None,
        (),
        "user-memory",
        apply_mode="suggest_default",
        vocabulary_version="notebook-memory-defaults-v1",
        verifier=verifier,
        last_validated_at=last_validated_at,
        expires_at=expires_at,
    )
    store.append_content(content)
    approval = DomainMemoryApprovalRecord(
        "approval-memory",
        content.memory_id,
        content.revision,
        content.content_hash,
        scope,
        "user-memory",
        "2026-08-01T00:00:00Z",
        None,
        None,
        1,
    )
    store.append_approval(approval)
    store.append_validity(
        DomainMemoryValidityRecord(
            approval.approval_ref,
            content.memory_id,
            content.revision,
            1,
            1,
            "active",
            "2026-08-01T00:00:00Z",
            "approved",
            "user-review",
            ("review-memory",),
        )
    )
    return store


def test_domain_memory_projection_is_visible_but_not_a_freshness_dependency(tmp_path: Path) -> None:
    base = _context(tmp_path)
    assert "domain_memory_projection" not in base.to_dict()
    projection = {
        "contract_version": "domain-memory-context-input/v1",
        "retrieval_ref": "retrieval-1",
        "scope_ref": "scope-1",
        "outcome": "used",
        "reason": "approved hint",
        "entries": [{
            "memory_id": "memory-1",
            "revision": 1,
            "content_hash": "sha256:memory",
            "memory_kind": "workflow_lesson",
            "domain_tags": ["econometrics"],
            "compact_lesson": "check clusters",
            "recommended_effect_kind": "assumption_check_hint",
            "recommended_target_refs": ["model"],
            "source_summary_refs": ["summary-1"],
            "match_reason": ["analysis_family=ols"],
            "memory_authority": "non_authoritative_hint",
        }],
        "omissions": [],
        "bounded": True,
        "preference_ref": "preference-1",
        "memory_authority": "non_authoritative",
    }

    attached = attach_domain_memory_projection(base, projection)

    assert attached.domain_memory_projection == projection
    assert generation_context_hash(attached) != generation_context_hash(base)
    assert freshness_dependency_fingerprint(attached) == freshness_dependency_fingerprint(base)
    assert (
        notebook_planning_workbench_context(attached)["content"]["domain_memory_projection"]
        == projection
    )


def test_memory_v2_projection_preserves_apply_mode_without_becoming_a_freshness_input(
    tmp_path: Path,
) -> None:
    base = _context(tmp_path)
    projection = _memory_projection(_memory_hint())

    attached = attach_domain_memory_projection(base, projection)

    entry = attached.domain_memory_projection["entries"][0]
    assert entry["apply_mode"] == "suggest_default"
    assert entry["memory_source"] == {"memory_id": "memory-1", "revision": 1}
    assert generation_context_hash(attached) != generation_context_hash(base)
    assert freshness_dependency_fingerprint(attached) == freshness_dependency_fingerprint(base)


def test_memory_defaults_are_atomic_provenanced_and_fail_closed(tmp_path: Path) -> None:
    proposal = _ols_genesis_proposal()
    projection = _memory_projection(_memory_hint())

    defaulted = apply_memory_defaults(proposal, projection)

    assert defaulted.changes["model_options"] == {"covariance": "unadjusted"}
    assert defaulted.memory_default_sources == (
        MemoryDefaultSource(
            memory_id="memory-1",
            revision=1,
            target_ref="model.genesis.ols.covariance.unadjusted",
        ),
    )
    assert defaulted.canonical_hash() != proposal.canonical_hash()
    validate_memory_default_sources(defaulted, projection)

    inform_only = apply_memory_defaults(
        proposal,
        _memory_projection(_memory_hint(apply_mode="inform_only")),
    )
    assert inform_only == proposal

    conflict = apply_memory_defaults(
        proposal,
        _memory_projection(
            _memory_hint(),
            _memory_hint(
                memory_id="memory-2",
                target_ref="model.genesis.ols.covariance.robust",
            ),
        ),
    )
    assert conflict == proposal

    with pytest.raises(MemoryDefaultApplicationError, match="source is not current"):
        validate_memory_default_sources(
            defaulted,
            _memory_projection(_memory_hint(revision=2)),
        )


def test_memory_preflight_reports_expiry_and_default_verifier_risks_without_blocking(
    tmp_path: Path,
) -> None:
    missing_verifier = _approved_memory_store(
        tmp_path / "missing",
        verifier=None,
        last_validated_at=None,
        expires_at="2026-08-02T00:00:00Z",
    )
    stale_verifier = _approved_memory_store(
        tmp_path / "stale",
        verifier=MemoryVerifier("verify-memory", 60),
        last_validated_at="2026-07-01T00:00:00Z",
        expires_at=None,
    )

    missing = collect_domain_memory_preflight(
        missing_verifier,
        now="2026-08-01T00:00:00Z",
        warning_window_seconds=172800,
    )
    stale = collect_domain_memory_preflight(
        stale_verifier,
        now="2026-08-01T00:00:00Z",
        warning_window_seconds=172800,
    )

    assert {item.code for item in missing.findings} == {"EXPIRES_SOON", "VERIFIER_MISSING"}
    assert {item.code for item in stale.findings} == {"VERIFIER_STALE"}
    assert missing.approved_count == 1
    assert stale.approved_count == 1


def test_memory_default_provenance_persists_as_a_v13_option_revision(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    notebook = service.create_notebook(title="memory provenance", created_by="user-memory")
    context = attach_domain_memory_projection(
        service.compile_context(notebook.notebook_id),
        _memory_projection(
            _memory_hint(
                memory_id="memory-ols-covariance",
                revision=2,
                target_ref="model.genesis.ols.covariance.robust",
            )
        ),
    )
    proposal = apply_memory_defaults(
        TypedProposal(
            proposal_id="proposal-memory-persisted",
            operation_id="model.genesis",
            target={"dataset_source_id": "upload-memory"},
            preconditions={
                "context_version": "node-operation-context/v1",
                "context_fingerprint": freshness_dependency_fingerprint(context),
                "owner_resolution": "single_candidate",
            },
            changes={"model_params": {"model_type": "ols", "y": "outcome", "x": ["exposure"]}},
        ),
        context.domain_memory_projection,
    )
    (revision,) = service.propose_batch(
        notebook.notebook_id,
        context=context,
        drafts=(
            OptionDraft(
                rank=1,
                rationale="The source columns support the declared OLS model.",
                proposal=proposal,
                expected_artifacts=(ExpectedArtifact("ols_1", "model_result", True, 1),),
                capability_id="ols",
                option_id="option-memory-persisted",
                evidence_refs=(EvidenceRef("evidence-memory", "hash-memory", ("source-memory",)),),
                comparative_claims=("The sole candidate is supported by completed evidence.",),
                recommendation_decision_id="decision-memory",
                recommendation_status="recommended",
            ),
        ),
        recommendation_decision=RecommendationDecision(
            "decision-memory",
            "batch-memory",
            "context-memory",
            "freshness-memory",
            ("evidence-memory",),
            (),
            ("option-memory-persisted",),
            "recommended",
            "option-memory-persisted",
            ("evidence-memory",),
        ),
    )

    assert isinstance(revision, NotebookOptionRevisionV13)
    assert revision.memory_default_sources == (
        MemoryDefaultSource(
            memory_id="memory-ols-covariance",
            revision=2,
            target_ref="model.genesis.ols.covariance.robust",
        ),
    )
    assert (
        service.store.read_option(notebook.notebook_id, "option-memory-persisted")
        .current_revision.to_dict()["memory_default_sources"]
        == [item.to_dict() for item in revision.memory_default_sources]
    )
    with pytest.raises(OptionRevisionStale, match="memory default is no longer current"):
        service._assert_current_memory_default_sources(
            service.store.read_option(notebook.notebook_id, "option-memory-persisted"),
            attach_domain_memory_projection(
                service.compile_context(notebook.notebook_id),
                _memory_projection(_memory_hint(apply_mode="inform_only")),
            ),
        )

    inform_context = attach_domain_memory_projection(
        service.compile_context(notebook.notebook_id),
        _memory_projection(_memory_hint(apply_mode="inform_only")),
    )
    revalidated = service.revalidate_option(
        notebook.notebook_id,
        "option-memory-persisted",
        context=inform_context,
        draft=OptionDraft(
            rank=1,
            rationale="The user retained the same covariance explicitly after revalidation.",
            proposal=replace(proposal, memory_default_sources=()),
            expected_artifacts=(ExpectedArtifact("ols_1", "model_result", True, 1),),
            capability_id="ols",
            option_id="option-memory-persisted",
            evidence_refs=(EvidenceRef("evidence-memory", "hash-memory", ("source-memory",)),),
            comparative_claims=("The sole candidate is supported by completed evidence.",),
        ),
    )
    assert isinstance(revalidated, NotebookOptionRevisionV11)
    assert not isinstance(revalidated, NotebookOptionRevisionV13)


def test_invalid_or_oversized_domain_memory_projection_fails_closed(tmp_path: Path) -> None:
    base = _context(tmp_path)
    with pytest.raises(ValueError, match="invalid contract shape"):
        attach_domain_memory_projection(base, {"entries": []})
    with pytest.raises(ValueError, match="bounded"):
        attach_domain_memory_projection(
            base,
            {
                "contract_version": "domain-memory-context-input/v1",
                "retrieval_ref": "retrieval-1",
                "scope_ref": "scope-1",
                "outcome": "used",
                "reason": "invalid",
                "entries": [],
                "omissions": [],
                "memory_authority": "non_authoritative",
                "bounded": False,
                "preference_ref": "preference-1",
            },
        )


def test_notebook_provider_is_opt_in_and_receives_independent_preferences(tmp_path: Path) -> None:
    calls: list[object] = []
    projection = {
        "contract_version": "domain-memory-context-input/v1",
        "retrieval_ref": "retrieval-1",
        "scope_ref": "scope-1",
        "outcome": "used",
        "reason": "approved hint",
        "entries": [],
        "omissions": [],
        "bounded": True,
        "preference_ref": "preference-1",
        "memory_authority": "non_authoritative",
    }

    def provider(**kwargs):
        calls.append(kwargs["preferences"])
        return projection

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(domain_memory_context_provider=provider))
    )
    assert _domain_memory_projection(request, tmp_path, object(), "notebook-1", use=False, iteration=True) is None
    assert calls == []
    assert _domain_memory_projection(request, tmp_path, object(), "notebook-1", use=True, iteration=False) == projection
    assert calls[0].cross_project_domain_memory_use is True
    assert calls[0].cross_project_domain_memory_iteration is False


def test_notebook_provider_receives_compiled_project_context_before_memory_lookup(
    tmp_path: Path,
) -> None:
    seen: list[NotebookPlanningContextV1] = []
    base = _context(tmp_path)

    def provider(**kwargs):
        seen.append(kwargs["context"])
        return None

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(domain_memory_context_provider=provider))
    )
    assert (
        _domain_memory_projection(
            request,
            tmp_path,
            object(),
            "notebook-1",
            context=base,
            use=True,
            iteration=False,
        )
        is None
    )
    assert seen == [base]
    assert base.analysis_contract == {"question": "bounded"}
    assert base.domain_memory_projection is None


def test_configured_memory_service_is_the_default_read_only_notebook_provider(
    tmp_path: Path,
) -> None:
    scope = MemoryScope("ns-a", "profile-a", "user-a", None, "private", "user")
    service = DomainMemoryService(
        DomainMemoryStore(tmp_path / "memory", scope),
        MemoryCandidateStore(tmp_path / "memory", scope),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                domain_memory_context_provider=None,
                domain_memory_service=service,
            )
        )
    )

    projection = _domain_memory_projection(
        request,
        tmp_path,
        object(),
        "notebook-1",
        context=_context(tmp_path),
        use=True,
        iteration=False,
    )

    assert projection is not None
    assert projection["outcome"] == "empty"
    assert projection["memory_authority"] == "non_authoritative"
    assert projection["entries"] == []
