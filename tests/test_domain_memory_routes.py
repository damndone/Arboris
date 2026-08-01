from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from workbench.domain_memory.local_runtime import bootstrap_local_domain_memory_runtime
from workbench.domain_memory.scope import MemoryScope
from workbench.http.memory_routes import router


SCOPE = MemoryScope("ns-a", "profile-a", "user-a", "org-a", "private", "user")


def _client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    runtime = bootstrap_local_domain_memory_runtime(tmp_path / "memory")
    app.state.domain_memory_runtime = runtime
    app.state.domain_memory_service = runtime.service
    app.include_router(router)
    return TestClient(app)


def test_router_is_explicitly_unmounted_from_product_app_and_has_no_run_route() -> None:
    paths = {route.path for route in router.routes}
    assert "/domain-memory/retrieve" in paths
    assert "/domain-memory/candidates" in paths
    assert all("run" not in path for path in paths)


def test_retrieve_route_defaults_to_not_used(tmp_path: Path) -> None:
    response = _client(tmp_path).post(
        "/domain-memory/retrieve",
        json={
            "requester_scope": SCOPE.to_dict(),
            "facts": {},
            "now": "2026-07-27T00:00:00Z",
        },
    )
    assert response.status_code == 200
    assert response.json()["reason"] == "DOMAIN_MEMORY_DISABLED"


def test_route_rejects_unknown_fields(tmp_path: Path) -> None:
    response = _client(tmp_path).post(
        "/domain-memory/retrieve",
        json={"requester_scope": SCOPE.to_dict(), "now": "2026-07-27T00:00:00Z", "execute": True},
    )
    assert response.status_code == 422
