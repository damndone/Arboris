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
    budget = api.RoundBudget(tmp_path / "budget.json", cap_cny="0.003", context_tokens=100)
    budget.reserve(b'{"max_tokens":10}')
    with pytest.raises(api.BudgetStop):
        budget.reserve(b'{"max_tokens":10}')


def test_missing_max_tokens_reserves_entire_pinned_context_without_changing_request(tmp_path):
    api = budget_api()
    budget = api.RoundBudget(tmp_path / "budget.json", cap_cny="5", context_tokens=1_048_576)
    request = b'{"model":"deepseek-flash","messages":[]}'
    key = budget.reserve(request)
    assert Decimal(budget.state["reservations"][key]) > Decimal("2")
    assert json.loads(request) == {"model": "deepseek-flash", "messages": []}


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
