from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from workbench.domain_memory.candidate_store import MemoryCandidateStore
from workbench.domain_memory.conflicts import ConflictStore
from workbench.domain_memory.curator_runtime import CuratorRuntime
from workbench.domain_memory.preferences import DomainMemoryPreferences, resolve_preferences
from workbench.domain_memory.review_service import MemoryReviewService
from workbench.domain_memory.scope import MemoryScope
from workbench.domain_memory.service import DomainMemoryService
from workbench.domain_memory.store import DomainMemoryStore
from workbench.http.memory_routes import router

from test_memory_curator_contracts import _summary


SCOPE = MemoryScope("ns-a", "profile-a", "user-a", "org-a", "private", "user")


def _client(tmp_path: Path) -> tuple[TestClient, MemoryCandidateStore]:
    candidates = MemoryCandidateStore(tmp_path, SCOPE)
    service = DomainMemoryService(DomainMemoryStore(tmp_path, SCOPE), candidates)
    CuratorRuntime(candidates).generate(_summary(), resolve_preferences(SCOPE, DomainMemoryPreferences(cross_project_domain_memory_iteration=True)))
    app = FastAPI()
    app.state.domain_memory_service = service
    app.state.domain_memory_review_service = MemoryReviewService(service, candidates, ConflictStore(tmp_path, SCOPE))
    app.include_router(router)
    return TestClient(app), candidates


def test_review_route_is_explicit_and_has_no_execution_surface(tmp_path: Path) -> None:
    client, candidates = _client(tmp_path)
    paths = {route.path for route in router.routes}
    assert "/domain-memory/review/candidates/{candidate_id}" in paths
    assert all("execute" not in path and "run" not in path for path in paths)
    candidate = candidates.pending(SCOPE)[0]
    response = client.post(f"/domain-memory/review/candidates/{candidate.candidate_id}", json={"decision": "rejected", "expected_revision": candidate.revision, "actor_id": "user-a"})
    assert response.status_code == 200
    assert response.json()["automatic_execution"] is False


def test_review_route_forbids_unknown_fields(tmp_path: Path) -> None:
    client, candidates = _client(tmp_path)
    candidate = candidates.pending(SCOPE)[0]
    response = client.post(f"/domain-memory/review/candidates/{candidate.candidate_id}", json={"decision": "rejected", "expected_revision": candidate.revision, "actor_id": "user-a", "execute": True})
    assert response.status_code == 422


def test_curator_candidate_can_be_explicitly_approved_without_a_hidden_transition(tmp_path: Path) -> None:
    client, candidates = _client(tmp_path)
    candidate = candidates.pending(SCOPE)[0]
    assert candidate.status == "needs_review"

    response = client.post(
        f"/domain-memory/review/candidates/{candidate.candidate_id}",
        json={
            "decision": "approved",
            "expected_revision": candidate.revision,
            "actor_id": "user-a",
            "approved_at": "2026-08-01T00:00:00Z",
            "review_after": "2026-12-01T00:00:00Z",
        },
    )

    assert response.status_code == 200
    assert response.json()["automatic_execution"] is False
    assert response.json()["validity"]["state"] == "active"
