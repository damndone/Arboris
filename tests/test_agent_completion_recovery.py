"""Incomplete final drafts recover within the same durable command and budget."""
import asyncio

import pytest

from tests.test_agent_core_restart import setup, ProcessLost
from workbench.agent.model import ModelStreamEvent


def partial():
    return {'status': 'partial', 'missing': ['report:registered_nonempty'],
            'recovery_action': 'inspect_and_repair', 'scientific_validity': 'not_certified'}


class DraftAdapter:
    def __init__(self, *, lose=False):
        self.requests = []
        self.lose = lose

    async def stream(self, request):
        self.requests.append(request)
        if self.lose and len(self.requests) == 2:
            raise ProcessLost()
        yield ModelStreamEvent.text_delta(request.request_id, 'The analysis is saved.')
        yield ModelStreamEvent.done(request.request_id)


def test_partial_final_retries_without_user_nudge_and_preserves_original_budget(tmp_path):
    async def scenario():
        adapter = DraftAdapter(); core, store, repo = setup(tmp_path, adapter)
        core.completion_check = lambda: partial() if len(adapter.requests) == 1 else {
            'status': 'requirements_met', 'missing': [], 'scientific_validity': 'not_certified'}
        await core.prompt('请完成分析和报告', budget={'max_steps': 4, 'timeout_s': 30})
        assert len(adapter.requests) == 2
        assert any(m.get('name') == 'workbench_completion_recovery' for m in adapter.requests[-1].messages)
        assert len([e for e in repo.get_branch('session-a') if e.payload.get('role') == 'user']) == 1
        assert not store.list_active()
        corrections = [e for e in repo.get_branch('session-a') if e.payload.get('message_type') == 'completion_recovery']
        assert len(corrections) == 1 and len(corrections[0].payload['content']) <= 6000
    asyncio.run(scenario())


def test_completion_recovery_stops_after_two_corrections_and_does_not_claim_success(tmp_path):
    async def scenario():
        adapter = DraftAdapter(); core, _, repo = setup(tmp_path, adapter)
        core.completion_check = partial
        answer = await core.prompt('请完成分析和报告', budget={'max_steps': 6, 'timeout_s': 30})
        assert len(adapter.requests) == 3
        assert '部分完成' in answer
        assert len([e for e in repo.get_branch('session-a') if e.payload.get('message_type') == 'completion_recovery']) == 2
    asyncio.run(scenario())


def test_restart_keeps_completion_recovery_count_and_never_resets_budget(tmp_path):
    async def scenario():
        adapter = DraftAdapter(lose=True); core, store, repo = setup(tmp_path, adapter)
        core.completion_check = partial
        with pytest.raises(ProcessLost):
            await core.prompt('请完成分析和报告', budget={'max_steps': 5, 'timeout_s': 30})
        [turn] = store.list_active()
        assert turn.steps_used == 2
        adapter2 = DraftAdapter(); resumed, fresh, repository = setup(tmp_path, adapter2, create=False)
        resumed.completion_check = partial
        await resumed.resume(turn.turn_id)
        assert len(adapter2.requests) == 2  # replay original correction, one correction remains
        assert fresh.get(turn.turn_id).steps_used == 4
        assert len([e for e in repository.get_branch('session-a') if e.payload.get('message_type') == 'completion_recovery']) == 2
    asyncio.run(scenario())


@pytest.mark.parametrize('question', ['解释这个系数', 'What does this standard error mean?',
                                    '停止分析', 'Stop the analysis', '请暂停'])
def test_recovery_does_not_hijack_a_new_question_or_stop_request(tmp_path, question):
    from workbench.canonical import sha256_canonical
    async def scenario():
        adapter = DraftAdapter(); core, _, repo = setup(tmp_path, adapter)
        core.completion_check = lambda: {**partial(),
            'recovery_question_sha256': sha256_canonical('请完成原分析和报告')}
        await core.prompt(question, budget={'max_steps': 5, 'timeout_s': 30})
        assert len(adapter.requests) == 1
        assert not any(e.payload.get('message_type') == 'completion_recovery'
                       for e in repo.get_branch('session-a'))
    asyncio.run(scenario())


@pytest.mark.parametrize('question', ['请完成原分析和报告', '继续分析', 'Continue the analysis'])
def test_recovery_accepts_the_original_question_or_explicit_continuation(tmp_path, question):
    from workbench.canonical import sha256_canonical
    async def scenario():
        adapter = DraftAdapter(); core, _, _ = setup(tmp_path, adapter)
        core.completion_check = lambda: {**partial(),
            'recovery_question_sha256': sha256_canonical('请完成原分析和报告')}
        await core.prompt(question, budget={'max_steps': 5, 'timeout_s': 30})
        assert len(adapter.requests) == 3
    asyncio.run(scenario())


@pytest.mark.parametrize('stop_reason,missing,action', [
    ('proposal_ready', ['report:registered_nonempty'], 'inspect_and_repair'),
    ('stop', ['iv:diagnostics:ar_empty'], None)])
def test_recovery_never_overrides_approval_or_scientific_failures(tmp_path, stop_reason, missing, action):
    from types import SimpleNamespace
    from workbench.agent.recovery import prepare_completion_recovery
    adapter = DraftAdapter(); core, _, repo = setup(tmp_path, adapter)
    core._has_step_left = lambda: True
    assert not prepare_completion_recovery(core, {'stop_reason': stop_reason,
        'completion_check': {**partial(), 'missing': missing, 'recovery_action': action}},
        SimpleNamespace(entry_id='not-a-repair'))
    assert not any(e.payload.get('message_type') == 'completion_recovery'
                   for e in repo.get_branch('session-a'))
