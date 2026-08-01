from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
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
from workbench.canonical import canonical_json_v1
from workbench.agent.notebook.memory_defaults import (
    MemoryDefaultApplicationError,
    apply_memory_defaults,
    validate_memory_default_sources,
)
from workbench.agent.notebook.evidence import DataEvidencePackV1, EvidenceRecord
from workbench.agent.notebook.planning_agent import (
    AgentOptionSubmission,
    NotebookPlanningAgent,
)
from workbench.agent.notebook.producer import option_drafts_from_submissions
from workbench.agent.notebook import NotebookService, OptionDraft
from workbench.agent.notebook.errors import OptionRevisionStale
from workbench.agent.notebook.proposal import TypedProposal
from workbench.contracts.agent.notebook_option import (
    EvidenceRef,
    ExpectedArtifact,
    MemoryDefaultSource,
    NotebookOptionRevision,
    NotebookOptionRevisionV11,
    NotebookOptionRevisionV13,
    NotebookOptionRevisionV14,
    RecommendationDecision,
)
from workbench.domain_memory.candidate_store import MemoryCandidateStore
from workbench.domain_memory.local_runtime import bootstrap_local_domain_memory_runtime
from workbench.domain_memory.contracts import (
    ApplicabilityPredicate,
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
        "contract_version": "domain-memory-context-input/v3",
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
    compact_lesson: str = "The approved analysis convention uses unadjusted covariance.",
) -> dict[str, object]:
    return {
        "memory_id": memory_id,
        "revision": revision,
        "content_hash": "a" * 64,
        "memory_kind": "project_domain_fact",
        "domain_tags": ["domain-a"],
        "compact_lesson": compact_lesson,
        "recommended_effect_kind": "assumption_check_hint",
        "recommended_target_refs": [target_ref],
        "source_summary_refs": ["summary-1"],
        "match_reason": ["goal"],
        "apply_mode": apply_mode,
        "apply_mode_reason": "verifier_current" if apply_mode == "suggest_default" else "declared_inform_only",
        "vocabulary_version": "notebook-memory-defaults-v1",
        "source_scope_ref": "scope-1",
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


def _current_verifier_time() -> str:
    """Keep live-runtime verifier tests independent from the calendar date."""

    return datetime.now(timezone.utc).isoformat()


def _approved_memory_store(
    tmp_path: Path,
    *,
    verifier: MemoryVerifier | None,
    last_validated_at: str | None,
    expires_at: str | None,
    store: DomainMemoryStore | None = None,
    memory_id: str = "memory-preflight",
    target_ref: str = "model.genesis.ols.covariance.robust",
    applicability_predicates: tuple[ApplicabilityPredicate, ...] | None = None,
    compact_lesson: str = "The approved convention is current only while its verifier remains current.",
) -> DomainMemoryStore:
    if store is None:
        scope = MemoryScope(
            "ns-memory", "profile-memory", "user-memory", None, "private", "user"
        )
        store = DomainMemoryStore(tmp_path / "approved-memory", scope)
    else:
        scope = store.scope
    snapshot = build_redacted_summary_snapshot(
        summary_text="Reviewed domain-memory source.",
        source_ref="source-memory",
        source_kind="trace_summary",
        redaction_subject="subject-memory",
    )
    binding = SourceAccessBinding(
        f"binding-{memory_id}",
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
            binding.binding_ref,
            1,
            1,
            "valid",
            "2026-08-01T00:00:00Z",
            "granted",
            "acl-v1",
            ("acl-memory",),
        )
    )
    content = DomainMemoryContentRevision(
        memory_id,
        1,
        scope,
        ("domain-memory",),
        "project_domain_fact",
        applicability_predicates
        or (ApplicabilityPredicate("goal", "exists", None),),
        compact_lesson,
        "assumption_check_hint",
        (target_ref,),
        (
            SourceSummaryRef(
                "project-memory",
                snapshot.summary_snapshot_ref,
                snapshot.summary_snapshot_hash,
                snapshot.summary_schema_version,
                binding.binding_ref,
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
        f"approval-{memory_id}",
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


def test_memory_v3_projection_preserves_apply_mode_without_becoming_a_freshness_input(
    tmp_path: Path,
) -> None:
    base = _context(tmp_path)
    projection = _memory_projection(_memory_hint())

    attached = attach_domain_memory_projection(base, projection)

    entry = attached.domain_memory_projection["entries"][0]
    assert entry["apply_mode"] == "suggest_default"
    assert entry["vocabulary_version"] == "notebook-memory-defaults-v1"
    assert entry["source_scope_ref"] == "scope-1"
    assert entry["memory_source"] == {"memory_id": "memory-1", "revision": 1}
    assert generation_context_hash(attached) != generation_context_hash(base)
    assert freshness_dependency_fingerprint(attached) == freshness_dependency_fingerprint(base)


def test_memory_v3_projection_rejects_missing_authority_ordering_facts(tmp_path: Path) -> None:
    projection = _memory_projection(_memory_hint())
    del projection["entries"][0]["source_scope_ref"]

    with pytest.raises(ValueError, match="invalid contract shape"):
        attach_domain_memory_projection(_context(tmp_path), projection)


def test_memory_projection_rejects_non_ascii_payload_over_utf8_byte_budget(
    tmp_path: Path,
) -> None:
    """The shared attachment boundary measures the actual UTF-8 payload."""

    projection = _memory_projection(
        *(
            _memory_hint(
                memory_id=f"memory-unicode-{index}",
                compact_lesson="时间索引解释需要逐项核实。" * 26,
            )
            for index in range(8)
        )
    )
    assert len(canonical_json_v1(projection)) < 8192
    assert len(canonical_json_v1(projection).encode("utf-8")) > 8192

    with pytest.raises(ValueError, match="byte budget"):
        attach_domain_memory_projection(_context(tmp_path), projection)


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
            target_label="Covariance estimator",
            method_risk="medium",
            restore_value=None,
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


def test_memory_default_provenance_persists_as_a_v14_option_revision(tmp_path: Path) -> None:
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

    assert isinstance(revision, NotebookOptionRevisionV14)
    assert revision.memory_default_sources == (
        MemoryDefaultSource(
            memory_id="memory-ols-covariance",
            revision=2,
            target_ref="model.genesis.ols.covariance.robust",
            target_label="Covariance estimator",
            method_risk="medium",
            restore_value=None,
        ),
    )
    assert (
        service.store.read_option(notebook.notebook_id, "option-memory-persisted")
        .current_revision.to_dict()["memory_default_sources"]
        == [item.to_dict() for item in revision.memory_default_sources]
    )
    legacy_payload = revision.to_dict()
    legacy_payload["contract_version"] = "1.3"
    legacy_payload["memory_default_sources"] = [
        {
            "memory_id": "memory-ols-covariance",
            "revision": 2,
            "target_ref": "model.genesis.ols.covariance.robust",
        }
    ]
    assert isinstance(NotebookOptionRevision.from_dict(legacy_payload), NotebookOptionRevisionV13)
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
    assert not isinstance(revalidated, (NotebookOptionRevisionV13, NotebookOptionRevisionV14))


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


def test_notebook_provider_receives_compiled_context_without_browser_owned_preferences(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
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
        calls.append(kwargs)
        return projection

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(domain_memory_context_provider=provider))
    )
    assert _domain_memory_projection(request, tmp_path, object(), "notebook-1", context=_context(tmp_path)) == projection
    assert len(calls) == 1
    assert "preferences" not in calls[0]


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
        )
        is None
    )
    assert seen == [base]
    assert base.analysis_contract == {"question": "bounded"}
    assert base.domain_memory_projection is None


