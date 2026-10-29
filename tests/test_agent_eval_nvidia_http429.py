"""Offline v5 recovery of the observed complete error-only HTTP429 response."""
import asyncio
import hashlib
import json
import sys
from types import SimpleNamespace

import httpx
import pytest

from tests.test_agent_eval_nvidia_guard import BASE, MODEL, USAGE, available_test_storage, guard, run_module
from agent_eval import budget
from tests.test_agent_eval_nvidia_http500 import HTTP500, setup_http500
from tests.test_agent_eval_nvidia_recovery import OVERLOAD, SUCCESS, run

HTTP429 = b'{"status":429,"title":"Too Many Requests"}'
V5_OPTIONS = dict(unanswered_read_errors=True, unanswered_protocol_errors=True,
                  complete_http_500_errors=True, complete_http_429_errors=True)


def setup_http429(tmp_path, monkeypatch, replies):
    return setup_http500(tmp_path, monkeypatch, replies, recover_complete_http_429_errors=True,
                         request_limit=480)


@pytest.mark.parametrize('failures', [1, 2])
def test_complete_http429_retries_original_payload_60_120_without_zero_settlement(tmp_path, monkeypatch, failures):
    g, calls, waits = setup_http429(tmp_path, monkeypatch, [(429, HTTP429)] * failures + [SUCCESS])
    events = asyncio.run(run(g, tmp_path))
    assert events[-1].type == 'done' and len(calls) == failures + 1 and len(set(calls)) == 1
    assert waits == [60, 120][:failures]
    assert g.state['requests'] == failures + 1 and g.state['calls'] == 1 and not g.state['reservations']
    assert g.overload_recovery.state['schema'] == 'nvidia-overload-recovery/v5'
    assert g.overload_recovery.state['complete_http_429_errors'] is True
    assert g.overload_recovery.state['retries'] == failures
    assert len(g.state['charges']) == 1 and g.state['charges'][0]['usage'] == USAGE
    assert len(g.state['accepted_unknown_requests']) == failures
    assert all(entry['raw_sha256'] == hashlib.sha256(HTTP429).hexdigest()
               and 'complete error-only HTTP 429' in entry['reason'] for entry in g.state['accepted_unknown_requests'])
    rows = [json.loads(line) for line in (tmp_path / 'tape.jsonl').read_text().splitlines()]
    assert all(row['status'] == 429 and row['usage'] is None and row['response_raw'] == HTTP429.decode()
               for row in rows[:-1])


def test_http429_remains_refused_without_its_explicit_opt_in(tmp_path, monkeypatch):
    g, calls, waits = setup_http500(tmp_path, monkeypatch, [(429, HTTP429)])
    with pytest.raises(budget.BudgetStop):
        asyncio.run(run(g, tmp_path))
    assert len(calls) == 1 and not waits and g.stopped
    assert g.overload_recovery.state['schema'] == 'nvidia-overload-recovery/v4'
    assert g.overload_recovery.state['retries'] == 0 and g.state['reservations']


def test_mixed_http429_http500_and_sse503_share_two_retry_limit(tmp_path, monkeypatch):
    g, calls, waits = setup_http429(tmp_path, monkeypatch, [(429, HTTP429), (500, HTTP500), OVERLOAD])
    with pytest.raises(budget.BudgetStop, match='per-request'):
        asyncio.run(run(g, tmp_path))
    assert len(calls) == 3 and len(set(calls)) == 1 and waits == [60, 120]
    assert g.stopped and g.overload_recovery.state['retries'] == 2
    assert len(g.state['accepted_unknown_requests']) == 2 and len(g.state['reservations']) == 1
    assert not g.state['charges']


@pytest.mark.parametrize('extra', [{'choices': []}, {'choices': [{'delta': {'content': 'output'}}]},
    {'text': 'output'}, {'tool_calls': [{}]}, {'usage': USAGE}, {'usage': {**USAGE, 'credit': 1}},
    {'credit': 1}, {'status': 429.0}, {'status': '429'}, {'title': 'unobserved error'}])
