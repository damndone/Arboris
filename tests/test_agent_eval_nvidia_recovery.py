"""Offline acceptance of the explicitly authorized 503-only recovery contract."""
import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from tests.test_agent_eval_nvidia_guard import BASE, MODEL, USAGE, guard, available_test_storage
from agent_eval import budget
from agent_eval.recorder import provider_tape
from workbench.agent.model import ModelRequest, OpenAICompatibleModelAdapter
from workbench.llm.config import LLMConfig

OVERLOAD = b'data: {"error":{"message":"Service temporarily overloaded","type":"service_unavailable","code":503}}\n\ndata: [DONE]\n\n'
SUCCESS = ('data: ' + json.dumps({'choices': [{'delta': {'content': 'offline done'}, 'finish_reason': 'stop'}], 'usage': USAGE}) + '\n\ndata: [DONE]\n\n').encode()


def setup_recovery(tmp_path, monkeypatch, responses, *, closed=None, unanswered_reads=False, pool_closed=None):
    assert hasattr(budget, 'NvidiaOverloadRecovery'), 'missing opt-in bounded overload recovery'
    options = {'recover_unanswered_read_errors': True} if unanswered_reads else {}
    g, now = guard(tmp_path, monkeypatch, overload_recovery_ledger=tmp_path / 'recovery.json', **options)
    calls, waits = [], []
    async def wait(seconds):
        if closed is not None: assert len(closed) == len(calls), 'retry wait began before failed HTTP stream closed'
        if pool_closed is not None: assert len(pool_closed) == len(calls), 'retry wait began before failed client pool closed'
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
        raw = responses[len(calls)-1]
        if isinstance(raw, BaseException): raise raw
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=Stream(raw))
    class TrackedTransport(httpx.MockTransport):
        async def aclose(self):
            if pool_closed is not None: pool_closed.append(True)
            await super().aclose()
    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', lambda: TrackedTransport(handle))
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


@pytest.mark.parametrize('unanswered_reads', [False, True])
def test_cancelling_the_wait_never_resends_and_persists_stop(tmp_path, monkeypatch, unanswered_reads):
    response = httpx.ReadError('unanswered') if unanswered_reads else OVERLOAD
    g, calls, waits, _ = setup_recovery(tmp_path, monkeypatch, [response], unanswered_reads=unanswered_reads)
    async def cancel(seconds):
        waits.append(seconds)
        raise asyncio.CancelledError()
    monkeypatch.setattr(asyncio, 'sleep', cancel)
    with pytest.raises(asyncio.CancelledError): asyncio.run(run(g, tmp_path))
    assert len(calls) == 1 and waits == [60] and g.stopped and g.overload_recovery.stopped
    assert g.overload_recovery.state['retries'] == 1
    restored = budget.NvidiaOverloadRecovery(tmp_path / 'recovery.json', unanswered_read_errors=unanswered_reads)
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


@pytest.mark.parametrize('unanswered_reads', [False, True])
def test_recovery_cli_requires_nvidia_opt_in_and_records_shared_ledger(tmp_path, monkeypatch, unanswered_reads):
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
    if unanswered_reads: sys.argv.append('--nvidia-recover-unanswered-read-error')
    assert module.main() == 86
    meta = json.loads((tmp_path / 'out/run_meta.json').read_text())['nvidia_free_endpoint']
    assert meta['recover_unanswered_read_errors'] is unanswered_reads
    assert meta['overload_recovery_schema'] == ('nvidia-overload-recovery/v2' if unanswered_reads else 'nvidia-overload-recovery/v1')
    assert meta['overload_recovery_ledger'] == str(tmp_path / 'shared.json')
    eligibility = 'complete observed error-only SSE 503 plus DONE; no generated output'
    if unanswered_reads: eligibility += '; or ReadError before any response headers or body'
    assert meta['overload_recovery'] == {'shared_retry_limit': 10, 'per_request_retry_limit': 2,
        'delays_s': [60, 120], 'eligibility': eligibility}


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


