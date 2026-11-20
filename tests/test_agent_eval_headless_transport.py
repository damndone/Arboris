"""Evaluator transports share policy actions without model or task fixtures."""
from __future__ import annotations
from workbench.http import agent_route_runtime

import importlib.util
from pathlib import Path
import sys

import pytest


@pytest.fixture
def runner():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'agent_eval' / 'runner.py'
    spec = importlib.util.spec_from_file_location('agent_eval_runner_transport_test', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Response:
    status_code = 200
    headers = {'content-type': 'application/json'}
    def __init__(self, value):
        self.value = value
    def json(self):
        return self.value
    def raise_for_status(self):
        assert self.status_code == 200


@pytest.mark.parametrize('mode', ['legacy', 'ask', 'auto'])
@pytest.mark.parametrize('text', ['Inspect.', None])
def test_headless_uses_actual_entry_and_preserves_request_policy(tmp_path, monkeypatch, runner, mode, text):
    from workbench import cli_agent
    from workbench.http import agent_routes as routes

    calls = []
    seen = []
    monkeypatch.setattr(routes, 'require_agent_session', lambda *args, **kwargs: None)
    monkeypatch.setattr(routes, 'get_agent_events', lambda *args, **kwargs: {
        'events': [] if kwargs.get('after_seq') else [{'seq': 1, 'event_type': 'original_event'}],
    })
    monkeypatch.setattr(routes, 'get_agent_proposals', lambda *args: {'proposals': []})
    monkeypatch.setattr(routes, 'get_agent_plan', lambda *args: {'plan': None})
    async def route(session_id, root, body, *, http_request):
        from workbench.app import app
        assert http_request.app is app
        seen.append(body)
        return {'status': 'idle', 'assistant': {'content': 'ANALYSIS COMPLETE'}}
    monkeypatch.setattr(routes, 'run_agent_turn', route)
    monkeypatch.setattr(routes, 'continue_agent_turn', route)
    original = cli_agent.run_headless if text is not None else cli_agent.continue_headless
    async def entry(*args, **kwargs):
        calls.append(kwargs)
        return await original(*args, **kwargs)
    monkeypatch.setattr(cli_agent, 'run_headless' if text is not None else 'continue_headless', entry)
    result = runner._turn(None, tmp_path, 'session', text, 'proposal_only', mode, transport='headless')
    assert result['reply'] == 'ANALYSIS COMPLETE'
    assert result['transport'] == 'headless' and result['http_status'] is None
    assert result['requested_mode'] == mode
    assert result['execution_mode_request'] == ('server_default' if mode == 'legacy' else mode)
    assert result['raw_events'] == [{'seq': 1, 'event_type': 'original_event'}]
    assert calls[0]['mode'] == (None if mode == 'legacy' else mode)
    assert calls[0]['execution_policy'] == 'proposal_only'
    assert seen[0].execution_policy == 'proposal_only'
    assert seen[0].execution_mode == ('ask' if mode == 'legacy' else mode)
    assert ('execution_mode' in seen[0].model_fields_set) == (mode != 'legacy')


def test_headless_failure_preserves_events_and_never_falls_back(tmp_path, monkeypatch, runner):
    from workbench import cli_agent
    from workbench.api_errors import WorkbenchAPIError
    async def failed(*args, **kwargs):
        kwargs['on_event']({'seq': 2, 'event_type': 'tool_failed', 'payload': {'error': 'original'}})
        raise WorkbenchAPIError(409, 'ORIGINAL_FAILURE', 'Rejected.', {'reason': 'exact'})
    monkeypatch.setattr(cli_agent, 'run_headless', failed)
    class NoHTTP:
        def post(self, *args, **kwargs):
            raise AssertionError('no HTTP fallback')
    result = runner._turn(NoHTTP(), tmp_path, 'session', 'Inspect.', 'proposal_only', 'ask', transport='headless')
    assert result['http_status'] is None
    assert result['status'] == 'transport_error'
    assert result['error']['code'] == 'ORIGINAL_FAILURE'
    assert result['transport_error']['api_status_code'] == 409
    assert result['raw_events'][0]['payload']['error'] == 'original'


def test_http_remains_explicit_and_keeps_legacy_omitted_mode(tmp_path, runner):
    calls = []
    class Client:
        def post(self, path, **kwargs):
            calls.append((path, kwargs))
            return Response({'status': 'idle', 'assistant': {'content': 'original'}})
    result = runner._turn(Client(), tmp_path, 'session', 'Inspect.', 'proposal_only', 'legacy', transport='http')
    assert calls[0][1]['json'] == {'question': 'Inspect.', 'execution_policy': 'proposal_only'}
    assert result['transport'] == 'http' and result['http_status'] == 200
    assert result['reply'] == 'original'


def test_unknown_transport_refuses_before_running_any_entry(tmp_path, runner):
    with pytest.raises(ValueError, match='transport'):
        runner._turn(None, tmp_path, 'session', 'Inspect.', 'proposal_only', 'ask', transport='fallback')


@pytest.mark.parametrize('mode,expected', [
    ('legacy', {'user_actions': 2, 'confirmations': 1, 'nudges': 1, 'continuations': 0, 'plan_approvals': 0}),
    ('ask', {'user_actions': 1, 'confirmations': 1, 'nudges': 0, 'continuations': 1, 'plan_approvals': 0}),
    ('auto', {'user_actions': 1, 'confirmations': 0, 'nudges': 0, 'continuations': 1, 'plan_approvals': 1}),
])
def test_transports_share_confirmation_nudge_and_completion_counts(tmp_path, monkeypatch, runner, mode, expected):
    from workbench import cli_agent

    class ScenarioClient:
        def __init__(self):
            self.turns = 0
            self.confirmed = False
            self.approved = False
            self.actions = []
        def result(self):
            self.turns += 1
            return {'status': 'idle', 'assistant': {'content': 'Review required.' if self.turns == 1 else 'ANALYSIS COMPLETE'}}
        def post(self, path, **kwargs):
            if path == '/agent/sessions':
                return Response({'session_id': 'session'})
            if path.endswith('/confirm'):
                self.actions.append('confirm')
                self.confirmed = True
                return Response({'operation': {'record_id': 'record', 'status': 'completed'}})
            if path.endswith('/plan/approve'):
                self.actions.append('approve_plan')
                self.approved = True
                return Response({})
            self.actions.append(('turn', kwargs['json'].get('question')))
            return Response(self.result())
        def get(self, path, **kwargs):
            if path.endswith('/plan'):
                return Response({'plan': {'status': 'approved' if self.approved else 'draft', 'version': 1}})
            if path.endswith('/proposals'):
                proposals = [] if self.confirmed else [{'proposal_id': 'proposal', 'revision': 1, 'fingerprint': 'fp', 'status': 'pending'}]
                return Response({'proposals': proposals})
            return Response({'active_head_run_id': 'run'})

    results = []
    actions = []
    for transport in ('http', 'headless'):
        client = ScenarioClient()
        async def headless(*args, **kwargs):
            text = args[1] if 'session_id' in kwargs else None
            client.actions.append(('turn', text))
            kwargs['on_event']({'seq': client.turns + 1, 'event_type': 'raw_provider_step'})
            return client.result()
        monkeypatch.setattr(cli_agent, 'run_headless', headless)
        monkeypatch.setattr(cli_agent, 'continue_headless', headless)
        policy = runner.Policy(mode=mode, transport=transport, language='en', max_nudges=2)
        result = runner.run_conversation(client, tmp_path, 'run', 'Inspect.', policy)
        assert result['transport'] == transport
        assert result['completed_marker'] is True and result['stop_reason'] == 'completion_marker'
        for key, value in expected.items():
            assert (len(result[key]) if key == 'confirmations' else result[key]) == value
        results.append(result)
        actions.append(client.actions)
    assert actions[0] == actions[1]
    assert [item['user'] for item in results[0]['turns']] == [item['user'] for item in results[1]['turns']]


def test_headless_turn_uses_scoped_fake_runtime_without_current_provider(tmp_path, monkeypatch, runner):
    from workbench.http import agent_routes as routes
    from workbench.agent.runtime_adapter import headless_runtime_scope
    from workbench.agent.model import ModelStreamEvent
    from workbench.llm.config import LLMConfig

    requests = []
    class Model:
        async def stream(self, request):
            requests.append(request)
            yield ModelStreamEvent.text_delta(request.request_id, 'ANALYSIS COMPLETE')
            yield ModelStreamEvent.done(request.request_id)
    def forbidden(*args, **kwargs):
        raise AssertionError('the evaluator must retain the explicit in-process runtime')
    monkeypatch.setattr(agent_route_runtime, 'load_llm_config', forbidden)
    monkeypatch.setattr(agent_route_runtime, 'OpenAICompatibleModelAdapter', forbidden)
    config = LLMConfig(base_url='https://example.test', api_key='fake', model='fake')
    with headless_runtime_scope(adapter_factory=lambda _: Model(), config=config):
        session = routes.create_agent_session(str(tmp_path), routes.AgentSessionCreateRequest(role='chain'))['session_id']
        result = runner._turn(None, tmp_path, session, 'Inspect.', 'proposal_only', 'ask', transport='headless')
    assert len(requests) == 1
    assert 'Partially complete' in result['reply']
    assert 'ANALYSIS COMPLETE' not in result['reply']
    assert result['http_status'] is None
    assert {'agent_start', 'agent_end'} <= {event['event_type'] for event in result['raw_events']}


def test_inprocess_headless_retains_existing_provider_tape_without_network(tmp_path, monkeypatch, runner):
    import json
    from workbench.http import agent_routes as routes
    from workbench.llm.config import LLMConfig
    from workbench.agent.model import OpenAICompatibleModelAdapter
    import httpx

    recorder_path = Path(__file__).resolve().parents[1] / 'scripts' / 'agent_eval' / 'recorder.py'
    spec = importlib.util.spec_from_file_location('agent_eval_recorder_transport_test', recorder_path)
    recorder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(recorder)
    config = LLMConfig(base_url='https://example.test', api_key='fake', model='fake')
    monkeypatch.setattr(agent_route_runtime, 'load_llm_config', lambda: config)
    monkeypatch.setattr(agent_route_runtime, 'OpenAICompatibleModelAdapter', OpenAICompatibleModelAdapter)
    def forbidden(*args, **kwargs):
        raise AssertionError('a local tape must not create an upstream transport')
    monkeypatch.setattr(httpx.AsyncHTTPTransport, '__init__', forbidden)
    tape_file = tmp_path / 'fake-provider.jsonl'
    content = {'id': 'fake-provider-id', 'choices': [{'delta': {'content': 'ANALYSIS COMPLETE'}, 'finish_reason': 'stop'}],
               'usage': {'prompt_tokens': 12, 'completion_tokens': 3}}
    tape_file.write_text(json.dumps({
        'request_sha256': '0' * 64, 'status': 200, 'content_type': 'text/event-stream',
        'response_raw': 'data: ' + json.dumps(content) + '\n\ndata: [DONE]\n\n',
    }) + '\n')
    project = tmp_path / 'project'
    project.mkdir()
    session = routes.create_agent_session(str(project), routes.AgentSessionCreateRequest(role='chain'))['session_id']
    with recorder.provider_tape(tape_file, mode='replay') as tape:
        result = runner._turn(None, project, session, 'Inspect.', 'proposal_only', 'ask', transport='headless')
    assert 'Partially complete' in result['reply']
    assert 'ANALYSIS COMPLETE' not in result['reply']
    assert not tape.queue
    # This pre-existing evaluator tape reports mismatches; it is not the strict
    # product ReplayAdapter and must never be described as one.
    assert tape.mismatches == 1


def test_formal_development_headless_records_the_pinned_nvidia_request(tmp_path, monkeypatch, runner):
    import json
    import httpx
    from agent_eval import budget
    from agent_eval.recorder import provider_tape
    from workbench.http import agent_routes as routes
    from workbench.llm.config import LLMConfig

    config = LLMConfig(provider_id=budget.NVIDIA_PROVIDER_ID, base_url=budget.NVIDIA_BASE_URL,
                       model=budget.NVIDIA_MODEL, api_key='offline-key', reasoning_efforts=('none', 'high'))
    monkeypatch.setenv('WORKBENCH_REASONING_EFFORT', 'high')
    monkeypatch.setattr(agent_route_runtime, 'load_llm_config', lambda: config)
    received = []

    def respond(request):
        received.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, headers={'content-type': 'text/event-stream'},
            text='data: {"choices":[{"delta":{"content":"Inspected."},"finish_reason":"stop"}]}\n\n'
                 'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":3}}\n\n'
                 'data: [DONE]\n\n')

    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', lambda **kwargs: httpx.MockTransport(respond))
    project = tmp_path / 'project'
    project.mkdir()
    session = routes.create_agent_session(str(project), routes.AgentSessionCreateRequest(role='chain'))['session_id']
    guard = budget.M5DevNvidiaGuard(tmp_path / 'budget.json', config=config, serial_path=tmp_path / 'serial.json')
    tape = tmp_path / 'tape.jsonl'
    with provider_tape(tape, budget=guard):
        runner._turn(None, project, session, 'Inspect.', 'proposal_only', 'ask', transport='headless')
    assert len(received) == guard.state['requests'] == guard.state['calls'] == 1
    url, body = received[0]
    assert url == budget.NVIDIA_BASE_URL + '/chat/completions'
    assert (body['model'], body['reasoning_effort'], body['max_tokens']) == (budget.NVIDIA_MODEL, 'high', 32768)
    assert guard.state['reservations'] == {}
    assert json.loads(tape.read_text())['status'] == 200


