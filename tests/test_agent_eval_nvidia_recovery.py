"""Offline acceptance of the explicitly authorized 503-only recovery contract."""
import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from tests.test_agent_eval_nvidia_guard import BASE, MODEL, USAGE, guard
from agent_eval import budget
from agent_eval.recorder import provider_tape
from workbench.agent.model import ModelRequest, OpenAICompatibleModelAdapter
from workbench.llm.config import LLMConfig

OVERLOAD = b'data: {"error":{"message":"Service temporarily overloaded","type":"service_unavailable","code":503}}\n\ndata: [DONE]\n\n'
SUCCESS = ('data: ' + json.dumps({'choices': [{'delta': {'content': 'offline done'}, 'finish_reason': 'stop'}], 'usage': USAGE}) + '\n\ndata: [DONE]\n\n').encode()


def setup_recovery(tmp_path, monkeypatch, responses, *, closed=None):
    assert hasattr(budget, 'NvidiaOverloadRecovery'), 'missing opt-in bounded overload recovery'
    g, now = guard(tmp_path, monkeypatch, overload_recovery_ledger=tmp_path / 'recovery.json')
    calls, waits = [], []
    async def wait(seconds):
        if closed is not None: assert len(closed) == len(calls), 'retry wait began before failed HTTP stream closed'
        waits.append(seconds)
        now[0] += seconds
    monkeypatch.setattr(asyncio, 'sleep', wait)
    class Stream(httpx.AsyncByteStream):
        def __init__(self, raw): self.raw = raw
        async def __aiter__(self): yield self.raw
        async def aclose(self):
            if closed is not None: closed.append(True)
    def handle(request):
        calls.append(request.content)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Stream(responses[len(calls)-1]))
    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', lambda: httpx.MockTransport(handle))
    return g, calls, waits, now


async def run(g, tmp_path, text='offline'):
    with provider_tape(tmp_path / 'tape.jsonl', budget=g):
        adapter = OpenAICompatibleModelAdapter(LLMConfig(base_url=BASE, api_key='offline', model=MODEL,
            provider_id='nvidia-nemotron-free'))
        return [e async for e in adapter.stream(ModelRequest(messages=[{'role': 'user', 'content': text}]))]


@pytest.mark.parametrize('overloads', [1, 2])
def test_only_503_retries_wait_60_120_and_keep_original_payload(tmp_path, monkeypatch, overloads):
    closed = []
    g, calls, waits, _ = setup_recovery(tmp_path, monkeypatch, [OVERLOAD]*overloads + [SUCCESS], closed=closed)
    events = asyncio.run(run(g, tmp_path))
    assert events[-1].type == 'done' and len(calls) == overloads + 1
    assert waits == [60, 120][:overloads] and len(set(calls)) == 1
    state = g.state
    assert state['requests'] == overloads + 1 and state['calls'] == 1 and not state['reservations']
    assert len(state['accepted_unknown_requests']) == overloads and len(state['charges']) == 1
    assert g.overload_recovery.state['retries'] == overloads
    restored = budget.NvidiaOverloadRecovery(tmp_path / 'recovery.json')
    assert restored.state['request_retries'][hashlib.sha256(calls[0]).hexdigest()] == overloads
    assert len((tmp_path / 'tape.jsonl').read_text().splitlines()) == overloads + 1
    assert all(e.type != 'retry' for e in events), 'product adapter must not add retry scheduling'


def test_third_503_stops_after_two_retries_without_settling_unknown(tmp_path, monkeypatch):
    g, calls, waits, _ = setup_recovery(tmp_path, monkeypatch, [OVERLOAD]*3)
    with pytest.raises(budget.BudgetStop, match='per-request'):
        asyncio.run(run(g, tmp_path))
    assert len(calls) == 3 and waits == [60, 120]
    assert g.stopped and g.state['requests'] == 3 and g.state['calls'] == 0
    assert len(g.state['accepted_unknown_requests']) == 2 and len(g.state['reservations']) == 1


@pytest.mark.parametrize('extra', [b'data: {"choices":[{"delta":{"content":"text"}}]}\n\n',
    b'data: {"choices":[{"delta":{"tool_calls":[{}]}}]}\n\n',
    b'data: {"choices":[{"delta":{"reasoning_content":"private"}}]}\n\n', b'no-DONE', b'non503'])
def test_output_incomplete_or_non503_never_recovers(tmp_path, monkeypatch, extra):
    raw = OVERLOAD.replace(b'503', b'502') if extra == b'non503' else OVERLOAD.replace(b'data: [DONE]\n\n', b'') if extra == b'no-DONE' else extra + OVERLOAD
    g, calls, waits, _ = setup_recovery(tmp_path, monkeypatch, [raw])
    with pytest.raises(budget.BudgetStop): asyncio.run(run(g, tmp_path))
    assert len(calls) == 1 and waits == [] and g.stopped
    assert g.overload_recovery.state['retries'] == 0 and g.state['reservations']


def test_cancelling_the_wait_never_resends_and_persists_stop(tmp_path, monkeypatch):
    g, calls, waits, _ = setup_recovery(tmp_path, monkeypatch, [OVERLOAD])
    async def cancel(seconds):
        waits.append(seconds)
        raise asyncio.CancelledError()
    monkeypatch.setattr(asyncio, 'sleep', cancel)
    with pytest.raises(asyncio.CancelledError): asyncio.run(run(g, tmp_path))
    assert len(calls) == 1 and waits == [60] and g.stopped and g.overload_recovery.stopped
    assert g.overload_recovery.state['retries'] == 1
    restored = budget.NvidiaOverloadRecovery(tmp_path / 'recovery.json')
    assert restored.stopped and restored.state['retries'] == 1