def test_legacy_memory_service_does_not_enable_notebook_memory_without_a_runtime(
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
    )

    assert projection is None


def test_local_runtime_uses_only_persisted_memory_settings(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "domain-memory")
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                domain_memory_runtime=runtime,
                domain_memory_context_provider=None,
                domain_memory_service=None,
            )
        )
    )
    context = _context(project_root)

    assert _domain_memory_projection(request, project_root, object(), "notebook-1", context=context) is None

    global_settings = runtime.preferences.update_global(
        expected_revision=0,
        library_enabled=True,
    )
    project_scope = runtime.project_scope(project_root)
    runtime.preferences.update_project(
        project_scope,
        expected_revision=0,
        library_enabled=False,
        inherit_global=True,
        candidate_generation_enabled=False,
    )

    projection = _domain_memory_projection(
        request,
        project_root,
        object(),
        "notebook-1",
        context=context,
    )

    assert global_settings.library_enabled is True
    assert projection is not None
    assert projection["outcome"] == "empty"
    assert projection["entries"] == []


def test_local_runtime_materializes_only_published_recipe_default_matches(
    tmp_path: Path,
) -> None:
    """Recipe-targeted memory is retrieved before the provider selects a Recipe."""

    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "domain-memory")
    project_scope = runtime.project_scope(project_root)
    runtime.preferences.update_project(
        project_scope,
        expected_revision=0,
        library_enabled=True,
        inherit_global=False,
        candidate_generation_enabled=False,
    )
    store = runtime.service_for_project(project_root, create=True).store
    _approved_memory_store(
        tmp_path,
        store=store,
        memory_id="memory-ets-observation-order",
        target_ref=(
            "model.genesis.time_series.ets.time_index_semantics.observation_order"
        ),
        applicability_predicates=(
            ApplicabilityPredicate("analysis_family", "equals", "time_series.ets"),
        ),
        verifier=MemoryVerifier("verify-ets-observation-order", 31_536_000),
        last_validated_at=_current_verifier_time(),
        expires_at=None,
    )
    _approved_memory_store(
        tmp_path,
        store=store,
        memory_id="memory-ets-target-with-arma-predicate",
        target_ref=(
            "model.genesis.time_series.ets.time_index_semantics.observation_order"
        ),
        applicability_predicates=(
            ApplicabilityPredicate("analysis_family", "equals", "time_series.arma_garch"),
        ),
        verifier=MemoryVerifier("verify-mismatched-recipe-target", 31_536_000),
        last_validated_at=_current_verifier_time(),
        expires_at=None,
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                domain_memory_runtime=runtime,
                domain_memory_context_provider=None,
                domain_memory_service=None,
            )
        )
    )

    projection = _domain_memory_projection(
        request,
        project_root,
        object(),
        "notebook-1",
        context=_context(project_root),
    )

    assert projection is not None
    assert [entry["memory_id"] for entry in projection["entries"]] == [
        "memory-ets-observation-order"
    ]
    assert projection["entries"][0]["recommended_target_refs"] == [
        "model.genesis.time_series.ets.time_index_semantics.observation_order"
    ]
    assert projection["entries"][0]["match_reason"] == ["analysis_family"]

    defaulted = apply_memory_defaults(
        TypedProposal(
            proposal_id="proposal-ets-runtime-projection",
            operation_id="model.genesis",
            target={"dataset_source_id": "upload-ets-runtime-projection"},
            preconditions={"context_version": "node-operation-context/v1"},
            changes={
                "model_params": {
                    "model_type": "time_series.ets",
                    "model_options": {
                        "time_column": "when",
                        "value_column": "value",
                        "error": "add",
                        "trend": None,
                        "seasonal": None,
                        "damped_trend": False,
                    },
                }
            },
        ),
        projection,
    )

    assert defaulted.changes["model_params"]["model_options"][
        "time_index_semantics"
    ] == "observation_order"
    assert defaulted.memory_default_sources == (
        MemoryDefaultSource(
            memory_id="memory-ets-observation-order",
            revision=1,
            target_ref=(
                "model.genesis.time_series.ets.time_index_semantics.observation_order"
            ),
            target_label="Time-index interpretation",
            method_risk="high",
            restore_value=None,
        ),
    )


