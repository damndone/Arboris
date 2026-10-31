"""Offline cross-process serial HTTP while tasks may overlap local work."""
import asyncio
import importlib
import importlib.util
import json
import multiprocessing
from pathlib import Path
import time

import httpx
import pytest

from agent_eval import budget
from agent_eval.recorder import _RecordingTransport, _Tape, provider_tape
from tests.test_agent_eval_nvidia_guard import BASE, BODY, MODEL, USAGE, available_test_storage, guard


def serial_type():
    spec = importlib.util.find_spec('agent_eval.nvidia_serial')
    assert spec is not None, 'missing explicit serial coordinator; do not relax the original guard'
    return importlib.import_module('agent_eval.nvidia_serial').NvidiaSerialCoordinator


def _child_request(directory, barrier, report):
    """Real independent process and real file locks; fake accounting, no HTTP."""
    from agent_eval.budget import NvidiaFreeEndpointGuard
    root = Path(directory)
    g = NvidiaFreeEndpointGuard(root / 'dev.json', provider_id='nvidia-nemotron-free',
        base_url=BASE, model=MODEL, round_kind='dev8', allow_low_space_this_round=True,
        shared_serial_ledger=root / 'serial.json')
    barrier.wait(timeout=10)

    async def request():
        await g.wait_for_request_slot()
        key = g.reserve(json.dumps(BODY).encode())
        started = time.time()
        await asyncio.sleep(0.05)
        g.settle(key, USAGE)
        report.put((started, time.time()))

    asyncio.run(request())


def test_two_processes_preserve_single_reservation_and_global_start_gap(tmp_path):
    serial_type()
    ctx = multiprocessing.get_context('spawn')
    barrier, report = ctx.Barrier(2), ctx.Queue()
    workers = [ctx.Process(target=_child_request, args=(str(tmp_path), barrier, report)) for _ in range(2)]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=20)
        assert [worker.exitcode for worker in workers] == [0, 0]
        spans = sorted([report.get(timeout=2), report.get(timeout=2)])
        assert spans[1][0] - spans[0][0] >= 1.99
        assert spans[1][0] >= spans[0][1], 'HTTP slots overlapped'
        state = json.loads((tmp_path / 'dev.json').read_text())
        assert state['requests'] == state['calls'] == 2 and not state['reservations']
        serial = json.loads((tmp_path / 'serial.json').read_text())
        assert len(serial['starts']) == 2 and serial['active'] is None and not serial['stopped']
        assert serial['starts'][1]['at'] - serial['starts'][0]['at'] >= 2
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=2)


def test_waiter_observes_shared_stop_without_reservation_or_retry(tmp_path):
    cls = serial_type()
    holder, waiter = cls(tmp_path / 'serial.json'), cls(tmp_path / 'serial.json')

    async def scenario():
        await holder.acquire()
        waiting = asyncio.create_task(waiter.acquire())
        await asyncio.sleep(0.03)
        holder.stop('offline shared stop')
        with pytest.raises(budget.BudgetStop, match='offline shared stop'):
            await asyncio.wait_for(waiting, timeout=1)
        assert not waiter.held and waiter.wait_s > 0
        holder.release()

    asyncio.run(scenario())
    assert not json.loads((tmp_path / 'serial.json').read_text())['starts']


def test_orphaned_serial_owner_cannot_be_claimed_as_success(tmp_path):
    cls = serial_type()
    old = cls(tmp_path / 'serial.json')
    asyncio.run(old.acquire())
    old.release(preserve_unknown=True)
    new = cls(tmp_path / 'serial.json')
    with pytest.raises(budget.BudgetStop):
        asyncio.run(new.acquire())
    assert new.stopped and new.state['active'] is not None


def test_recorded_success_settles_after_shared_stop_without_zeroing_usage(tmp_path, monkeypatch):
    g, _ = guard(tmp_path, monkeypatch, shared_serial_ledger=tmp_path / 'serial.json')
    coordinator = g.serial_coordinator

    def handle(request):
        coordinator.stop('offline stop while one response is returning')
        return httpx.Response(200, json={'choices': [], 'usage': USAGE})

    async def scenario():
        transport = _RecordingTransport(_Tape(tmp_path / 'tape.jsonl', 'record'),
            httpx.MockTransport(handle), budget=g)
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.post(BASE + '/chat/completions', json=BODY)
            assert response.status_code == 200
            with pytest.raises(budget.BudgetStop):
                await client.post(BASE + '/chat/completions', json=BODY)

    asyncio.run(scenario())
    assert g.state['requests'] == g.state['calls'] == 1
    assert g.state['charges'][0]['usage'] == USAGE and not g.state['reservations']
    row, = [json.loads(line) for line in (tmp_path / 'tape.jsonl').read_text().splitlines()]
    assert row['status'] == 200 and row['usage'] == USAGE
    assert coordinator.stopped and coordinator.state['active'] is None


