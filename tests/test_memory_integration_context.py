from __future__ import annotations

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
from workbench.domain_memory.candidate_store import MemoryCandidateStore
from workbench.domain_memory.service import DomainMemoryService
from workbench.domain_memory.scope import MemoryScope
from workbench.domain_memory.store import DomainMemoryStore
from workbench.http.notebook_routes import _domain_memory_projection


def _context(tmp_path: Path):
    return compile_notebook_planning_context(
        tmp_path,
        notebook_id="notebook-1",
        run_family_id="family-1",
        active_head_run_id=None,
        analysis_contract={"question": "bounded"},
        user_focus={"section": "model"},
    )


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