def test_shared_global_limit_counts_manual_restart_and_rejects_eleventh(tmp_path, monkeypatch):
    g, calls, waits, _ = setup_recovery(tmp_path, monkeypatch, [OVERLOAD])
    shared = g.overload_recovery
    for i in range(10): shared.record_manual_restart(source_path=f'prior-{i}', reason='approved restart')
    shared.record_manual_restart(source_path='prior-0', reason='approved restart')
    assert shared.state['retries'] == 10
    with pytest.raises(budget.BudgetStop, match='shared'):
        asyncio.run(run(g, tmp_path))
    assert len(calls) == 1 and waits == [] and g.state['requests'] == 1
    assert len(g.state['reservations']) == 1 and shared.state['retries'] == 10
    qr = budget.NvidiaFreeEndpointGuard(tmp_path / 'qr.json', provider_id='nvidia-nemotron-free',
        base_url=BASE, model=MODEL, round_kind='qrdata40', overload_recovery_ledger=tmp_path / 'recovery.json')
    with pytest.raises(budget.BudgetStop): qr.reserve(json.dumps({'model': MODEL}).encode())
    assert qr.state['requests'] == 0


def test_pending_ticket_survives_restart_and_refuses_another_sender(tmp_path, monkeypatch):
    g, _, _, _ = setup_recovery(tmp_path, monkeypatch, [])
    body=json.dumps({'model': MODEL}).encode()
    key=g.reserve(body)
    with pytest.raises(budget.NvidiaOverloadRetry): g.recover_overload(200, OVERLOAD, key)
    restored = budget.NvidiaFreeEndpointGuard(tmp_path / 'fresh.json', provider_id='nvidia-nemotron-free',
        base_url=BASE, model=MODEL, round_kind='dev8', overload_recovery_ledger=tmp_path / 'recovery.json')
    with pytest.raises(budget.BudgetStop, match='pending'):
        restored.reserve(body)
    assert restored.overload_recovery.state['retries'] == 1 and restored.state['requests'] == 0


def test_recovery_ledger_binding_cannot_change_on_restart(tmp_path, monkeypatch):
    g, _, _, _ = setup_recovery(tmp_path, monkeypatch, [])
    with pytest.raises(ValueError, match='recovery ledger'):
        guard(tmp_path, monkeypatch, overload_recovery_ledger=tmp_path / 'different.json')
    with pytest.raises(ValueError, match='recovery ledger'):
        guard(tmp_path, monkeypatch)


def test_recovery_cli_requires_nvidia_opt_in_and_records_shared_ledger(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from tests.test_agent_eval_nvidia_guard import run_module
    module = run_module()
    monkeypatch.setattr(module, 'load_llm_config', lambda: pytest.fail('invalid recovery opt-in reached provider config'))
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(tmp_path / 'out'),
        '--nvidia-overload-recovery-ledger', str(tmp_path / 'shared.json')])
    with pytest.raises(SystemExit) as rejected: module.main()
    assert rejected.value.code == 2
    config = SimpleNamespace(provider_id='nvidia-nemotron-free', base_url=BASE, model=MODEL, is_configured=lambda: True)
    monkeypatch.setattr(module, 'load_llm_config', lambda: config)
    monkeypatch.setattr(module, 'dev_tasks', lambda: [SimpleNamespace(id='panel_fe.specific')])
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda _: SimpleNamespace(free=1))
    monkeypatch.setattr(module, '_seed', lambda *a: pytest.fail('storage stop reached provider setup'))
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(tmp_path / 'out'), '--tasks', 'panel_fe.specific',
        '--mode', 'ask', '--nvidia-free-round', 'dev8', '--nvidia-free-ledger', str(tmp_path / 'dev.json'),
        '--nvidia-overload-recovery-ledger', str(tmp_path / 'shared.json')])
    assert module.main() == 86
    meta = json.loads((tmp_path / 'out/run_meta.json').read_text())['nvidia_free_endpoint']
    assert meta['overload_recovery_ledger'] == str(tmp_path / 'shared.json')
    assert meta['overload_recovery'] == {'shared_retry_limit': 10, 'per_request_retry_limit': 2,
        'delays_s': [60, 120], 'eligibility': 'complete observed error-only SSE 503 plus DONE; no generated output'}


def test_read_error_before_headers_stops_without_spending_overload_recovery(tmp_path, monkeypatch):
    g, calls, waits, now = setup_recovery(tmp_path, monkeypatch, [])
    shared_before = g.overload_recovery.state
    def fail_read(request):
        calls.append(request.content)
        now[0] += 46.8665  # Reproduce the saved elapsed value without waiting or measuring.
        raise httpx.ReadError('upstream closed before any response', request=request)
    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', lambda: httpx.MockTransport(fail_read))
    with pytest.raises(budget.BudgetStop, match='unknown usage.*ReadError'):
        asyncio.run(run(g, tmp_path))
    assert len(calls) == 1 and waits == [] and g.stopped
    assert g.state['requests'] == 1 and g.state['calls'] == 0
    assert len(g.state['reservations']) == 1 and g.state['charges'] == []
    assert not g.state.get('accepted_unknown_requests')
    assert g.overload_recovery.state == shared_before
    [record] = [json.loads(line) for line in (tmp_path / 'tape.jsonl').read_text().splitlines()]
    assert record['status'] == 0 and record['upstream_http_status'] is None
    assert record['transport_error'] == 'ReadError' and record['response_raw'] == ''
    assert record['usage'] is None and record['sent'] is True
    assert record['elapsed_s'] == pytest.approx(46.8665)
    assert record['budget_reservation'] in g.state['reservations']
