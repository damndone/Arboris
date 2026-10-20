"""Two failed attempts pause the real common Core, including after restart."""
import asyncio

import pytest

from tests.test_agent_core_restart import ProcessLost, setup
from workbench.agent.model import ModelStreamEvent
from workbench.agent.tools import ToolResult


class RetryAdapter:
    def __init__(self, *, lost_after_first=False):
        self.calls = 0
        self.lost_after_first = lost_after_first

    async def stream(self, request):
        self.calls += 1
        if self.lost_after_first and self.calls == 2:
            raise ProcessLost()
        call = {'tool_call_id': f'fit-{self.calls}', 'tool_id': 'run_operation',
                'arguments': {'operation_id': 'time_series.arima',
                    'target': {'run_id': 'source', 'artifact_id': 'data'},
                    'changes': {'order': [self.calls, 0, 0]}}}
        yield ModelStreamEvent.tool_call_delta(request.request_id, call)
        yield ModelStreamEvent.done(request.request_id, 'tool_calls')


class FailingRuntime:
    def __init__(self, *, receipt=False):
        self.calls = 0
        self.receipt = receipt

    async def execute(self, call, **kwargs):
        self.calls += 1
        return ToolResult(tool_call_id=call['tool_call_id'], tool_id=call['tool_id'],
            ok=self.receipt, error=None if self.receipt else 'invalid_arguments',
            error_details=None if self.receipt else [{'message': 'The series is too short for this order.'}],
            output={'executed': True, 'operation': {'status': 'failed', 'error': 'singular design'}} if self.receipt else None)


@pytest.mark.parametrize('receipt', [False, True])
def test_second_failure_stops_without_a_third_provider_or_tool_call(tmp_path, receipt):
    async def scenario():
        adapter, runtime = RetryAdapter(), FailingRuntime(receipt=receipt)
        core, store, repo = setup(tmp_path, adapter, runtime=runtime)
        answer = await core.prompt('完成分析', budget={'max_steps': 6, 'timeout_s': 30})
        assert runtime.calls == adapter.calls == 2
        assert '2' in answer and ('原因' in answer or '失败' in answer)
        assert '选项' in answer and '部分完成' in answer
        failures = [e for e in repo.get_branch('session-a') if e.entry_type == 'analysis_step_failure']
        assert len(failures) == 2
        assert core.phase == 'idle'
        assert repo.get_metadata('session-a')['status'] == 'blocked'
        terminal = [e for e in repo.get_branch('session-a') if e.payload.get('error') == 'analysis_recovery_limit']
        assert len(terminal) == 1
        assert not store.list_active()
    asyncio.run(scenario())


def test_restart_preserves_first_failure_and_replay_does_not_count_it_twice(tmp_path):
    async def scenario():
        runtime = FailingRuntime()
        core, store, repo = setup(tmp_path, RetryAdapter(lost_after_first=True), runtime=runtime)
        with pytest.raises(ProcessLost):
            await core.prompt('完成分析', budget={'max_steps': 6, 'timeout_s': 30})
        assert runtime.calls == 1
        [turn] = store.list_active()
        adapter = RetryAdapter()
        resumed, fresh, repository = setup(tmp_path, adapter, runtime=runtime, create=False)
        answer = await resumed.resume(turn.turn_id)
        assert runtime.calls == 2 and adapter.calls == 1
        assert '部分完成' in answer
        assert len([e for e in repository.get_branch('session-a') if e.entry_type == 'analysis_step_failure']) == 2
        assert fresh.get(turn.turn_id).status == 'failed'
    asyncio.run(scenario())


def test_original_failure_receipt_replay_does_not_double_count_or_change_receipt(tmp_path, monkeypatch):
    async def scenario():
        runtime = FailingRuntime()
        core, store, repo = setup(tmp_path, RetryAdapter(), runtime=runtime)
        original = repo.append_once
        def lost_before_message(*args, **kwargs):
            if kwargs.get('stage') == 'tool_result':
                raise ProcessLost()
            return original(*args, **kwargs)
        monkeypatch.setattr(repo, 'append_once', lost_before_message)
        with pytest.raises(ProcessLost):
            await core.prompt('完成分析', budget={'max_steps': 6, 'timeout_s': 30})
        [turn] = store.list_active()
        resumed, fresh, repository = setup(tmp_path, RetryAdapter(), runtime=runtime, create=False)
        assert '部分完成' in await resumed.resume(turn.turn_id)
        assert runtime.calls == 2
        failures = [e for e in repository.get_branch('session-a') if e.entry_type == 'analysis_step_failure']
        assert len(failures) == 2
        receipts = [e for e in repository.get_branch('session-a') if e.payload.get('role') == 'tool']
        assert len(receipts) == 2
    asyncio.run(scenario())


def test_remaining_tools_in_a_failed_batch_get_nonexecution_receipts(tmp_path):
    class BatchAdapter:
        async def stream(self, request):
            for i in range(3):
                yield ModelStreamEvent.tool_call_delta(request.request_id, {'tool_call_id': f'fit-{i}',
                    'tool_id': 'run_operation', 'arguments': {'operation_id': 'fit', 'changes': {'p': i}}})
            yield ModelStreamEvent.done(request.request_id, 'tool_calls')
    async def scenario():
        runtime = FailingRuntime()
        core, store, repo = setup(tmp_path, BatchAdapter(), runtime=runtime)
        await core.prompt('完成分析', budget={'max_steps': 6, 'timeout_s': 30})
        assert runtime.calls == 2
        receipts = [e for e in repo.get_branch('session-a') if e.payload.get('role') == 'tool']
        assert len(receipts) == 3
        assert 'analysis_recovery_limit' in receipts[-1].payload['content']
    asyncio.run(scenario())


def test_unrelated_operations_do_not_share_a_failure_budget(tmp_path):
    from workbench.agent.recovery import record_failure
    from workbench.agent.session import JsonlSessionRepository
    repository = JsonlSessionRepository(tmp_path)
    repository.create_session('s', chain_id='c', role='chain')
    for i, op in enumerate(['time_series.arima', 'time_series.garch', 'time_series.arima']):
        result = record_failure(repository, 's', 'command', i, {'tool_call_id': str(i), 'tool_id': 'run_operation',
            'arguments': {'operation_id': op, 'changes': {'order': i}}}, {'ok': False, 'error': 'bad fit'})
        assert result['attempts'] == (2 if i == 2 else 1)
        assert result['exhausted'] is (i == 2)
