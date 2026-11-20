"""Offline configurable NVIDIA shared recovery cap; never migrate a live ledger."""
import copy
import json
import sys
from types import SimpleNamespace

import pytest

from tests.test_agent_eval_nvidia_guard import BASE, BODY, MODEL, available_test_storage, guard, run_module
from agent_eval import budget


def recovery(tmp_path, monkeypatch, *, retry_limit=10, name='recovery.json'):
    now = [1000.0]
    monkeypatch.setattr(budget.time, 'time', lambda: now[0])
    return budget.NvidiaOverloadRecovery(tmp_path / name, retry_limit=retry_limit), now


def consume(shared, now, ident):
    request = f'{ident:064x}'
    retry = shared.claim(request, round_ledger='offline-round.json', reservation=f'offline-{ident}')
    now[0] += retry.delay_s
    shared.ready(retry.ticket)
    shared.before_send(request, retry.ticket)
    return retry


def test_default_shared_retry_limit_stays_ten(tmp_path, monkeypatch):
    shared, now = recovery(tmp_path, monkeypatch)
    for ident in range(10):
        consume(shared, now, ident)
    with pytest.raises(budget.BudgetStop, match='shared'):
        shared.claim('f' * 64, round_ledger='offline', reservation='eleventh')
    assert shared.state['retry_limit'] == shared.state['retries'] == 10


def test_new_ledger_can_carry_ten_used_tickets_then_stop_at_explicit_thirty(tmp_path, monkeypatch):
    old, now = recovery(tmp_path, monkeypatch, name='old.json')
    for ident in range(10):
        consume(old, now, ident)
    with pytest.raises(budget.BudgetStop):
        old.claim('e' * 64, round_ledger='offline', reservation='old-stop')
    old_bytes = old.path.read_bytes()
    original = old.state
    derived = copy.deepcopy(original)
    # Synthetic future-authorized new round only; the original remains stopped.
    derived.update(retry_limit=30, stopped=False, reason=None,
                   historical_stop={'reason': original['reason'], 'source': str(old.path)},
                   carried_from_sha256='a' * 64)
    path = tmp_path / 'new.json'
    path.write_text(json.dumps(derived))
    shared = budget.NvidiaOverloadRecovery(path, retry_limit=30)
    assert shared.state['retries'] == 10 and shared.state['pending'] is None
    assert shared.state['tickets'] == original['tickets']
    assert shared.state['request_retries'] == original['request_retries']
    for ident in range(10, 30):
        consume(shared, now, ident)
    restored = budget.NvidiaOverloadRecovery(path, retry_limit=30)
    with pytest.raises(budget.BudgetStop, match='shared'):
        restored.claim('f' * 64, round_ledger='offline', reservation='thirty-first')
    assert restored.state['retries'] == restored.state['retry_limit'] == 30
    assert restored.state['carried_from_sha256'] == 'a' * 64
    assert old.path.read_bytes() == old_bytes and old.stopped


@pytest.mark.parametrize('retry_limit', [None, 0, -1, True, False, 1.5, '30'])
def test_shared_retry_limit_must_be_positive_integer(tmp_path, monkeypatch, retry_limit):
    with pytest.raises(ValueError, match='retry limit.*positive integer'):
        recovery(tmp_path, monkeypatch, retry_limit=retry_limit)
    assert not (tmp_path / 'recovery.json').exists()


@pytest.mark.parametrize('old_limit,new_limit', [(10, 30), (30, 10)])
def test_existing_shared_retry_limit_cannot_change_in_place(tmp_path, monkeypatch, old_limit, new_limit):
    shared, _ = recovery(tmp_path, monkeypatch, retry_limit=old_limit)
    original = shared.path.read_bytes()
    with pytest.raises(ValueError, match='configuration changed'):
        budget.NvidiaOverloadRecovery(shared.path, retry_limit=new_limit)
    assert shared.path.read_bytes() == original


@pytest.mark.parametrize('retry_limit,persisted', [(30, 30.0), (1, True)])
def test_persisted_shared_limit_must_be_integer_even_when_equal(tmp_path, monkeypatch, retry_limit, persisted):
    shared, _ = recovery(tmp_path, monkeypatch, retry_limit=retry_limit)
    state = shared.state
    state['retry_limit'] = persisted
    shared.path.write_text(json.dumps(state))
    original = shared.path.read_bytes()
    with pytest.raises(ValueError, match='configuration changed'):
        budget.NvidiaOverloadRecovery(shared.path, retry_limit=retry_limit)
    assert shared.path.read_bytes() == original


def test_custom_shared_limit_keeps_two_per_request_and_60_120_delays(tmp_path, monkeypatch):
    shared, now = recovery(tmp_path, monkeypatch, retry_limit=30)
    assert consume(shared, now, 1).delay_s == 60
    assert consume(shared, now, 1).delay_s == 120
    with pytest.raises(budget.BudgetStop, match='per-request'):
        shared.claim(f'{1:064x}', round_ledger='offline', reservation='third')
    assert shared.state['retries'] == 2 and len(shared.state['tickets']) == 2