def test_adapter_waits_before_original_idle_timer_and_restores_method(tmp_path, monkeypatch):
    from workbench.agent import model
    from workbench.agent.model import ModelRequest, ModelStreamEvent, OpenAICompatibleModelAdapter
    from workbench.llm.config import LLMConfig
    cls = serial_type()
    holder = cls(tmp_path / 'serial.json')
    g, _ = guard(tmp_path, monkeypatch, shared_serial_ledger=tmp_path / 'serial.json')
    entered = []

    async def original(adapter, request):
        entered.append(time.monotonic())
        yield ModelStreamEvent.from_error(request.request_id, 'offline no provider')

    monkeypatch.setattr(model.OpenAICompatibleModelAdapter, 'stream', original)

    async def scenario():
        await holder.acquire()
        with provider_tape(tmp_path / 'tape.jsonl', budget=g):
            adapter = OpenAICompatibleModelAdapter(LLMConfig(base_url=BASE, api_key='offline', model=MODEL,
                provider_id='nvidia-nemotron-free'), idle_timeout_s=0.01)
            request = ModelRequest(messages=[{'role': 'user', 'content': 'offline'}])
            stream = adapter.stream(request)
            pending = asyncio.create_task(anext(stream))
            await asyncio.sleep(0.04)
            assert not entered, 'original model idle timer began while globally queued'
            holder.release()
            event = await asyncio.wait_for(pending, timeout=1)
            assert event.type == 'error'
            await stream.aclose()
        assert model.OpenAICompatibleModelAdapter.stream is original

    asyncio.run(scenario())
    assert entered and g.serial_queue_wait_s >= 0.03
    assert g.state['requests'] == 0 and g.state['calls'] == 0


def test_serial_binding_cannot_change_on_restart(tmp_path, monkeypatch):
    g, _ = guard(tmp_path, monkeypatch, shared_serial_ledger=tmp_path / 'serial.json')
    before = g.path.read_bytes()
    with pytest.raises(ValueError, match='serial'):
        guard(tmp_path, monkeypatch)
    assert g.path.read_bytes() == before


def test_serial_lease_is_retained_through_the_original_retry_ticket(tmp_path, monkeypatch):
    from tests.test_agent_eval_nvidia_recovery import OVERLOAD
    cls = serial_type()
    g, now = guard(tmp_path, monkeypatch, shared_serial_ledger=tmp_path / 'serial.json',
        overload_recovery_ledger=tmp_path / 'recovery.json')
    waiter = cls(tmp_path / 'serial.json')
    payload = json.dumps(BODY).encode()

    async def scenario():
        await g.wait_for_request_slot()
        key = g.reserve(payload)
        with pytest.raises(budget.NvidiaOverloadRetry) as failure:
            g.recover_overload(200, OVERLOAD, key)
        queued = asyncio.create_task(waiter.acquire())
        await asyncio.sleep(0.03)
        assert not queued.done() and g.serial_coordinator.held
        assert g.overload_recovery.state['pending'] == failure.value.ticket
        now[0] += failure.value.delay_s
        g.overload_recovery.ready(failure.value.ticket)
        g._retry_ticket = failure.value.ticket
        retry_key = g.reserve(payload)
        assert not queued.done() and g.overload_recovery.state['pending'] is None
        g.settle(retry_key, USAGE)
        await asyncio.wait_for(queued, timeout=1)
        waiter.release()

    asyncio.run(scenario())
    assert g.state['requests'] == 2 and g.state['calls'] == 1 and not g.state['reservations']
    assert g.overload_recovery.state['retries'] == 1
    assert len(g.state['accepted_unknown_requests']) == 1
    assert len(g.serial_coordinator.state['starts']) == 2


def test_shared_pace_spaces_starts_across_lanes_and_a_429_holds_them_back(tmp_path, monkeypatch):
    from agent_eval import nvidia_serial
    from agent_eval.nvidia_serial import SharedStartPace

    pace = SharedStartPace(tmp_path / 'pace')
    clock, slept = [1000.0], []
    monkeypatch.setattr(nvidia_serial.time, 'time', lambda: clock[0])

    def sleep(seconds):
        slept.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(nvidia_serial.time, 'sleep', sleep)
    starts = []
    for _ in range(4):
        pace.wait_turn()
        starts.append(clock[0])
    assert [round(b - a, 6) for a, b in zip(starts, starts[1:])] == [1.6, 1.6, 1.6]
    pace.hold_after_429()
    before = clock[0]
    pace.wait_turn()
    assert clock[0] == before + 30.0