def test_recipe_default_bridge_excludes_noncurrent_hints_and_bounds_projection(
    tmp_path: Path,
) -> None:
    """Recipe preselection cannot overflow the context or bless stale hints."""

    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "domain-memory")
    project_scope = runtime.project_scope(project_root)
    runtime.preferences.update_project(
        project_scope,
        expected_revision=0,
        library_enabled=True,
        inherit_global=False,
        candidate_generation_enabled=False,
    )
    store = runtime.service_for_project(project_root, create=True).store
    now = datetime.now(timezone.utc)
    common = {
        "store": store,
        "target_ref": (
            "model.genesis.time_series.ets.time_index_semantics.observation_order"
        ),
        "applicability_predicates": (
            ApplicabilityPredicate("analysis_family", "equals", "time_series.ets"),
        ),
        "verifier": MemoryVerifier("verify-recipe-default", 60),
        "expires_at": None,
    }
    _approved_memory_store(
        tmp_path,
        memory_id="memory-ets-00-stale",
        last_validated_at=(now - timedelta(days=1)).isoformat(),
        **common,
    )
    for index in range(1, 2):
        _approved_memory_store(
            tmp_path,
            memory_id=f"memory-ets-{index:02d}-current",
            last_validated_at=now.isoformat(),
            **common,
        )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                domain_memory_runtime=runtime,
                domain_memory_context_provider=None,
                domain_memory_service=None,
            )
        )
    )

    projection = _domain_memory_projection(
        request,
        project_root,
        object(),
        "notebook-1",
        context=_context(project_root),
    )

    assert projection is not None
    assert "memory-ets-00-stale" not in {
        entry["memory_id"] for entry in projection["entries"]
    }
    assert any(
        entry["memory_id"] == "memory-ets-01-current"
        for entry in projection["entries"]
    )
    assert all(
        entry["apply_mode"] == "suggest_default"
        and entry["apply_mode_reason"] == "verifier_current"
        for entry in projection["entries"]
    )
    assert len(projection["entries"]) <= 8
    assert len(projection["omissions"]) <= 32
    attach_domain_memory_projection(_context(project_root), projection)


