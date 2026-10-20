"""Explicit headless recovery and strictly offline replay."""
from __future__ import annotations
from workbench.http import agent_route_runtime

import asyncio
import json

from typer.testing import CliRunner
import pytest

from workbench.cli import app


def test_budget_blocked_headless_command_returns_failure_exit(tmp_path, monkeypatch):
    from workbench import cli_agent
    async def blocked(*args, **kwargs):
        return {"status": "blocked", "assistant": {"content": "The step budget was exhausted."}}
    monkeypatch.setattr(cli_agent, "run_headless", blocked)
    result = CliRunner().invoke(app, ["agent", "run", "--project", str(tmp_path), "--prompt", "Finish."])
    assert result.exit_code == 1
    assert json.loads(result.stdout.splitlines()[-1])["status"] == "blocked"


def test_resume_uses_saved_mode_and_same_approval_exit(tmp_path, monkeypatch):
    from workbench import cli_agent
    from workbench.http import agent_routes as routes

    project = tmp_path / 'project'
    project.mkdir()
    seen = {}
    monkeypatch.setattr(routes, 'get_agent_turn_state', lambda session_id, project_root: {
        'turns': [{'turn_id': 'turn_saved', 'execution_mode': 'auto'}],
    })

    async def resume(session_id, project_root, body, http_request=None):
        seen['resume'] = (session_id, project_root, body.turn_id)
        return {'assistant': {'content': 'saved'}, 'status': 'completed'}

    async def stream(project_root, session_id, *, mode, on_event, start_turn):
        seen['mode'] = mode
        on_event({'seq': 1, 'event_type': 'agent_start'})
        result = await start_turn()
        return {'type': 'agent_result', 'session_id': session_id,
                'status': 'awaiting_plan_approval', 'assistant': result['assistant'],
                'pending_proposals': [], 'plan': {'status': 'draft'}}

    monkeypatch.setattr(routes, 'resume_agent_turn', resume)
    monkeypatch.setattr(cli_agent, '_stream_headless_turn', stream)
    evidence = tmp_path / 'events.jsonl'
    result = CliRunner().invoke(app, ['agent', 'resume', '--project', str(project),
                                     '--session', 'session_saved', '--turn', 'turn_saved',
                                     '--events-jsonl', str(evidence)])
    assert result.exit_code == 3, result.output
    assert seen == {'mode': 'auto', 'resume': ('session_saved', str(project), 'turn_saved')}
    assert json.loads(result.stdout.splitlines()[-1])['status'] == 'awaiting_plan_approval'
    assert json.loads(evidence.read_text())['event_type'] == 'agent_start'


def test_resume_unknown_turn_does_not_start_provider(tmp_path, monkeypatch):
    from workbench import cli_agent
    from workbench.http import agent_routes as routes

    monkeypatch.setattr(routes, 'get_agent_turn_state', lambda *args: {'turns': []})
    monkeypatch.setattr(routes, 'resume_agent_turn', lambda *args: (_ for _ in ()).throw(
        AssertionError('unknown turn must not start')))
    result = CliRunner().invoke(app, ['agent', 'resume', '--project', str(tmp_path),
                                     '--session', 'session_saved', '--turn', 'unknown'])
    assert result.exit_code != 0
    assert 'AGENT_TURN_NOT_FOUND' in result.output


