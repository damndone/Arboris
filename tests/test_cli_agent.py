"""Headless Agent uses the same core, events and refusal path as HTTP."""
from __future__ import annotations
from workbench.http import agent_analysis_routes, agent_route_runtime

import json

import pytest
from typer.testing import CliRunner

from tests.test_agent_routes import FakeAgentAdapter, _config
from workbench.cli import app


def test_headless_agent_persists_and_streams_the_server_events(tmp_path, monkeypatch):
    from workbench.http import agent_routes
    monkeypatch.setattr(agent_route_runtime, 'load_llm_config', _config)
    monkeypatch.setattr(agent_route_runtime, 'OpenAICompatibleModelAdapter', FakeAgentAdapter)
    project = tmp_path / 'project'
    project.mkdir()
    event_file = tmp_path / 'events.jsonl'
    result = CliRunner().invoke(app, ['agent', 'run', '--project', str(project),
                                     '--prompt', 'Inspect the available evidence.',
                                     '--events-jsonl', str(event_file)])
    assert result.exit_code == 0, result.output
    lines = [json.loads(line) for line in result.stdout.splitlines()]
    receipt = lines[-1]
    assert receipt['type'] == 'agent_result'
    assert receipt['session_id']
    assert receipt['assistant']['content'] == '已读取当前分析上下文。'
    events = [json.loads(line) for line in event_file.read_text().splitlines()]
    assert [item['seq'] for item in events] == list(range(1, len(events) + 1))
    assert 'agent_end' in {item['event_type'] for item in events}
    assert lines[:-1] == events
    assert list((project / 'workbench/agent-sessions').glob('*.jsonl'))


