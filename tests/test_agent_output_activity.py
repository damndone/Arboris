"""Show transport activity without publishing private or unchecked model prose."""
import asyncio
import json

import pytest

from tests.test_agent_core_restart import setup
from tests.test_agent_delivery_takeover import partial
from workbench.agent.model import ModelRequest, ModelStreamEvent, OpenAICompatibleModelAdapter
from workbench.llm.config import LLMConfig


@pytest.mark.parametrize("activity_first", [False, True])
def test_checked_analysis_signals_activity_before_publication_only_once(tmp_path, activity_first):
    observed = []

    class Adapter:
        async def stream(self, request):
            if activity_first:
                yield ModelStreamEvent(type="activity", request_id=request.request_id)
            for _ in range(100):
                yield ModelStreamEvent.text_delta(request.request_id, "A draft awaiting verification. ")
            # The model has not finished; the public event log must already
            # distinguish receipt from waiting, without exposing its draft.
            observed.extend(core.events.replay("session-a"))
            yield ModelStreamEvent.reasoning(request.request_id, "PRIVATE_REASONING_SENTINEL", {})
            yield ModelStreamEvent.done(request.request_id)

    core, _, _ = setup(tmp_path, Adapter())
    core.completion_check = partial
    answer = asyncio.run(core.prompt("Please complete the analysis.", budget={"max_steps": 1, "timeout_s": 30}))
    activity = [event for event in observed if event.event_type == "message_progress"]
    assert len(activity) == 1
    assert activity[0].command_id
    assert activity[0].payload == {"request_id": activity[0].payload["request_id"],
                                   "stage": "receiving", "validation_pending": True}
    assert len(activity[0].payload["request_id"]) == 32
    assert not any(event.event_type == "message_update" for event in observed)
    public = json.dumps([event.to_dict() for event in core.events.replay("session-a")])
    assert "PRIVATE_REASONING_SENTINEL" not in public
    assert "draft awaiting verification" not in json.dumps([event.to_dict() for event in observed])
    assert answer.startswith("Partially complete")
    assert "source-run" in answer


@pytest.mark.parametrize("meaningful", [True, False])
@pytest.mark.parametrize("heartbeat_first", [True, False])
def test_adapter_exposes_only_first_meaningful_provider_activity(monkeypatch, meaningful, heartbeat_first):
    async def wire(*args, **kwargs):
        if heartbeat_first:
            yield {"type": "provider_activity"}
        for _ in range(20):
            yield {"type": "provider_activity", **({"reasoning": "PRIVATE_SENTINEL", "meaningful": True}
                                                       if meaningful else {})}
        yield {"type": "done", "finish_reason": "stop"}

    monkeypatch.setattr("workbench.agent.model.async_stream_chat_completion", wire)
    adapter = OpenAICompatibleModelAdapter(LLMConfig(base_url="https://example.test/v1",
                                                     api_key="offline", model="offline"))

    async def scenario():
        return [event async for event in adapter.stream(ModelRequest(messages=[{"role": "user", "content": "x"}]))]

    events = asyncio.run(scenario())
    visible = [event for event in events if event.type == "activity"]
    assert len(visible) == int(meaningful)
    assert all(event.delta == "" and event.reasoning_source is None and event.tool_call is None for event in visible)
    assert events[-1].type == "done"