def test_local_runtime_projection_reaches_validated_ets_draft(
    tmp_path: Path,
) -> None:
    """A real local projection may resolve one omitted Recipe field in a Draft."""

    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "domain-memory")
    project_scope = runtime.project_scope(project_root)
    runtime.preferences.update_project(
        project_scope,
        expected_revision=0,
        library_enabled=True,
        inherit_global=False,
        candidate_generation_enabled=False,
    )
    store = runtime.service_for_project(project_root, create=True).store
    _approved_memory_store(
        tmp_path,
        store=store,
        memory_id="memory-ets-draft-bridge",
        target_ref=(
            "model.genesis.time_series.ets.time_index_semantics.observation_order"
        ),
        applicability_predicates=(
            ApplicabilityPredicate("analysis_family", "equals", "time_series.ets"),
        ),
        verifier=MemoryVerifier("verify-ets-draft-bridge", 31_536_000),
        last_validated_at=_current_verifier_time(),
        expires_at=None,
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                domain_memory_runtime=runtime,
                domain_memory_context_provider=None,
                domain_memory_service=None,
            )
        )
    )
    context = _context(project_root)
    projection = _domain_memory_projection(
        request,
        project_root,
        object(),
        "notebook-1",
        context=context,
    )
    assert projection is not None
    context = attach_domain_memory_projection(context, projection)
    evidence = DataEvidencePackV1(
        source_id="dataset:ets-draft-bridge",
        records=(
            EvidenceRecord(
                evidence_id="evidence:ets-draft-bridge",
                inspection_id="profile.v1",
                source_refs=("profile:ets-draft-bridge",),
                protocol_version="profile/v1",
                status="completed",
                observations={"columns": [{"name": "when"}, {"name": "value"}]},
                result_hash="sha256:ets-draft-bridge",
            ),
        ),
    )
    submission = AgentOptionSubmission(
        rank=1,
        rationale="The verified source contains one time-indexed series.",
        assumptions=("Observation order is the approved interpretation.",),
        capability_id="time_series.ets",
        option_id="option-ets-draft-bridge",
        proposal=TypedProposal(
            proposal_id="proposal-ets-draft-bridge",
            operation_id="model.genesis",
            target={"dataset_source_id": "upload-ets-draft-bridge"},
            preconditions={
                "context_version": "node-operation-context/v1",
                "context_fingerprint": freshness_dependency_fingerprint(context),
                "owner_resolution": "single_candidate",
            },
            changes={
                "model_params": {
                    "model_type": "time_series.ets",
                    "model_options": {
                        "time_column": "when",
                        "value_column": "value",
                        "error": "add",
                        "trend": None,
                        "seasonal": None,
                        "damped_trend": False,
                    },
                }
            },
        ),
        expected_artifacts=(ExpectedArtifact("ets_1", "model_result", True, 1),),
        evidence_refs=(
            EvidenceRef(
                "evidence:ets-draft-bridge",
                "sha256:ets-draft-bridge",
                ("profile:ets-draft-bridge",),
            ),
        ),
        comparative_claims=(
            "evidence:ets-draft-bridge confirms the declared source columns.",
        ),
    )
    agent = NotebookPlanningAgent(
        adapter=object(),
        capability_catalog={"time_series.ets": {"model_type": "time_series.ets"}},
    )

    (validated,) = agent._validate_submissions(
        context,
        evidence,
        (submission,),
        {"time_series.ets": {"model_type": "time_series.ets"}},
    )
    (draft,) = option_drafts_from_submissions(context, (validated,))

    assert draft.proposal.changes["model_params"]["model_options"][
        "time_index_semantics"
    ] == "observation_order"
    assert draft.proposal.memory_default_sources[0].memory_id == "memory-ets-draft-bridge"


