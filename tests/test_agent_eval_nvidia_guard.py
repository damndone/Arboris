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


@pytest.fixture(autouse=True)
def available_test_storage(monkeypatch):
    monkeypatch.setattr(budget.shutil, 'disk_usage', lambda root: SimpleNamespace(free=6_000_000_000))


def guard(tmp_path, monkeypatch, **kw):
    now = [1000.0]
    monkeypatch.setattr(budget.time, 'time', lambda: now[0])
    monkeypatch.setattr(budget.time, 'sleep', lambda seconds: now.__setitem__(0, now[0] + seconds))
    return budget.NvidiaFreeEndpointGuard(tmp_path / 'ledger.json', provider_id='nvidia-nemotron-free',
        base_url=BASE, model=MODEL, round_kind='dev8', **kw), now


def test_nvidia_guard_is_explicit_and_pins_entire_route(tmp_path):
    cls = getattr(budget, 'NvidiaFreeEndpointGuard', None)
    assert cls is not None, 'missing independent NVIDIA endpoint guard'
    for field, value in [('provider_id', 'magpie-workbuddy-ai'), ('base_url', BASE + '/wrong'),
                         ('model', 'nvidia/nemotron-super'), ('round_kind', 'heldout')]:
        args = dict(provider_id='nvidia-nemotron-free', base_url=BASE, model=MODEL, round_kind='dev8')
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


def test_cli_builds_nvidia_guard_before_task_setup_and_keeps_billing_unknown(tmp_path, monkeypatch):
    module = run_module()
    config = SimpleNamespace(provider_id='nvidia-nemotron-free', base_url=BASE, model=MODEL,
        is_configured=lambda: True)
    monkeypatch.setattr(module, 'load_llm_config', lambda: config)
    monkeypatch.setattr(module, 'dev_tasks', lambda: [SimpleNamespace(id='iv_weak.goal')])
    monkeypatch.setattr(module.shutil, 'disk_usage', lambda root: SimpleNamespace(free=1))
    monkeypatch.setattr(module, '_seed', lambda *a: pytest.fail('must stop before setup'))
    monkeypatch.setattr(sys, 'argv', ['agent_eval_run.py', '--out', str(tmp_path / 'run'),
        '--tasks', 'iv_weak.goal', '--mode', 'ask', '--nvidia-free-ledger', str(tmp_path / 'ledger.json'),
        '--nvidia-free-round', 'dev8'])
    assert module.main() == 86
    state = json.loads((tmp_path / 'ledger.json').read_text())
    assert state['request_limit'] == 240 and state['requests'] == 0
    meta = json.loads((tmp_path / 'run/run_meta.json').read_text())
    assert meta['nvidia_free_endpoint']['billing_status'].startswith('unknown')
    assert meta['nvidia_free_endpoint']['default_output_limit'] == 'provider_default_unverified'


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
        '--nvidia-free-round', 'dev8', '--allow-low-space-this-round'])
    assert module.main() == 86
    assert captured['allow_low_space_this_round'] is True


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
