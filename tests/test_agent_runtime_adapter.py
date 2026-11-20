"""Headless adapter overrides are explicit, isolated, and fail closed offline."""
from __future__ import annotations
from workbench.http import agent_route_runtime, agent_turn_routes

import asyncio
from dataclasses import replace
import importlib
import json
from pathlib import Path
from shutil import copytree

import pytest
from pydantic import ValidationError

from tests.test_agent_routes import FakeAgentAdapter, _config
from workbench.agent.model import ModelStreamEvent
from workbench.agent.events import AgentEventStream
from workbench.agent.model_replay import RecordingAdapter, ReplayAdapter
from workbench.agent.session import JsonlSessionRepository
from workbench.http import agent_routes as routes


def _api():
    return importlib.import_module('workbench.agent.runtime_adapter')


def _forbidden(*args, **kwargs):
    raise AssertionError('Offline mode must not read current configuration or build an upstream adapter')


def _empty_replay(tmp_path):
    from workbench.agent.model import ModelRequest
    class Done:
        async def stream(self, request):
            yield ModelStreamEvent.done(request.request_id)
    recorder=RecordingAdapter(Done(),root=tmp_path,name='provider.jsonl')
    async def record():
        return [e async for e in recorder.stream(ModelRequest(request_id='r',messages=[]))]
    asyncio.run(record())
    return ReplayAdapter(root=tmp_path,name='provider.jsonl')


def test_route_defaults_preserve_live_monkeypatch_aliases(monkeypatch):
    api=_api();config=_config();seen=[]
    monkeypatch.setattr(agent_route_runtime,'load_llm_config',lambda:config)
    monkeypatch.setattr(agent_route_runtime,'OpenAICompatibleModelAdapter',lambda value:seen.append(value) or FakeAgentAdapter(value))
    assert routes._agent_llm_config() is config
    assert routes._agent_llm_configured(config)
    assert isinstance(routes._agent_model_adapter(config),FakeAgentAdapter)
    assert seen==[config]


def test_record_scope_uses_default_config_and_one_adapter(monkeypatch):
    api=_api();config=_config();calls=[]
    monkeypatch.setattr(agent_route_runtime,'load_llm_config',lambda:config)
    with api.headless_runtime_scope(adapter_factory=lambda value:calls.append(value) or FakeAgentAdapter(value)):
        assert routes._agent_llm_config() is config
        adapter=routes._agent_model_adapter(config)
        assert routes._agent_model_adapter(config) is adapter
    assert calls==[config]


def test_runtime_scope_reaches_tool_threads_and_refuses_use_after_exit(monkeypatch):
    api=_api();config=_config()
    monkeypatch.setattr(agent_route_runtime,'load_llm_config',_forbidden)
    async def scenario():
        ready=asyncio.Event()
        async def delayed():
            await ready.wait()
            with pytest.raises(api.RuntimeAdapterError,match='closed'):
                routes._agent_llm_config()
        with api.headless_runtime_scope(adapter_factory=FakeAgentAdapter,config=config):
            task=asyncio.create_task(delayed())
            assert await asyncio.to_thread(routes._agent_llm_config) is config
        ready.set();await task
    asyncio.run(scenario())


def test_parallel_runtime_scopes_have_distinct_configs_and_adapters(monkeypatch):
    api=_api()
    monkeypatch.setattr(agent_route_runtime,'load_llm_config',_forbidden)
    monkeypatch.setattr(agent_route_runtime,'OpenAICompatibleModelAdapter',_forbidden)
    async def one(model):
        config=replace(_config(),model=model)
        with api.headless_runtime_scope(adapter_factory=FakeAgentAdapter,config=config):
            await asyncio.sleep(0)
            assert routes._agent_llm_config() is config
            return routes._agent_model_adapter(config)
    async def scenario():
        first,second=await asyncio.gather(one('first'),one('second'))
        assert first is not second and first.config.model=='first' and second.config.model=='second'
    asyncio.run(scenario())


def test_one_recording_runtime_rejects_configuration_drift(monkeypatch):
    api=_api();config=_config()
    monkeypatch.setattr(agent_route_runtime,'load_llm_config',lambda:config)
    with api.headless_runtime_scope(adapter_factory=FakeAgentAdapter):
        routes._agent_model_adapter(routes._agent_llm_config())
        monkeypatch.setattr(agent_route_runtime,'load_llm_config',lambda:replace(config,model='changed'))
        with pytest.raises(api.RuntimeAdapterError,match='changed'):
            routes._agent_llm_config()


