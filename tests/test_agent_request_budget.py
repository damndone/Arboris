"""Offline request admission uses the existing Core wall budget, including retries."""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from tests.test_agent_core_restart import ProcessLost, setup
from tests.test_agent_eval_nvidia_guard import BASE, MODEL, USAGE, available_test_storage, guard
from agent_eval.budget import BudgetStop
from agent_eval.recorder import provider_tape
from workbench.agent import turn_clock
from workbench.agent.model import ModelStreamEvent, OpenAICompatibleModelAdapter
from workbench.agent.tools import ToolResult
from workbench.llm.config import LLMConfig


class TimedAdapter:
    def __init__(self, durations=(), *, wait_s=300.0):
        self.request_wait_s = wait_s
        self.durations = durations
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        index = len(self.requests) - 1
        if index < len(self.durations):
            self.core._turn_started_at -= self.durations[index]
            if self.core.turn_journal is not None:
                self.core.turn_journal._active_since -= self.durations[index]
            yield ModelStreamEvent.tool_call_delta(request.request_id, {
                "tool_call_id": f"call-{index}", "tool_id": "inspect", "arguments": {"index": index},
            })
            yield ModelStreamEvent.done(request.request_id, "tool_calls")
        else:
            yield ModelStreamEvent.text_delta(request.request_id, "Continued from saved results.")
            yield ModelStreamEvent.done(request.request_id)


class Runtime:
    def __init__(self):
        self.calls = []

    async def execute(self, call, *, session_id, metadata):
        self.calls.append(call)
        return ToolResult(tool_call_id=call["tool_call_id"], tool_id="inspect", ok=True,
                          output={"saved_result": len(self.calls)})


def assert_yield(core, store, repo, *, steps, required_s=300.0):
    record = store.get(core.turn_journal.record.turn_id)
    assert record.steps_used == steps and record.budget["timeout_s"] == 600
    branch = repo.get_branch("session-a")
    terminal = [e.payload for e in branch if e.entry_type == "turn_state"][-1]
    assert terminal["final_status"] == "blocked"
    messages = [e.payload for e in branch if e.entry_type == "message"]
    final = messages[-1]
    assert final["error"] == "provider_request_budget"
    assert final["stop_reason"] == "error"
    assert final["request_budget"]["required_s"] == pytest.approx(required_s, abs=0.5)
    assert final["request_budget"]["configured_wait_s"] == 300.0
    assert final["request_budget"]["remaining_s"] < final["request_budget"]["required_s"]
    assert final["request_budget"]["timeout_s"] == 600
    assert "not sent" in final["content"] and "continue" in final["content"].lower()
    assert "agent_timeout" not in final["content"]
    return record


def test_observed_requests_admit_the_fourth_that_fits_and_yield_before_the_fifth(tmp_path):
    """The recorded turn: 209 s remained, the fourth request took 161 s and the declared wait is 300 s.

    Admission by the declared wait stopped before a request that fit. The slowest request completed
    in this turn (183 s) admits it and still refuses the fifth with 48 s left.
    """
    async def scenario():
        adapter = TimedAdapter((183.381, 102.581, 104.681, 160.987))
        runtime = Runtime()
        core, store, repo = setup(tmp_path, adapter, runtime=runtime)
        adapter.core = core
        reply = await core.prompt("Inspect the saved results.", budget={"max_steps": 8, "timeout_s": 600})
        assert len(adapter.requests) == 4, "the fifth request cannot fit the slowest observed request"
        record = assert_yield(core, store, repo, steps=4, required_s=183.381)
        assert len(runtime.calls) == 4 and reply
        # A new explicit continuation owns a new unchanged budget; no tool is replayed.
        resumed = TimedAdapter()
        resumed.core = core
        core.adapter = resumed
        assert await core.continue_(budget={"max_steps": 8, "timeout_s": 600}) == "Continued from saved results."
        assert len(runtime.calls) == 4 and len(resumed.requests) == 1
        assert core.turn_journal.record.command_id != record.command_id
        assert len([m for m in resumed.requests[0].messages if m["role"] == "tool"]) == 4
    asyncio.run(scenario())