def test_recipe_default_bridge_excludes_recipe_hints_from_generic_fallback(
    tmp_path: Path,
) -> None:
    """Known Recipe targets are admitted only by their exact preselection."""

    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "domain-memory")
    project_scope = runtime.project_scope(project_root)
    runtime.preferences.update_project(
        project_scope,
        expected_revision=0,
        library_enabled=True,
        inherit_global=False,
        candidate_generation_enabled=False,
    )
    store = runtime.service_for_project(project_root, create=True).store
    matching_ets = (
        ApplicabilityPredicate("analysis_family", "equals", "time_series.ets"),
    )
    _approved_memory_store(
        tmp_path,
        store=store,
        memory_id="memory-arma-wrong-recipe",
        target_ref=(
            "model.genesis.time_series.arma_garch.time_index_semantics.observation_order"
        ),
        applicability_predicates=matching_ets,
        verifier=MemoryVerifier("verify-wrong-recipe", 31_536_000),
        last_validated_at=_current_verifier_time(),
        expires_at=None,
    )
    _approved_memory_store(
        tmp_path,
        store=store,
        memory_id="memory-ets-inform-only",
        target_ref=(
            "model.genesis.time_series.ets.time_index_semantics.observation_order"
        ),
        applicability_predicates=matching_ets,
        verifier=None,
        last_validated_at=None,
        expires_at=None,
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                domain_memory_runtime=runtime,
                domain_memory_context_provider=None,
                domain_memory_service=None,
            )
        )
    )

    projection = _domain_memory_projection(
        request,
        project_root,
        object(),
        "notebook-1",
        context=replace(
            _context(project_root),
            analysis_contract={"analysis_family": "time_series.ets"},
        ),
    )

    assert projection is not None
    assert projection["entries"] == []