def test_http429_extra_output_usage_credit_or_unobserved_fields_never_retry(tmp_path, monkeypatch, extra):
    raw = json.dumps({**json.loads(HTTP429), **extra}).encode()
    g, calls, waits = setup_http429(tmp_path, monkeypatch, [(429, raw)])
    with pytest.raises(budget.BudgetStop):
        asyncio.run(run(g, tmp_path))
    assert len(calls) == 1 and not waits and g.stopped
    assert g.overload_recovery.state['retries'] == 0 and g.state['reservations']
    assert not g.state['charges'] and not g.state.get('accepted_unknown_requests')


@pytest.mark.parametrize('raw', [b'', HTTP429[:-1], HTTP429 + b' extra',
    b'data: ' + HTTP429 + b'\n\ndata: [DONE]\n\n',
    b'{"status":429,"title":"unobserved","title":"Too Many Requests"}'])
def test_http429_incomplete_sse_or_duplicate_envelope_never_retries(tmp_path, monkeypatch, raw):
    g, calls, waits = setup_http429(tmp_path, monkeypatch, [(429, raw)])
    with pytest.raises(budget.BudgetStop):
        asyncio.run(run(g, tmp_path))
    assert len(calls) == 1 and not waits and g.overload_recovery.state['retries'] == 0
    assert g.state['reservations'] and not g.state['charges']


def test_interrupted_http429_body_cannot_use_complete_response_exception(tmp_path, monkeypatch):
    g, calls, waits = setup_http429(tmp_path, monkeypatch, [])

    class Interrupted(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield HTTP429
            raise httpx.ReadError('after complete-looking body but before stream EOF')

    def handle(request):
        calls.append(request.content)
        return httpx.Response(429, headers={'content-type': 'application/json'}, stream=Interrupted())

    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', lambda: httpx.MockTransport(handle))
    with pytest.raises(budget.BudgetStop):
        asyncio.run(run(g, tmp_path))
    assert len(calls) == 1 and not waits and g.overload_recovery.state['retries'] == 0
    row, = [json.loads(line) for line in (tmp_path / 'tape.jsonl').read_text().splitlines()]
    assert row['status'] == 0 and row['upstream_http_status'] == 429 and row['transport_error'] == 'ReadError'
    assert g.state['reservations'] and not g.state['charges']


def test_http429_preserves_carried_208_requests_four_retries_tickets_and_unknown_history(tmp_path, monkeypatch):
    g, calls, waits = setup_http429(tmp_path, monkeypatch, [(429, HTTP429), SUCCESS])
    old_unknown = {'key': 'prior-429', 'reason': 'prior stopped cohort; unknown usage', 'retry_ticket': None}
    old_ticket = {'request_sha256': 'b' * 64, 'round_ledger': 'prior-dev.json', 'reservation': 'prior',
                  'delay_s': 60, 'ready_at': 0, 'status': 'sent'}
    with g._change() as state:
        state.update(requests=208, calls=204, accepted_unknown_requests=[old_unknown])
    with g.overload_recovery._change() as state:
        state.update(retries=4, tickets={'prior-ticket': old_ticket}, request_retries={'b' * 64: 1},
                     carried_from_sha256='a' * 64)
    asyncio.run(run(g, tmp_path))
    assert len(calls) == 2 and waits == [60]
    assert g.state['requests'] == 210 and g.state['calls'] == 205 and g.state['request_limit'] == 480
    assert g.state['accepted_unknown_requests'][0] == old_unknown
    restored = budget.NvidiaOverloadRecovery(tmp_path / 'recovery.json', **V5_OPTIONS)
    assert restored.state['retries'] == 5 and restored.state['pending'] is None
    assert restored.state['tickets']['prior-ticket'] == old_ticket
    assert restored.state['request_retries']['b' * 64] == 1
    assert restored.state['carried_from_sha256'] == 'a' * 64


def test_http429_cannot_exceed_the_shared_ten_retry_allowance(tmp_path, monkeypatch):
    g, calls, waits = setup_http429(tmp_path, monkeypatch, [(429, HTTP429)])
    with g.overload_recovery._change() as state:
        state['retries'] = 10
    with pytest.raises(budget.BudgetStop, match='shared'):
        asyncio.run(run(g, tmp_path))
    assert len(calls) == 1 and not waits and g.overload_recovery.state['retries'] == 10
    assert g.state['reservations'] and not g.state['charges']


def test_http429_wait_cancellation_retains_pending_ticket_and_stops(tmp_path, monkeypatch):
    g, calls, waits = setup_http429(tmp_path, monkeypatch, [(429, HTTP429)])

    async def cancel(seconds):
        waits.append(seconds)
        raise asyncio.CancelledError()

    monkeypatch.setattr(asyncio, 'sleep', cancel)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run(g, tmp_path))
    assert len(calls) == 1 and waits == [60] and g.stopped and g.overload_recovery.stopped
    restored = budget.NvidiaOverloadRecovery(tmp_path / 'recovery.json', **V5_OPTIONS)
    assert restored.stopped and restored.state['retries'] == 1 and restored.state['pending']


