"""Paid evaluation stops at one durable round budget, including retries/modes."""
import asyncio
from decimal import Decimal
import json
from pathlib import Path
import sys

import httpx
import pytest
from tests.test_agent_eval_headless_transport import runner

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def budget_api():
    import importlib.util
    assert importlib.util.find_spec("agent_eval.budget") is not None, "missing hard round budget"
    from agent_eval import budget
    return budget


def test_original_usage_price_and_reasoning_is_not_charged_twice():
    api = budget_api()
    usage = {"prompt_tokens": 30037, "prompt_cache_hit_tokens": 13696,
             "prompt_cache_miss_tokens": 16341, "completion_tokens": 180,
             "completion_tokens_details": {"reasoning_tokens": 156}}
    assert api.cost_usd(usage) == Decimal("0.0023764888")


def test_native_cny_peak_quote_guards_output_cost_above_archived_usd_estimate():
    api = budget_api()
    usage = {"prompt_tokens": 30037, "prompt_cache_hit_tokens": 13696,
             "prompt_cache_miss_tokens": 16341, "completion_tokens": 180}
    assert api.cost_cny_upper(usage) == Decimal("0.03466984")
    assert api.cost_cny_upper(usage) > api.cost_usd(usage) * 8


def test_schema_one_ledger_migration_keeps_charges_and_storage_stop(tmp_path):
    api = budget_api()
    usage = {"prompt_tokens": 10, "completion_tokens": 10}
    original = {"schema": 1, "cap_cny": "5", "context_tokens": 1_048_576,
        "spent_usd": str(api.cost_usd(usage)), "reservations": {},
        "charges": [{"key": "original", "usage": usage, "cost_usd": str(api.cost_usd(usage))}],
        "stopped": True, "reason": "storage threshold"}
    path = tmp_path / "budget.json"; path.write_text(json.dumps(original))
    budget = api.RoundBudget(path, cap_cny="5", context_tokens=1_048_576)
    assert budget.state["schema"] == 2 and budget.stopped
    assert budget.spent_usd == api.cost_usd(usage)
    assert Decimal(budget.state["spent_cny_upper"]) == api.cost_cny_upper(usage)
    assert json.loads(path.with_suffix(".v1.json").read_text()) == original


def test_explicit_storage_exception_preserves_all_spending(tmp_path):
    api = budget_api()
    budget = api.RoundBudget(tmp_path / "budget.json", cap_cny="5", context_tokens=1_048_576)
    key = budget.reserve(b'{"max_tokens":100}')
    budget.settle(key, {"prompt_tokens": 10, "completion_tokens": 20})
    before = budget.state
    budget.stop("storage threshold: less than 10 GB free")
    budget.resume_storage_stop()
    assert not budget.stopped
    assert budget.state["charges"] == before["charges"]
    assert budget.state["spent_cny_upper"] == before["spent_cny_upper"]
    assert budget.spent_usd == Decimal(before["spent_usd"])


@pytest.mark.parametrize("reason", ["cost bound reached", "unknown usage"])
def test_storage_exception_never_releases_financial_stops(tmp_path, reason):
    api = budget_api()
    budget = api.RoundBudget(tmp_path / "budget.json", cap_cny="5", context_tokens=1_048_576)
    budget.stop(reason)
    with pytest.raises(api.BudgetStop):
        budget.resume_storage_stop()
    assert budget.stopped


def test_shared_budget_reserves_inflight_cost_and_survives_mode_restart(tmp_path):
    api = budget_api()
    path = tmp_path / "budget.json"
    budget = api.RoundBudget(path, cap_cny="0.001", context_tokens=100)
    request = json.dumps({"messages": [], "max_tokens": 100}).encode()
    with pytest.raises(api.BudgetStop):
        budget.reserve(request)
    assert budget.stopped and path.exists()
    assert api.RoundBudget(path, cap_cny="0.001", context_tokens=100).stopped


def test_unknown_usage_keeps_reservation_and_stops_whole_round(tmp_path):
    api = budget_api()
    budget = api.RoundBudget(tmp_path / "budget.json", cap_cny="5", context_tokens=100)
    reservation = budget.reserve(b'{"max_tokens":10}')
    with pytest.raises(api.BudgetStop, match="usage"):
        budget.settle(reservation, None)
    assert budget.stopped and budget.state["reservations"]


