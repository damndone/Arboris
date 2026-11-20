"""Local notifications use real durable turns and entirely mocked OS delivery."""
import asyncio
import importlib.util
from types import SimpleNamespace

import pytest

from tests.test_agent_core_restart import Adapter, setup
from workbench.agent.model import ModelStreamEvent
from workbench.agent.plans import Plan, PlanStore
from workbench.agent.turn_runtime import TurnRegistry


def test_notification_owner_exists():
    assert importlib.util.find_spec('workbench.agent.desktop_notifications') is not None


@pytest.fixture
def notifications(monkeypatch):
    from workbench.agent import desktop_notifications
    monkeypatch.setattr(desktop_notifications, 'send_on_mac', lambda kind: pytest.fail('real notification forbidden'))
    return desktop_notifications


def receipts(repo):
    return [e.payload for e in repo.get_branch('session-a') if e.entry_type == 'desktop_notification_result']


def test_default_disabled_and_explicit_session_preference(notifications, tmp_path, monkeypatch):
    async def scenario():
        sent = []
        monkeypatch.setattr(notifications, 'send_on_mac', sent.append)
        core, _, repo = setup(tmp_path, Adapter())
        await core.prompt('First.', budget={'max_steps': 1, 'timeout_s': 10})
        assert not notifications._tasks and sent == [] and receipts(repo) == []
        repo.update_metadata('session-a', desktop_notifications=True)
        await core.prompt('Second.', budget={'max_steps': 1, 'timeout_s': 10})
        await asyncio.gather(*notifications._tasks)
        assert sent == ['turn_ended']
        assert receipts(repo)[0]['status'] == 'submitted'
        assert 'delivered' not in receipts(repo)[0]
    asyncio.run(scenario())


def test_closed_waiter_keeps_original_work_and_notifies_after_durable_terminal(notifications, tmp_path, monkeypatch):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        class PausedAdapter:
            async def stream(self, request):
                entered.set()
                await release.wait()
                yield ModelStreamEvent.text_delta(request.request_id, 'Finished turn.')
                yield ModelStreamEvent.done(request.request_id)
        core, store, repo = setup(tmp_path, PausedAdapter())
        repo.update_metadata('session-a', desktop_notifications=True)
        observed = []
        def send(kind):
            observed.append((kind, store.get(core.turn_journal.record.turn_id).status))
        monkeypatch.setattr(notifications, 'send_on_mac', send)
        registry = TurnRegistry()
        key = registry.reserve(tmp_path, 'session-a')
        waiter = asyncio.create_task(registry.run_owned(key,
            lambda: core.prompt('One original turn.', budget={'max_steps': 1, 'timeout_s': 10})))
        await entered.wait()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert observed == []
        owned = registry.tasks[key]
        release.set()
        await owned
        await asyncio.gather(*notifications._tasks)
        assert observed == [('turn_ended', 'completed')]
        assert len(receipts(repo)) == 1
    asyncio.run(scenario())


def test_tool_boundary_never_sends_a_completion_notification(notifications, tmp_path, monkeypatch):
    from workbench.agent.tools import ToolResult
    async def scenario():
        reached_second, finish = asyncio.Event(), asyncio.Event()
        sent = []
        monkeypatch.setattr(notifications, 'send_on_mac', sent.append)
        class ReadingAdapter:
            calls = 0
            async def stream(self, request):
                self.calls += 1
                if self.calls == 1:
                    yield ModelStreamEvent.tool_call_delta(request.request_id,
                        {'tool_call_id': 'read-a', 'tool_id': 'read', 'arguments': {}})
                    yield ModelStreamEvent.done(request.request_id, 'tool_calls')
                else:
                    reached_second.set()
                    await finish.wait()
                    yield ModelStreamEvent.text_delta(request.request_id, 'Read complete.')
                    yield ModelStreamEvent.done(request.request_id)
        class Reader:
            async def execute(self, call, **kwargs):
                return ToolResult(tool_call_id=call['tool_call_id'], tool_id='read', ok=True, output={'read': True})
        core, _, repo = setup(tmp_path, ReadingAdapter(), runtime=Reader())
        repo.update_metadata('session-a', desktop_notifications=True)
        work = asyncio.create_task(core.prompt('Read.', budget={'max_steps': 2, 'timeout_s': 10}))
        await reached_second.wait()
        assert sent == [] and receipts(repo) == []
        finish.set()
        await work
        await asyncio.gather(*notifications._tasks)
        assert sent == ['turn_ended']
    asyncio.run(scenario())


@pytest.mark.parametrize('pending', [True, False])
def test_only_a_real_pending_plan_selects_approval_wording(notifications, tmp_path, monkeypatch, pending):
    async def scenario():
        sent = []
        monkeypatch.setattr(notifications, 'send_on_mac', sent.append)
        core, _, repo = setup(tmp_path, Adapter())
        core.turn_journal.execution_mode = 'auto'
        repo.update_metadata('session-a', desktop_notifications=True)
        PlanStore(repo.root).save('session-a', Plan(plan_id='p', version=2,
            status='needs_approval' if pending else 'approved', approved_version=1 if pending else 2,
            question='Private project question', criteria=(), steps=(), allowed_classes=()))
        await core.prompt('Needs approval! Analysis complete!', budget={'max_steps': 1, 'timeout_s': 10})
        await asyncio.gather(*notifications._tasks)
        assert sent == ['approval_required' if pending else 'turn_ended']
    asyncio.run(scenario())


