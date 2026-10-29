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

    async def aclose(self) -> None:
        if self.inner is not None:
            await self.inner.aclose()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.tape.mode != "replay" and hasattr(self.budget, "check_request"):
            self.budget.check_request(request)
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
            request_json = json.loads(body)
        except ValueError:
            request_json = None
        response = None
        try:
            response = await self.inner.handle_async_request(request)
            content_type = response.headers.get("content-type", "")
            if response.status_code == 200 and "event-stream" in content_type:
                # Pass the stream through as it arrives. Reading it whole first hid
                # every chunk from the product until the model had finished, so its
                # 90 s no-progress bound cut any answer longer than 90 s (Hy3 and
                # Step-5 "stalls", 2026-10-23: no successful call ever exceeded 90 s).
                headers = [(k, v) for k, v in response.headers.items()
                           if k.lower() not in {"content-encoding", "content-length", "transfer-encoding"}]
                tee = _TeeStream(response, lambda raw, exc: self._finish(
                    request, digest, body, request_json, started, reservation, response, raw, exc))
                return httpx.Response(response.status_code, headers=headers, stream=tee)
            raw = await response.aread()
        except BaseException as exc:
            self._interrupted(request, digest, body, started, reservation, exc, b"",
                sent=not isinstance(exc, _NOT_SENT), response=response)
            raise
        self._record(request, digest, body, request_json, started, reservation, response, raw)
        # ``aread`` already decoded the body: pass it on without the
        # encoding and length headers, or the client decodes it a second time,
        # fails, and the adapter retries a request that had succeeded.
        headers = [(k, v) for k, v in response.headers.items()
                   if k.lower() not in {"content-encoding", "content-length", "transfer-encoding"}]
        return httpx.Response(response.status_code, headers=headers, content=raw)

    def _finish(self, request, digest, body, request_json, started, reservation, response, raw, exc):
        """The streamed reply ended: completely, or abandoned or cut off part-way.

        The product closes a stream once it has the completion and its usage, a
        moment before the connection's end; usage comes only at the end, so a
        stream closed after it is complete, not abandoned (first streaming run,
        2026-10-23: four complete replies were taped as interruptions).
        """
        if exc is None or (isinstance(exc, asyncio.CancelledError) and _usage_from_stream(raw) is not None):
            self._record(request, digest, body, request_json, started, reservation, response, raw)
        else:
            self._interrupted(request, digest, body, started, reservation, exc, raw, sent=True, response=response)

    def _record(self, request, digest, body, request_json, started, reservation, response, raw):
        content_type = response.headers.get("content-type", "")
        usage = _usage_from_stream(raw) if "event-stream" in content_type else _usage_from_json(raw)
        self.tape.write({
            **self.tape.context,
            "at": started,
            "elapsed_s": round(time.time() - started, 3),
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
        if hasattr(self.budget, "recover_overload"):
            self.budget.recover_overload(response.status_code, raw, reservation)
        if hasattr(self.budget, "check_response"):
            self.budget.check_response(response.status_code, raw)
        if hasattr(self.budget, "end_incomplete_stream_task"):
            self.budget.end_incomplete_stream_task(status=response.status_code, content_type=content_type,
                raw=raw, key=reservation, task=str(self.tape.path.parent))
        if usage is None and response.status_code >= 400 and hasattr(self.budget, "refused"):
            self.budget.refused(response.status_code, raw)
        if self.budget is not None:
            self.budget.settle(reservation, usage)

    def _interrupted(self, request, digest, body, started, reservation, exc, raw, *, sent, response=None):
        """Tape an exchange that did not complete, then apply the round's rules.
        Raises when the round (or, on the free route, the task) must stop."""
        self.tape.write({**self.tape.context, "at": started, "elapsed_s": time.time() - started,
            "url_path": request.url.path, "status": 0,
            "upstream_http_status": response.status_code if response is not None else None,
            "content_type": response.headers.get("content-type", "") if response is not None else "", "request_sha256": digest,
            "request": json.loads(body), "request_bytes": len(body), "response_raw": raw.decode("utf-8", "replace"),
            "usage": None, "transport_error": type(exc).__name__, "budget_reservation": reservation, "sent": sent})
        if hasattr(self.budget, "recover_unanswered_transport_error"):
            self.budget.recover_unanswered_transport_error(response=response, raw=raw, sent=sent, error=exc, key=reservation)
        if response is not None and hasattr(self.budget, "recover_overload"):
            self.budget.recover_overload(response.status_code, raw, reservation)
        if response is not None and hasattr(self.budget, "check_response"):
            self.budget.check_response(response.status_code, raw)
        if not sent and hasattr(self.budget, "unreachable"):
            self.budget.release(reservation)
            self.budget.unreachable(type(exc).__name__)
        if self.budget is not None and not sent:
            # No connection, so no request reached the provider: nothing can be
            # billed. Release it and let the product's own retry run (the paid
            # fix1 round froze on one such ConnectError).
            self.budget.release(reservation)
            return
        tolerate = getattr(self.budget, "tolerate_transport_interruption", None)
        # The task's own directory: Ask and Auto runs of one task share its name and ledger.
        if tolerate is not None and not isinstance(exc, KeyboardInterrupt) and tolerate(
                type(exc).__name__, task=str(self.tape.path.parent)):
            # Only a guard with an explicitly authorized recovery policy can
            # permit this. The current free-route guard raises BudgetStop on
            # the first unknown usage; catalog pricing is not billing evidence.
            return
        if self.budget is not None:
            self.budget.stop("transport interrupted; preserve reservation until billing is reconciled")
            from .budget import BudgetStop
            raise BudgetStop("unknown usage after transport failure") from exc


class _TeeStream(httpx.AsyncByteStream):
    """Hand each chunk on as it arrives and keep a copy; report once, when the stream ends."""

    def __init__(self, response: httpx.Response, finish) -> None:
        self._response = response
        self._finish = finish
        self._parts: list[bytes] = []
        self._done = False

    async def __aiter__(self):
        try:
            async for chunk in self._response.aiter_bytes():
                self._parts.append(chunk)
                yield chunk
        except BaseException as exc:
            self._end(exc)
            raise
        self._end(None)

    async def aclose(self) -> None:
        # Closed before the end: the reader abandoned the stream (the product's
        # own no-progress cancel, or its Stop).
        try:
            if not self._done:
                self._end(asyncio.CancelledError())
        finally:
            await self._response.aclose()

    def _end(self, exc) -> None:
        if self._done:
            return
        self._done = True
        self._finish(b"".join(self._parts), exc)


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
    stream_original = model_original = None
    if mode == "record" and getattr(budget, "overload_recovery", None) is not None:
        from workbench.agent import model as agent_model
        from .budget import NvidiaOverloadRetry
        stream_original = llm_client.async_stream_chat_completion
        model_original = agent_model.async_stream_chat_completion

        async def recovering_stream(*args, **kwargs):
            while True:
                try:
                    async for event in stream_original(*args, **kwargs):
                        yield event
                    return
                except NvidiaOverloadRetry as retry:
                    await budget.wait_for_retry(retry)

        llm_client.async_stream_chat_completion = recovering_stream
        agent_model.async_stream_chat_completion = recovering_stream
    try:
        yield tape
    finally:
        llm_client._async_client_factory = original
        if stream_original is not None:
            llm_client.async_stream_chat_completion = stream_original
            agent_model.async_stream_chat_completion = model_original