def test_paid_transport_journals_usage_and_refuses_next_call_before_network(tmp_path):
    api = budget_api()
    from agent_eval.recorder import _Tape, _RecordingTransport
    calls = []
    usage = {"prompt_tokens": 10, "prompt_cache_hit_tokens": 5,
             "prompt_cache_miss_tokens": 5, "completion_tokens": 10}
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"usage": usage})
    budget = api.RoundBudget(tmp_path / "budget.json", cap_cny="5", context_tokens=100)
    tape = _Tape(tmp_path / "tape.jsonl", "record")
    async def scenario():
        transport = _RecordingTransport(tape, httpx.MockTransport(handle), budget=budget)
        async with httpx.AsyncClient(transport=transport) as client:
            await client.post("https://provider.invalid/chat", json={"max_tokens": 10})
            assert budget.spent_usd == api.cost_usd(usage)
            budget.stop("test boundary")
            with pytest.raises(api.BudgetStop):
                await client.post("https://provider.invalid/chat", json={"max_tokens": 10})
    asyncio.run(scenario())
    assert len(calls) == 1
    records = [json.loads(line) for line in tape.path.read_text().splitlines()]
    assert len(records) == 1 and records[0]["usage"] == usage


def test_two_simultaneous_reservations_cannot_overbook_the_cap(tmp_path):
    api = budget_api()
    budget = api.RoundBudget(tmp_path / "budget.json", cap_cny="0.008", context_tokens=100)
    budget.reserve(b'{"max_tokens":10}')
    with pytest.raises(api.BudgetStop):
        budget.reserve(b'{"max_tokens":10}')


def test_missing_max_tokens_reserves_documented_thinking_default_without_changing_request(tmp_path):
    api = budget_api()
    budget = api.RoundBudget(tmp_path / "budget.json", cap_cny="5", context_tokens=1_048_576)
    request = b'{"model":"deepseek-flash","messages":[]}'
    key = budget.reserve(request)
    assert Decimal(budget.state["reservations"][key]) >= Decimal("0.524288")
    assert json.loads(request) == {"model": "deepseek-flash", "messages": []}


@pytest.mark.parametrize("controls,output", [({}, 65536), ({"thinking": {"type": "disabled"}}, 8192),
    ({"reasoning_effort": "max"}, 131072), ({"max_tokens": 393216}, 393216)])
def test_server_defaults_and_explicit_output_ceiling_use_native_peak_tariff(tmp_path, controls, output):
    api = budget_api()
    budget = api.RoundBudget(tmp_path / "budget.json", cap_cny="5", context_tokens=1_048_576)
    body = json.dumps(controls).encode()
    key = budget.reserve(body)
    assert Decimal(budget.state["reservations"][key]) == (len(body) + 2048) * api.CNY_MISS + output * api.CNY_OUTPUT


def test_each_task_checks_storage_before_seed_or_provider(tmp_path, monkeypatch):
    import importlib.util
    from types import SimpleNamespace
    spec = importlib.util.spec_from_file_location("agent_eval_run_storage_test", Path(__file__).resolve().parents[1] / "scripts/agent_eval_run.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    config = SimpleNamespace(model="deepseek-flash", base_url="https://api.deepseek.com", is_configured=lambda: True)
    monkeypatch.setattr(module, "load_llm_config", lambda: config)
    monkeypatch.setattr(module, "dev_tasks", lambda: [SimpleNamespace(id="task")])
    import shutil
    monkeypatch.setattr(shutil, "disk_usage", lambda root: SimpleNamespace(free=4_999_999_999))
    monkeypatch.setattr(module, "_seed", lambda *a, **k: pytest.fail("low storage reached seed execution"))
    monkeypatch.setattr(module, "run_conversation", lambda *a, **k: pytest.fail("low storage reached provider execution"))
    monkeypatch.setattr(sys, "argv", ["agent_eval_run.py", "--out", str(tmp_path / "round"),
        "--round-budget-cny", "5", "--budget-ledger", str(tmp_path / "budget.json")])
    assert module.main() == 86
    state = json.loads((tmp_path / "budget.json").read_text())
    assert state["stopped"] and "storage" in state["reason"]


def test_budget_stop_keeps_session_and_actions_before_first_response(tmp_path, runner, monkeypatch):
    api = budget_api()
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"session_id": "preserved-session"}
    class Client:
        def post(self, *args, **kwargs): return Response()
    def stop(*args, **kwargs):
        raise api.BudgetStop("cap")
    monkeypatch.setattr(runner, "_turn", stop)
    progress = tmp_path / "conversation-progress.json"
    with pytest.raises(api.BudgetStop):
        runner.run_conversation(Client(), tmp_path, "run", "Analyze", runner.Policy(), progress_path=progress)
    value = json.loads(progress.read_text())
    assert value["session_id"] == "preserved-session" and value["turns"] == []
    assert value["confirmations"] == [] and value["nudges"] == 0