def test_offline_scope_uses_explicit_keyless_config_and_exact_replay(tmp_path,monkeypatch):
    api=_api();replay=_empty_replay(tmp_path);config=replace(_config(),api_key='');calls=[]
    monkeypatch.setattr(agent_route_runtime,'load_llm_config',_forbidden)
    monkeypatch.setattr(agent_route_runtime,'OpenAICompatibleModelAdapter',_forbidden)
    with api.headless_runtime_scope(adapter_factory=lambda value:calls.append(value) or replay,config=config,offline=True):
        assert routes._agent_llm_config() is config
        assert routes._agent_llm_configured(config)
        assert not config.is_configured() and config.api_key==''
        assert routes._agent_model_adapter(config) is replay
        assert routes._agent_model_adapter(config) is replay
    assert calls==[config]


@pytest.mark.parametrize('changes',[None, {'api_key':'secret-must-not-appear'}, {'base_url':'file:///tmp/provider'},
                                   {'base_url':'https://user:password@example.test'}, {'base_url':'https://example.test?key=x'},
                                   {'model':' '}])
def test_invalid_offline_config_is_rejected_without_loader_or_factory(changes,monkeypatch):
    api=_api()
    monkeypatch.setattr(agent_route_runtime,'load_llm_config',_forbidden)
    config=replace(_config(),api_key='',**changes) if changes and 'api_key' not in changes else (
        replace(_config(),**changes) if changes else None)
    with pytest.raises(api.RuntimeAdapterError) as error:
        with api.headless_runtime_scope(adapter_factory=_forbidden,config=config,offline=True): pass
    assert 'secret-must-not-appear' not in str(error.value)


def test_offline_rejects_an_adapter_wrapper_or_subclass(tmp_path):
    api=_api();config=replace(_config(),api_key='')
    class PretendingReplay:
        async def stream(self,request):
            raise AssertionError('must never execute')
            yield
    with pytest.raises(api.RuntimeAdapterError,match='ReplayAdapter'):
        with api.headless_runtime_scope(adapter_factory=lambda config:PretendingReplay(),config=config,offline=True): pass
    replay=_empty_replay(tmp_path)
    class SubclassReplay(ReplayAdapter): pass
    replay.__class__=SubclassReplay
    with pytest.raises(api.RuntimeAdapterError,match='ReplayAdapter'):
        with api.headless_runtime_scope(adapter_factory=lambda config:replay,config=config,offline=True): pass


def test_record_scope_cannot_override_a_missing_provider_key(tmp_path,monkeypatch):
    api=_api();config=replace(_config(),api_key='')
    monkeypatch.setattr(agent_route_runtime,'load_llm_config',lambda:config)
    root=tmp_path/'project';root.mkdir();repo=JsonlSessionRepository(root/'workbench')
    repo.create_session('s',chain_id='chain',role='chain')
    with api.headless_runtime_scope(adapter_factory=_forbidden):
        with pytest.raises(Exception) as error:
            asyncio.run(routes.run_agent_turn('s',str(root),routes.AgentTurnRequest(question='Inspect.')))
    assert error.value.code=='LLM_NOT_CONFIGURED'


def test_offline_cannot_be_enabled_in_an_http_body():
    with pytest.raises(ValidationError):
        routes.AgentTurnRequest(question='Inspect.',offline=True)


def test_record_then_strict_headless_replay_without_current_config_or_upstream(tmp_path,monkeypatch):
    api=_api()
    from workbench.cli_agent import run_headless
    root=tmp_path/'project';root.mkdir()
    repo=JsonlSessionRepository(root/'workbench');repo.create_session('s',chain_id='chain',role='chain')
    initial=tmp_path/'initial';copytree(root,initial)
    config=_config();monkeypatch.setattr(agent_route_runtime,'load_llm_config',lambda:config)
    record_dir=tmp_path/'recording';record_dir.mkdir()
    recorder=RecordingAdapter(FakeAgentAdapter(config),root=record_dir,name='provider.jsonl')
    with api.headless_runtime_scope(adapter_factory=lambda value:recorder):
        first=asyncio.run(run_headless(root,'Inspect.',session_id='s',on_event=lambda e:None))
    root.rename(tmp_path/'recorded-project');copytree(initial,root)
    replay=ReplayAdapter(root=record_dir,name='provider.jsonl')
    monkeypatch.setattr(agent_route_runtime,'load_llm_config',_forbidden)
    monkeypatch.setattr(agent_route_runtime,'OpenAICompatibleModelAdapter',_forbidden)
    with api.headless_runtime_scope(adapter_factory=lambda value:replay,config=replace(config,api_key=''),offline=True):
        created=routes.create_agent_session(str(root),routes.AgentSessionCreateRequest(role='main'))
        assert 'api_key' not in json.dumps(created)
        # The unrelated session creation must not affect this existing session's context.
        second=asyncio.run(run_headless(root,'Inspect.',session_id='s',on_event=lambda e:None))
        public=routes.get_agent_session('s',str(root))
    assert second['assistant']['content']==first['assistant']['content']
    assert replay.remaining==0 and second['status']=='idle'
    assert config.api_key not in json.dumps(public,ensure_ascii=False)