def test_technical_resume_at_551_seconds_does_not_send_a_fifth_request(tmp_path, monkeypatch):
    async def scenario():
        # Reproduce an already durable prefix from the pre-admission implementation.
        original = TimedAdapter((183.381, 102.581, 104.681, 160.987), wait_s=0)
        runtime = Runtime()
        core, store, repo = setup(tmp_path, original, runtime=runtime)
        original.core = core
        save = core.turn_journal.result_message

        def lose_after_four_results(agent, call, payload):
            result = save(agent, call, payload)
            if agent._steps_used == 4:
                raise ProcessLost()
            return result

        monkeypatch.setattr(core.turn_journal, "result_message", lose_after_four_results)
        with pytest.raises(ProcessLost):
            await core.prompt("Inspect results.", budget={"max_steps": 8, "timeout_s": 600})
        [record] = store.list_active()
        assert record.steps_used == 4 and record.wall_s_used >= 551.63
        adapter = TimedAdapter()
        resumed, fresh, repo = setup(tmp_path, adapter, runtime=runtime, create=False)
        adapter.core = resumed
        await resumed.resume(record.turn_id)
        assert not adapter.requests, "technical resume must retain the spent 551.63 seconds"
        assert_yield(resumed, fresh, repo, steps=4)
        assert resumed.turn_journal.record.command_id == record.command_id
        assert len(runtime.calls) == 4
    asyncio.run(scenario())


def success_response():
    payload = {"choices": [{"delta": {"content": "Saved."}, "finish_reason": "stop"}], "usage": USAGE}
    return httpx.Response(200, headers={"content-type": "text/event-stream"},
                          content=("data: " + json.dumps(payload) + "\n\ndata: [DONE]\n\n").encode())


@pytest.mark.parametrize("declared_pacing,elapsed", [(False, 350), (True, 350), (False, 601)])
def test_http_boundary_rechecks_after_queue_before_reserving(tmp_path, monkeypatch, declared_pacing, elapsed):
    g, _ = guard(tmp_path, monkeypatch)
    requests, held = [], [0.0]

    def handle(request):
        requests.append(request)
        return success_response()

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kw: httpx.MockTransport(handle))

    async def scenario():
        adapter = OpenAICompatibleModelAdapter(LLMConfig(base_url=BASE, model=MODEL, api_key="offline", timeout_s=300))
        core, store, repo = setup(tmp_path, adapter)

        async def queue(*args):
            core._turn_started_at -= elapsed
            held[0] += elapsed if declared_pacing else 0

        monkeypatch.setattr(g, "wait_for_request_slot", queue)
        previous = turn_clock.exclude_waits(lambda: held[0])
        try:
            with provider_tape(tmp_path / "tape.jsonl", budget=g):
                await core.prompt("Answer.", budget={"max_steps": 8, "timeout_s": 600})
        finally:
            turn_clock.exclude_waits(previous)
        assert len(requests) == int(declared_pacing)
        assert g.state["requests"] == int(declared_pacing) and not g.state["reservations"]
        assert not g.stopped
        if not declared_pacing:
            if elapsed < 600:
                assert_yield(core, store, repo, steps=0)
            else:
                assert store.get(core.turn_journal.record.turn_id).steps_used == 0
                final = [e.payload for e in repo.get_branch("session-a") if e.entry_type == "message"][-1]
                assert final["error"] == "agent_timeout"
            observation = [e for e in core.events.replay("session-a") if e.event_type == "provider_step"][-1]
            assert observation.payload["outcome"] == "not_sent"
            assert observation.payload["usage"] is None and observation.payload["usage_state"] == "not_requested"
    asyncio.run(scenario())