@pytest.mark.parametrize("failure, released", [
    (httpx.ConnectError("refused"), True),
    (httpx.ConnectTimeout("handshake timed out"), True),
    (httpx.ReadTimeout("no response"), False),
    (httpx.RemoteProtocolError("dropped"), False),
])
def test_only_a_request_that_never_left_releases_its_reservation(tmp_path, failure, released):
    """The fix1 round froze on a ConnectError: no connection, so nothing could be billed."""
    api = budget_api()
    from agent_eval.recorder import _Tape, _RecordingTransport
    usage = {"prompt_tokens": 10, "prompt_cache_hit_tokens": 5,
             "prompt_cache_miss_tokens": 5, "completion_tokens": 10}
    attempts = []

    def handle(request):
        attempts.append(request)
        if len(attempts) == 1:
            raise failure
        return httpx.Response(200, json={"usage": usage})

    budget = api.RoundBudget(tmp_path / "budget.json", cap_cny="5", context_tokens=100)
    tape = _Tape(tmp_path / "tape.jsonl", "record")

    async def scenario():
        transport = _RecordingTransport(tape, httpx.MockTransport(handle), budget=budget)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(type(failure) if released else api.BudgetStop):
                await client.post("https://provider.invalid/chat", json={"max_tokens": 10})
            if released:  # the product's retry goes through and is charged normally
                await client.post("https://provider.invalid/chat", json={"max_tokens": 10})
    asyncio.run(scenario())
    state = json.loads((tmp_path / "budget.json").read_text())
    first = json.loads(tape.path.read_text().splitlines()[0])
    assert first["sent"] is (not released)
    assert budget.stopped is (not released)
    if released:
        assert state["reservations"] == {} and budget.spent_usd == api.cost_usd(usage)
    else:
        assert len(state["reservations"]) == 1


def test_the_free_route_guard_stops_on_any_non_zero_or_missing_credit(tmp_path):
    import pytest
    from agent_eval.budget import BudgetStop, FreeRouteGuard

    with pytest.raises(ValueError):
        FreeRouteGuard(tmp_path / "x.json", provider_id="deepseek", base_url="https://api.deepseek.com")
    guard = FreeRouteGuard(tmp_path / "free.json", provider_id="magpie-workbuddy-ai", base_url="http://127.0.0.1:3425/v1")
    key = guard.reserve(b"{}")
    guard.settle(key, {"prompt_tokens": 10, "completion_tokens": 2, "credit": 0})
    assert guard.state["calls"] == 1 and not guard.stopped
    with pytest.raises(BudgetStop):
        guard.settle(guard.reserve(b"{}"), {"prompt_tokens": 10, "completion_tokens": 2, "credit": 0.01})
    assert guard.stopped
    with pytest.raises(BudgetStop):
        guard.reserve(b"{}")
    fresh = FreeRouteGuard(tmp_path / "free2.json", provider_id="magpie-workbuddy-ai", base_url="http://127.0.0.1:3425/v1")
    with pytest.raises(BudgetStop):
        fresh.settle(fresh.reserve(b"{}"), {"prompt_tokens": 10, "completion_tokens": 2})
    with pytest.raises(ValueError):
        FreeRouteGuard(tmp_path / "free.json", provider_id="magpie-workbuddy-ai", base_url="http://127.0.0.1:9999/v1")



def test_the_free_route_stops_at_first_unknown_usage_and_keeps_the_interruption(tmp_path):
    from agent_eval.budget import BudgetStop, FreeRouteGuard
    guard = FreeRouteGuard(tmp_path / "free.json", provider_id="magpie-workbuddy-ai", base_url="http://127.0.0.1:3425/v1")
    with pytest.raises(BudgetStop, match="unknown usage"):
        guard.tolerate_transport_interruption("ReadTimeout", task="iv")
    assert guard.stopped
    assert guard.state["transport_interruptions"] == [{"task": "iv", "error": "ReadTimeout"}]
    with pytest.raises(BudgetStop):
        guard.reserve(b"{}")


@pytest.mark.parametrize('usage', [{'credit': 0}, {'credit': 0, 'prompt_tokens': 10},
    {'credit': 0, 'prompt_tokens': True, 'completion_tokens': 2},
    {'credit': 0, 'prompt_tokens': 10, 'completion_tokens': -1}])
