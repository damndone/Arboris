"""Bounded, non-model-visible observations of actual provider steps.

Usage is the provider's reported object, not an estimate or billing receipt.
Missing information never becomes zero; pricing is deliberately unverified.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

MAX_USAGE_BYTES = 16_384


def snapshot_usage(value: Any) -> tuple[dict[str, Any] | None, str]:
    if value is None:
        return None, "unavailable"
    if type(value) is not dict:
        return None, "invalid"
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(raw.encode("utf-8")) > MAX_USAGE_BYTES:
            return None, "oversized"
        return json.loads(raw), "reported"
    except (TypeError, ValueError, UnicodeError, RecursionError):
        return None, "invalid"


async def observe_provider(source_factory, *, request, events, session_id, command_id, provider_step,
                           phase_episode_id, model, timeout_s=None):
    """Observe a Core-selected source, closing it before tool execution starts.

    The caller must close this iterator on early exit. It cannot run tools,
    allocate a command, change budgets, retry or instantiate a model adapter.
    """
    loop = asyncio.get_running_loop()
    started = loop.time()
    usage, usage_state = None, "unavailable"
    first_public = provider_request_id = None
    outcome, retries, source = "interrupted", 0, None
    try:
        source = source_factory()
        async with asyncio.timeout(timeout_s):
            async for event in source:
                if event.usage is not None:
                    usage, usage_state = snapshot_usage(event.usage)
                if event.provider_request_id:
                    provider_request_id = event.provider_request_id
                public = ((event.type == "text_delta" and bool(event.delta))
                          or (event.type in {"tool_call_start", "tool_call_delta"} and bool(event.tool_call)))
                if first_public is None and public:
                    first_public = loop.time() - started
                if event.type == "done":
                    outcome = event.finish_reason or "stop"
                elif event.type == "error":
                    outcome = "aborted" if event.error == "aborted" else "error"
                elif event.type == "retry":
                    retries += 1
                yield event
        if outcome == "interrupted":
            outcome = "eof"
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except TimeoutError:
        outcome = "timeout"
        raise
    except Exception:
        outcome = "error"
        raise
    finally:
        try:
            close = getattr(source, "aclose", None)
            if close is not None:
                await close()
        except Exception:
            outcome = "error"
            raise
        finally:
            events.emit(session_id, "provider_step", {
                "request_id": request.request_id, "provider_request_id": provider_request_id,
                "provider_step": provider_step, "phase_episode_id": phase_episode_id, "model": model,
                "elapsed_s": loop.time() - started, "first_public_s": first_public,
                "outcome": outcome, "retries": retries, "usage": usage, "usage_state": usage_state,
                "usage_scope": "last_reported_snapshot", "cost": None, "cost_state": "pricing_unverified",
            }, command_id=command_id)
