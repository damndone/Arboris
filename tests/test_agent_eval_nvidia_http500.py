"""Offline complete HTTP500 opt-in; do not execute during native A/B freeze."""
import asyncio
import hashlib
import json

import httpx
import pytest

from agent_eval import budget
from agent_eval.recorder import provider_tape
from tests.test_agent_eval_nvidia_guard import BASE, MODEL, USAGE, available_test_storage, guard
from tests.test_agent_eval_nvidia_recovery import OVERLOAD, SUCCESS, run

HTTP500 = b'{"error":{"message":"Failed to generate completions","type":"Internal Server Error","code":500}}'


def setup_http500(tmp_path, monkeypatch, replies, **extra):
    g, now = guard(tmp_path, monkeypatch, overload_recovery_ledger=tmp_path / 'recovery.json',
        recover_unanswered_read_errors=True, recover_unanswered_protocol_errors=True,
        recover_complete_http_500_errors=True, **extra)
    calls, waits = [], []

    async def wait(seconds):
        waits.append(seconds)
        now[0] += seconds

    def handle(request):
        calls.append(request.content)
        reply = replies[len(calls) - 1]
        if isinstance(reply, BaseException):
            raise reply
        if isinstance(reply, tuple):
            status, raw = reply
            return httpx.Response(status, headers={'content-type': 'application/json'}, content=raw)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=reply)

    monkeypatch.setattr(asyncio, 'sleep', wait)
    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', lambda: httpx.MockTransport(handle))
    return g, calls, waits


def test_complete_error_only_http500_retries_same_payload_without_zero_settlement(tmp_path, monkeypatch):
    g, calls, waits = setup_http500(tmp_path, monkeypatch, [(500, HTTP500), SUCCESS])
    result = asyncio.run(run(g, tmp_path))
    assert result[-1].type == 'done' and len(calls) == 2 and len(set(calls)) == 1
    assert waits == [60] and g.state['requests'] == 2 and g.state['calls'] == 1
    assert g.overload_recovery.state['schema'] == 'nvidia-overload-recovery/v4'
    assert g.overload_recovery.state['retries'] == 1
    unknown, = g.state['accepted_unknown_requests']
    assert unknown['raw_sha256'] == hashlib.sha256(HTTP500).hexdigest()
    assert 'complete error-only HTTP 500' in unknown['reason']
    assert len(g.state['charges']) == 1 and g.state['charges'][0]['usage'] == USAGE
    rows = [json.loads(line) for line in (tmp_path / 'tape.jsonl').read_text().splitlines()]
    assert rows[0]['status'] == 500 and rows[0]['usage'] is None
    assert rows[0]['response_raw'] == HTTP500.decode()
    assert 'transport_error' not in rows[0]


def test_mixed_500_503_and_unanswered_errors_keep_two_retry_limit(tmp_path, monkeypatch):
    g, calls, waits = setup_http500(tmp_path, monkeypatch,
        [(500, HTTP500), OVERLOAD, httpx.RemoteProtocolError('unanswered')])
    with pytest.raises(budget.BudgetStop, match='per-request'):
        asyncio.run(run(g, tmp_path))
    assert len(calls) == 3 and len(set(calls)) == 1 and waits == [60, 120]
    assert g.state['calls'] == 0 and len(g.state['reservations']) == 1
    assert len(g.state['accepted_unknown_requests']) == 2
    assert g.overload_recovery.state['retries'] == 2


@pytest.mark.parametrize('payload', [
    {'error': {'message': 'Failed to generate completions', 'type': 'Internal Server Error', 'code': 500}, 'choices': []},
    {'error': {'message': 'Failed to generate completions', 'type': 'Internal Server Error', 'code': 500}, 'usage': USAGE},
    {'choices': [{'delta': {'content': 'public'}}]},
    {'choices': [{'delta': {'reasoning_content': 'private'}}]},
    {'choices': [{'delta': {'tool_calls': [{}]}}]},
    {'error': {'message': 'other unobserved failure', 'type': 'Internal Server Error', 'code': 500}},
    {'error': {'message': 'Failed to generate completions', 'type': 'Internal Server Error', 'code': '500'}},
])
def test_http500_generated_usage_or_unobserved_envelopes_do_not_retry(tmp_path, monkeypatch, payload):
    raw = json.dumps(payload).encode()
    g, calls, waits = setup_http500(tmp_path, monkeypatch, [(500, raw)])
    with pytest.raises(budget.BudgetStop):
        asyncio.run(run(g, tmp_path))
    assert len(calls) == 1 and not waits and g.stopped
    assert g.overload_recovery.state['retries'] == 0
    assert len(g.state['reservations']) == 1 and not g.state['charges']


@pytest.mark.parametrize('raw', [b'', HTTP500[:-1], HTTP500 + b' extra', b'data: ' + HTTP500 + b'\n\ndata: [DONE]\n\n'])
def test_empty_truncated_or_non_json_500_does_not_retry(tmp_path, monkeypatch, raw):
    g, calls, waits = setup_http500(tmp_path, monkeypatch, [(500, raw)])
    with pytest.raises(budget.BudgetStop):
        asyncio.run(run(g, tmp_path))
    assert len(calls) == 1 and not waits and g.overload_recovery.state['retries'] == 0