def test_zero_credit_does_not_turn_missing_or_invalid_tokens_into_zero(tmp_path, usage):
    from agent_eval.budget import BudgetStop, FreeRouteGuard
    guard = FreeRouteGuard(tmp_path / 'free.json', provider_id='magpie-workbuddy-ai', base_url=FREE_BASE)
    with pytest.raises(BudgetStop, match='token usage'):
        guard.settle(guard.reserve(b'{}'), usage)
    assert guard.stopped and guard.state['calls'] == 0


def test_unknown_usage_stops_the_round_through_the_recorder_before_a_second_request(tmp_path):
    from agent_eval.budget import BudgetStop, FreeRouteGuard
    from agent_eval.recorder import _Tape, _RecordingTransport
    guard = FreeRouteGuard(tmp_path / "free.json", provider_id="magpie-workbuddy-ai", base_url=FREE_BASE)
    tape = _Tape(tmp_path / "tape.jsonl", "record")
    tape.context = {"task": "panel_fe.specific.r1"}
    calls = []
    def stall(request):
        calls.append(request)
        raise httpx.ReadTimeout("no first byte", request=request)
    async def scenario():
        transport = _RecordingTransport(tape, httpx.MockTransport(stall), budget=guard)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(BudgetStop, match="unknown usage"):
                await client.post(f"{FREE_BASE}/chat/completions", json={"max_tokens": 10})
            with pytest.raises(BudgetStop):
                await client.post(f"{FREE_BASE}/chat/completions", json={"max_tokens": 10})
    asyncio.run(scenario())
    assert guard.stopped and len(calls) == 1
    [record] = [json.loads(line) for line in tape.path.read_text().splitlines()]
    assert record["usage"] is None and record["transport_error"] == "ReadTimeout"


FREE_BASE = "http://127.0.0.1:3425/v1"
#: The response that ended off4b's Auto mode (2026-10-22), verbatim.
RATE_LIMITED = {"error": {"code": None, "message": "WorkBuddy AI: usage exceeds frequency limit, but don't worry, your "
                "usage will reset at 2026-10-23 20:56:28 UTC+8, alternatively, you can switch to the other models to "
                "continue using it.", "param": None, "type": "rate_limit_error"}}


def _free_call(tmp_path, handle):
    from agent_eval.budget import BudgetStop, FreeRouteGuard
    from agent_eval.recorder import _Tape, _RecordingTransport

    guard = FreeRouteGuard(tmp_path / "free.json", provider_id="magpie-workbuddy-ai", base_url=FREE_BASE)
    tape = _Tape(tmp_path / "tape.jsonl", "record")

    async def scenario():
        transport = _RecordingTransport(tape, httpx.MockTransport(handle), budget=guard)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(BudgetStop) as stopped:
                await client.post(f"{FREE_BASE}/chat/completions", json={"max_tokens": 10})
            with pytest.raises(BudgetStop):  # and nothing further goes out
                await client.post(f"{FREE_BASE}/chat/completions", json={"max_tokens": 10})
            return str(stopped.value)
    return asyncio.run(scenario()), guard, tape


def test_a_rate_limited_free_route_stops_with_the_providers_reason(tmp_path):
    calls = []
    reason, guard, tape = _free_call(tmp_path, lambda request: calls.append(request) or httpx.Response(429, json=RATE_LIMITED))
    assert len(calls) == 1 and guard.stopped
    assert "rate-limited (HTTP 429)" in reason and "2026-10-23 20:56:28" in reason and "credit" not in reason
    assert json.loads(tape.path.read_text().splitlines()[0])["status"] == 429


def test_the_recorded_account_restriction_stops_before_a_second_request(tmp_path):
    calls = []
    response = {'error': {'message': 'WorkBuddy AI: request illegal — WorkBuddy restricted this account for unusual activity'}}
    reason, guard, tape = _free_call(tmp_path, lambda request: calls.append(request) or httpx.Response(403, json=response))
    assert len(calls) == 1 and guard.stopped
    assert 'HTTP 403' in reason and 'restricted this account' in reason
    [record] = [json.loads(line) for line in tape.path.read_text().splitlines()]
    assert record['status'] == 403 and record['usage'] is None


