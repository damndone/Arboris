"""V1812-LOCAL-API-SECURITY: the local API only answers this computer's UI.

Two attacks reach a loopback server from an ordinary web page:

* DNS rebinding -- the page's own host name is re-pointed at 127.0.0.1, so the
  browser treats ``:8000`` as same-origin and may read and write freely. The
  request still carries the attacker's name in ``Host``.
* Cross-site submission -- a form post or ``no-cors`` fetch from any other
  origin (including another port on this computer) changes state without a
  CORS preflight. The request carries the foreign ``Origin`` and, in current
  browsers, ``Sec-Fetch-Site: cross-site``.

The guard therefore admits only loopback Host names, refuses any request
that names an Origin other than this server or an allowed UI origin, and
refuses a cross-site state-changing request. Clients that send no Origin (the
CLI, scripts, curl) are unaffected.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.http import local_request_guard

LOCAL = "http://127.0.0.1:8000"
VITE_UI = "http://localhost:5173"


@pytest.fixture(autouse=True)
def _default_configuration(monkeypatch, tmp_path):
    # The suite-wide conftest admits TestClient's "testserver" host; these
    # tests check the shipped defaults, so that allowance is removed here.
    for name in ("WORKBENCH_ALLOWED_HOSTS", "WORKBENCH_ALLOWED_ORIGINS", "WORKBENCH_UI_ORIGIN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("WORKBENCH_EGRESS_AUDIT_DIR", str(tmp_path / "audit"))
    local_request_guard.reset_audit_budget()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, base_url=LOCAL)


def _audit_records(tmp_path: Path) -> list[dict]:
    path = tmp_path / "audit" / "egress_audit.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _assert_rejected(response, code: str) -> None:
    assert response.status_code == 403, response.text
    body = response.json()
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    # Nothing about the server's configuration is disclosed to the caller.
    assert body["error"]["details"] == {}
    assert "127.0.0.1" not in response.text
    assert "5173" not in response.text
    assert "access-control-allow-origin" not in {key.lower() for key in response.headers}


# --- Host allowlist (DNS rebinding) -------------------------------------------------


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "127.0.0.1:8000", "localhost", "LocalHost:8000", "[::1]", "[::1]:8000"],
)
def test_loopback_host_names_are_admitted(client, host):
    response = client.get("/health", headers={"Host": host})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    "host",
    [
        "attacker.example",
        "attacker.example:8000",
        "localhost.attacker.example",
        "127.0.0.1.attacker.example:8000",
        "127.0.0.2:8000",
        "0.0.0.0:8000",
        "testserver",
        "",
    ],
)
def test_foreign_host_names_are_rejected_for_reads(client, host, tmp_path):
    response = client.get("/llm/config", headers={"Host": host})
    _assert_rejected(response, "LOCAL_REQUEST_HOST_REJECTED")
    records = _audit_records(tmp_path)
    assert records[-1]["kind"] == "local_request_rejected"
    assert records[-1]["code"] == "LOCAL_REQUEST_HOST_REJECTED"
    assert records[-1]["method"] == "GET"
    assert records[-1]["path"] == "/llm/config"


def test_rebound_host_cannot_create_a_project(client, tmp_path):
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "rebound"},
        headers={"Host": "attacker.example:8000", "Origin": "http://attacker.example:8000"},
    )
    _assert_rejected(response, "LOCAL_REQUEST_HOST_REJECTED")
    assert not (tmp_path / "rebound").exists()


def test_missing_host_header_is_rejected():
    asgi = local_request_guard.LocalRequestGuard(_ok_app)
    status, body = asyncio.run(_call(asgi, method="GET", headers=[]))
    assert status == 403
    assert json.loads(body)["error"]["code"] == "LOCAL_REQUEST_HOST_REJECTED"


def test_extra_host_names_come_only_from_explicit_configuration(client, monkeypatch):
    assert client.get("/health", headers={"Host": "workbench.test:8000"}).status_code == 403
    monkeypatch.setenv("WORKBENCH_ALLOWED_HOSTS", "workbench.test, other.test")
    assert client.get("/health", headers={"Host": "workbench.test:8000"}).status_code == 200
    assert client.get("/health", headers={"Host": "other.test"}).status_code == 200
    assert client.get("/health", headers={"Host": "third.test"}).status_code == 403


# --- Origin and Sec-Fetch-Site on state-changing requests ----------------------------


@pytest.mark.parametrize(
    "origin",
    [
        "http://attacker.example",
        "http://127.0.0.1:9999",  # another page on this computer, another port
        "http://localhost:5174",
        "https://localhost:5173",
        "null",  # sandboxed iframe, file:// and data: documents
    ],
)
def test_foreign_origin_cannot_post_json(client, tmp_path, origin):
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "foreign"},
        headers={"Origin": origin},
    )
    _assert_rejected(response, "LOCAL_REQUEST_ORIGIN_REJECTED")
    assert not (tmp_path / "foreign").exists()
    record = _audit_records(tmp_path)[-1]
    assert record["code"] == "LOCAL_REQUEST_ORIGIN_REJECTED"
    assert record["method"] == "POST"
    assert record["path"] == "/projects"
    assert record["origin"] == origin


def test_foreign_origin_cannot_submit_a_multipart_form(client, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    response = client.post(
        "/runs",
        data={"project_root": str(project), "y": "y", "x": "x"},
        files={"file": ("data.csv", b"y,x\n1,2\n3,4\n", "text/csv")},
        headers={"Origin": "http://127.0.0.1:9999", "Sec-Fetch-Site": "same-site"},
    )
    _assert_rejected(response, "LOCAL_REQUEST_ORIGIN_REJECTED")
    assert list(project.iterdir()) == []


@pytest.mark.parametrize(
    "content_type", ["application/x-www-form-urlencoded", "text/plain"]
)
def test_foreign_origin_cannot_send_a_simple_request(client, tmp_path, content_type):
    response = client.post(
        "/projects",
        content=b"parent=/tmp&name=simple",
        headers={"Origin": "http://attacker.example", "Content-Type": content_type},
    )
    _assert_rejected(response, "LOCAL_REQUEST_ORIGIN_REJECTED")


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_every_state_changing_method_is_checked(client, tmp_path, method):
    response = client.request(
        method,
        "/compare-nodes/anything",
        params={"project_root": str(tmp_path)},
        headers={"Origin": "http://attacker.example"},
    )
    _assert_rejected(response, "LOCAL_REQUEST_ORIGIN_REJECTED")


def test_cross_site_fetch_metadata_is_rejected_without_an_origin(client, tmp_path):
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "cross"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    _assert_rejected(response, "LOCAL_REQUEST_CROSS_SITE_REJECTED")
    assert not (tmp_path / "cross").exists()


def test_cross_site_fetch_metadata_wins_over_an_allowed_origin(client, tmp_path):
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "cross"},
        headers={"Origin": VITE_UI, "Sec-Fetch-Site": "cross-site"},
    )
    _assert_rejected(response, "LOCAL_REQUEST_CROSS_SITE_REJECTED")


# --- Legitimate clients keep working -----------------------------------------------


def test_cli_and_scripts_without_origin_are_unaffected(client, tmp_path):
    response = client.post("/projects", json={"parent": str(tmp_path), "name": "cli"})
    assert response.status_code == 200, response.text
    assert (tmp_path / "cli").is_dir()
    assert _audit_records(tmp_path) == []


def test_vite_proxied_ui_request_is_admitted(client, tmp_path):
    # Vite's proxy (changeOrigin) rewrites Host to the backend's own address
    # and forwards the browser's Origin and fetch metadata unchanged.
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "ui"},
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": VITE_UI,
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
        },
    )
    assert response.status_code == 200, response.text
    assert (tmp_path / "ui").is_dir()


@pytest.mark.parametrize("origin", ["http://127.0.0.1:5173", "http://[::1]:5173"])
def test_vite_ui_on_other_loopback_names_is_admitted(client, tmp_path, origin):
    response = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "ui"}, headers={"Origin": origin}
    )
    assert response.status_code == 200, response.text


def test_same_origin_page_served_by_the_backend_is_admitted(client, tmp_path):
    # e.g. the OpenAPI docs page at :8000/docs using "Try it out".
    response = client.post(
        "/projects",
        json={"parent": str(tmp_path), "name": "docs"},
        headers={"Host": "localhost:8000", "Origin": "http://localhost:8000", "Sec-Fetch-Site": "same-origin"},
    )
    assert response.status_code == 200, response.text


def test_configured_ui_origins_are_admitted(client, tmp_path, monkeypatch):
    headers = {"Origin": "http://127.0.0.1:4173"}
    body = {"parent": str(tmp_path), "name": "configured"}
    assert client.post("/projects", json=body, headers=headers).status_code == 403
    monkeypatch.setenv("WORKBENCH_UI_ORIGIN", "http://127.0.0.1:4173/")
    assert client.post("/projects", json=body, headers=headers).status_code == 200
    monkeypatch.delenv("WORKBENCH_UI_ORIGIN")
    monkeypatch.setenv("WORKBENCH_ALLOWED_ORIGINS", "http://127.0.0.1:4173, http://localhost:4173")
    body["name"] = "configured-2"
    assert client.post("/projects", json=body, headers=headers).status_code == 200


@pytest.mark.parametrize("origin", ["http://attacker.example", "http://127.0.0.1:9999"])
def test_reads_that_name_a_foreign_origin_are_rejected(client, origin):
    # The Vite dev server answers CORS for any localhost origin, including on
    # its /api proxy, so a page on another local port could otherwise read
    # proxied responses. The proxy forwards the browser's Origin unchanged.
    response = client.get("/llm/config", headers={"Origin": origin, "Sec-Fetch-Mode": "cors"})
    _assert_rejected(response, "LOCAL_REQUEST_ORIGIN_REJECTED")


def test_reads_from_the_ui_and_without_origin_are_admitted(client):
    assert client.get("/llm/config").status_code == 200
    assert client.get("/llm/config", headers={"Origin": VITE_UI}).status_code == 200


def test_cross_site_navigation_reads_are_admitted(client):
    # A link from another site carries no Origin; reads stay unshared with
    # foreign pages because no CORS header is ever granted.
    response = client.get("/health", headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in {key.lower() for key in response.headers}


# --- Audit is bounded ---------------------------------------------------------------


def test_rejection_audit_is_bounded_and_counts_what_it_dropped(client, tmp_path):
    limit = local_request_guard.AUDIT_RECORDS_PER_WINDOW
    for _ in range(limit + 25):
        client.post("/projects", json={}, headers={"Origin": "http://attacker.example"})
    records = _audit_records(tmp_path)
    assert len(records) == limit
    local_request_guard.reset_audit_budget(keep_suppressed=True)
    client.post("/projects", json={}, headers={"Origin": "http://attacker.example"})
    records = _audit_records(tmp_path)
    assert len(records) == limit + 1
    assert records[-1]["suppressed_before"] == 25


def test_audited_header_values_are_bounded(client, tmp_path):
    client.post("/projects", json={}, headers={"Origin": "http://" + "a" * 5000 + ".example"})
    record = _audit_records(tmp_path)[-1]
    assert len(record["origin"]) <= local_request_guard.AUDIT_VALUE_LIMIT


# --- Budget -------------------------------------------------------------------------


def test_guard_overhead_is_far_below_one_millisecond():
    asgi = local_request_guard.LocalRequestGuard(_ok_app)
    headers = [
        (b"host", b"127.0.0.1:8000"),
        (b"origin", VITE_UI.encode()),
        (b"sec-fetch-site", b"same-origin"),
        (b"content-type", b"application/json"),
    ]
    rounds = 5000

    async def run() -> float:
        started = time.perf_counter()
        for _ in range(rounds):
            await _call_async(asgi, method="POST", headers=headers)
        return (time.perf_counter() - started) / rounds

    assert asyncio.run(run()) < 0.001


# --- helpers ------------------------------------------------------------------------


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def _call_async(asgi, *, method: str, headers: list[tuple[bytes, bytes]]):
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8000),
    }
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await asgi(scope, receive, send)
    status = next(item["status"] for item in sent if item["type"] == "http.response.start")
    body = b"".join(item.get("body", b"") for item in sent if item["type"] == "http.response.body")
    return status, body


def _call(asgi, *, method: str, headers: list[tuple[bytes, bytes]]):
    return _call_async(asgi, method=method, headers=headers)


def test_an_allowed_loopback_origin_covers_every_loopback_name_for_that_port(client, tmp_path, monkeypatch):
    # The same UI is reached as localhost, 127.0.0.1 or [::1]; listing one
    # name must not leave the UI broken under another.
    monkeypatch.setenv("WORKBENCH_ALLOWED_ORIGINS", "http://127.0.0.1:5192")
    for index, origin in enumerate(["http://localhost:5192", "http://[::1]:5192", "http://127.0.0.1:5192"]):
        body = {"parent": str(tmp_path), "name": f"alias-{index}"}
        assert client.post("/projects", json=body, headers={"Origin": origin}).status_code == 200, origin
    for origin in ["http://localhost:5193", "https://localhost:5192", "http://localhost"]:
        response = client.post("/projects", json={}, headers={"Origin": origin})
        _assert_rejected(response, "LOCAL_REQUEST_ORIGIN_REJECTED")


def test_rejection_messages_describe_reads_and_writes_alike(client):
    message = client.get("/health", headers={"Origin": "http://attacker.example"}).json()["error"]["message"]
    assert "change" not in message.lower()