def test_send_failure_is_durable_and_restart_never_retries_automatically(notifications, tmp_path, monkeypatch):
    import subprocess
    async def scenario():
        def fail(kind):
            raise subprocess.TimeoutExpired('/usr/bin/osascript', 2)
        monkeypatch.setattr(notifications, 'send_on_mac', fail)
        core, store, repo = setup(tmp_path, Adapter())
        repo.update_metadata('session-a', desktop_notifications=True)
        await core.prompt('Private text.', budget={'max_steps': 1, 'timeout_s': 10})
        await asyncio.gather(*notifications._tasks)
        record = core.turn_journal.record
        assert store.get(record.turn_id).status == 'completed'
        assert receipts(repo)[0]['status'] == 'failed'
        assert receipts(repo)[0]['automatic_retry'] is False
        assert receipts(repo)[0]['error_type'] == 'TimeoutExpired'
        assert 'Private text' not in str(receipts(repo))
        _, _, fresh = setup(tmp_path, Adapter(), create=False)
        monkeypatch.setattr(notifications, 'send_on_mac', lambda kind: pytest.fail('restart must not resend'))
        assert notifications.schedule_notification(fresh, record) is None
        assert len(receipts(fresh)) == 1
    asyncio.run(scenario())


def test_real_pending_proposal_selects_approval_wording(notifications, tmp_path, monkeypatch):
    from workbench.agent.proposals import ProposalStore
    async def scenario():
        sent = []
        monkeypatch.setattr(notifications, 'send_on_mac', sent.append)
        core, _, repo = setup(tmp_path, Adapter())
        repo.update_metadata('session-a', desktop_notifications=True)
        ProposalStore(repo.root).create(session_id='session-a', chain_id='chain-a',
            operation_id='graph.fork', target={'run_id': 'run-a', 'node_ref': 'stage:source'},
            preconditions={}, changes={}, evidence_refs=[], expected_effect=[], risks=[])
        await core.prompt('Review pending work.', budget={'max_steps': 1, 'timeout_s': 10})
        await asyncio.gather(*notifications._tasks)
        assert sent == ['approval_required']
    asyncio.run(scenario())


def test_unknown_attempt_is_retained_and_never_auto_reissued(notifications, tmp_path, monkeypatch):
    async def scenario():
        core, _, repo = setup(tmp_path, Adapter())
        await core.prompt('An existing turn.', budget={'max_steps': 1, 'timeout_s': 10})
        record = core.turn_journal.record
        repo.update_metadata('session-a', desktop_notifications=True)
        repo.append_once('session-a', 'desktop_notification_attempt', {
            'turn_id': record.turn_id, 'command_id': record.command_id, 'kind': 'turn_ended',
            'status': 'unknown', 'automatic_retry': False,
        }, key=record.turn_id, stage='desktop_notification_attempt')
        _, _, fresh = setup(tmp_path, Adapter(), create=False)
        assert notifications.schedule_notification(fresh, record) is None
        assert receipts(fresh) == []
        from workbench.agent.conversations import summary
        assert summary(fresh, fresh.get_metadata('session-a'))['desktop_notification_status'] == 'unknown'
    asyncio.run(scenario())


def test_disabling_before_dispatch_cancels_the_notice_without_replaying_work(notifications, tmp_path):
    async def scenario():
        core, _, repo = setup(tmp_path, Adapter())
        repo.update_metadata('session-a', desktop_notifications=True)
        await core.prompt('One turn.', budget={'max_steps': 1, 'timeout_s': 10})
        repo.update_metadata('session-a', desktop_notifications=False)
        await asyncio.gather(*notifications._tasks)
        assert receipts(repo)[0]['status'] == 'disabled'
    asyncio.run(scenario())


def test_sender_uses_fixed_script_argv_timeout_and_reports_nonzero_exit(monkeypatch):
    from workbench.agent import desktop_notifications as notifications
    monkeypatch.setattr(notifications.sys, 'platform', 'darwin')
    calls = []
    monkeypatch.setattr(notifications.subprocess, 'run', lambda args, **kwargs:
        calls.append((args, kwargs)) or SimpleNamespace(returncode=0))
    notifications.send_on_mac('approval_required')
    args, options = calls[0]
    assert args[:2] == ['/usr/bin/osascript', '-e']
    assert 'on run argv' in args[2] and 'display notification' in args[2]
    assert args[-1] == notifications.NOTICES['approval_required']
    assert options['timeout'] <= 3 and options.get('shell', False) is False
    monkeypatch.setattr(notifications.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1))
    with pytest.raises(OSError):
        notifications.send_on_mac('turn_ended')


def test_conversation_patch_explicit_bool_is_the_only_product_opt_in(notifications, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from workbench.app import app
    from workbench.agent.session import JsonlSessionRepository
    root = tmp_path / 'project'
    repo = JsonlSessionRepository(root / 'workbench')
    repo.create_session('session-a', chain_id='c', role='chain')
    repo.append('session-a', 'message', {'role': 'user', 'content': 'Question'})
    monkeypatch.setattr(notifications, 'supported', lambda: True)
    with TestClient(app) as client:
        params = {'project_root': str(root)}
        item = client.get('/agent/conversations', params=params).json()['conversations'][0]
        assert item['desktop_notifications'] is False
        route = '/agent/conversations/session-a'
        assert client.patch(route, params=params, json={'desktop_notifications': 'yes'}).status_code == 422
        enabled = client.patch(route, params=params, json={'desktop_notifications': True})
        assert enabled.status_code == 200 and enabled.json()['desktop_notifications'] is True
        assert repo.get_metadata('session-a')['desktop_notifications'] is True
        disabled = client.patch(route, params=params, json={'desktop_notifications': False})
        assert disabled.status_code == 200 and disabled.json()['desktop_notifications'] is False