def test_recipe_default_bridge_blocks_truncated_recipe_candidates(
    tmp_path: Path,
) -> None:
    """An unseen ninth candidate must not choose a default by truncation."""

    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "domain-memory")
    project_scope = runtime.project_scope(project_root)
    runtime.preferences.update_project(
        project_scope,
        expected_revision=0,
        library_enabled=True,
        inherit_global=False,
        candidate_generation_enabled=False,
    )
    store = runtime.service_for_project(project_root, create=True).store
    common = {
        "store": store,
        "applicability_predicates": (
            ApplicabilityPredicate("analysis_family", "equals", "time_series.ets"),
        ),
        "verifier": MemoryVerifier("verify-truncation", 31_536_000),
        "last_validated_at": _current_verifier_time(),
        "expires_at": None,
    }
    for index in range(1, 9):
        _approved_memory_store(
            tmp_path,
            memory_id=f"memory-ets-{index:02d}-observation",
            target_ref=(
                "model.genesis.time_series.ets.time_index_semantics.observation_order"
            ),
            **common,
        )
    _approved_memory_store(
        tmp_path,
        memory_id="memory-ets-09-regular-calendar",
        target_ref=(
            "model.genesis.time_series.ets.time_index_semantics.regular_calendar"
        ),
        **common,
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                domain_memory_runtime=runtime,
                domain_memory_context_provider=None,
                domain_memory_service=None,
            )
        )
    )

    projection = _domain_memory_projection(
        request,
        project_root,
        object(),
        "notebook-1",
        context=_context(project_root),
    )
    assert projection is not None
    assert projection["entries"] == []
    proposal = TypedProposal(
        proposal_id="proposal-ets-truncated",
        operation_id="model.genesis",
        target={"dataset_source_id": "upload-ets-truncated"},
        preconditions={"context_version": "node-operation-context/v1"},
        changes={
            "model_params": {
                "model_type": "time_series.ets",
                "model_options": {
                    "time_column": "when",
                    "value_column": "value",
                    "error": "add",
                    "trend": None,
                    "seasonal": None,
                    "damped_trend": False,
                },
            }
        },
    )
    assert apply_memory_defaults(proposal, projection) == proposal


def test_recipe_default_bridge_never_partially_admits_a_recipe_group(
    tmp_path: Path,
) -> None:
    """A global entry budget cannot conceal a conflict inside one Recipe group."""

    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "domain-memory")
    project_scope = runtime.project_scope(project_root)
    runtime.preferences.update_project(
        project_scope,
        expected_revision=0,
        library_enabled=True,
        inherit_global=False,
        candidate_generation_enabled=False,
    )
    store = runtime.service_for_project(project_root, create=True).store
    common = {
        "store": store,
        "applicability_predicates": (
            ApplicabilityPredicate("analysis_family", "equals", "time_series.ets"),
        ),
        "verifier": MemoryVerifier("verify-cross-recipe-budget", 31_536_000),
        "last_validated_at": _current_verifier_time(),
        "expires_at": None,
    }
    for index in range(5):
        _approved_memory_store(
            tmp_path,
            memory_id=f"memory-arma-{index:02d}",
            target_ref=(
                "model.genesis.time_series.arma_garch.time_index_semantics.observation_order"
            ),
            applicability_predicates=(
                ApplicabilityPredicate(
                    "analysis_family", "equals", "time_series.arma_garch"
                ),
            ),
            **{key: value for key, value in common.items() if key != "applicability_predicates"},
        )
    for index in range(1, 5):
        _approved_memory_store(
            tmp_path,
            memory_id=f"memory-ets-{index:02d}-observation",
            target_ref=(
                "model.genesis.time_series.ets.time_index_semantics.observation_order"
            ),
            **common,
        )
    _approved_memory_store(
        tmp_path,
        memory_id="memory-ets-05-regular-calendar",
        target_ref=(
            "model.genesis.time_series.ets.time_index_semantics.regular_calendar"
        ),
        **common,
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                domain_memory_runtime=runtime,
                domain_memory_context_provider=None,
                domain_memory_service=None,
            )
        )
    )

    projection = _domain_memory_projection(
        request,
        project_root,
        object(),
        "notebook-1",
        context=_context(project_root),
    )
    assert projection is not None
    assert not any(
        entry["memory_id"].startswith("memory-ets-")
        for entry in projection["entries"]
    )