def test_retry_does_not_send_when_original_attempt_used_the_remaining_window(tmp_path, monkeypatch):
    g, _ = guard(tmp_path, monkeypatch)
    requests = []

    async def scenario():
        adapter = OpenAICompatibleModelAdapter(LLMConfig(base_url=BASE, model=MODEL, api_key="offline", timeout_s=300))
        adapter.retry_delays_s = (0,)
        core, store, repo = setup(tmp_path, adapter)

        def handle(request):
            requests.append(request)
            if len(requests) == 1:
                core._turn_started_at -= 350
                # A fully accounted but incomplete response is retryable by the
                # existing adapter; no unknown usage exception is being relaxed.
                return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=(
                    "data: " + json.dumps({"choices": [], "usage": USAGE}) + "\n\ndata: [DONE]\n\n"
                ).encode())
            return success_response()

        monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kw: httpx.MockTransport(handle))
        with provider_tape(tmp_path / "tape.jsonl", budget=g):
            await core.prompt("Answer.", budget={"max_steps": 8, "timeout_s": 600})
        assert len(requests) == 1, "retry must not send with less than the declared wait remaining"
        assert_yield(core, store, repo, steps=1)
        assert g.state["requests"] == 1 and not g.state["reservations"] and not g.stopped
    asyncio.run(scenario())


def test_inflight_comment_only_cancel_keeps_unknown_usage_stop(tmp_path, monkeypatch):
    g, _ = guard(tmp_path, monkeypatch)

    async def scenario():
        adapter = OpenAICompatibleModelAdapter(
            LLMConfig(base_url=BASE, model=MODEL, api_key="offline", timeout_s=0.01), idle_timeout_s=1,
        )
        core, _, _ = setup(tmp_path, adapter)

        class Comments(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b": still queued\n\n"
                await asyncio.Event().wait()

        monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kw: httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Comments())))
        with provider_tape(tmp_path / "tape.jsonl", budget=g):
            try:
                reply = await core.prompt("Answer.", budget={"max_steps": 8, "timeout_s": 0.05})
            except BudgetStop:
                pass
            else:
                assert "agent_timeout" in reply
        assert g.stopped and g.state["requests"] == 1 and len(g.state["reservations"]) == 1
        [row] = [json.loads(line) for line in (tmp_path / "tape.jsonl").read_text().splitlines()]
        assert row["usage"] is None and row["sent"] is True
    asyncio.run(scenario())


def test_http_send_has_durable_provider_step_before_transport_and_resume_keeps_it(tmp_path, monkeypatch):
    from workbench.llm import client

    async def scenario():
        adapter = OpenAICompatibleModelAdapter(LLMConfig(base_url=BASE, model=MODEL, api_key="offline", timeout_s=300))
        core, store, _ = setup(tmp_path, adapter)
        calls = []

        def handle(request):
            record = store.get(core.turn_journal.record.turn_id)
            assert record.steps_used == len(calls) + 1
            checkpoint = core.repository.get_branch("session-a")[-1]
            assert checkpoint.entry_type == "turn_state" and checkpoint.payload["stage"] == "provider"
            calls.append(request)
            if len(calls) == 1:
                raise ProcessLost()
            return success_response()

        # The supported factory seam must get the same admission/checkpoint hook.
        monkeypatch.setattr(client, "_async_client_factory", lambda config: httpx.AsyncClient(
            transport=httpx.MockTransport(handle)))
        with pytest.raises(ProcessLost):
            await core.prompt("Answer.", budget={"max_steps": 8, "timeout_s": 600})
        [record] = store.list_active()
        assert record.steps_used == 1
        resumed, _, _ = setup(tmp_path, adapter, create=False)
        core = resumed
        assert await resumed.resume(record.turn_id) == "Saved."
        assert len(calls) == 2 and store.get(record.turn_id).steps_used == 2
    asyncio.run(scenario())


