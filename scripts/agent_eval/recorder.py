"""Record (and later replay) every model-provider exchange of an evaluation run.

Wraps the provider HTTP client at the transport, so the product code under
evaluation is not changed: the request body (messages, tool schemas) and the
raw response stream, including the provider's ``usage`` (DeepSeek reports
``prompt_cache_hit_tokens`` / ``prompt_cache_miss_tokens`` in the final chunk),
are appended to a JSONL file. The API key never reaches the record: only the
request body is kept, and the Authorization header is dropped.

Replay serves the recorded responses in recorded order and never reaches the
network; running out of recorded responses fails loudly. Request bodies carry
session ids and timestamps, so replay matches by order and counts how many
request bodies differed from the recording (``tape.mismatches``) instead of
requiring identical hashes.
"""

from __future__ import annotations

import hashlib
import asyncio
import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import httpx


def _body_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _usage_from_stream(raw: bytes) -> dict[str, Any] | None:
    usage = None
    for line in raw.decode("utf-8", "replace").splitlines():
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            payload = json.loads(data)
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("usage"), dict):
            usage = payload["usage"]
    return usage


def _usage_from_json(raw: bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    return payload.get("usage") if isinstance(payload, dict) else None


class _Tape:
    def __init__(self, path: Path, mode: str) -> None:
        self.path = path
        self.mode = mode
        self.lock = threading.Lock()
        self.context: dict[str, Any] = {}
        self.queue: list[dict[str, Any]] = []
        self.mismatches = 0
        if mode == "replay":
            self.queue = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def write(self, record: dict[str, Any]) -> None:
        with self.lock, self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def take(self, digest: str) -> dict[str, Any]:
        with self.lock:
            if not self.queue:
                raise RuntimeError(f"replay: no recorded response left for request {digest[:12]}")
            record = self.queue.pop(0)
            if record["request_sha256"] != digest:
                self.mismatches += 1
            return record


#: Failures to establish the connection (TCP, proxy CONNECT or TLS handshake):
#: the request was never sent. Anything later may have been billed.
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout)


class _RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, tape: _Tape, inner: httpx.AsyncBaseTransport | None, *, budget=None) -> None:
        self.tape = tape
        self.inner = inner
        self.budget = budget

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = request.content if isinstance(request.content, bytes) else await request.aread()
        digest = _body_hash(body)
        if self.tape.mode == "replay":
            record = self.tape.take(digest)
            raw = record["response_raw"].encode("utf-8")
            return httpx.Response(record["status"], headers={"content-type": record["content_type"]}, content=raw)
        started = time.time()
        assert self.inner is not None
        reservation = self.budget.reserve(body) if self.budget is not None else None
        try:
            response = await self.inner.handle_async_request(request)
            raw = await response.aread()
        except BaseException as exc:
            self.tape.write({**self.tape.context, "at": started, "elapsed_s": time.time() - started,
                "url_path": request.url.path, "status": 0, "content_type": "", "request_sha256": digest,
                "request": json.loads(body), "request_bytes": len(body), "response_raw": "", "usage": None,
                "transport_error": type(exc).__name__, "budget_reservation": reservation,
                "sent": not isinstance(exc, _NOT_SENT)})
            if isinstance(exc, _NOT_SENT) and hasattr(self.budget, "unreachable"):
                self.budget.release(reservation)
                self.budget.unreachable(type(exc).__name__)
            if self.budget is not None and isinstance(exc, _NOT_SENT):
                # No connection, so no request reached the provider: nothing can be
                # billed. Release it and let the product's own retry run (the paid
                # fix1 round froze on one such ConnectError).
                self.budget.release(reservation)
                raise
            tolerate = getattr(self.budget, "tolerate_transport_interruption", None)
            # The task's own directory: Ask and Auto runs of one task share its name and ledger.
            if tolerate is not None and not isinstance(exc, KeyboardInterrupt) and tolerate(
                    type(exc).__name__, task=str(self.tape.path.parent)):
                # Free route: nothing is billed, so an interrupted call is the product's to
                # handle (including its own no-progress cancel, a CancelledError after the
                # idle bound); after repeated interruptions in one task the guard ends that task.
                raise
            if self.budget is not None:
                self.budget.stop("transport interrupted; preserve reservation until billing is reconciled")
                from .budget import BudgetStop
                raise BudgetStop("unknown usage after transport failure") from exc
            raise
        elapsed = time.time() - started
        content_type = response.headers.get("content-type", "")
        try:
            request_json = json.loads(body)
        except ValueError:
            request_json = None
        stream = "event-stream" in content_type
        usage = _usage_from_stream(raw) if stream else _usage_from_json(raw)
        self.tape.write({
            **self.tape.context,
            "at": started,
            "elapsed_s": round(elapsed, 3),
            "url_path": request.url.path,
            "status": response.status_code,
            "content_type": content_type,
            "request_sha256": digest,
            "request": request_json,
            "request_bytes": len(body),
            "response_raw": raw.decode("utf-8", "replace"),
            "usage": usage,
            "budget_reservation": reservation,
        })
        if usage is None and response.status_code >= 400 and hasattr(self.budget, "refused"):
            self.budget.refused(response.status_code, raw)
        if self.budget is not None:
            self.budget.settle(reservation, usage)
        # ``aread`` already decoded the body: pass it on without the
        # encoding and length headers, or the client decodes it a second time,
        # fails, and the adapter retries a request that had succeeded.
        headers = [(k, v) for k, v in response.headers.items()
                   if k.lower() not in {"content-encoding", "content-length", "transfer-encoding"}]
        return httpx.Response(response.status_code, headers=headers, content=raw)


@contextmanager
def provider_tape(path: Path, *, mode: str = "record", budget=None) -> Iterator[_Tape]:
    """Install the recording (or replaying) transport for the provider client."""

    from workbench.llm import client as llm_client

    if mode not in {"record", "replay"}:
        raise ValueError("mode must be record or replay")
    path.parent.mkdir(parents=True, exist_ok=True)
    tape = _Tape(path, mode)
    original = llm_client._async_client_factory

    def factory(config):
        inner = None if mode == "replay" else httpx.AsyncHTTPTransport()
        return httpx.AsyncClient(timeout=config.timeout_s, transport=_RecordingTransport(tape, inner, budget=budget))

    llm_client._async_client_factory = factory
    try:
        yield tape
    finally:
        llm_client._async_client_factory = original