def test_an_unreachable_free_gateway_stops_the_round_at_once(tmp_path):
    def refuse(request):
        raise httpx.ConnectError("All connection attempts failed", request=request)
    reason, guard, tape = _free_call(tmp_path, refuse)
    assert guard.stopped and "unreachable (ConnectError)" in reason and FREE_BASE in reason
    [record] = [json.loads(line) for line in tape.path.read_text().splitlines()]
    assert record["sent"] is False


def test_a_paid_round_still_retries_a_connection_that_was_never_made(tmp_path):
    api = budget_api()
    from agent_eval.recorder import _Tape, _RecordingTransport

    budget = api.RoundBudget(tmp_path / "budget.json", cap_cny="5", context_tokens=100)

    def refuse(request):
        raise httpx.ConnectError("All connection attempts failed", request=request)

    async def scenario():
        transport = _RecordingTransport(_Tape(tmp_path / "tape.jsonl", "record"), httpx.MockTransport(refuse), budget=budget)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(httpx.ConnectError):
                await client.post("https://provider.invalid/chat", json={"max_tokens": 10})
    asyncio.run(scenario())
    assert not budget.stopped and budget.state["reservations"] == {}


def _sse_transport(gate, *, response_headers=None):
    async def body():
        yield b'data: {"choices":[{"delta":{"reasoning_content":"thinking"}}]}\n\n'
        await gate.wait()
        yield (b'data: {"choices":[{"delta":{"content":"ok"}}],"usage":{"prompt_tokens":10,'
               b'"completion_tokens":2,"credit":0}}\n\ndata: [DONE]\n\n')

    return httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type": "text/event-stream", **(response_headers or {})},
                                                              content=body()))


def test_a_streamed_reply_reaches_the_product_as_it_arrives_and_is_taped_at_the_end(tmp_path):
    """The recorder read whole replies before handing them on, so the product saw nothing until
    the model finished and its 90 s no-progress bound cut every longer answer (2026-10-23)."""
    from agent_eval.budget import FreeRouteGuard
    from agent_eval.recorder import _Tape, _RecordingTransport

    guard = FreeRouteGuard(tmp_path / "free.json", provider_id="magpie-workbuddy-ai", base_url=FREE_BASE)
    tape = _Tape(tmp_path / "tape.jsonl", "record")

    async def scenario():
        gate = asyncio.Event()
        transport = _RecordingTransport(tape, _sse_transport(gate), budget=guard)
        async with httpx.AsyncClient(transport=transport) as client:
            async with client.stream("POST", f"{FREE_BASE}/chat/completions", json={"max_tokens": 10}) as response:
                chunks = response.aiter_bytes()
                first = await chunks.__anext__()
                assert b"thinking" in first and not tape.path.exists()  # before the provider finished
                gate.set()
                rest = b"".join([chunk async for chunk in chunks])
        assert b'"content":"ok"' in rest
    asyncio.run(scenario())
    [record] = [json.loads(line) for line in tape.path.read_text().splitlines()]
    assert record["status"] == 200 and record["usage"]["credit"] == 0 and "thinking" in record["response_raw"]
    assert guard.state["calls"] == 1


def test_a_stream_the_product_abandons_is_taped_as_interrupted(tmp_path):
    from agent_eval.budget import BudgetStop, FreeRouteGuard
    from agent_eval.recorder import _Tape, _RecordingTransport

    guard = FreeRouteGuard(tmp_path / "free.json", provider_id="magpie-workbuddy-ai", base_url=FREE_BASE)
    tape = _Tape(tmp_path / "tape.jsonl", "record")

    async def scenario():
        transport = _RecordingTransport(tape, _sse_transport(
            asyncio.Event(), response_headers={"nvcf-reqid": "interrupted-provider-id"}), budget=guard)
        async with httpx.AsyncClient(transport=transport) as client:
            async with client.stream("POST", f"{FREE_BASE}/chat/completions", json={"max_tokens": 10}) as response:
                await response.aiter_bytes().__anext__()  # then leaves, as a no-progress cancel does
    with pytest.raises(BudgetStop, match="unknown usage"):
        asyncio.run(scenario())
    [record] = [json.loads(line) for line in tape.path.read_text().splitlines()]
    assert record["transport_error"] == "CancelledError" and record["sent"] is True and "thinking" in record["response_raw"]
    assert record["response_identifiers"] == {"nvcf-reqid": "interrupted-provider-id"}
    assert guard.stopped and len(guard.state["transport_interruptions"]) == 1