def test_recipe_default_bridge_caps_generic_omissions_at_context_boundary(
    tmp_path: Path,
) -> None:
    """Many ineligible memories cannot invalidate an otherwise valid context."""

    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "domain-memory")
    project_scope = runtime.project_scope(project_root)
    runtime.preferences.update_project(
        project_scope,
        expected_revision=0,
        library_enabled=True,
        inherit_global=False,
        candidate_generation_enabled=False,
    )
    store = runtime.service_for_project(project_root, create=True).store
    for index in range(33):
        _approved_memory_store(
            tmp_path,
            store=store,
            memory_id=f"memory-mismatch-{index:02d}",
            applicability_predicates=(
                ApplicabilityPredicate("analysis_family", "equals", "time_series.ets"),
            ),
            verifier=MemoryVerifier("verify-mismatch", 31_536_000),
            last_validated_at=_current_verifier_time(),
            expires_at=None,
        )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                domain_memory_runtime=runtime,
                domain_memory_context_provider=None,
                domain_memory_service=None,
            )
        )
    )

    projection = _domain_memory_projection(
        request,
        project_root,
        object(),
        "notebook-1",
        context=_context(project_root),
    )

    assert projection is not None
    assert len(projection["omissions"]) <= 32
    attach_domain_memory_projection(_context(project_root), projection)


def test_recipe_default_bridge_budgets_the_complete_projection_payload(
    tmp_path: Path,
) -> None:
    """Entry bytes plus public omissions must fit the final context envelope."""

    project_root = tmp_path / "project"
    project_root.mkdir()
    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "domain-memory")
    project_scope = runtime.project_scope(project_root)
    runtime.preferences.update_project(
        project_scope,
        expected_revision=0,
        library_enabled=True,
        inherit_global=False,
        candidate_generation_enabled=False,
    )
    store = runtime.service_for_project(project_root, create=True).store
    for index in range(8):
        _approved_memory_store(
            tmp_path,
            store=store,
            memory_id=f"memory-large-entry-{index:02d}",
            applicability_predicates=(ApplicabilityPredicate("goal", "exists", None),),
            verifier=MemoryVerifier("verify-large-entry", 31_536_000),
            last_validated_at=_current_verifier_time(),
            expires_at=None,
            compact_lesson="时间索引解释需要逐项核实。" * 28,
        )
    for index in range(32):
        _approved_memory_store(
            tmp_path,
            store=store,
            memory_id=f"memory-large-omission-{index:02d}",
            applicability_predicates=(
                ApplicabilityPredicate("analysis_family", "equals", "time_series.ets"),
            ),
            verifier=MemoryVerifier("verify-large-omission", 31_536_000),
            last_validated_at=_current_verifier_time(),
            expires_at=None,
        )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                domain_memory_runtime=runtime,
                domain_memory_context_provider=None,
                domain_memory_service=None,
            )
        )
    )
    context = replace(_context(project_root), analysis_contract={"goal": "forecast"})

    projection = _domain_memory_projection(
        request,
        project_root,
        object(),
        "notebook-1",
        context=context,
    )

    assert projection is not None
    assert len(canonical_json_v1(projection).encode("utf-8")) <= 8192
    attach_domain_memory_projection(context, projection)
