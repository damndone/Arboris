"""Answer only this computer's UI and local clients (V1812-LOCAL-API-SECURITY).

The backend listens on loopback, but any web page the user opens can still
reach it:

* DNS rebinding points the page's own host name at 127.0.0.1, so the browser
  treats this server as same-origin. The request still names the attacker's
  host in ``Host``, so only loopback host names are admitted.
* A form post or ``no-cors`` fetch from another origin -- including another
  port on this computer -- changes state without a CORS preflight. Such a
  request carries its ``Origin`` and, in current browsers,
  ``Sec-Fetch-Site: cross-site``.

Any request that names an Origin other than this server itself or an allowed
UI origin is refused, whatever its method: the Vite dev server answers CORS
for every localhost origin, including on its ``/api`` proxy, and forwards the
browser's Origin unchanged, so this is what keeps a page on another local
port from reading proxied responses. A state-changing request is also refused
when it is cross-site. Clients that send no Origin (the CLI, scripts, curl)
and same-origin UI reads (browsers omit Origin there) are unaffected. This
server never grants a CORS header itself.

Allowances are explicit only: ``WORKBENCH_ALLOWED_HOSTS`` (host names) and
``WORKBENCH_ALLOWED_ORIGINS`` (origins), both comma-separated, plus the UI
origin the CLI already honours, ``WORKBENCH_UI_ORIGIN``. Every refusal is
appended to the user-level egress audit log, at a bounded rate so a hostile
page cannot fill the disk.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from .. import egress

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})
DEFAULT_UI_ORIGIN = "http://localhost:5173"
STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

HOST_REJECTED = "LOCAL_REQUEST_HOST_REJECTED"
ORIGIN_REJECTED = "LOCAL_REQUEST_ORIGIN_REJECTED"
CROSS_SITE_REJECTED = "LOCAL_REQUEST_CROSS_SITE_REJECTED"

_MESSAGES = {
    HOST_REJECTED: "This Workbench server only answers requests addressed to this computer.",
    ORIGIN_REJECTED: "This Workbench server does not accept requests from this web page.",
    CROSS_SITE_REJECTED: "This Workbench server does not accept changes from another site.",
}

AUDIT_RECORDS_PER_WINDOW = 100
AUDIT_WINDOW_S = 60.0
AUDIT_VALUE_LIMIT = 256

_HOST_PATTERN = re.compile(r"^(\[[0-9a-f:.]+\]|[^\[\]:/@\s]+)(?::[0-9]{1,5})?$")


def _hostname(host: str) -> str | None:
    match = _HOST_PATTERN.match(host.strip().lower())
    return match.group(1) if match else None


def _normalize_origin(origin: str) -> str:
    return origin.strip().lower().rstrip("/")


@lru_cache(maxsize=8)
def _allowed_hosts(extra: str) -> frozenset[str]:
    names = {_hostname(item) for item in extra.split(",") if item.strip()}
    return LOOPBACK_HOSTS | {name for name in names if name}


_ORIGIN_PATTERN = re.compile(r"^(https?)://(\[[0-9a-f:.]+\]|[^\[\]:/@\s]+)(:[0-9]{1,5})?$")


@lru_cache(maxsize=8)
def _allowed_origins(ui_origin: str, extra: str) -> frozenset[str]:
    """Configured origins; a loopback origin also stands for the other
    loopback names on the same scheme and port (one listener, one UI)."""

    allowed: set[str] = set()
    for item in (DEFAULT_UI_ORIGIN, ui_origin, *extra.split(",")):
        origin = _normalize_origin(item)
        if not origin:
            continue
        allowed.add(origin)
        match = _ORIGIN_PATTERN.match(origin)
        if match and match.group(2) in LOOPBACK_HOSTS:
            scheme, _host, port = match.groups()
            allowed.update(f"{scheme}://{name}{port or ''}" for name in LOOPBACK_HOSTS)
    return frozenset(allowed)


def rejection(method: str, scheme: str, headers: dict[str, str]) -> str | None:
    """The refusal code for a request, or ``None`` when it is admitted."""

    host = headers.get("host", "")
    name = _hostname(host)
    if name is None or name not in _allowed_hosts(os.environ.get("WORKBENCH_ALLOWED_HOSTS", "")):
        return HOST_REJECTED
    origin = headers.get("origin")
    if origin is not None:
        origin = _normalize_origin(origin)
        allowed = origin == f"{scheme}://{host.strip().lower()}" or origin in _allowed_origins(
            os.environ.get("WORKBENCH_UI_ORIGIN", ""),
            os.environ.get("WORKBENCH_ALLOWED_ORIGINS", ""),
        )
        if not allowed:
            return ORIGIN_REJECTED
    if method in STATE_CHANGING_METHODS and headers.get("sec-fetch-site", "").strip().lower() == "cross-site":
        return CROSS_SITE_REJECTED
    return None


class LocalRequestGuard:
    """Pure ASGI middleware; refuses before any route, body or upload is read."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        kind = scope["type"]
        if kind not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", ())
        }
        # A WebSocket handshake is not covered by the same-origin policy, so
        # it is held to the state-changing rules.
        method = scope.get("method", "GET") if kind == "http" else "POST"
        scheme = {"wss": "https", "ws": "http"}.get(scope.get("scheme", "http"), scope.get("scheme", "http"))
        code = rejection(method, scheme, headers)
        if code is None:
            await self.app(scope, receive, send)
            return
        _audit(code, scope.get("method", "WEBSOCKET"), scope.get("path", ""), headers)
        if kind == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = json.dumps(
            {"error": {"code": code, "message": _MESSAGES[code], "details": {}}}
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


_budget_lock = threading.Lock()
_budget = {"window_start": 0.0, "written": 0, "suppressed": 0}


def reset_audit_budget(*, keep_suppressed: bool = False) -> None:
    """Start a fresh audit window (tests and window rollover)."""

    with _budget_lock:
        _budget["window_start"] = time.monotonic()
        _budget["written"] = 0
        if not keep_suppressed:
            _budget["suppressed"] = 0


def _audit(code: str, method: str, path: str, headers: dict[str, str]) -> None:
    with _budget_lock:
        now = time.monotonic()
        if now - _budget["window_start"] >= AUDIT_WINDOW_S:
            _budget["window_start"] = now
            _budget["written"] = 0
        if _budget["written"] >= AUDIT_RECORDS_PER_WINDOW:
            _budget["suppressed"] += 1
            return
        _budget["written"] += 1
        suppressed, _budget["suppressed"] = _budget["suppressed"], 0
    record = {
        "at": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "kind": "local_request_rejected",
        "code": code,
        "method": method,
        "path": path[:AUDIT_VALUE_LIMIT],
        "host": headers.get("host", "")[:AUDIT_VALUE_LIMIT],
        "origin": headers.get("origin", "")[:AUDIT_VALUE_LIMIT],
        "sec_fetch_site": headers.get("sec-fetch-site", "")[:AUDIT_VALUE_LIMIT],
        "suppressed_before": suppressed,
    }
    try:
        egress.append_user_audit_record(record)
    except OSError:
        # The refusal stands even when the log cannot be written.
        pass
