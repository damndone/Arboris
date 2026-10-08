"""V1812-LOCAL-API-SECURITY ③: no GET route writes.

The local request guard checks Origin and fetch metadata only on
state-changing methods, because any page may issue a GET (an image tag, a
link). A GET must therefore never change state. This test builds a project
with a completed run and a notebook, calls every registered GET route once,
and fails when any of them creates or modifies a file in the project or in
the user's home directory. A new GET route is covered automatically.

One conditional write is accepted and not exercised here: reading a run whose
manifest still says ``running`` after its worker died records it as
``interrupted`` (``_mark_interrupted_if_dead``). That is crash reconciliation
of a fact the server owns -- no caller-supplied content is written, and the
run id is unguessable -- so it stays on the read path.
"""

from __future__ import annotations

import inspect
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench import app as app_module
from workbench.api import app

FIXTURE = Path(__file__).parent / "fixtures" / "forest_min.csv"
_MEMORY_STATE = (
    "domain_memory_service",
    "domain_memory_review_service",
    "domain_memory_runtime",
    "domain_memory_bootstrap_error",
)
_FRAMEWORK_ROUTES = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def _routes(routes):
    for item in routes:
        inner = getattr(item, "original_router", None)
        if inner is not None:
            yield from _routes(inner.routes)
        else:
            yield item


def _get_routes():
    return sorted(
        {
            route.path: route
            for route in _routes(app.routes)
            if "GET" in getattr(route, "methods", set()) and route.path not in _FRAMEWORK_ROUTES
        }.values(),
        key=lambda route: route.path,
    )


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    base = tmp_path_factory.mktemp("get-read-only")
    home = base / "home"
    home.mkdir()
    patch = pytest.MonkeyPatch()
    patch.setenv("HOME", str(home))
    # The memory routes need the local memory library that app startup
    # installs; install it under the temporary home and restore afterwards.
    saved_state = {name: getattr(app.state, name) for name in _MEMORY_STATE}
    app_module.configure_domain_memory_services(None, None)
    assert app_module.bootstrap_local_domain_memory_services() is not None
    client = TestClient(app)
    root = client.post("/projects", json={"parent": str(base), "name": "proj"}).json()["project_root"]
    response = client.post(
        "/runs",
        data={"project_root": root, "mode": "auto", "model_type": "ols", "y": "wage", "x": "education,experience"},
        files={"file": ("forest_min.csv", FIXTURE.read_bytes(), "text/csv")},
    )
    run_id = response.json()["run_id"]
    status = None
    for _ in range(600):
        status = client.get(f"/runs/{run_id}", params={"project_root": root}).json().get("status")
        if status not in (None, "queued", "running"):
            break
        time.sleep(0.05)
    assert status == "completed", status
    notebook = client.post(
        "/notebooks",
        params={"project_root": root},
        json={"title": "read-only", "created_by": "test", "from_run_id": run_id},
    )
    assert notebook.status_code == 201, notebook.text
    graph = client.get(f"/runs/{run_id}/graph", params={"project_root": root}).json()
    node_id = next(
        (node.get("node_id") or node.get("id") for node in graph.get("nodes", []) if isinstance(node, dict)),
        "node-unknown",
    )
    values = {
        "project_root": root,
        "run_id": run_id,
        "notebook_id": notebook.json()["notebook_id"],
        "node_id": node_id,
        "model_target": node_id,
        "source_run_id": run_id,
        "source_node_id": node_id,
        "child_node_id": node_id,
        "library": "project",
    }
    yield client, Path(root), home, values
    for name, value in saved_state.items():
        setattr(app.state, name, value)
    patch.undo()


def _snapshot(*tops: Path) -> dict[str, tuple[int, int]]:
    seen = {}
    for top in tops:
        for path in top.rglob("*"):
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            seen[str(path)] = (stat.st_mtime_ns, stat.st_size if path.is_file() else -1)
    return seen


@pytest.mark.parametrize("route", _get_routes(), ids=lambda route: route.path)
def test_get_route_does_not_write(world, route):
    client, root, home, values = world
    url = re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), f"{m.group(1)}-unknown"), route.path)
    params = {
        name: values[name]
        for name in inspect.signature(route.endpoint).parameters
        if name in values and "{" + name + "}" not in route.path
    }
    before = _snapshot(root, home)
    if route.path == "/runs/{run_id}/events":
        with client.stream("GET", url, params=params) as response:
            for _ in response.iter_bytes():
                break
    else:
        response = client.get(url, params=params)
    after = _snapshot(root, home)
    created = sorted(set(after) - set(before))
    modified = sorted(key for key in set(after) & set(before) if after[key] != before[key] and after[key][1] != -1)
    assert response.status_code < 500, response.text
    assert (created, modified) == ([], []), f"GET {route.path} wrote to disk"


def test_every_get_route_is_covered():
    # Guards the enumeration itself: FastAPI wraps included routers, and a
    # silently empty list would make the test above vacuous.
    assert len(_get_routes()) >= 40