def test_the_requested_final_answer_ends_the_conversation_without_a_nudge(monkeypatch, runner, tmp_path):
    replies = ['FINAL ANSWER: 3']
    monkeypatch.setattr(runner, '_turn', lambda *args, **kwargs: {'reply': replies[-1], 'user': args[3] if len(args) > 3 else None})
    monkeypatch.setattr(runner, '_pending_proposals', lambda *args: [])
    class Client:
        def post(self, *args, **kwargs):
            class Created:
                status_code = 200
                raise_for_status = staticmethod(lambda: None)
                json = staticmethod(lambda: {'session_id': 's', 'session': {'session_id': 's'}})
            return Created()
    result = runner.run_conversation(Client(), tmp_path, 'run', 'Q', runner.Policy(mode='ask', language='en', max_nudges=8))
    assert result['stop_reason'] == 'final_answer' and result['nudges'] == 0 and result['completed_marker'] is True


@pytest.mark.parametrize('decline_status', [200, 409])
def test_a_policy_denied_revision_is_declined_and_never_confirmed_twice(tmp_path, monkeypatch, runner, decline_status):
    denied = {'proposal_id': 'denied', 'revision': 1, 'fingerprint': 'blocked', 'status': 'pending'}
    revised = {**denied, 'revision': 2, 'fingerprint': 'revised'}
    turns = iter(['Review required.', 'A revised proposal is ready.', 'ANALYSIS COMPLETE'])
    monkeypatch.setattr(runner, '_turn', lambda *args, **kwargs: {'reply': next(turns)})
    polls = iter([[denied], [denied, revised]])
    monkeypatch.setattr(runner, '_pending_proposals', lambda *args: next(polls))
    monkeypatch.setattr(runner, '_active_head', lambda *args: 'run')

    attempts = []
    declines = []

    class Client:
        def post(self, path, **kwargs):
            if path == '/agent/sessions':
                return Response({'session_id': 'session'})
            if path.endswith('/decline'):
                declines.append(kwargs['json'])
                response = Response({})
                response.status_code = decline_status
                return response
            attempts.append(kwargs['json']['revision'])
            if kwargs['json']['revision'] == 1:
                response = Response({'error': {'code': 'OPERATION_PERMISSION_DENIED'}})
                response.status_code = 403
                return response
            return Response({'operation': {'status': 'completed'}})

    result = runner.run_conversation(Client(), tmp_path, 'run', 'Inspect.', runner.Policy(mode='ask'))
    assert attempts == [1, 2]
    assert len(declines) == 1
    assert (declines[0]['revision'], declines[0]['fingerprint']) == (1, 'blocked')
    assert result['confirmations'][0]['status'] == 'http_403'
    assert result['confirmations'][1]['status'] == 'completed'
    assert result['completed_marker'] is True
