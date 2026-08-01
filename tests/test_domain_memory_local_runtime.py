from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from workbench.domain_memory.local_runtime import (
    LocalDomainMemoryRuntimeError,
    bootstrap_local_domain_memory_runtime,
)


def test_bootstrap_creates_an_empty_private_local_memory_store(tmp_path: Path) -> None:
    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "memory")

    assert runtime.service.store.scope.exact_match(runtime.scope_resolver.global_scope)
    assert runtime.service.store.list_content() == ()
    assert runtime.candidate_store.pending(runtime.scope_resolver.global_scope) == ()
    assert runtime.service.store.root.is_relative_to(tmp_path / "memory")
    assert os.stat(runtime.service.store.root).st_mode & 0o077 == 0


def test_project_scope_is_canonical_and_never_persists_the_raw_path(tmp_path: Path) -> None:
    project = tmp_path / "a project with spaces"
    project.mkdir()
    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "memory")

    scope = runtime.scope_resolver.project_scope(project)

    assert scope.exact_match(runtime.scope_resolver.project_scope(project / "."))
    assert scope.owner_id.startswith("project-")
    assert str(project) not in scope.to_dict().values()
    assert not scope.exact_match(runtime.scope_resolver.global_scope)


def test_bootstrap_rejects_a_symlinked_local_memory_base(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "memory-link"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(LocalDomainMemoryRuntimeError, match="safe"):
        bootstrap_local_domain_memory_runtime(link)


def test_bootstrap_rejects_a_symlink_in_the_parent_path(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "parent-link"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(LocalDomainMemoryRuntimeError, match="safe"):
        bootstrap_local_domain_memory_runtime(link / "memory")


def test_bootstrap_canonicalizes_an_explicit_home_relative_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    runtime = bootstrap_local_domain_memory_runtime("~/memory")

    assert runtime.base_dir == tmp_path / "memory"


def test_product_bootstrap_installs_the_empty_local_memory_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from workbench import app as workbench_app

    monkeypatch.setenv("WORKBENCH_DOMAIN_MEMORY_ROOT", str(tmp_path / "memory"))
    workbench_app.configure_domain_memory_services(None, None)

    runtime = workbench_app.bootstrap_local_domain_memory_services()

    assert workbench_app.app.state.domain_memory_service is runtime.service
    assert workbench_app.app.state.domain_memory_review_service is runtime.review_service
    assert workbench_app.app.state.domain_memory_bootstrap_error is None


def test_product_bootstrap_fails_closed_when_the_local_memory_journal_is_corrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from workbench import app as workbench_app

    root = tmp_path / "memory"
    runtime = bootstrap_local_domain_memory_runtime(root)
    runtime.service.store.journal_path.write_text("not valid json\n", encoding="utf-8")
    monkeypatch.setenv("WORKBENCH_DOMAIN_MEMORY_ROOT", str(root))
    workbench_app.configure_domain_memory_services(None, None)

    assert workbench_app.bootstrap_local_domain_memory_services() is None
    assert workbench_app.app.state.domain_memory_service is None
    assert workbench_app.app.state.domain_memory_bootstrap_error == "DOMAIN_MEMORY_LOCAL_RUNTIME_UNAVAILABLE"


def test_bootstrap_rejects_a_corrupt_conflict_journal(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    runtime = bootstrap_local_domain_memory_runtime(root)
    runtime.review_service.conflict_store.journal_path.write_text("not valid json\n", encoding="utf-8")

    with pytest.raises(LocalDomainMemoryRuntimeError, match="safe"):
        bootstrap_local_domain_memory_runtime(root)


def test_product_memory_route_rejects_a_client_supplied_scope(tmp_path: Path) -> None:
    from workbench.http.memory_routes import router
    from workbench.domain_memory.scope import MemoryScope

    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "memory")
    app = FastAPI()
    app.state.domain_memory_runtime = runtime
    app.state.domain_memory_service = runtime.service
    app.include_router(router)
    project = tmp_path / "project"
    project.mkdir()
    forged_scope = MemoryScope("foreign", "foreign", "foreign", None, "private", "user")

    response = TestClient(app).post(
        "/domain-memory/retrieve",
        params={"project_root": str(project)},
        json={
            "requester_scope": forged_scope.to_dict(),
            "facts": {},
        },
    )

    assert response.status_code == 422


def test_product_memory_route_rejects_request_preferences_and_overrides(tmp_path: Path) -> None:
    from workbench.http.memory_routes import router

    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "memory")
    project = tmp_path / "project"
    project.mkdir()
    app = FastAPI()
    app.state.domain_memory_runtime = runtime
    app.state.domain_memory_service = runtime.service
    app.include_router(router)

    response = TestClient(app).post(
        "/domain-memory/retrieve",
        params={"project_root": str(project)},
        json={
            "preferences": {"cross_project_domain_memory_use": True},
            "override": {"cross_project_domain_memory_use": True},
            "facts": {},
        },
    )

    assert response.status_code == 422


def test_memory_route_fails_closed_without_a_server_owned_scope_resolver(
    tmp_path: Path,
) -> None:
    from workbench.domain_memory.candidate_store import MemoryCandidateStore
    from workbench.domain_memory.scope import MemoryScope
    from workbench.domain_memory.service import DomainMemoryService
    from workbench.domain_memory.store import DomainMemoryStore
    from workbench.http.memory_routes import router

    scope = MemoryScope("ns-a", "profile-a", "user-a", None, "private", "user")
    app = FastAPI()
    app.state.domain_memory_service = DomainMemoryService(
        DomainMemoryStore(tmp_path, scope), MemoryCandidateStore(tmp_path, scope)
    )
    app.include_router(router)

    response = TestClient(app).post(
        "/domain-memory/retrieve",
        params={"project_root": str(tmp_path)},
        json={"facts": {}},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DOMAIN_MEMORY_IDENTITY_UNAVAILABLE"


def test_bootstrapped_product_rejects_memory_mutation_until_settings_authorizes(
    tmp_path: Path,
) -> None:
    from workbench.http.memory_routes import router

    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "memory")
    app = FastAPI()
    app.state.domain_memory_runtime = runtime
    app.state.domain_memory_service = runtime.service
    app.state.domain_memory_review_service = runtime.review_service
    app.include_router(router)

    response = TestClient(app).post(
        "/domain-memory/review/candidates/candidate-a",
        json={"decision": "rejected", "expected_revision": 1, "actor_id": "local-user"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DOMAIN_MEMORY_MUTATIONS_DISABLED"
