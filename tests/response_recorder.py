"""Record real JSON responses per route while the suite runs (opt-in).

Enabled by ``WORKBENCH_RECORD_RESPONSES=<directory>``; tests/conftest.py then
installs ``ResponseRecorder`` on the app before any request. Each process
appends to ``<directory>/responses-<pid>.jsonl`` one line per 2xx JSON
response: method, route template, status, the test that made it, and the body
with arrays cut to ``ARRAY_SAMPLE`` items. At most ``SAMPLES_PER_ROUTE``
bodies are kept per route. scripts/infer_response_types.py turns the samples
into draft response types (V1812-OPENAPI-TYPES).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ARRAY_SAMPLE = 20
SAMPLES_PER_ROUTE = 40


def _trim(value: Any) -> Any:
    if isinstance(value, list):
        return [_trim(item) for item in value[:ARRAY_SAMPLE]]
    if isinstance(value, dict):
        return {key: _trim(item) for key, item in value.items()}
    return value


class ResponseRecorder:
    def __init__(self, app: Any, directory: Path) -> None:
        self.app = app
        self.path = Path(directory) / f"responses-{os.getpid()}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.counts: dict[tuple[str, str], int] = {}

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status = 0
        json_body = False
        chunks: list[bytes] = []

        async def capture(message: dict[str, Any]) -> None:
            nonlocal status, json_body
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = dict(message.get("headers", ()))
                json_body = headers.get(b"content-type", b"").startswith(b"application/json")
            elif message["type"] == "http.response.body" and json_body:
                chunks.append(message.get("body", b""))
            await send(message)

        await self.app(scope, receive, capture)
        route = getattr(scope.get("route"), "path", None)
        if route is None or not json_body or not 200 <= status < 300:
            return
        key = (scope["method"], route)
        if self.counts.get(key, 0) >= SAMPLES_PER_ROUTE:
            return
        try:
            body = json.loads(b"".join(chunks))
        except ValueError:
            return
        self.counts[key] = self.counts.get(key, 0) + 1
        test = (os.environ.get("PYTEST_CURRENT_TEST") or "").rsplit(" (", 1)[0]
        record = {"method": key[0], "route": key[1], "status": status, "test": test, "body": _trim(body)}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