def test_active_durable_turn_is_rejected_before_any_turn_mutation(tmp_path,monkeypatch):
    from workbench.agent.turn_store import TurnStore
    root=tmp_path/'project';root.mkdir();repo=JsonlSessionRepository(root/'workbench')
    repo.create_session('s',chain_id='chain',role='chain')
    entry=repo.append('s','custom_message',{'audience':'internal','content':'accepted'})
    TurnStore(root).create('s',entry.entry_id,budget={'max_steps':5,'timeout_s':60})
    before=repo.get_metadata('s');before_entries=[e.to_dict() for e in repo.get_branch('s')]
    for name in ['_tell_agent_finished_outcomes','load_llm_config','OpenAICompatibleModelAdapter','_ensure_current_global_protocol']:
        monkeypatch.setattr(agent_route_runtime if name in {'load_llm_config','OpenAICompatibleModelAdapter'} else agent_turn_routes,name,_forbidden)
    with pytest.raises(Exception) as error:
        asyncio.run(routes.run_agent_turn('s',str(root),routes.AgentTurnRequest(question='New turn.',execution_mode='auto')))
    assert error.value.code=='AGENT_TURN_RECOVERY_REQUIRED' and error.value.status_code==409
    assert repo.get_metadata('s')==before
    assert [e.to_dict() for e in repo.get_branch('s')]==before_entries


@pytest.mark.parametrize('role',['main','chain'])
def test_resume_keeps_checkpoint_context_and_passes_safe_runtime_identity(tmp_path,monkeypatch,role):
    api=_api();config=_config();root=tmp_path/'project';root.mkdir()
    repo=JsonlSessionRepository(root/'workbench');repo.create_session('s',chain_id='chain',role=role)
    repo.update_metadata('s',execution_mode='ask')
    repo.append('s','message',{'role':'assistant','content':'Original response.'})
    before=repo.get_metadata('s');before_entries=[e.to_dict() for e in repo.get_branch('s')];seen=[]
    original=agent_turn_routes.AgentCore
    class CaptureCore(original):
        def __init__(self,*args,**kwargs): seen.append(kwargs);super().__init__(*args,**kwargs)
        async def resume(self,turn_id,**kwargs): assert turn_id=='original-turn';return 'Original response.'
    monkeypatch.setattr(agent_turn_routes,'AgentCore',CaptureCore)
    monkeypatch.setattr(agent_route_runtime,'load_llm_config',lambda:config)
    monkeypatch.setattr(agent_route_runtime,'OpenAICompatibleModelAdapter',FakeAgentAdapter)
    for name in ['_tell_agent_finished_outcomes','_ensure_current_global_protocol','_refresh_main_context']:
        monkeypatch.setattr(agent_route_runtime if name in {'load_llm_config','OpenAICompatibleModelAdapter'} else agent_turn_routes,name,_forbidden)
    key=routes._reserve_turn(root,'s')
    asyncio.run(routes.turn_registry.run_owned(key,lambda:routes._run_reserved_agent_turn(
        root,'s',routes.AgentContinueRequest(execution_mode='auto',context_packet={'new':'must not be injected'}),
        repo,AgentEventStream(root/'workbench'),before,key,resume_turn_id='original-turn')))
    assert repo.get_metadata('s')==before
    assert [e.to_dict() for e in repo.get_branch('s')]==before_entries
    identity=seen[0]['model_config_identity']
    assert set(identity)=={'base_url','model','provider_id','provider_name','timeout_s','context_window_tokens','supports_1m','supports_vision'}
    assert config.api_key not in json.dumps(identity) and 'source' not in identity


def test_notebook_planning_uses_the_shared_runtime_factory(tmp_path, monkeypatch):
    """A runtime scope (replay, fake model) governs Notebook planning as it does Agent turns."""
    from workbench.agent.runtime_adapter import headless_runtime_scope
    from workbench.http import notebook_routes
    from workbench.llm.config import LLMConfig

    made = []

    class Fake:
        def __init__(self, config):
            made.append(config)

    config = LLMConfig(base_url="https://api.example.test", api_key="offline", model="fake",
                       context_window_tokens=64_000, provider_id="fake", provider_name="Fake", source="local")
    monkeypatch.setattr(notebook_routes, "load_llm_config", lambda: config)
    with headless_runtime_scope(adapter_factory=Fake, config=config):
        try:
            notebook_routes._planning_agent(tmp_path, None, "nb", None, None)
        except Exception:
            pass  # only the adapter construction matters here
    assert made, "Notebook planning built its own provider adapter outside the runtime scope"