def test_http429_policy_requires_the_complete_v4_policy(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='HTTP429.*HTTP500'):
        guard(tmp_path, monkeypatch, recover_complete_http_429_errors=True)
    with pytest.raises(ValueError, match='HTTP429.*HTTP500'):
        budget.NvidiaOverloadRecovery(tmp_path / 'recovery.json', complete_http_429_errors=True)


@pytest.mark.parametrize('old_v5', [False, True])
def test_http429_recovery_policy_cannot_upgrade_or_downgrade_a_ledger_in_place(tmp_path, old_v5):
    options = {**V5_OPTIONS, 'complete_http_429_errors': old_v5}
    path = tmp_path / 'recovery.json'
    budget.NvidiaOverloadRecovery(path, **options)
    original = path.read_bytes()
    options['complete_http_429_errors'] = not old_v5
    with pytest.raises(ValueError, match='configuration changed'):
        budget.NvidiaOverloadRecovery(path, **options)
    assert path.read_bytes() == original


def test_http429_cli_requires_explicit_http500_policy_before_config(tmp_path, monkeypatch, capsys):
    module = run_module()
    monkeypatch.setattr(module, 'load_llm_config', lambda: pytest.fail('invalid v5 reached config'))
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(tmp_path / 'out'),
                                    '--nvidia-recover-complete-http-429'])
    with pytest.raises(SystemExit) as failure:
        module.main()
    assert failure.value.code == 2
    assert 'HTTP429 recovery requires' in capsys.readouterr().err


def test_http429_cli_forwards_v5_and_480_to_real_guard_and_run_metadata(tmp_path, monkeypatch):
    module = run_module()
    monkeypatch.setattr(module, 'load_llm_config', lambda: SimpleNamespace(provider_id='nvidia-nemotron-free',
        base_url=BASE, model=MODEL, is_configured=lambda: True))
    monkeypatch.setattr(module, 'dev_tasks', lambda: [SimpleNamespace(id='panel_fe.specific')])
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda _: SimpleNamespace(free=1))
    monkeypatch.setattr(module, '_seed', lambda *a: pytest.fail('offline storage stop reached model setup'))
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(tmp_path / 'out'), '--mode', 'auto',
        '--tasks', 'panel_fe.specific', '--nvidia-free-ledger', str(tmp_path / 'dev.json'),
        '--nvidia-free-round', 'dev8', '--nvidia-free-request-limit', '480',
        '--nvidia-overload-recovery-ledger', str(tmp_path / 'recovery.json'),
        '--nvidia-recover-unanswered-read-error', '--nvidia-recover-unanswered-protocol-error',
        '--nvidia-recover-complete-http-500', '--nvidia-recover-complete-http-429'])
    assert module.main() == 86
    state = json.loads((tmp_path / 'dev.json').read_text())
    assert state['request_limit'] == 480 and state['requests'] == 0
    recovery = json.loads((tmp_path / 'recovery.json').read_text())
    assert recovery['schema'] == 'nvidia-overload-recovery/v5' and recovery['complete_http_429_errors'] is True
    meta = json.loads((tmp_path / 'out/run_meta.json').read_text())['nvidia_free_endpoint']
    assert meta['recover_complete_http_429_errors'] is True
    assert meta['overload_recovery_schema'] == 'nvidia-overload-recovery/v5'
    assert 'complete error-only HTTP429 JSON' in meta['overload_recovery']['eligibility']