def test_provider_tape_replay_preserves_two_steps_and_one_original_tool_receipt(tmp_path):
    from agent_eval.recorder import _body_hash

    path = tmp_path / "wire.jsonl"
    tool = {"id": "recorded-call", "index": 0, "type": "function",
            "function": {"name": "inspect", "arguments": "{}"}}
    payloads = [
        {"choices": [{"delta": {"tool_calls": [tool]}, "finish_reason": "tool_calls"}], "usage": USAGE},
        {"choices": [{"delta": {"content": "Saved."}, "finish_reason": "stop"}], "usage": USAGE},
    ]
    path.write_text("".join(json.dumps({"status": 200, "request_sha256": _body_hash(b"{}"),
        "content_type": "text/event-stream", "response_raw": "data: " + json.dumps(payload) + "\n\ndata: [DONE]\n\n"
    }) + "\n" for payload in payloads))

    async def scenario():
        adapter = OpenAICompatibleModelAdapter(LLMConfig(base_url=BASE, model=MODEL, api_key="offline", timeout_s=300))
        runtime = Runtime()
        core, store, repo = setup(tmp_path, adapter, runtime=runtime)
        with provider_tape(path, mode="replay"):
            assert await core.prompt("Inspect.", budget={"max_steps": 2, "timeout_s": 600}) == "Saved."
        record = store.get(core.turn_journal.record.turn_id)
        assert record.steps_used == 2 and len(runtime.calls) == 1
        assert len([e for e in repo.get_branch("session-a") if e.entry_type == "tool_receipt"]) == 1
    asyncio.run(scenario())


def test_recording_adapter_preserves_http_admission_after_pacing(tmp_path, monkeypatch):
    from workbench.agent.model_replay import RecordingAdapter

    g, _ = guard(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kw: httpx.MockTransport(
        lambda request: calls.append(request) or success_response()))

    async def scenario():
        upstream = OpenAICompatibleModelAdapter(LLMConfig(base_url=BASE, model=MODEL, api_key="offline", timeout_s=300))
        adapter = RecordingAdapter(upstream, root=tmp_path, name="model.jsonl")
        core, store, repo = setup(tmp_path, adapter)
        async def queue(*args):
            core._turn_started_at -= 350
        monkeypatch.setattr(g, "wait_for_request_slot", queue)
        with provider_tape(tmp_path / "wire.jsonl", budget=g):
            await core.prompt("Answer.", budget={"max_steps": 8, "timeout_s": 600})
        assert not calls and g.state["requests"] == 0
        assert_yield(core, store, repo, steps=0)
    asyncio.run(scenario())


def test_authorized_overload_retry_rechecks_after_its_wait(tmp_path, monkeypatch):
    from tests.test_agent_eval_nvidia_recovery import OVERLOAD

    g, now = guard(tmp_path, monkeypatch, overload_recovery_ledger=tmp_path / "recovery.json")
    calls = []

    async def scenario():
        adapter = OpenAICompatibleModelAdapter(LLMConfig(base_url=BASE, model=MODEL, api_key="offline", timeout_s=300))
        core, store, repo = setup(tmp_path, adapter)
        async def retry_wait(seconds):
            now[0] += seconds
            core._turn_started_at -= seconds
        def handle(request):
            calls.append(request)
            core._turn_started_at -= 250
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=OVERLOAD)
        monkeypatch.setattr(asyncio, "sleep", retry_wait)
        monkeypatch.setattr(httpx, "AsyncHTTPTransport", lambda **kw: httpx.MockTransport(handle))
        with provider_tape(tmp_path / "wire.jsonl", budget=g):
            await core.prompt("Answer.", budget={"max_steps": 8, "timeout_s": 600})
        assert len(calls) == 1 and g.state["requests"] == 1
        assert g.overload_recovery.state["retries"] == 1
        assert not g.stopped and not g.state["reservations"]
        assert_yield(core, store, repo, steps=1)
        observation = [e for e in core.events.replay("session-a") if e.event_type == "provider_step"][-1]
        assert observation.payload["outcome"] == "budget_yield"
    asyncio.run(scenario())