def test_interrupted_http500_never_uses_complete_response_recovery(tmp_path, monkeypatch):
    g, calls, waits = setup_http500(tmp_path, monkeypatch, [])

    class Interrupted(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield HTTP500
            raise httpx.ReadError('after headers and body')

    def handle(request):
        calls.append(request.content)
        return httpx.Response(500, headers={'content-type': 'application/json'}, stream=Interrupted())

    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', lambda: httpx.MockTransport(handle))
    with pytest.raises(budget.BudgetStop):
        asyncio.run(run(g, tmp_path))
    assert len(calls) == 1 and not waits and g.overload_recovery.state['retries'] == 0
    row, = [json.loads(line) for line in (tmp_path / 'tape.jsonl').read_text().splitlines()]
    assert row['status'] == 0 and row['upstream_http_status'] == 500
    assert row['transport_error'] == 'ReadError' and row['usage'] is None
    assert g.state['reservations'] and not g.state['charges']


def test_v3_policy_cannot_be_silently_upgraded_in_place(tmp_path):
    path = tmp_path / 'recovery.json'
    budget.NvidiaOverloadRecovery(path, unanswered_read_errors=True, unanswered_protocol_errors=True)
    original = path.read_bytes()
    with pytest.raises(ValueError):
        budget.NvidiaOverloadRecovery(path, unanswered_read_errors=True, unanswered_protocol_errors=True,
            complete_http_500_errors=True)
    assert path.read_bytes() == original


def test_http500_opt_in_cannot_raise_shared_or_per_request_allowance(tmp_path, monkeypatch):
    g, calls, waits = setup_http500(tmp_path, monkeypatch, [(500, HTTP500)])
    with g.overload_recovery._change() as state:
        state['retries'] = 10
    with pytest.raises(budget.BudgetStop, match='shared'):
        asyncio.run(run(g, tmp_path))
    assert len(calls) == 1 and not waits and g.overload_recovery.state['retries'] == 10
    assert g.state['reservations'] and not g.state['charges']


def test_recovery_v4_retains_the_carried_retry_charge(tmp_path, monkeypatch):
    g, calls, waits = setup_http500(tmp_path, monkeypatch, [(500, HTTP500), SUCCESS])
    with g.overload_recovery._change() as state:
        state['retries'] = 1
        state['carried_from_sha256'] = 'a' * 64
    asyncio.run(run(g, tmp_path))
    assert len(calls) == 2 and waits == [60]
    assert g.overload_recovery.state['retries'] == 2
    assert g.overload_recovery.state['carried_from_sha256'] == 'a' * 64


@pytest.mark.parametrize('extra', [['--nvidia-recover-complete-http-500'],
    ['--nvidia-shared-serial-ledger', 'serial.json']])
def test_new_cli_opt_ins_require_their_explicit_endpoint_and_recovery_policy(tmp_path, monkeypatch, extra):
    import sys
    from tests.test_agent_eval_nvidia_guard import run_module
    module = run_module()
    monkeypatch.setattr(module, 'load_llm_config', lambda: pytest.fail('invalid CLI reached provider config'))
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(tmp_path / 'run'), *extra])
    with pytest.raises(SystemExit) as failure:
        module.main()
    assert failure.value.code == 2


def test_cli_forwards_v4_and_shared_serial_flags_to_the_strict_guard(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    from tests.test_agent_eval_nvidia_guard import run_module
    module = run_module()
    monkeypatch.setattr(module, 'load_llm_config', lambda: SimpleNamespace(provider_id='nvidia-nemotron-free',
        base_url=BASE, model=MODEL, is_configured=lambda: True))
    captured = {}

    def stopped_guard(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(stopped=True, state={'reason': 'offline stopped'})

    monkeypatch.setattr(module, 'NvidiaFreeEndpointGuard', stopped_guard)
    serial, recovery = tmp_path / 'serial.json', tmp_path / 'recovery.json'
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(tmp_path / 'run'), '--mode', 'ask',
        '--nvidia-free-ledger', str(tmp_path / 'dev.json'), '--nvidia-free-round', 'dev8',
        '--nvidia-overload-recovery-ledger', str(recovery), '--nvidia-recover-unanswered-read-error',
        '--nvidia-recover-unanswered-protocol-error', '--nvidia-recover-complete-http-500',
        '--nvidia-shared-serial-ledger', str(serial), '--nvidia-skip-incomplete-stream-task',
        '--allow-low-space-this-round'])
    assert module.main() == 86
    assert captured['recover_complete_http_500_errors'] is True
    assert captured['recover_unanswered_read_errors'] is True and captured['recover_unanswered_protocol_errors'] is True
    assert captured['shared_serial_ledger'] == serial and captured['overload_recovery_ledger'] == recovery
    assert captured['allow_low_space_this_round'] is True and captured['skip_incomplete_stream_task'] is True
