"""HTTP waiters do not own accepted in-process Agent work."""
from workbench.http import agent_turn_routes
from workbench.http import agent_route_runtime

import asyncio
import logging
from dataclasses import replace

import httpx
import pytest

from tests.test_agent_routes import _config, _context_packet
from workbench.agent.model import ModelStreamEvent
from workbench.app import app


async def _session(client, project, chain):
    response = await client.post("/agent/sessions", params={"project_root": str(project)}, json={
        "role": "chain", "chain_id": chain, "run_id": "run-a", "context_packet": _context_packet(),
    })
    assert response.status_code == 200, response.text
    return response.json()["session_id"]


@pytest.mark.parametrize("endpoint", ["turns", "continue"])
@pytest.mark.parametrize("control", ["finish", "steer", "abort"])
def test_cancelled_http_waiter_keeps_one_owned_turn_and_live_controls(tmp_path, monkeypatch, endpoint, control):
    from workbench.http import agent_routes as routes

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        instances = []

        class BlockingProvider:
            def __init__(self, config):
                self.requests = []
                self.cancelled = False
                instances.append(self)
            async def stream(self, request):
                self.requests.append(request)
                if self is instances[0] and len(self.requests) == 1:
                    started.set()
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        self.cancelled = True
                        raise
                yield ModelStreamEvent.text_delta(request.request_id, "Completed.")
                yield ModelStreamEvent.done(request.request_id)

        monkeypatch.setattr(agent_route_runtime, "load_llm_config", lambda: replace(_config(), context_window_tokens=128_000))
        monkeypatch.setattr(agent_route_runtime, "OpenAICompatibleModelAdapter", BlockingProvider)
        project = tmp_path / "project"
        project.mkdir()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            session = await _session(client, project, "chain-a")
            other = await _session(client, project, "chain-b")
            params = {"project_root": str(project)}
            body = {"question": "Work once."} if endpoint == "turns" else {}
            waiter = asyncio.create_task(client.post(f"/agent/sessions/{session}/{endpoint}", params=params, json=body))
            try:
                await asyncio.wait_for(started.wait(), 2)
                core = routes.turn_registry.get(project, session)
                waiter.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await waiter
                assert routes.turn_registry.get(project, session) is core
                assert not instances[0].cancelled
                busy = await client.post(f"/agent/sessions/{session}/turns", params=params, json={"question": "Duplicate."})
                assert busy.status_code == 409
                other_result = await client.post(f"/agent/sessions/{other}/turns", params=params, json={"question": "Other."})
                assert other_result.status_code == 200, other_result.text
                if control == "steer":
                    response = await client.post(f"/agent/sessions/{session}/steer", params=params, json={"text": "Steer once."})
                    assert response.status_code == 200
                elif control == "abort":
                    response = await client.post(f"/agent/sessions/{session}/abort", params=params)
                    assert response.status_code == 200
                    assert instances[0].requests[0].abort_event.is_set()
                owned = routes.turn_registry.tasks[routes._active_turn_key(project, session)]
                release.set()
                await asyncio.wait_for(asyncio.shield(owned), 2)
                await asyncio.sleep(0)  # Allow the registry's completion callback.
                assert routes.turn_registry.get(project, session) is None
                assert routes._active_turn_key(project, session) not in routes.turn_registry.tasks
                assert routes._active_turn_key(project, session) not in routes._RESERVED_TURNS
                assert len(instances[0].requests) == (2 if control == "steer" else 1), [request.messages[-1] for request in instances[0].requests]
                loaded = await client.get(f"/agent/sessions/{session}", params=params)
                messages = loaded.json()["messages"]
                assert sum(message["role"] == "user" and message["content"] == "Work once." for message in messages) == (endpoint == "turns")
                assert any(message["role"] == "assistant" for message in messages)
                events = await client.get(f"/agent/sessions/{session}/events", params=params)
                assert "message_end" in {event["event_type"] for event in events.json()["events"]}
            finally:
                release.set()
                await asyncio.gather(waiter, return_exceptions=True)
                owned = getattr(routes.turn_registry, "tasks", {}).get(routes._active_turn_key(project, session))
                if owned is not None:
                    await asyncio.gather(owned, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("detached", [False, True])
def test_owned_route_failure_is_observed_and_releases_reservation(tmp_path, monkeypatch, caplog, detached):
    from workbench.http import agent_routes as routes

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        failure = RuntimeError("owned setup failed")
        async def failing_setup(*args, **kwargs):
            started.set()
            await release.wait()
            raise failure
        monkeypatch.setattr(agent_turn_routes, "_run_reserved_agent_turn", failing_setup)
        project = tmp_path / "project"
        project.mkdir()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            session = await _session(client, project, "chain-a")
            waiter = asyncio.create_task(client.post(f"/agent/sessions/{session}/turns", params={"project_root": str(project)}, json={"question": "Fail."}))
            await asyncio.wait_for(started.wait(), 2)
            if detached:
                waiter.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await waiter
                owned = routes.turn_registry.tasks[routes._active_turn_key(project, session)]
                release.set()
                await asyncio.wait({owned}, timeout=2)  # Do not retrieve its exception for the registry.
                await asyncio.sleep(0)
                assert not owned._log_traceback
            else:
                release.set()
                with pytest.raises(RuntimeError) as caught:
                    await waiter
                assert caught.value is failure
            await asyncio.sleep(0)
            key = routes._active_turn_key(project, session)
            assert key not in routes._RESERVED_TURNS
            assert key not in routes.turn_registry.tasks
            assert routes.turn_registry.get(project, session) is None

    with caplog.at_level(logging.ERROR, logger="workbench.agent.turn_runtime"):
        asyncio.run(scenario())
    assert "owned setup failed" in caplog.text


def test_task_registration_failure_releases_setup_reservation(tmp_path, monkeypatch):
    from workbench.agent.turn_runtime import TurnRegistry

    async def scenario():
        registry = TurnRegistry()
        key = registry.reserve(tmp_path, "session")
        def fail_task(coro):
            raise RuntimeError("cannot create task")
        monkeypatch.setattr(asyncio, "create_task", fail_task)
        async def work():
            raise AssertionError("must not run")
        with pytest.raises(RuntimeError, match="cannot create task"):
            await registry.run_owned(key, work)
        assert key not in registry.reserved
        assert key not in registry.tasks

    asyncio.run(scenario())