def test_wait_larger_than_whole_turn_is_an_explicit_configuration_boundary(tmp_path):
    async def scenario():
        adapter = TimedAdapter()
        core, store, repo = setup(tmp_path, adapter)
        adapter.core = core
        reply = await core.prompt("Answer.", budget={"max_steps": 2, "timeout_s": 60})
        assert not adapter.requests
        assert "adjust the existing configuration" in reply
        assert store.get(core.turn_journal.record.turn_id).steps_used == 0
        final = [e.payload for e in repo.get_branch("session-a") if e.entry_type == "message"][-1]
        assert final["request_budget"]["timeout_s"] == 60
        assert final["request_budget"]["required_s"] == 300
    asyncio.run(scenario())


@pytest.mark.parametrize("boundary", ["phase_applied", "phase_received"])
def test_phase_receipt_resume_yields_without_consuming_the_phase_again(tmp_path, monkeypatch, boundary):
    from tests.test_agent_phase_restart import Model, configured

    async def scenario():
        effects = []
        class Prefix(Model):
            async def stream(self, request):
                async for event in super().stream(request):
                    if len(self.requests) == 2 and event.type == "done":
                        core._turn_started_at -= 551.63
                        core.turn_journal._active_since -= 551.63
                    yield event
        core, store, repo = configured(tmp_path, Prefix(), effects, create=True)
        save = core.turn_journal.save
        def lose_after_checkpoint(agent, stage, **details):
            result = save(agent, stage, **details)
            if stage == boundary:
                raise ProcessLost()
            return result
        monkeypatch.setattr(core.turn_journal, "save", lose_after_checkpoint)
        with pytest.raises(ProcessLost):
            await core.prompt("Plan.", budget={"max_steps": 8, "timeout_s": 600})
        [record] = store.list_active()
        adapter = TimedAdapter()
        resumed, fresh, repo = configured(tmp_path, adapter, effects, create=False)
        adapter.core = resumed
        await resumed.resume(record.turn_id)
        assert not adapter.requests and effects == ["consumed"]
        assert_yield(resumed, fresh, repo, steps=2)
        assert resumed.turn_journal.record.command_id == record.command_id
    asyncio.run(scenario())


def test_compaction_rewrite_uses_same_budget_without_publishing_an_unfinished_summary(tmp_path):
    from workbench.agent.compaction import CompactionPolicy

    async def scenario():
        class Summary(TimedAdapter):
            async def stream(self, request):
                self.requests.append(request)
                self.core._turn_started_at -= 350
                yield ModelStreamEvent.text_delta(request.request_id, "An unsupported number: 987654321.")
                yield ModelStreamEvent.done(request.request_id)

        adapter = Summary()
        core, store, repo = setup(tmp_path, adapter)
        adapter.core = core
        for text in ("old question " * 100, "old answer " * 100, "recent question", "recent answer"):
            repo.append("session-a", "message", {"role": "user" if "question" in text else "assistant", "content": text})
        before = [e.entry_id for e in repo.get_branch("session-a")]
        core.compaction_policy = CompactionPolicy(window_tokens=1000, budget_tokens=10, keep_recent_tokens=10)
        await core.prompt("Continue inspecting.", budget={"max_steps": 8, "timeout_s": 600})
        assert len(adapter.requests) == 1, "compaction correction is also a fresh provider request"
        assert not [e for e in repo.get_branch("session-a") if e.entry_type == "compaction"]
        assert [e.entry_id for e in repo.get_branch("session-a")][:len(before)] == before
        assert_yield(core, store, repo, steps=0)  # compaction retains its existing step-count contract
    asyncio.run(scenario())


