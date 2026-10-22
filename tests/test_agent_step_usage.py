"""Provider usage is retained as evidence, never inferred from visible text."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from tests.test_llm_providers import _install_async_upstream
from workbench.agent.core import AgentCore
from workbench.agent.events import AgentEventStream
from workbench.agent.model import ModelRequest, ModelStreamEvent, OpenAICompatibleModelAdapter
from workbench.agent.session import JsonlSessionRepository
from workbench.llm.client import LLMConfig

USAGE = {'prompt_tokens': 80, 'completion_tokens': 9, 'total_tokens': 89,
         'prompt_cache_hit_tokens': 60, 'prompt_cache_miss_tokens': 20,
         'completion_tokens_details': {'reasoning_tokens': 4}}


def test_actual_sse_finish_frame_keeps_reported_usage_and_provider_identity(monkeypatch):
    frame = {'id': 'provider-trace', 'model': 'test-model', 'usage': USAGE,
             'choices': [{'delta': {'content': 'Finished.'}, 'finish_reason': 'stop'}]}
    wire = ('data: ' + json.dumps(frame) + '\n\ndata: [DONE]\n\n').encode()
    seen = _install_async_upstream(monkeypatch, lambda request: httpx.Response(200, content=wire))
    adapter = OpenAICompatibleModelAdapter(LLMConfig(base_url='https://api.example.com/v1',
                                                   api_key='test-not-a-real-key', model='test-model'))
    async def collect():
        return [event async for event in adapter.stream(ModelRequest(messages=[{'role': 'user', 'content': 'Inspect.'}]))]
    events = asyncio.run(collect())
    assert events[-1].type == 'done'
    assert events[-1].usage == USAGE
    assert events[-1].provider_request_id == 'provider-trace'
    assert 'stream_options' not in json.loads(seen[0].content)  # No provider request change.


def _core(tmp_path, adapter):
    repository = JsonlSessionRepository(tmp_path)
    repository.create_session('s', chain_id='c', role='chain')
    events = AgentEventStream(tmp_path)
    return AgentCore(repository, events, adapter, session_id='s', model_name='test-model'), repository, events


def test_core_step_observation_keeps_usage_separate_from_model_context(tmp_path):
    class Model:
        async def stream(self, request):
            yield ModelStreamEvent.text_delta(request.request_id, 'Finished.')
            yield ModelStreamEvent(type='done', request_id=request.request_id, finish_reason='stop',
                                   usage=USAGE, provider_request_id='provider-trace')
    core, repository, events = _core(tmp_path, Model())
    assert asyncio.run(core.prompt('Inspect.', budget={'max_steps': 1})) == 'Finished.'
    [event] = [e for e in events.replay('s') if e.event_type == 'provider_step']
    assert event.payload['usage'] == USAGE and event.payload['usage_state'] == 'reported'
    assert event.payload['provider_request_id'] == 'provider-trace'
    assert event.payload['provider_step'] == 1 and event.payload['outcome'] == 'stop'
    assert event.payload['elapsed_s'] >= 0
    assert 0 <= event.payload['first_public_s'] <= event.payload['elapsed_s']
    assert event.payload['cost'] is None and event.payload['cost_state'] == 'pricing_unverified'
    assert 'prompt_cache_hit_tokens' not in str(core.context_builder.build('s').messages)


def test_offline_transport_decodes_the_fixed_development_finish_frame(monkeypatch):
    import hashlib
    tape = (Path(__file__).resolve().parents[1] / 'local/agent-eval/baseline-v190/tasks'
            / 'ts_garch.open.r1/provider_tape.jsonl')
    if not tape.is_file():
        pytest.skip('local development recording is not included in the repository')
    raw = tape.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '89148bca5baac2a622861bb006d282f6f4c8aafa1234224179dfdd125a59e468'
    record = json.loads(raw.splitlines()[15])
    _install_async_upstream(monkeypatch, lambda request: httpx.Response(200, content=record['response_raw'].encode()))
    adapter = OpenAICompatibleModelAdapter(LLMConfig(base_url='https://api.example.com/v1',
                                                   api_key='test-not-a-real-key', model='test-model'))
    async def collect():
        return [event async for event in adapter.stream(ModelRequest())]
    events = asyncio.run(collect())
    assert events[-1].type == 'done' and events[-1].usage == record['usage']
    assert events[-1].provider_request_id
    # This decodes an original response; it is not full-request analysis replay.
    assert all(event.type in {'text_delta', 'tool_call_delta', 'reasoning', 'done'} for event in events)
    # The private reasoning arrives once, whole, just before done (it is sent back to the provider).
    streamed = ''.join((json.loads(line[6:])['choices'][0].get('delta') or {}).get('reasoning_content') or ''
                       for line in record['response_raw'].splitlines()
                       if line.startswith('data: {') and json.loads(line[6:]).get('choices'))
    reasoning = [event for event in events if event.type == 'reasoning']
    assert [event.delta for event in reasoning] == ([streamed] if streamed else [])
    if reasoning:
        assert events[-2] is reasoning[0]


@pytest.mark.parametrize(('usage', 'state'), [(None, 'unavailable'), ({}, 'reported'),
                                            ({'bad': float('nan')}, 'invalid'),
                                            ({'bad': 'x' * 20_000}, 'oversized')])
def test_missing_or_unusable_usage_is_not_zero(tmp_path, usage, state):
    class Model:
        async def stream(self, request):
            yield ModelStreamEvent.text_delta(request.request_id, 'Finished.')
            yield ModelStreamEvent(type='done', request_id=request.request_id, usage=usage)
    core, repository, events = _core(tmp_path, Model())
    asyncio.run(core.prompt('Inspect.', budget={'max_steps': 1}))
    [event] = [e for e in events.replay('s') if e.event_type == 'provider_step']
    assert event.payload['usage_state'] == state
    assert event.payload['usage'] == ({} if state == 'reported' else None)
    assert event.payload['cost'] is None


def test_step_stream_closes_and_records_before_any_tool_runs(tmp_path):
    from workbench.agent.tools import ToolDefinition, ToolRegistry
    closed = []
    class Model:
        calls = 0
        async def stream(self, request):
            self.calls += 1
            index = self.calls
            try:
                if index == 1:
                    yield ModelStreamEvent.tool_call_delta(request.request_id,
                        {'tool_call_id': 'inspect', 'tool_id': 'inspect', 'arguments': {}})
                    yield ModelStreamEvent(type='done', request_id=request.request_id,
                                           finish_reason='tool_calls', usage=USAGE)
                else:
                    yield ModelStreamEvent.text_delta(request.request_id, 'Finished.')
                    yield ModelStreamEvent(type='done', request_id=request.request_id, usage=USAGE)
            finally:
                closed.append(index)
    core, repository, events = _core(tmp_path, Model())
    def inspect(arguments, context):
        assert closed == [1]
        assert len([e for e in events.replay('s') if e.event_type == 'provider_step']) == 1
        return {'state': 'ready'}
    registry = ToolRegistry()
    registry.register(ToolDefinition('inspect', 'v1', {'type': 'object'}, 'none', inspect))
    core.attach_tools(registry.descriptors(), registry)
    assert asyncio.run(core.prompt('Inspect.', budget={'max_steps': 2})) == 'Finished.'
    observations = [e for e in events.replay('s') if e.event_type == 'provider_step']
    assert [e.payload['provider_step'] for e in observations] == [1, 2]
    assert len({e.command_id for e in observations}) == 1
    assert closed == [1, 2]


@pytest.mark.parametrize('failure', ['error', 'exception', 'cancelled'])
def test_provider_failure_is_observed_without_a_success_or_cost(tmp_path, failure):
    class Model:
        async def stream(self, request):
            yield ModelStreamEvent.retrying(request.request_id, 'temporary')
            if failure == 'exception':
                raise RuntimeError('offline provider failure')
            if failure == 'cancelled':
                raise asyncio.CancelledError()
            yield ModelStreamEvent.from_error(request.request_id, 'offline provider error')
    core, repository, events = _core(tmp_path, Model())
    if failure == 'cancelled':
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(core.prompt('Inspect.', budget={'max_steps': 1}))
    else:
        asyncio.run(core.prompt('Inspect.', budget={'max_steps': 1}))
    [event] = [e for e in events.replay('s') if e.event_type == 'provider_step']
    assert event.payload['outcome'] == ('cancelled' if failure == 'cancelled' else 'error')
    assert event.payload['retries'] == 1 and event.payload['first_public_s'] is None
    assert event.payload['usage'] is None and event.payload['cost'] is None


def test_phase_and_regular_steps_use_the_same_observation_boundary(tmp_path):
    from workbench.agent.phases import PhaseRequest, PhaseStep
    class Phase:
        episode_id = 'phase-inspection'
        def request(self, transcript):
            return PhaseRequest([{'role': 'user', 'content': 'Inspect phase.'}], [])
        async def consume(self, events, *, error=None):
            assert error is None
            return PhaseStep('completed', (), 'Done.', {'state': 'ready'})
        def checkpoint(self):
            return {'episode_id': self.episode_id}
        def failure(self, reason, error=None):
            return RuntimeError(reason)
    class Model:
        async def stream(self, request):
            yield ModelStreamEvent(type='done', request_id=request.request_id, usage=USAGE)
    core, repository, events = _core(tmp_path, Model())
    assert asyncio.run(core.run_phase(Phase(), budget={'max_steps': 1})) == 'Done.'
    [event] = [e for e in events.replay('s') if e.event_type == 'provider_step']
    assert event.payload['phase_episode_id'] == 'phase-inspection'
    assert event.payload['usage'] == USAGE
    assert 'prompt_cache_hit_tokens' not in str(core.context_builder.build('s').messages)


def test_failed_stream_close_cannot_be_observed_as_success(tmp_path):
    class Source:
        def __init__(self, request):
            self.request = request
            self.done = False
        def __aiter__(self):
            return self
        async def __anext__(self):
            if self.done:
                raise StopAsyncIteration
            self.done = True
            return ModelStreamEvent.done(self.request.request_id)
        async def aclose(self):
            raise OSError('offline source cleanup failure')
    class Model:
        def stream(self, request):
            return Source(request)
    core, repository, events = _core(tmp_path, Model())
    asyncio.run(core.prompt('Inspect.', budget={'max_steps': 1}))
    [event] = [e for e in events.replay('s') if e.event_type == 'provider_step']
    assert event.payload['outcome'] == 'error'


def test_absent_upstream_id_is_not_replaced_by_local_request_id(monkeypatch):
    wire = b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
    _install_async_upstream(monkeypatch, lambda request: httpx.Response(200, content=wire))
    adapter = OpenAICompatibleModelAdapter(LLMConfig(base_url='https://api.example.com/v1',
                                                   api_key='test-not-a-real-key', model='test-model'))
    async def collect():
        return [event async for event in adapter.stream(ModelRequest(request_id='local-request'))]
    [done] = asyncio.run(collect())
    assert done.request_id == 'local-request' and done.provider_request_id is None
    assert done.usage is None


@pytest.mark.parametrize('index', [0, 1, 2])
def test_frozen_original_usage_frame_matches_persisted_event(monkeypatch, tmp_path, index):
    import hashlib
    fixture = json.loads((Path(__file__).parent / 'fixtures/agent_usage/development_frames.json').read_text())
    record = fixture['records'][index]
    frame = json.loads(record['frame'][6:])
    assert frame['usage'] == record['usage']
    local = Path(__file__).parents[1] / fixture['source']
    if local.exists():
        raw = local.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == fixture['source_sha256']
        original = json.loads(raw.splitlines()[record['line'] - 1])
        assert hashlib.sha256(original['response_raw'].encode()).hexdigest() == record['response_sha256']
        assert record['frame'] in original['response_raw'].splitlines()
    wire = (record['frame'] + '\n\ndata: [DONE]\n\n').encode()
    _install_async_upstream(monkeypatch, lambda request: httpx.Response(200, content=wire))
    adapter = OpenAICompatibleModelAdapter(LLMConfig(base_url='https://offline.invalid/v1',api_key='unused',model='offline'))
    core, repository, events = _core(tmp_path, adapter)
    asyncio.run(core.prompt('Inspect.', budget={'max_steps': 1}))
    [observation] = [e for e in events.replay('s') if e.event_type == 'provider_step']
    assert observation.payload['usage'] == frame['usage']
    assert observation.payload['provider_request_id'] == frame['id']


def test_repeated_snapshots_are_not_counted_as_extra_steps_or_summed(tmp_path):
    class Model:
        async def stream(self, request):
            yield ModelStreamEvent(type='text_delta',request_id=request.request_id,delta='Ready.',usage={'prompt_tokens':70})
            yield ModelStreamEvent(type='done',request_id=request.request_id,usage=USAGE)
    core, repository, events = _core(tmp_path, Model())
    asyncio.run(core.prompt('Inspect.', budget={'max_steps':1}))
    [observation] = [e for e in events.replay('s') if e.event_type == 'provider_step']
    assert observation.payload['usage'] == USAGE