def test_manual_restart_uses_the_same_custom_shared_limit(tmp_path, monkeypatch):
    shared, _ = recovery(tmp_path, monkeypatch, retry_limit=30)
    for index in range(30):
        shared.record_manual_restart(source_path=f'offline-{index}', reason='synthetic approved restart')
    shared.record_manual_restart(source_path='offline-0', reason='synthetic approved restart')
    with pytest.raises(budget.BudgetStop, match='shared'):
        shared.record_manual_restart(source_path='offline-30', reason='synthetic approved restart')
    assert shared.state['retries'] == 30 and len(shared.state['manual_restarts']) == 30


def test_custom_shared_limit_does_not_release_unknown_stop_or_reset_request_counters(tmp_path, monkeypatch):
    options = {'request_limit': 480, 'shared_retry_limit': 30,
               'overload_recovery_ledger': tmp_path / 'recovery.json'}
    g, _ = guard(tmp_path, monkeypatch, **options)
    with g._change() as state:
        state.update(requests=237, calls=226, historical_unsettled_requests={'prior': {'unknown': True}})
    again, _ = guard(tmp_path, monkeypatch, **options)
    assert again.state['requests'] == 237 and again.state['calls'] == 226
    assert again.overload_recovery.state['retry_limit'] == 30
    key = again.reserve(json.dumps(BODY).encode())
    with pytest.raises(budget.BudgetStop):
        again.settle(key, None)
    original = again.path.read_bytes()
    stopped, _ = guard(tmp_path, monkeypatch, **options)
    assert stopped.stopped and key in stopped.state['reservations']
    assert stopped.state['historical_unsettled_requests'] == {'prior': {'unknown': True}}
    assert stopped.path.read_bytes() == original


@pytest.mark.parametrize('retry_limit', [0, -1, True, 1.5, '30'])
def test_guard_rejects_invalid_shared_limit(tmp_path, monkeypatch, retry_limit):
    with pytest.raises(ValueError, match='retry limit.*positive integer'):
        guard(tmp_path, monkeypatch, shared_retry_limit=retry_limit,
              overload_recovery_ledger=tmp_path / 'recovery.json')


def test_guard_custom_shared_limit_requires_recovery_ledger(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match='shared retry limit requires'):
        guard(tmp_path, monkeypatch, shared_retry_limit=30)


@pytest.mark.parametrize('extra', [[], ['--free-route-ledger', 'offline-magpie.json'],
    ['--mode', 'auto', '--nvidia-free-ledger', 'offline-dev.json', '--nvidia-free-round', 'dev8']])
def test_cli_shared_limit_requires_nvidia_recovery_before_config(tmp_path, monkeypatch, capsys, extra):
    module = run_module()
    monkeypatch.setattr(module, 'load_llm_config', lambda: pytest.fail('invalid shared limit reached config'))
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(tmp_path / 'out'),
                                    '--nvidia-shared-retry-limit', '30', *extra])
    with pytest.raises(SystemExit) as failure:
        module.main()
    assert failure.value.code == 2
    assert 'shared retry limit requires' in capsys.readouterr().err


@pytest.mark.parametrize('limit', ['0', '-1', '1.5'])
def test_cli_shared_limit_rejects_bad_values_without_provider_config(tmp_path, monkeypatch, limit):
    module = run_module()
    monkeypatch.setattr(module, 'load_llm_config', lambda: pytest.fail('invalid shared limit reached config'))
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(tmp_path / 'out'), '--mode', 'auto',
        '--nvidia-free-ledger', str(tmp_path / 'dev.json'), '--nvidia-free-round', 'dev8',
        '--nvidia-overload-recovery-ledger', str(tmp_path / 'recovery.json'), '--nvidia-shared-retry-limit', limit])
    with pytest.raises(SystemExit) as failure:
        module.main()
    assert failure.value.code == 2
    assert not (tmp_path / 'recovery.json').exists()


@pytest.mark.parametrize('limit', [None, 30])
def test_cli_passes_shared_limit_to_guard_and_persistent_run_metadata(tmp_path, monkeypatch, limit):
    module = run_module()
    monkeypatch.setattr(module, 'load_llm_config', lambda: SimpleNamespace(provider_id='nvidia-nemotron-free',
        base_url=BASE, model=MODEL, is_configured=lambda: True))
    monkeypatch.setattr(module, 'dev_tasks', lambda: [SimpleNamespace(id='panel_fe.specific')])
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda _: SimpleNamespace(free=1))
    monkeypatch.setattr(module, '_seed', lambda *a: pytest.fail('offline storage stop reached setup'))
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(tmp_path / 'out'), '--mode', 'auto',
        '--tasks', 'panel_fe.specific', '--nvidia-free-ledger', str(tmp_path / 'dev.json'), '--nvidia-free-round', 'dev8',
        '--nvidia-overload-recovery-ledger', str(tmp_path / 'recovery.json'), '--nvidia-recover-unanswered-read-error',
        '--nvidia-recover-unanswered-protocol-error', '--nvidia-recover-complete-http-500',
        '--nvidia-recover-complete-http-429', *([] if limit is None else ['--nvidia-shared-retry-limit', str(limit)])])
    assert module.main() == 86
    state = json.loads((tmp_path / 'recovery.json').read_text())
    expected = 10 if limit is None else limit
    assert state['retry_limit'] == expected and state['retries'] == 0
    meta = json.loads((tmp_path / 'out/run_meta.json').read_text())['nvidia_free_endpoint']
    assert meta['overload_recovery']['shared_retry_limit'] == expected
    assert meta['overload_recovery']['per_request_retry_limit'] == 2
    assert meta['overload_recovery']['delays_s'] == [60, 120]