def test_turn_state_reads_real_store_without_config_or_provider(tmp_path, monkeypatch):
    from workbench.http import agent_routes as routes
    from workbench.agent.turn_store import TurnStore
    from workbench.agent.session import JsonlSessionRepository

    repository = JsonlSessionRepository(tmp_path / 'workbench')
    repository.create_session('session_saved', chain_id='chain_saved', role='chain')
    record = TurnStore(tmp_path).create('session_saved', 'entry_saved', budget={'max_steps': 4, 'timeout_s': 60}, execution_mode='auto')
    def forbidden(*args, **kwargs):
        raise AssertionError('state is a zero-model read')
    monkeypatch.setattr(agent_route_runtime, 'load_llm_config', forbidden)
    monkeypatch.setattr(agent_route_runtime, 'OpenAICompatibleModelAdapter', forbidden)
    result = CliRunner().invoke(app, ['agent', 'turn-state', '--project', str(tmp_path),
                                     '--session', 'session_saved'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {'turns': [record.to_dict()]}


def _record_existing_session(tmp_path, monkeypatch, *, command='run', adapter=None):
    from tests.test_agent_routes import FakeAgentAdapter, _config
    from workbench import cli_agent
    from workbench.http import agent_routes as routes

    project = tmp_path / 'project'
    project.mkdir()
    journal = tmp_path / 'journal'
    journal.mkdir()
    monkeypatch.setattr(agent_route_runtime, 'load_llm_config', _config)
    monkeypatch.setattr(cli_agent, 'OpenAICompatibleModelAdapter', adapter or FakeAgentAdapter, raising=False)
    session = routes.create_agent_session(str(project), routes.AgentSessionCreateRequest(role='chain'))['session_id']
    args = ['agent', command, '--project', str(project), '--session', session]
    if command == 'run':
        args += ['--prompt', 'Inspect evidence.']
    from shutil import copytree
    initial = tmp_path / 'initial'
    copytree(project, initial)
    result = CliRunner().invoke(app, args + ['--record-journal', str(journal)])
    assert result.exit_code == 0, result.output
    return project, journal, initial, args, result


def test_record_manifest_has_exact_input_fixture_and_safe_config(tmp_path, monkeypatch):
    project, journal, initial, args, result = _record_existing_session(tmp_path, monkeypatch)
    manifest = json.loads((journal / 'runtime.json').read_text())
    assert manifest['schema'] == 'workbench.headless-journal.v1'
    assert manifest['input']['project_root'] == str(project)
    assert manifest['input']['prompt'] == 'Inspect evidence.'
    assert manifest['config']['model'] == 'test-model'
    assert 'api_key' not in manifest['config']
    assert 'test-key' not in (journal / 'runtime.json').read_text()
    assert len(manifest['fixture_sha256']) == 64
    assert manifest['complete'] is True
    assert (journal / 'model.jsonl').is_file()
    assert (journal / 'business.jsonl').is_file()


def test_replay_refuses_modified_fixture_without_loading_config(tmp_path, monkeypatch):
    from workbench.http import agent_routes as routes
    project, journal, initial, args, result = _record_existing_session(tmp_path, monkeypatch)
    def forbidden(*args, **kwargs):
        raise AssertionError('offline replay must never load the current config')
    monkeypatch.setattr(agent_route_runtime, 'load_llm_config', forbidden)
    result = CliRunner().invoke(app, args + ['--replay-journal', str(journal)])
    assert result.exit_code != 0
    assert 'fixture' in result.output


def test_journal_options_refuse_mutual_selection_and_relative_paths(tmp_path):
    base = ['agent', 'run', '--project', str(tmp_path), '--prompt', 'Inspect.']
    result = CliRunner().invoke(app, base + ['--record-journal', str(tmp_path),
                                            '--replay-journal', str(tmp_path)])
    assert result.exit_code != 0
    assert 'mutually exclusive' in result.output
    result = CliRunner().invoke(app, base + ['--record-journal', 'relative'])
    assert result.exit_code != 0
    assert 'absolute' in result.output
    assert not (tmp_path / 'workbench').exists()


class ArithmeticAdapter:
    def __init__(self, config):
        self.calls = 0

    async def stream(self, request):
        from workbench.agent.model import ModelStreamEvent
        self.calls += 1
        if self.calls == 1:
            yield ModelStreamEvent.tool_call_delta(request.request_id, {
                'tool_call_id': 'call-calculate', 'tool_id': 'calculate',
                'arguments': {'calculations': [{'expression': '2 + 3', 'label': 'sum'}]},
            })
            yield ModelStreamEvent.done(request.request_id, finish_reason='tool_calls')
        else:
            yield ModelStreamEvent.text_delta(request.request_id, 'The calculation is supported.')
            yield ModelStreamEvent(type='done', request_id=request.request_id,
                                   usage={'prompt_tokens': 25, 'completion_tokens': 5},
                                   provider_request_id='provider-recorded')


@pytest.mark.parametrize('command', ['run', 'continue'])
def test_strict_cli_replay_recomputes_tools_and_has_no_provider(tmp_path, monkeypatch, command):
    from shutil import copytree
    from workbench import cli_agent
    from workbench.http import agent_routes as routes
    from workbench.agent import numeric_grounding

    calls = []
    calculate = numeric_grounding.calculate
    def counted(values):
        calls.append(values)
        return calculate(values)
    monkeypatch.setattr(numeric_grounding, 'calculate', counted)
    project, journal, initial, args, recorded = _record_existing_session(
        tmp_path, monkeypatch, command=command, adapter=ArithmeticAdapter,
    )
    assert len(calls) == 1
    project.rename(tmp_path / 'recorded-project')
    copytree(initial, project)
    def forbidden(*args, **kwargs):
        raise AssertionError('strict replay must not load config or construct an upstream')
    monkeypatch.setattr(agent_route_runtime, 'load_llm_config', forbidden)
    monkeypatch.setattr(agent_route_runtime, 'OpenAICompatibleModelAdapter', forbidden)
    monkeypatch.setattr(cli_agent, 'OpenAICompatibleModelAdapter', forbidden)
    replayed = CliRunner().invoke(app, args + ['--replay-journal', str(journal)])
    assert replayed.exit_code == 0, (replayed.output, replayed.exception)
    assert len(calls) == 2
    first = json.loads(recorded.stdout.splitlines()[-1])
    second = json.loads(replayed.stdout.splitlines()[-1])
    assert second['assistant']['content'] == first['assistant']['content']
    assert second['status'] == first['status'] == 'idle'
    assert 'provider-recorded' in replayed.stdout
    assert 'prompt_tokens' in replayed.stdout


def test_cli_resume_missing_receipt_never_reexecutes_or_calls_provider(tmp_path, monkeypatch):
    from tests.test_agent_routes import _config
    from workbench import cli_agent
    from workbench.http import agent_routes as routes
    from workbench.agent import numeric_grounding
    from workbench.agent.turn_store import TurnStore

    class ProcessLost(BaseException):
        pass
    effects = []
    def lose_after_effect(values):
        effects.append(values)
        raise ProcessLost()
    monkeypatch.setattr(numeric_grounding, 'calculate', lose_after_effect)
    monkeypatch.setattr(agent_route_runtime, 'load_llm_config', _config)
    monkeypatch.setattr(agent_route_runtime, 'OpenAICompatibleModelAdapter', ArithmeticAdapter)
    session = routes.create_agent_session(str(tmp_path), routes.AgentSessionCreateRequest(role='chain'))['session_id']
    with pytest.raises(ProcessLost):
        asyncio.run(cli_agent.run_headless(tmp_path, 'Inspect evidence.', session_id=session, on_event=lambda _: None))
    [record] = TurnStore(tmp_path).list_active()
    assert record.status == 'interrupted'
    assert len(effects) == 1
    class NoProvider:
        def __init__(self, config):
            pass
        async def stream(self, request):
            raise AssertionError('an unknown receipt must not consume provider budget')
            yield
    monkeypatch.setattr(agent_route_runtime, 'OpenAICompatibleModelAdapter', NoProvider)
    result = CliRunner().invoke(app, ['agent', 'resume', '--project', str(tmp_path),
                                     '--session', session, '--turn', record.turn_id])
    assert result.exit_code != 0
    assert 'AGENT_TURN_RECOVERY_REQUIRED' in result.output
    assert len(effects) == 1
    final = TurnStore(tmp_path).get(record.turn_id)
    assert final.status == 'interrupted' and final.steps_used == record.steps_used


def test_cli_replay_cannot_report_success_without_consuming_recording(tmp_path, monkeypatch):
    from shutil import copytree
    from workbench import cli_agent
    project, journal, initial, args, result = _record_existing_session(tmp_path, monkeypatch)
    project.rename(tmp_path / 'recorded-project')
    copytree(initial, project)
    async def skipped(*args, **kwargs):
        return {'type': 'agent_result', 'status': 'idle', 'assistant': {'content': 'skipped'}}
    monkeypatch.setattr(cli_agent, 'run_headless', skipped)
    result = CliRunner().invoke(app, args + ['--replay-journal', str(journal)])
    assert result.exit_code != 0
    assert 'unconsumed' in result.output
    assert '"type": "agent_result"' not in result.stdout


def test_incomplete_recording_is_not_a_successful_cli_journal(tmp_path, monkeypatch):
    from tests.test_agent_routes import _config
    from workbench import cli_agent
    from workbench.http import agent_routes as routes

    class TruncatedAdapter:
        def __init__(self, config):
            pass
        async def stream(self, request):
            from workbench.agent.model import ModelStreamEvent
            yield ModelStreamEvent.text_delta(request.request_id, 'Incomplete response.')
    project = tmp_path / 'project'
    project.mkdir()
    journal = tmp_path / 'journal'
    journal.mkdir()
    monkeypatch.setattr(agent_route_runtime, 'load_llm_config', _config)
    monkeypatch.setattr(cli_agent, 'OpenAICompatibleModelAdapter', TruncatedAdapter)
    result = CliRunner().invoke(app, ['agent', 'run', '--project', str(project),
                                     '--prompt', 'Inspect.', '--record-journal', str(journal)])
    assert result.exit_code != 0
    assert json.loads((journal / 'runtime.json').read_text())['complete'] is False
    assert '"type": "agent_result"' not in result.stdout


def test_journal_input_drift_is_rejected_before_turn_start(tmp_path, monkeypatch):
    from shutil import copytree
    from workbench import cli_agent
    project, journal, initial, args, result = _record_existing_session(tmp_path, monkeypatch)
    project.rename(tmp_path / 'recorded-project')
    copytree(initial, project)
    def forbidden(*args, **kwargs):
        raise AssertionError('changed input must not start a turn')
    monkeypatch.setattr(cli_agent, 'run_headless', forbidden)
    args[-1] = 'A different question.'
    result = CliRunner().invoke(app, args + ['--replay-journal', str(journal)])
    assert result.exit_code != 0
    assert 'input does not match' in result.output