def test_headless_refuses_bad_mode_before_creating_a_session(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    result = CliRunner().invoke(app, ['agent', 'run', '--project', str(project),
                                     '--prompt', 'Inspect.', '--mode', 'unrestricted'])
    assert result.exit_code != 0
    assert '--mode must be ask or auto' in result.output
    assert not (project / 'workbench').exists()


def test_headless_does_not_overwrite_event_evidence(tmp_path):
    project = tmp_path / 'project'
    project.mkdir()
    evidence = tmp_path / 'events.jsonl'
    evidence.write_text('prior evidence\n')
    result = CliRunner().invoke(app, ['agent', 'run', '--project', str(project),
                                     '--prompt', 'Inspect.', '--events-jsonl', str(evidence)])
    assert result.exit_code != 0
    assert 'File exists' in result.output
    assert evidence.read_text() == 'prior evidence\n'
    assert not (project / 'workbench').exists()


@pytest.mark.parametrize('mode', ['ask', 'auto'])
def test_headless_returns_pending_approval_without_confirming_it(tmp_path, monkeypatch, mode):
    from tests.test_read_only_analysis import _Fixture, _recode
    from workbench.http import agent_routes
    fixture = _Fixture(tmp_path)
    pending = fixture.propose([_recode()])
    assert pending['requires_confirmation'] is True
    monkeypatch.setattr(agent_route_runtime, 'load_llm_config', _config)
    monkeypatch.setattr(agent_route_runtime, 'OpenAICompatibleModelAdapter', FakeAgentAdapter)
    result = CliRunner().invoke(app, ['agent', 'run', '--project', str(fixture.project_root),
                                     '--session', 'chain-session', '--prompt', 'Inspect.', '--mode', mode])
    assert result.exit_code == 3, result.output
    receipt = json.loads(result.stdout.splitlines()[-1])
    assert receipt['status'] == 'awaiting_approval'
    assert receipt['pending_proposals']
    assert fixture.orchestrator.operation_store.list_records() == []
    for item in receipt['pending_proposals']:
        assert fixture.orchestrator.proposal_store.latest_confirmation(item['proposal_id']) is None


def test_headless_does_not_report_an_unapproved_auto_plan_as_done(tmp_path, monkeypatch):
    from tests.test_read_only_analysis import _Fixture
    from workbench.agent import plans
    from workbench.http import agent_routes
    fixture = _Fixture(tmp_path)
    plan = plans.merge(None, question='q', criteria=['c'], budget=None, allowed_classes=None,
                       steps=(plans.PlanStep('fit', 'Fit model', ('model.genesis',)),))
    fixture.orchestrator.plan_store.save('chain-session', plan)
    monkeypatch.setattr(agent_route_runtime, 'load_llm_config', _config)
    monkeypatch.setattr(agent_route_runtime, 'OpenAICompatibleModelAdapter', FakeAgentAdapter)
    result = CliRunner().invoke(app, ['agent', 'run', '--project', str(fixture.project_root),
                                     '--session', 'chain-session', '--prompt', 'Inspect.', '--mode', 'auto'])
    assert result.exit_code == 3, result.output
    receipt = json.loads(result.stdout.splitlines()[-1])
    assert receipt['status'] == 'awaiting_plan_approval'
    assert receipt['plan']['approved_version'] is None


def test_headless_plan_approval_checks_version_without_provider_calls(tmp_path, monkeypatch):
    from tests.test_read_only_analysis import _Fixture
    from workbench.agent import plans
    from workbench.http import agent_routes

    fixture = _Fixture(tmp_path)
    plan = plans.merge(None, question='q', criteria=['c'], budget=None, allowed_classes=None,
                       steps=(plans.PlanStep('fit', 'Fit model', ('model.genesis',)),))
    fixture.orchestrator.plan_store.save('chain-session', plan)

    def no_provider(*args, **kwargs):
        raise AssertionError('Explicit plan approval must not load or call a provider')

    monkeypatch.setattr(agent_route_runtime, 'load_llm_config', no_provider)
    monkeypatch.setattr(agent_route_runtime, 'OpenAICompatibleModelAdapter', no_provider)
    arguments = ['agent', 'plan-approve', '--project', str(fixture.project_root), '--session', 'chain-session']
    stale = CliRunner().invoke(app, [*arguments, '--version', str(plan.version + 1)])
    assert stale.exit_code != 0
    assert 'AGENT_PLAN_CHANGED' in stale.output
    assert fixture.orchestrator.plan_store.current('chain-session').approved_version is None
    approved = CliRunner().invoke(app, [*arguments, '--version', str(plan.version)])
    assert approved.exit_code == 0, approved.output
    receipt = json.loads(approved.stdout)
    assert receipt['plan']['status'] == 'approved'
    assert receipt['plan']['approved_version'] == plan.version
    assert fixture.orchestrator.operation_store.list_records() == []


def test_headless_continue_streams_events_and_uses_the_server_continuation_note(tmp_path, monkeypatch):
    from workbench.http import agent_routes
    monkeypatch.setattr(agent_route_runtime, 'load_llm_config', _config)
    monkeypatch.setattr(agent_route_runtime, 'OpenAICompatibleModelAdapter', FakeAgentAdapter)
    project = tmp_path / 'project'
    project.mkdir()
    runner = CliRunner()
    first = runner.invoke(app, ['agent', 'run', '--project', str(project), '--prompt', 'Inspect.'])
    assert first.exit_code == 0, first.output
    session_id = json.loads(first.stdout.splitlines()[-1])['session_id']
    event_file = tmp_path / 'continued.jsonl'
    resumed = runner.invoke(app, ['agent', 'continue', '--project', str(project), '--session', session_id,
                                  '--mode', 'ask', '--events-jsonl', str(event_file)])
    assert resumed.exit_code == 0, resumed.output
    output = [json.loads(line) for line in resumed.stdout.splitlines()]
    assert output[-1]['type'] == 'agent_result'
    assert output[-1]['session_id'] == session_id
    events = [json.loads(line) for line in event_file.read_text().splitlines()]
    assert output[:-1] == events
    assert [item['seq'] for item in events] == list(range(1, len(events) + 1))
    note = FakeAgentAdapter.instances[-1].requests[0].messages[-1]
    assert note['role'] == 'user'
    assert note['content'] == agent_routes.CONTINUATION_NOTE
    loaded = agent_routes.get_agent_session(session_id, str(project))
    assert [message['role'] for message in loaded['messages']] == ['user', 'assistant', 'assistant']


@pytest.mark.parametrize('mode', ['ask', 'auto'])
def test_headless_continue_keeps_pending_cards_unconfirmed(tmp_path, monkeypatch, mode):
    from tests.test_read_only_analysis import _Fixture, _recode
    from workbench.http import agent_routes
    fixture = _Fixture(tmp_path)
    pending = fixture.propose([_recode()])
    monkeypatch.setattr(agent_route_runtime, 'load_llm_config', _config)
    monkeypatch.setattr(agent_route_runtime, 'OpenAICompatibleModelAdapter', FakeAgentAdapter)
    result = CliRunner().invoke(app, ['agent', 'continue', '--project', str(fixture.project_root),
                                     '--session', 'chain-session', '--mode', mode])
    assert result.exit_code == 3, result.output
    receipt = json.loads(result.stdout.splitlines()[-1])
    assert receipt['status'] == 'awaiting_approval'
    assert any(item['proposal_id'] == pending['proposal']['proposal_id'] for item in receipt['pending_proposals'])
    assert fixture.orchestrator.operation_store.list_records() == []
    assert fixture.orchestrator.proposal_store.latest_confirmation(pending['proposal']['proposal_id']) is None


def test_headless_continue_does_not_approve_an_auto_plan(tmp_path, monkeypatch):
    from tests.test_read_only_analysis import _Fixture
    from workbench.agent import plans
    from workbench.http import agent_routes
    fixture = _Fixture(tmp_path)
    plan = plans.merge(None, question='q', criteria=['c'], budget=None, allowed_classes=None,
                       steps=(plans.PlanStep('fit', 'Fit model', ('model.genesis',)),))
    fixture.orchestrator.plan_store.save('chain-session', plan)
    monkeypatch.setattr(agent_route_runtime, 'load_llm_config', _config)
    monkeypatch.setattr(agent_route_runtime, 'OpenAICompatibleModelAdapter', FakeAgentAdapter)
    result = CliRunner().invoke(app, ['agent', 'continue', '--project', str(fixture.project_root),
                                     '--session', 'chain-session', '--mode', 'auto'])
    assert result.exit_code == 3, result.output
    receipt = json.loads(result.stdout.splitlines()[-1])
    assert receipt['status'] == 'awaiting_plan_approval'
    assert receipt['plan']['approved_version'] is None


def test_headless_continue_retains_project_permission_denials(tmp_path, monkeypatch):
    from tests.test_agent_routes import ProposingAdapter
    from tests.test_read_only_analysis import _Fixture, _recode
    from workbench.http import agent_routes
    fixture = _Fixture(tmp_path)
    proposal = fixture.propose([_recode()])['proposal']
    ProposingAdapter.proposal_arguments = {
        key: proposal[key] for key in ('operation_id', 'operation_version', 'target', 'preconditions', 'changes',
                                      'evidence_refs', 'expected_effect', 'risks')
    }
    (fixture.project_root / 'workbench/agent-permissions.json').write_text(json.dumps({'deny': [{'class': 'derive'}]}))
    monkeypatch.setattr(agent_route_runtime, 'load_llm_config', _config)
    monkeypatch.setattr(agent_route_runtime, 'OpenAICompatibleModelAdapter', ProposingAdapter)
    result = CliRunner().invoke(app, ['agent', 'continue', '--project', str(fixture.project_root),
                                     '--session', 'chain-session', '--mode', 'auto'])
    assert result.exit_code == 3, result.output
    entries = fixture.repository.get_branch('chain-session')
    tool_results = [json.loads(entry.payload['content']) for entry in entries
                    if entry.entry_type == 'message' and entry.payload.get('role') == 'tool']
    assert tool_results[-1]['output']['denied'] is True
    assert fixture.orchestrator.operation_store.list_records() == []
    assert fixture.repository.get_metadata('chain-session')['execution_mode'] == 'auto'


@pytest.mark.parametrize('continuation', [False, True])
@pytest.mark.parametrize('blocked_at', ['provider', 'tool'])
def test_broken_event_sink_drains_original_owned_turn_despite_repeated_cancellation(
    tmp_path, monkeypatch, continuation, blocked_at,
):
    import asyncio
    from dataclasses import replace
    from tests.test_agent_routes import _context_packet
    from workbench.agent.model import ModelStreamEvent
    from workbench.agent.tools import ToolDefinition
    from workbench.cli_agent import run_headless, continue_headless
    from workbench.http import agent_routes as routes

    async def scenario():
        started, output_failed, aborted, release = (asyncio.Event() for _ in range(4))
        completed = []
        calls = []
        original_error = OSError('original broken output')

        async def blocking_inspection(arguments, context):
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                aborted.set()
                # Mimic an operation that must finish binding its effect before
                # cancellation can release the active tool and turn ownership.
                await release.wait()
            completed.append('effect-bound')
            return {'completed': True}

        class BlockingProvider:
            def __init__(self, config):
                pass
            async def stream(self, request):
                calls.append(request)
                if blocked_at == 'provider':
                    started.set()
                    await request.abort_event.wait()
                    aborted.set()
                    await release.wait()
                else:
                    yield ModelStreamEvent.tool_call_delta(request.request_id, {
                        'tool_call_id': 'blocking-read', 'tool_id': 'inspect_blocking', 'arguments': {},
                    })
                yield ModelStreamEvent.done(request.request_id, 'tool_calls' if blocked_at == 'tool' else 'stop')

        monkeypatch.setattr(agent_route_runtime, 'load_llm_config', lambda: replace(_config(), context_window_tokens=128_000))
        monkeypatch.setattr(agent_route_runtime, 'OpenAICompatibleModelAdapter', BlockingProvider)
        monkeypatch.setattr(agent_analysis_routes.NodeOperationContextProvider, 'tool_definitions', lambda *args, **kwargs: [
            ToolDefinition('inspect_blocking', 'v1', {'type': 'object'}, 'none', blocking_inspection),
        ])
        project = tmp_path / 'project'
        project.mkdir()
        session = routes.create_agent_session(str(project), routes.AgentSessionCreateRequest(
            role='chain', chain_id='chain-a', run_id='run-a', context_packet=_context_packet(),
        ))['session_id']
        emitted = []
        def broken_sink(event):
            if started.is_set():
                output_failed.set()
                # A second output attempt must not replace the first error.
                if emitted:
                    raise OSError('secondary broken output')
                emitted.append(event)
                raise original_error

        if continuation:
            work = continue_headless(project, session, on_event=broken_sink)
        else:
            work = run_headless(project, 'Inspect once.', session_id=session, on_event=broken_sink)
        runner = asyncio.create_task(work)
        key = routes._active_turn_key(project, session)
        try:
            await asyncio.wait_for(output_failed.wait(), 2)
            await asyncio.wait_for(aborted.wait(), 2)
            owned = routes.turn_registry.tasks[key]
            core = routes.turn_registry.get(project, session)
            await asyncio.sleep(0)
            assert not runner.done(), 'CLI cleanup returned before its owned turn drained'
            for _ in range(2):
                runner.cancel()
                await asyncio.sleep(0)
                assert not runner.done(), 'repeated cancellation bypassed the drain'
                assert routes.turn_registry.get(project, session) is core
                assert key in routes.turn_registry.tasks and key in routes.turn_registry.reserved
            release.set()
            with pytest.raises(OSError) as caught:
                await runner
            assert caught.value is original_error
            await asyncio.sleep(0)
            assert owned.done()
            assert key not in routes.turn_registry.tasks and key not in routes.turn_registry.reserved
            assert routes.turn_registry.get(project, session) is None
            assert len(calls) == 1  # Cleanup must never start another turn.
            if blocked_at == 'tool':
                assert completed == ['effect-bound']
        finally:
            release.set()
            await asyncio.gather(runner, return_exceptions=True)
            owned = routes.turn_registry.tasks.get(key)
            if owned is not None:
                await asyncio.gather(owned, return_exceptions=True)

    asyncio.run(scenario())