def test_recording_transport_closes_inner_after_unanswered_read_error(tmp_path):
    from agent_eval.recorder import _RecordingTransport, _Tape
    closed = []
    class TrackedTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request): raise httpx.ReadError('unanswered', request=request)
        async def aclose(self): closed.append(True)
    async def scenario():
        transport = _RecordingTransport(_Tape(tmp_path / 'tape.jsonl', 'record'), TrackedTransport())
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(httpx.ReadError): await client.post(BASE+'/chat/completions', json={'model': MODEL})
    asyncio.run(scenario())
    assert closed == [True], 'failed client exit must close the inner connection pool before any retry wait'


@pytest.mark.parametrize('failures', [[httpx.ReadError('unanswered')], [OVERLOAD, httpx.ReadError('unanswered')]])
def test_v2_unanswered_read_error_and_503_share_payload_delays_and_allowance(tmp_path, monkeypatch, failures):
    pool_closed = []
    g, calls, waits, _ = setup_recovery(tmp_path, monkeypatch, failures+[SUCCESS], unanswered_reads=True, pool_closed=pool_closed)
    events = asyncio.run(run(g, tmp_path))
    assert events[-1].type == 'done' and len(calls) == len(failures)+1 and len(set(calls)) == 1
    assert len(pool_closed) == len(calls)
    assert waits == [60,120][:len(failures)]
    assert g.state['requests'] == len(calls) and g.state['calls'] == 1 and not g.state['reservations']
    unknown = g.state['accepted_unknown_requests']
    assert len(unknown) == len(failures) and unknown[-1]['raw_sha256'] == hashlib.sha256(b'').hexdigest()
    assert 'unanswered ReadError' in unknown[-1]['reason']
    assert g.overload_recovery.state['retries'] == len(failures)
    restored = budget.NvidiaOverloadRecovery(tmp_path/'recovery.json', unanswered_read_errors=True)
    assert restored.state['schema'] == 'nvidia-overload-recovery/v2'
    assert restored.state['request_retries'][hashlib.sha256(calls[0]).hexdigest()] == len(failures)
    rows=[json.loads(line) for line in (tmp_path/'tape.jsonl').read_text().splitlines()]
    failed=rows[len(failures)-1]
    assert failed['transport_error']=='ReadError' and failed['upstream_http_status'] is None and failed['response_raw']==''


def test_v2_third_mixed_503_read_error_attempt_stops(tmp_path, monkeypatch):
    g, calls, waits, _ = setup_recovery(tmp_path, monkeypatch,
        [OVERLOAD,httpx.ReadError('unanswered'),httpx.ReadError('unanswered again')], unanswered_reads=True)
    with pytest.raises(budget.BudgetStop,match='per-request'): asyncio.run(run(g,tmp_path))
    assert len(calls)==3 and waits==[60,120] and g.stopped
    assert len(g.state['accepted_unknown_requests'])==2 and len(g.state['reservations'])==1
    assert g.state['calls']==0 and g.overload_recovery.state['retries']==2


@pytest.mark.parametrize('shape',['headers','partial_body','other_error'])
def test_v2_refuses_read_failures_outside_unanswered_read_error(tmp_path, monkeypatch, shape):
    g,calls,waits,_=setup_recovery(tmp_path,monkeypatch,[],unanswered_reads=True)
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            if shape=='partial_body': yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            raise httpx.ReadError('after headers')
    def handle(request):
        calls.append(request.content)
        if shape=='other_error': raise httpx.ReadTimeout('not an eligible ReadError',request=request)
        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Stream())
    monkeypatch.setattr(httpx,'AsyncHTTPTransport',lambda:httpx.MockTransport(handle))
    with pytest.raises(budget.BudgetStop): asyncio.run(run(g,tmp_path))
    assert len(calls)==1 and waits==[] and g.stopped
    assert g.overload_recovery.state['retries']==0 and len(g.state['reservations'])==1


def test_recovery_policy_versions_cannot_silently_upgrade_or_downgrade(tmp_path):
    old=tmp_path/'v1.json';budget.NvidiaOverloadRecovery(old);before=old.read_bytes()
    with pytest.raises(ValueError): budget.NvidiaOverloadRecovery(old,unanswered_read_errors=True)
    assert old.read_bytes()==before
    new=tmp_path/'v2.json';budget.NvidiaOverloadRecovery(new,unanswered_read_errors=True);before=new.read_bytes()
    with pytest.raises(ValueError): budget.NvidiaOverloadRecovery(new)
    assert new.read_bytes()==before
