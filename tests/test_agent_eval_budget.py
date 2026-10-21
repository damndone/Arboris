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
    monkeypatch.setattr(shutil, "disk_usage", lambda root: SimpleNamespace(free=9_999_999_999))
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