def test_shorter_phase_deadline_admits_its_actual_wait_window(tmp_path, monkeypatch):
    from workbench.agent.phases import PhaseRequest, PhaseStep
    from workbench.llm import client

    class Phase:
        episode_id = "bounded-phase"
        def request(self, transcript):
            return PhaseRequest([{"role": "user", "content": "phase"}], [], provider_timeout_s=30)
        async def consume(self, events, *, error=None):
            assert error is None
            return PhaseStep("completed", (), "done", {"result": "done"})
        def checkpoint(self):
            return {"episode_id": self.episode_id}
        def failure(self, reason, error=None):
            return RuntimeError(reason)

    async def scenario():
        adapter = OpenAICompatibleModelAdapter(LLMConfig(base_url=BASE, model=MODEL, api_key="offline", timeout_s=300))
        core, _, _ = setup(tmp_path, adapter)
        core.turn_journal = None
        calls = []
        def handle(request):
            calls.append(request)
            return success_response()
        monkeypatch.setattr(client, "_async_client_factory", lambda config: httpx.AsyncClient(
            transport=httpx.MockTransport(handle)))
        assert await core.run_phase(Phase(), budget={"max_steps": 2, "timeout_s": 60}) == "done"
        assert len(calls) == 1
    asyncio.run(scenario())


def test_equal_remaining_window_is_admitted_but_send_rechecks_later_elapsed_time(tmp_path):
    from workbench.agent.core_parts.budget import AgentRunBudget
    from workbench.llm.client import LLMRequestBudgetExceeded

    async def scenario():
        core, _, _ = setup(tmp_path, TimedAdapter())
        core._begin(AgentRunBudget(timeout_s=600, max_steps=8))
        try:
            # A controlled boundary value is exact; no hidden safety margin is added.
            core._turn_budget_elapsed = lambda: 300.0
            core._check_provider_request_budget(300.0)
            core._turn_budget_elapsed = lambda: 300.001
            with pytest.raises(LLMRequestBudgetExceeded):
                core._check_provider_request_budget(300.0)
        finally:
            core._end()
    asyncio.run(scenario())


def test_the_observed_bound_never_exceeds_the_declared_wait_and_resets_each_turn(tmp_path):
    from workbench.agent.core_parts.budget import AgentRunBudget
    from workbench.llm.client import LLMRequestBudgetExceeded

    async def scenario():
        core, _, _ = setup(tmp_path, TimedAdapter())
        core._begin(AgentRunBudget(timeout_s=600, max_steps=8))
        try:
            assert core._slowest_request_s == 0.0
            core._turn_budget_elapsed = lambda: 560.0
            with pytest.raises(LLMRequestBudgetExceeded) as nothing_observed:
                core._check_provider_request_budget(300.0)
            assert nothing_observed.value.details["required_s"] == 300.0
            core._slowest_request_s = 40.0
            core._check_provider_request_budget(300.0)
            core._turn_budget_elapsed = lambda: 560.001
            with pytest.raises(LLMRequestBudgetExceeded) as observed:
                core._check_provider_request_budget(300.0)
            assert observed.value.details["required_s"] == 40.0
            assert observed.value.details["configured_wait_s"] == 300.0
            core._slowest_request_s = 450.0  # a request slower than the declared wait cannot raise it
            core._turn_budget_elapsed = lambda: 300.0
            core._check_provider_request_budget(300.0)
        finally:
            core._end()
        core._begin(AgentRunBudget(timeout_s=600, max_steps=8))
        try:
            assert core._slowest_request_s == 0.0
        finally:
            core._end()
    asyncio.run(scenario())


def test_a_failed_request_is_not_an_observation(tmp_path):
    class Failing(TimedAdapter):
        async def stream(self, request):
            self.requests.append(request)
            self.core._turn_started_at -= 50
            raise RuntimeError("provider down")
            yield  # an async generator, like every adapter stream

    async def scenario():
        adapter = Failing()
        core, _, _ = setup(tmp_path, adapter)
        adapter.core = core
        await core.prompt("Answer.", budget={"max_steps": 2, "timeout_s": 600})
        assert adapter.requests and core._slowest_request_s == 0.0
    asyncio.run(scenario())
