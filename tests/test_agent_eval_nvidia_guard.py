"""Offline NVIDIA endpoint authorization, durable request limits, and fail-closed transport."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from agent_eval import budget
from agent_eval.recorder import _RecordingTransport, _Tape

BASE = 'https://integrate.api.nvidia.com/v1'
MODEL = 'nvidia/nemotron-3-ultra-550b-a55b'
BODY = {'model': MODEL, 'max_tokens': 8192}
USAGE = {'prompt_tokens': 20, 'completion_tokens': 3}
PARTIAL = b'data: {"choices":[{"delta":{"content":"partial public answer"},"finish_reason":null}]}\n\n'


@pytest.fixture(autouse=True)
def available_test_storage(monkeypatch):
    monkeypatch.setattr(budget.shutil, 'disk_usage', lambda root: SimpleNamespace(free=6_000_000_000))


def guard(tmp_path, monkeypatch, **kw):
    now = [1000.0]
    monkeypatch.setattr(budget.time, 'time', lambda: now[0])
    monkeypatch.setattr(budget.time, 'sleep', lambda seconds: now.__setitem__(0, now[0] + seconds))
    return budget.NvidiaFreeEndpointGuard(tmp_path / 'ledger.json', provider_id='nvidia-nemotron-free',
        base_url=BASE, model=MODEL, round_kind='dev8', **kw), now


@pytest.mark.parametrize('request_limit', [None, 480])
def test_nvidia_guard_is_explicit_and_pins_entire_route(tmp_path, request_limit):
    cls = getattr(budget, 'NvidiaFreeEndpointGuard', None)
    assert cls is not None, 'missing independent NVIDIA endpoint guard'
    for field, value in [('provider_id', 'magpie-workbuddy-ai'), ('base_url', BASE + '/wrong'),
                         ('model', 'nvidia/nemotron-super'), ('round_kind', 'heldout')]:
        args = dict(provider_id='nvidia-nemotron-free', base_url=BASE, model=MODEL, round_kind='dev8',
                    request_limit=request_limit)
        args[field] = value
        with pytest.raises(ValueError):
            cls(tmp_path / field, **args)


def test_durable_request_limit_counts_reservations_and_restart(tmp_path, monkeypatch):
    g, now = guard(tmp_path, monkeypatch)
    starts = []
    for _ in range(240):
        key = g.reserve(json.dumps(BODY).encode())
        starts.append(now[0])
        g.settle(key, USAGE)
    assert min(b - a for a, b in zip(starts, starts[1:])) >= 2
    again, _ = guard(tmp_path, monkeypatch)
    with pytest.raises(budget.BudgetStop, match='request limit'):
        again.reserve(json.dumps(BODY).encode())
    assert again.state['requests'] == 240 and again.stopped
    assert again.state['billing_status'] == 'unknown; free-listed endpoint is not billing certification'
    assert all('credit' not in item['usage'] for item in again.state['charges'])


def test_explicit_request_limit_survives_restart_and_caps_total_at_480(tmp_path, monkeypatch):
    g, now = guard(tmp_path, monkeypatch, request_limit=480)
    starts = []
    for _ in range(241):
        key = g.reserve(json.dumps(BODY).encode())
        starts.append(now[0])
        g.settle(key, USAGE)
    assert g.state['requests'] == g.state['calls'] == 241
    g, now = guard(tmp_path, monkeypatch, request_limit=480)
    assert g.state['requests'] == g.state['calls'] == 241
    for _ in range(239):
        key = g.reserve(json.dumps(BODY).encode())
        starts.append(now[0])
        g.settle(key, USAGE)
    with pytest.raises(budget.BudgetStop, match='request limit'):
        g.reserve(json.dumps(BODY).encode())
    assert g.state['request_limit'] == g.state['requests'] == g.state['calls'] == 480
    assert len(g.state['charges']) == 480 and not g.state['reservations']
    assert min(b - a for a, b in zip(starts, starts[1:])) >= 2


@pytest.mark.parametrize('request_limit', [0, -1, True, False, 1.5, '480'])
def test_explicit_request_limit_requires_a_positive_integer(tmp_path, monkeypatch, request_limit):
    with pytest.raises(ValueError, match='request limit.*positive integer'):
        guard(tmp_path, monkeypatch, request_limit=request_limit)
    assert not (tmp_path / 'ledger.json').exists()


@pytest.mark.parametrize('reopened_limit', [None, 240, 479])
def test_explicit_request_limit_must_match_persisted_ledger(tmp_path, monkeypatch, reopened_limit):
    g, _ = guard(tmp_path, monkeypatch, request_limit=480)
    key = g.reserve(json.dumps(BODY).encode())
    g.settle(key, USAGE)
    original = g.path.read_bytes()
    with pytest.raises(ValueError, match='ledger configuration changed'):
        guard(tmp_path, monkeypatch, request_limit=reopened_limit)
    assert g.path.read_bytes() == original
    again, _ = guard(tmp_path, monkeypatch, request_limit=480)
    assert again.state['requests'] == again.state['calls'] == 1


@pytest.mark.parametrize('request_limit,persisted_limit', [(480, 480.0), (1, True)])
def test_persisted_request_limit_requires_integer_even_when_equal(tmp_path, monkeypatch, request_limit, persisted_limit):
    g, _ = guard(tmp_path, monkeypatch, request_limit=request_limit)
    state = g.state
    state['request_limit'] = persisted_limit
    g.path.write_text(json.dumps(state))
    original = g.path.read_bytes()
    with pytest.raises(ValueError, match='ledger configuration changed'):
        guard(tmp_path, monkeypatch, request_limit=request_limit)
    assert g.path.read_bytes() == original


def test_custom_request_limit_keeps_unknown_usage_stop_on_restart(tmp_path, monkeypatch):
    g, _ = guard(tmp_path, monkeypatch, request_limit=480)
    key = g.reserve(json.dumps(BODY).encode())
    with pytest.raises(budget.BudgetStop):
        g.settle(key, None)
    original = g.path.read_bytes()
    again, _ = guard(tmp_path, monkeypatch, request_limit=480)
    assert again.stopped and again.state['requests'] == 1
    assert key in again.state['reservations'] and again.state['charges'] == []
    with pytest.raises(budget.BudgetStop):
        again.reserve(json.dumps(BODY).encode())
    assert again.path.read_bytes() == original


@pytest.mark.parametrize('body', [{}, {'model': 'wrong', 'max_tokens': 1},
    {'model': MODEL, 'max_tokens': 0}, {'model': MODEL, 'max_tokens': True},
    {'model': MODEL, 'max_tokens': 32769}, {'model': MODEL, 'max_tokens': 10, 'max_completion_tokens': 32769}])
def test_actual_request_model_and_output_bound_fail_closed(tmp_path, monkeypatch, body):
    g, _ = guard(tmp_path, monkeypatch)
    with pytest.raises(budget.BudgetStop):
        g.reserve(json.dumps(body).encode())
    assert g.stopped and g.state['requests'] == 0


@pytest.mark.parametrize('usage', [None, {}, {'prompt_tokens': 1},
    {'prompt_tokens': True, 'completion_tokens': 1}, {**USAGE, 'credit': 1}, {**USAGE, 'credit': None}])
def test_unknown_usage_or_credit_stops_and_retains_unsettled_request(tmp_path, monkeypatch, usage):
    g, _ = guard(tmp_path, monkeypatch)
    key = g.reserve(json.dumps(BODY).encode())
    with pytest.raises(budget.BudgetStop):
        g.settle(key, usage)
    assert g.stopped and key in g.state['reservations'] and g.state['requests'] == 1


def test_overlapping_request_is_refused(tmp_path, monkeypatch):
    g, _ = guard(tmp_path, monkeypatch)
    g.reserve(json.dumps(BODY).encode())
    with pytest.raises(budget.BudgetStop, match='unsettled'):
        g.reserve(json.dumps(BODY).encode())
    assert g.state['requests'] == 1


def test_explicit_incomplete_stream_skip_fails_only_task_without_retry_or_zero_settlement(tmp_path,monkeypatch):
    from agent_eval.recorder import provider_tape
    from workbench.agent.model import ModelRequest, OpenAICompatibleModelAdapter
    from workbench.llm.config import LLMConfig
    g,_=guard(tmp_path,monkeypatch,skip_incomplete_stream_task=True)
    calls=[];events=[]
    def handle(request):
        calls.append(request.content)
        return httpx.Response(200,headers={'content-type':'text/event-stream'},content=PARTIAL)
    monkeypatch.setattr(httpx,'AsyncHTTPTransport',lambda:httpx.MockTransport(handle))
    async def run():
        with provider_tape(tmp_path/'tape.jsonl',budget=g):
            adapter=OpenAICompatibleModelAdapter(LLMConfig(base_url=BASE,api_key='offline',model=MODEL,provider_id='nvidia-nemotron-free'))
            async for event in adapter.stream(ModelRequest(messages=[{'role':'user','content':'offline partial task'}])):events.append(event)
    with pytest.raises(budget.TaskStop,match='incomplete stream'):asyncio.run(run())
    assert len(calls)==1 and all(e.type not in {'done','tool_call'} for e in events)
    state=g.state
    assert not state['stopped'] and state['requests']==1 and state['calls']==0 and not state['reservations']
    assert len(state['accepted_unknown_requests'])==1 and state['charges']==[]
    assert state['accepted_unknown_requests'][0]['retry_ticket'] is None
    key=g.reserve(json.dumps({**BODY,'messages':[{'role':'user','content':'a different task'}]}).encode())
    g.settle(key,USAGE)
    assert g.state['requests']==2 and g.state['calls']==1


@pytest.mark.parametrize('raw',[PARTIAL+b'data: [DONE]\n\n',
    PARTIAL+b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
    PARTIAL+b'data: {"choices":[],"usage":{"credit":1}}\n\n',
    PARTIAL+b'data: {"error":{"message":"failure"}}\n\n',
    PARTIAL+b'data: invalid-json\n\n',
    b'data: {"choices":[{"delta":{"tool_calls":[{}]},"finish_reason":null}]}\n\n'])
def test_incomplete_skip_does_not_release_other_accounting_or_protocol_errors(tmp_path,monkeypatch,raw):
    g,_=guard(tmp_path,monkeypatch,skip_incomplete_stream_task=True)
    async def run():
        transport=_RecordingTransport(_Tape(tmp_path/'tape.jsonl','record'),
            httpx.MockTransport(lambda request:httpx.Response(200,headers={'content-type':'text/event-stream'},content=raw)),budget=g)
        async with httpx.AsyncClient(transport=transport) as client:
            await client.post(BASE+'/chat/completions',json=BODY)
    with pytest.raises(budget.BudgetStop):asyncio.run(run())
    assert g.stopped and len(g.state['reservations'])==1


def test_incomplete_skip_policy_is_pinned_to_new_ledger(tmp_path,monkeypatch):
    g,_=guard(tmp_path,monkeypatch,skip_incomplete_stream_task=True);before=g.path.read_bytes()
    with pytest.raises(ValueError,match='incomplete-stream policy'):guard(tmp_path,monkeypatch)
    assert g.path.read_bytes()==before


@pytest.mark.parametrize('status', [201, 302, 400, 429, 500])
def test_every_non_200_stops_even_with_valid_usage(tmp_path, monkeypatch, status):
    g, _ = guard(tmp_path, monkeypatch)
    calls = []
    async def scenario():
        transport = _RecordingTransport(_Tape(tmp_path / 'tape.jsonl', 'record'),
            httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(status, json={'usage': USAGE})), budget=g)
        async with httpx.AsyncClient(transport=transport) as client:
            for _ in range(2):
                with pytest.raises(budget.BudgetStop):
                    await client.post(BASE + '/chat/completions', json=BODY)
    asyncio.run(scenario())
    assert len(calls) == 1 and g.stopped
    assert g.state['reservations'] and g.state['charges'] == []


@pytest.mark.parametrize('url', ['https://paid.invalid/v1/chat/completions', BASE + '/wrong'])
def test_actual_url_is_checked_before_transport(tmp_path, monkeypatch, url):
    g, _ = guard(tmp_path, monkeypatch)
    async def scenario():
        transport = _RecordingTransport(_Tape(tmp_path / 'tape.jsonl', 'record'),
            httpx.MockTransport(lambda request: pytest.fail('wrong route reached transport')), budget=g)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(budget.BudgetStop):
                await client.post(url, json=BODY)
    asyncio.run(scenario())
    assert g.stopped and g.state['requests'] == 0


@pytest.mark.parametrize('error', [httpx.ReadTimeout, httpx.ConnectError])
def test_timeout_or_connection_failure_stops_entire_round(tmp_path, monkeypatch, error):
    g, _ = guard(tmp_path, monkeypatch)
    def fail(request):
        raise error('offline', request=request)
    async def scenario():
        transport = _RecordingTransport(_Tape(tmp_path / 'tape.jsonl', 'record'), httpx.MockTransport(fail), budget=g)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(budget.BudgetStop):
                await client.post(BASE + '/chat/completions', json=BODY)
    asyncio.run(scenario())
    assert g.stopped and g.state['requests'] == 1
    assert g.state['billing_status'].startswith('unknown')


def test_qr_round_has_separate_persistent_cap_and_cannot_reuse_dev_ledger(tmp_path, monkeypatch):
    g, _ = guard(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        budget.NvidiaFreeEndpointGuard(g.path, provider_id='nvidia-nemotron-free', base_url=BASE,
            model=MODEL, round_kind='qrdata40')
    qr = budget.NvidiaFreeEndpointGuard(tmp_path / 'qr.json', provider_id='nvidia-nemotron-free',
        base_url=BASE, model=MODEL, round_kind='qrdata40')
    assert qr.state['request_limit'] == 1200


def test_provider_default_output_is_recorded_as_unverified_without_changing_body(tmp_path, monkeypatch):
    g, _ = guard(tmp_path, monkeypatch)
    key = g.reserve(json.dumps({'model': MODEL}).encode())
    assert g.state['reservations'][key]['output_limit'] == 'provider_default_unverified'
    g.settle(key, {**USAGE, 'completion_tokens': 50000})
    assert g.state['charges'][0]['usage']['completion_tokens'] == 50000


def run_module():
    spec = importlib.util.spec_from_file_location('nvidia_guard_cli_test', Path(__file__).resolve().parents[1] / 'scripts/agent_eval_run.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_formal_development_dry_admission_never_loads_provider(tmp_path, monkeypatch, capsys):
    module = run_module()
    monkeypatch.setattr(module, 'load_llm_config', lambda: pytest.fail('dry admission loaded credentials'))
    monkeypatch.setattr(module, '_hold_machine_awake', lambda: pytest.fail('dry admission launched a worker'))
    out = tmp_path / 'new-round'
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(out), '--check-m5-dev-admission'])
    assert module.main() == 0
    scope = json.loads(capsys.readouterr().out)
    assert scope['candidate_sha'] == module._git('rev-parse', 'HEAD')
    assert scope['plan_sha256'] == '27110238a5ef0c02bcbf15ac9f020304e259489584ce405dc7b40e4ce7bd5222'
    assert scope['slot_count'] == 198 and scope['max_requests'] == 11880
    assert scope['launch'] is False and not out.exists()


def test_formal_development_rejects_draft_before_loading_provider(tmp_path, monkeypatch, capsys):
    module = run_module()
    monkeypatch.setattr(module, 'load_llm_config', lambda: pytest.fail('draft reached provider'))
    out, draft = tmp_path / 'round', tmp_path / 'draft.json'
    draft.write_text('{"launch": false}')
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(out),
                                   '--m5-dev-approval-receipt', str(draft)])
    with pytest.raises(SystemExit, match='2'):
        module.main()
    assert 'approval receipt' in capsys.readouterr().err
    assert not out.exists()


def test_formal_development_dispatches_all_slots_with_one_ledger(tmp_path, monkeypatch, capsys):
    from agent_eval import m5_dev_admission as admission

    module = run_module()
    candidate = module._git('rev-parse', 'HEAD')
    monkeypatch.setattr(module, '_git', lambda *args: candidate if args[:2] == ('rev-parse', 'HEAD') else '')
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda root: SimpleNamespace(free=admission.START_FREE_BYTES))
    monkeypatch.setattr(module, '_hold_machine_awake', lambda: None)
    monkeypatch.setattr(module, 'load_llm_config', lambda: SimpleNamespace(
        provider_id=budget.NVIDIA_PROVIDER_ID, base_url=BASE, model=MODEL,
        api_key='fake-key', data_location='remote', reasoning_effort='high', reasoning_efforts=('none', 'high'),
        is_configured=lambda: True))
    monkeypatch.setenv('WORKBENCH_REASONING_EFFORT', 'high')
    monkeypatch.setattr(httpx.AsyncHTTPTransport, '__init__',
                        lambda *a, **kw: pytest.fail('formal dispatch test attempted network'))
    monkeypatch.setattr(module, '_seed', lambda *a: 'fake-run')
    monkeypatch.setattr(module, 'create_project', lambda path, name: SimpleNamespace(root=path / name))
    observed = []

    def run(client, root, run_id, prompt, policy, **kwargs):
        observed.append((policy.mode, root.parent.name))
        permissions = json.loads((root / 'workbench/agent-permissions.json').read_text())
        assert permissions['deny'] == [{'class': 'external'}, {'class': 'high'}]
        return {'completed_marker': False}

    monkeypatch.setattr(module, 'run_conversation', run)
    out, receipt = tmp_path / 'round', tmp_path / 'approval.json'
    slots, _ = admission.frozen_slots(module.dev_tasks())
    approved = {**admission.scope(candidate, out, slots), 'launch': True, 'approval_ref': 'synthetic test'}
    receipt.write_text(json.dumps({**approved, 'max_requests': 11881}))
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(out),
                                   '--m5-dev-approval-receipt', str(receipt)])
    with pytest.raises(SystemExit, match='2'):
        module.main()
    assert 'approval receipt' in capsys.readouterr().err and not out.exists()
    receipt.write_text(json.dumps(approved))
    assert module.main() == 0
    assert observed == [(row['mode'], f"{row['task_id']}.r{row['repeat']}") for row in slots]
    assert len(list(out.glob('*/tasks/*/record.json'))) == 198
    ledger = json.loads((out / 'budget.json').read_text())
    assert ledger['request_limit'] == 11880 and ledger['requests'] == 0
    assert [json.loads(path.read_text())['repeat'] for path in sorted(out.glob('*/run_meta.json'))] == [1, 3, 1, 3]
    with pytest.raises(SystemExit, match='2'):
        module.main()
    assert 'fresh output root' in capsys.readouterr().err


def test_formal_development_rejects_unbounded_output_before_wire(tmp_path, monkeypatch):
    from workbench.llm.config import LLMConfig

    monkeypatch.setenv('WORKBENCH_REASONING_EFFORT', 'high')
    config = LLMConfig(provider_id=budget.NVIDIA_PROVIDER_ID, base_url=BASE, model=MODEL, api_key='fake-key',
                       reasoning_efforts=('none', 'high'))
    guard = budget.M5DevNvidiaGuard(tmp_path / 'budget.json', config=config, serial_path=tmp_path / 'serial.json')
    guard.check_client_config(config)
    with pytest.raises(budget.BudgetStop, match='output policy'):
        guard.reserve(json.dumps({'model': MODEL, 'reasoning_effort': 'high'}).encode())
    assert guard.stopped and guard.state['requests'] == 0


@pytest.mark.parametrize('override', [False, True])
def test_development_auto_probe_uses_the_recorded_execution_policy(tmp_path, monkeypatch, override):
    module = run_module()
    monkeypatch.setattr(module, '_hold_machine_awake', lambda: None)
    monkeypatch.setattr(module, 'load_llm_config', lambda: SimpleNamespace(
        provider_id=budget.NVIDIA_PROVIDER_ID, base_url=BASE, model=MODEL,
        api_key='fake-key', data_location='remote', is_configured=lambda: True))
    monkeypatch.setattr(httpx.AsyncHTTPTransport, '__init__',
                        lambda *a, **kw: pytest.fail('execution policy test attempted network'))
    monkeypatch.setattr(module, '_seed', lambda *a: 'fake-run')
    policies = []

    def run(client, root, run_id, prompt, policy, **kwargs):
        policies.append((policy.mode, policy.execution_policy))
        return {'completed_marker': False}

    monkeypatch.setattr(module, 'run_conversation', run)
    out = tmp_path / 'run'
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(out),
        '--tasks', 'panel_fe.specific', '--mode', 'auto', '--nvidia-free-round', 'dev8',
        '--nvidia-free-ledger', str(tmp_path / 'budget.json'), '--nvidia-free-request-limit', '8',
        *(['--execution-policy', 'auto_read_only'] if override else [])])
    assert module.main() == 0
    expected = 'auto_read_only' if override else 'proposal_only'
    assert policies == [('auto', expected)]
    assert json.loads((out / 'run_meta.json').read_text())['policy']['execution_policy'] == expected


def test_formal_development_refuses_execution_policy_override_before_provider(tmp_path, monkeypatch, capsys):
    module = run_module()
    monkeypatch.setattr(module, 'load_llm_config', lambda: pytest.fail('admission loaded provider'))
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(tmp_path / 'run'),
        '--check-m5-dev-admission', '--execution-policy', 'auto_read_only'])
    with pytest.raises(SystemExit, match='2'):
        module.main()
    assert 'execution policy override is only for development diagnostics' in capsys.readouterr().err


@pytest.mark.parametrize('request_limit', [None, 480])
def test_cli_builds_nvidia_guard_before_task_setup_and_keeps_billing_unknown(tmp_path, monkeypatch, request_limit):
    module = run_module()
    config = SimpleNamespace(provider_id='nvidia-nemotron-free', base_url=BASE, model=MODEL,
        is_configured=lambda: True)
    monkeypatch.setattr(module, 'load_llm_config', lambda: config)
    monkeypatch.setattr(module, 'dev_tasks', lambda: [SimpleNamespace(id='iv_weak.goal')])
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda root: SimpleNamespace(free=1))
    monkeypatch.setattr(module, '_seed', lambda *a: pytest.fail('must stop before setup'))
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(tmp_path / 'run'),
        '--tasks', 'iv_weak.goal', '--mode', 'ask', '--nvidia-free-ledger', str(tmp_path / 'ledger.json'),
        '--nvidia-free-round', 'dev8',
        *([] if request_limit is None else ['--nvidia-free-request-limit', str(request_limit)])])
    assert module.main() == 86
    state = json.loads((tmp_path / 'ledger.json').read_text())
    assert state['request_limit'] == (240 if request_limit is None else request_limit) and state['requests'] == 0
    meta = json.loads((tmp_path / 'run/run_meta.json').read_text())
    assert meta['nvidia_free_endpoint']['request_limit'] == state['request_limit']
    assert meta['nvidia_free_endpoint']['billing_status'].startswith('unknown')
    assert meta['nvidia_free_endpoint']['default_output_limit'] == 'provider_default_unverified'


@pytest.mark.parametrize('extra', [[], ['--free-route-ledger', 'offline-magpie.json'],
                                 ['--round-budget-cny', '1']])
def test_cli_custom_limit_requires_explicit_nvidia_endpoint_before_config(tmp_path, monkeypatch, capsys, extra):
    module = run_module()
    monkeypatch.setattr(module, 'load_llm_config', lambda: pytest.fail('invalid limit reached provider config'))
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(tmp_path / 'run'),
        '--nvidia-free-request-limit', '480', *extra])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
    assert 'request limit requires the explicit NVIDIA endpoint guard' in capsys.readouterr().err


@pytest.mark.parametrize('request_limit', ['0', '-1', '1.5'])
def test_cli_custom_limit_rejects_bad_values_before_config(tmp_path, monkeypatch, request_limit):
    module = run_module()
    monkeypatch.setattr(module, 'load_llm_config', lambda: pytest.fail('invalid limit reached provider config'))
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(tmp_path / 'run'), '--mode', 'ask',
        '--nvidia-free-ledger', str(tmp_path / 'ledger.json'), '--nvidia-free-round', 'dev8',
        '--nvidia-free-request-limit', request_limit])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
    assert not (tmp_path / 'ledger.json').exists()


def test_each_reservation_checks_storage_without_releasing_unknown_usage(tmp_path, monkeypatch):
    g, _ = guard(tmp_path, monkeypatch)
    monkeypatch.setattr(budget.shutil, 'disk_usage', lambda root: SimpleNamespace(free=4_999_999_999))
    with pytest.raises(budget.BudgetStop, match='storage threshold'):
        g.reserve(json.dumps(BODY).encode())
    assert g.stopped and g.state['requests'] == 0
    with pytest.raises(budget.BudgetStop):
        g.resume_storage_stop()


def test_explicit_storage_exception_preserves_unknown_usage_stop_and_policy(tmp_path, monkeypatch):
    g, _ = guard(tmp_path, monkeypatch, allow_low_space_this_round=True)
    monkeypatch.setattr(budget.shutil, 'disk_usage', lambda root: SimpleNamespace(free=1))
    key = g.reserve(json.dumps(BODY).encode())
    assert g.state['allow_low_space_this_round'] is True
    with pytest.raises(budget.BudgetStop):
        g.settle(key, None)
    assert g.stopped and key in g.state['reservations']
    again, _ = guard(tmp_path, monkeypatch, allow_low_space_this_round=True)
    assert again.stopped and again.state['requests'] == 1
    with pytest.raises(ValueError, match='storage policy'):
        guard(tmp_path, monkeypatch)


def test_cli_passes_explicit_storage_exception_to_guard(tmp_path, monkeypatch):
    module = run_module()
    monkeypatch.setattr(module, 'load_llm_config', lambda: SimpleNamespace(
        provider_id='nvidia-nemotron-free', base_url=BASE, model=MODEL, is_configured=lambda: True))
    captured = {}
    def stopped_guard(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(stopped=True, state={'reason': 'retained unknown usage'})
    monkeypatch.setattr(module, 'NvidiaFreeEndpointGuard', stopped_guard)
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(tmp_path / 'run'),
        '--mode', 'ask', '--nvidia-free-ledger', str(tmp_path / 'ledger.json'),
        '--nvidia-free-round', 'dev8', '--allow-low-space-this-round', '--nvidia-skip-incomplete-stream-task'])
    assert module.main() == 86
    assert captured['allow_low_space_this_round'] is True
    assert captured['skip_incomplete_stream_task'] is True


def test_cli_incomplete_skip_requires_explicit_nvidia_endpoint(tmp_path,monkeypatch):
    module=run_module()
    monkeypatch.setattr(module,'load_llm_config',lambda:pytest.fail('invalid skip reached provider config'))
    monkeypatch.setattr(sys,'argv',['agent_eval_run.py','--out',str(tmp_path/'run'),'--nvidia-skip-incomplete-stream-task'])
    with pytest.raises(SystemExit) as exc:module.main()
    assert exc.value.code==2


@pytest.mark.parametrize('extra', [['--suite', 'heldout'], ['--transport', 'http']])
def test_cli_rejects_nvidia_scope_or_storage_bypass_before_provider(tmp_path, monkeypatch, extra):
    module = run_module()
    monkeypatch.setattr(module, 'load_llm_config', lambda: pytest.fail('invalid CLI reached provider config'))
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(tmp_path / 'run'), '--mode', 'ask',
        '--nvidia-free-ledger', str(tmp_path / 'ledger.json'), '--nvidia-free-round', 'dev8', *extra])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2


@pytest.mark.parametrize('streaming', [False, True])
def test_normal_nvidia_usage_without_credit_is_recorded_and_body_is_unchanged(tmp_path, monkeypatch, streaming):
    g, _ = guard(tmp_path, monkeypatch)
    original = {'model': MODEL, 'messages': [{'role': 'user', 'content': 'offline'}]}
    observed = []
    def handle(request):
        observed.append(json.loads(request.content))
        if streaming:
            raw = 'data: ' + json.dumps({'choices': [], 'usage': USAGE}) + '\n\ndata: [DONE]\n\n'
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=raw)
        return httpx.Response(200, json={'choices': [], 'usage': USAGE})
    async def scenario():
        tape = _Tape(tmp_path / 'tape.jsonl', 'record')
        transport = _RecordingTransport(tape, httpx.MockTransport(handle), budget=g)
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.post(BASE + '/chat/completions', json=original)
            assert response.status_code == 200
    asyncio.run(scenario())
    assert observed == [original]
    assert g.state['requests'] == g.state['calls'] == 1 and not g.state['reservations']
    assert g.state['charges'][0]['usage'] == USAGE
    assert g.state['charges'][0]['billing_status'] == 'unknown; credit not reported'


@pytest.mark.parametrize('round_kind,suite,selected', [('dev8', 'dev', 'unapproved'),
    ('qrdata40', 'external', 'blade_fake')])
def test_cli_rejects_tasks_outside_authorized_frozen_scope(tmp_path, monkeypatch, round_kind, suite, selected):
    module = run_module()
    config = SimpleNamespace(provider_id='nvidia-nemotron-free', base_url=BASE, model=MODEL,
        is_configured=lambda: True)
    monkeypatch.setattr(module, 'load_llm_config', lambda: config)
    monkeypatch.setattr(module, 'dev_tasks', lambda: [SimpleNamespace(id=selected)])
    monkeypatch.setattr(module, 'qrdata_subset', lambda: [SimpleNamespace(id='qr_frozen')])
    monkeypatch.setattr(module, 'blade_tasks', lambda: [SimpleNamespace(id='blade_fake')])
    monkeypatch.setattr(module, 'replication_tasks', lambda: [])
    monkeypatch.setattr(module, '_seed', lambda *a: pytest.fail('unauthorized task reached setup'))
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(tmp_path / 'run'), '--mode', 'ask',
        '--tasks', selected, '--suite', suite, '--nvidia-free-ledger', str(tmp_path / 'ledger.json'),
        '--nvidia-free-round', round_kind])
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
    assert not (tmp_path / 'run').exists()


@pytest.mark.parametrize('streaming', [False, True])
def test_http_200_explicit_provider_error_stops_even_with_valid_usage(tmp_path, monkeypatch, streaming):
    g, _ = guard(tmp_path, monkeypatch)
    calls = []
    payload = {'error': {'message': 'provider returned an explicit failure'}, 'usage': USAGE}
    raw = json.dumps(payload).encode()
    content_type = 'application/json'
    if streaming:
        raw = b'data: ' + raw + b'\n\ndata: [DONE]\n\n'
        content_type = 'text/event-stream'
    def handle(request):
        calls.append(request)
        return httpx.Response(200, headers={'content-type': content_type}, content=raw)
    tape = _Tape(tmp_path / 'tape.jsonl', 'record')
    async def scenario():
        transport = _RecordingTransport(tape, httpx.MockTransport(handle), budget=g)
        async with httpx.AsyncClient(transport=transport) as client:
            for _ in range(2):
                with pytest.raises(budget.BudgetStop, match='provider error'):
                    await client.post(BASE + '/chat/completions', json=BODY)
    asyncio.run(scenario())
    assert len(calls) == 1 and g.stopped and g.state['requests'] == 1
    assert g.state['reservations'] and not g.state['charges']
    [record] = [json.loads(line) for line in tape.path.read_text().splitlines()]
    assert record['response_raw'] == raw.decode() and record['usage'] == USAGE


def test_nvidia_product_stream_consumes_usage_tail_and_recorder_settles_once(tmp_path, monkeypatch):
    from agent_eval.recorder import provider_tape
    from workbench.agent.model import ModelRequest, OpenAICompatibleModelAdapter
    from workbench.llm.config import LLMConfig
    g, _ = guard(tmp_path, monkeypatch)
    raw = (Path(__file__).parent / 'fixtures/llm/nvidia_ultra_finish_before_usage.sse').read_bytes()
    closed, calls = [], []
    class ProviderStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield raw
            yield ('data: ' + json.dumps({'choices': [], 'usage': USAGE}) + '\n\n').encode()
            yield b'data: [DONE]\n\n'
        async def aclose(self):
            closed.append(True)
    def handle(request):
        calls.append(request)
        assert json.loads(request.content)['stream_options'] == {'include_usage': True}
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=ProviderStream())
    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', lambda: httpx.MockTransport(handle))
    config = LLMConfig(base_url=BASE, api_key='offline', model=MODEL, provider_id='nvidia-nemotron-free')
    tape_path = tmp_path / 'tape.jsonl'
    async def scenario():
        with provider_tape(tape_path, budget=g):
            adapter = OpenAICompatibleModelAdapter(config)
            async for event in adapter.stream(ModelRequest(messages=[{'role': 'user', 'content': 'offline'}])):
                if event.type == 'done':
                    assert closed == [True] and g.state['calls'] == 1
                    break
    asyncio.run(scenario())
    assert len(calls) == 1 and g.state['requests'] == g.state['calls'] == 1
    assert not g.state['reservations'] and not g.stopped
    assert len(g.state['charges']) == 1 and g.state['charges'][0]['usage'] == USAGE
    [record] = [json.loads(line) for line in tape_path.read_text().splitlines()]
    assert record['status'] == 200 and record['usage'] == USAGE
    assert record['response_raw'].startswith(raw.decode()) and '[DONE]' in record['response_raw']
    assert 'transport_error' not in record


def test_nvidia_sse_overload_preserves_original_error_and_stops_after_taping(tmp_path, monkeypatch):
    from agent_eval.recorder import provider_tape
    from workbench.agent.model import ModelRequest, OpenAICompatibleModelAdapter
    from workbench.llm.config import LLMConfig
    g, _ = guard(tmp_path, monkeypatch)
    # Verbatim final raw response from the stopped panel_fe.specific request.
    raw = b'data: {"error":{"message":"Service temporarily overloaded","type":"service_unavailable","code":503}}\n\ndata: [DONE]\n\n'
    calls = []
    class OverloadStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield raw
    def handle(request):
        calls.append(request)
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=OverloadStream())
    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', lambda: httpx.MockTransport(handle))
    config = LLMConfig(base_url=BASE, api_key='offline', model=MODEL, provider_id='nvidia-nemotron-free')
    tape_path = tmp_path / 'tape.jsonl'
    original_check = g.check_response
    def checked_after_tape(status, body):
        assert tape_path.exists(), 'provider error policy ran before saving raw response'
        original_check(status, body)
    monkeypatch.setattr(g, 'check_response', checked_after_tape)
    async def scenario():
        with provider_tape(tape_path, budget=g):
            for _ in range(2):
                adapter = OpenAICompatibleModelAdapter(config)
                with pytest.raises(budget.BudgetStop, match='provider error.*503.*usage unknown'):
                    async for _ in adapter.stream(ModelRequest(messages=[{'role': 'user', 'content': 'offline'}])):
                        pass
    asyncio.run(scenario())
    assert len(calls) == g.state['requests'] == 1 and g.stopped
    assert g.state['reservations'] and not g.state['charges'] and g.state['calls'] == 0
    [record] = [json.loads(line) for line in tape_path.read_text().splitlines()]
    assert record['status'] == 0 and record['upstream_http_status'] == 200
    assert record['content_type'] == 'text/event-stream'
    assert record['transport_error'] == 'CancelledError'
    assert record['response_raw'] == raw.decode() and record['usage'] is None


def test_under_the_record_and_retry_rule_unknown_usage_is_kept_not_settled_and_credit_still_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, 'ACCEPT_UNKNOWN_USAGE', True)
    guard = budget.NvidiaFreeEndpointGuard(tmp_path / 'ledger.json', provider_id='nvidia-nemotron-free', base_url=BASE,
                                           model=budget.NVIDIA_MODEL, round_kind='dev8')
    with guard._change() as state:
        state['reservations']['k1'] = {'output_bound': 8192}
    guard.settle('k1', None)
    state = guard.state
    assert not state['stopped'] and state['calls'] == 0 and state['charges'] == []
    assert state['accepted_unknown_requests'][0]['key'] == 'k1'
    with guard._change() as state:
        state['reservations']['k2'] = {'output_bound': 8192}
    assert guard.tolerate_transport_interruption('ReadTimeout') is True
    assert [item['key'] for item in guard.state['accepted_unknown_requests']] == ['k1', 'k2']
    with guard._change() as state:
        state['reservations']['k3'] = {'output_bound': 8192}
    with pytest.raises(budget.BudgetStop):
        guard.settle('k3', {'prompt_tokens': 1, 'completion_tokens': 1, 'credit': 0.5})