def test_a_stream_closed_after_its_usage_arrived_is_complete(tmp_path):
    """The product closes the stream once it has the completion and usage, before the end marker."""
    from agent_eval.budget import FreeRouteGuard
    from agent_eval.recorder import _Tape, _RecordingTransport

    guard = FreeRouteGuard(tmp_path / "free.json", provider_id="magpie-workbuddy-ai", base_url=FREE_BASE)
    tape = _Tape(tmp_path / "tape.jsonl", "record")

    async def body():
        yield (b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}],'
               b'"usage":{"prompt_tokens":10,"completion_tokens":2,"credit":0}}\n\n')
        await asyncio.Event().wait()  # the end marker never comes before the reader leaves
        yield b"data: [DONE]\n\n"

    async def scenario():
        transport = _RecordingTransport(tape, httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body())), budget=guard)
        async with httpx.AsyncClient(transport=transport) as client:
            async with client.stream("POST", f"{FREE_BASE}/chat/completions", json={"max_tokens": 10}) as response:
                await response.aiter_bytes().__anext__()
    asyncio.run(scenario())
    [record] = [json.loads(line) for line in tape.path.read_text().splitlines()]
    assert record["status"] == 200 and record["usage"]["credit"] == 0 and "transport_error" not in record
    assert guard.state["calls"] == 1 and not guard.state.get("transport_interruptions")


@pytest.mark.parametrize("streaming", [True, False])
def test_recorder_keeps_only_bounded_response_ids_and_preserves_exact_request_bytes(tmp_path, streaming):
    import hashlib
    from agent_eval.recorder import _RecordingTransport, _Tape

    payload = b'{ "model" : "offline", "messages": [], "max_tokens": 10 }'
    expected_ids = {"x-request-id": "request-opaque-123", "nvcf-reqid": "nvcf-opaque-456",
                    "traceparent": "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"}
    sensitive = {"authorization": "Bearer response-secret", "set-cookie": "response-cookie=secret",
                 "cookie": "cookie-secret", "x-private-debug": "private-header-secret"}
    headers = {"X-Request-ID": expected_ids["x-request-id"], "NVCF-REQID": expected_ids["nvcf-reqid"],
               "Traceparent": expected_ids["traceparent"], **sensitive}
    status = 200 if streaming else 500
    raw = (b'data: {"choices":[{"delta":{"content":"ok"}}],"usage":{"prompt_tokens":1,"completion_tokens":1}}\n\ndata: [DONE]\n\n'
           if streaming else b'{"error":{"message":"Failed to generate completions","type":"Internal Server Error","code":500}}')
    headers["content-type"] = "text/event-stream" if streaming else "application/json"
    seen = []

    def handle(request):
        seen.append(request.content)
        assert request.headers["authorization"] == "Bearer request-secret"
        return httpx.Response(status, headers=headers, content=raw)

    tape = _Tape(tmp_path/"tape.jsonl", "record")

    async def scenario():
        transport = _RecordingTransport(tape, httpx.MockTransport(handle))
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.post("https://provider.invalid/v1/chat/completions", content=payload,
                                         headers={"authorization": "Bearer request-secret"})
            assert response.status_code == status and response.content == raw
            assert response.headers["x-request-id"] == expected_ids["x-request-id"]

    asyncio.run(scenario())
    [record] = [json.loads(line) for line in tape.path.read_text().splitlines()]
    assert record["response_identifiers"] == expected_ids
    assert seen == [payload] and record["request_bytes"] == len(payload)
    assert record["request_sha256"] == hashlib.sha256(payload).hexdigest()
    assert record["usage"] is None if not streaming else record["usage"]["completion_tokens"] == 1
    assert "headers" not in record
    for secret in (*sensitive.values(), "request-secret"):
        assert secret not in tape.path.read_text()


@pytest.mark.parametrize("headers", [{}, {"x-request-id": "x"*257, "nvcf-reqid": "bad\x00id", "traceparent": "a b"}])
def test_missing_or_invalid_response_ids_stay_unknown_not_local_sha(tmp_path, headers):
    from agent_eval.recorder import _RecordingTransport, _Tape

    tape = _Tape(tmp_path/"tape.jsonl", "record")

    async def scenario():
        transport = _RecordingTransport(tape, httpx.MockTransport(
            lambda request: httpx.Response(500, headers=headers, json={"error":{"message":"offline"}})))
        async with httpx.AsyncClient(transport=transport) as client:
            await client.post("https://provider.invalid/v1/chat/completions", content=b'{}')

    asyncio.run(scenario())
    [record] = [json.loads(line) for line in tape.path.read_text().splitlines()]
    assert record["response_identifiers"] == {}
    assert record["usage"] is None
