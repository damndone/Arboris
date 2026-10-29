"""Stopped analysis turns retain checked sources, real failures and the delivery gap."""
import asyncio

import pytest

from tests.test_agent_core_restart import setup
from workbench.agent.delivery import delivery_digest, delivery_lines
from workbench.agent.model import ModelStreamEvent
from workbench.agent.tools import ToolResult


SOURCE = {'run_id': 'source-run', 'artifact_id': 'registered_data', 'sha256': 'a' * 64}


def partial(family='iv'):
    return {'status': 'partial', 'missing': [f'{family}:diagnostics:computed_and_model_bound',
            'report:registered_nonempty'], 'verified_artifacts': [SOURCE],
            'scientific_validity': 'not_certified'}


def test_operation_delivery_digest_preserves_exact_checked_sources():
    check = {**partial(), 'evidence_catalog': {'models': ['large inspection only']}}
    digest = delivery_digest(check)
    assert digest['verified_artifacts'] == [SOURCE]
    assert digest['scientific_validity'] == 'not_certified'
    assert 'evidence_catalog' not in digest
    text = '\n'.join(delivery_lines(digest))
    assert 'source-run' in text and 'registered_data' in text
    assert 'not scientific certification' in text


def test_output_truncation_publishes_checked_gaps_without_certifying_the_draft(tmp_path):
    class Limited:
        requests = 0

        async def stream(self, request):
            self.requests += 1
            yield ModelStreamEvent.text_delta(request.request_id, 'IV 草稿，数字尚未核验。')
            yield ModelStreamEvent.done(request.request_id, 'length')

    adapter = Limited()
    core, store, repository = setup(tmp_path, adapter)
    core.completion_check = partial
    answer = asyncio.run(core.prompt('请完整分析并汇报。', budget={'max_steps': 3, 'timeout_s': 30}))
    assert answer.startswith('部分完成')
    assert 'registered_data' in answer and '缺少已计算且绑定主模型的诊断' in answer
    assert 'IV 草稿' in answer and '数字尚未核验' in answer
    assert '输出上限' in answer and '下一步建议' in answer
    assert adapter.requests == 1 and not store.list_active()
    message = next(e.payload for e in reversed(repository.get_branch('session-a'))
                   if e.payload.get('role') == 'assistant')
    assert message['error'] == 'provider_output_limit'
    assert message['completion_check'] == partial()


# Error excerpts from dev8 survival.open.r1 / iv_weak.goal.r1, 2026-10-29.
# Replay the actual failure receipts, not a reference answer or a new fit.
@pytest.mark.parametrize('family,failure,nested', [
    ('survival', 'model.genesis survival_cox model_options requires: event_column', False),
    ('survival', 'P7 pack survival.rmst failed closed: SURVIVAL_TAU_REQUIRED: tau must be explicitly declared', True),
    ('iv', 'model iv_2sls_1 in run 20261029_043422_951006_b84b0b73 has no inference kernel; '
     'it was fitted before kernels were recorded, so rerun it to use post-estimation', True),
])
def test_bounded_failure_receipts_leave_a_source_bound_takeover(tmp_path, family, failure, nested):
    class FailingRuntime:
        calls = 0

        async def execute(self, call, **kwargs):
            self.calls += 1
            return ToolResult(tool_call_id=call['tool_call_id'], tool_id='run_operation',
                ok=nested, output={'operation': {'status': 'failed', 'error': failure}} if nested else None,
                error=None if nested else 'OperationValidationError',
                error_details=None if nested else [{'message': failure}])

    class Adapter:
        requests = 0

        async def stream(self, request):
            self.requests += 1
            yield ModelStreamEvent.tool_call_delta(request.request_id, {
                'tool_call_id': f'call-{self.requests}', 'tool_id': 'run_operation',
                'arguments': {'operation_id': 'operation.multi_step', 'target': {'run_id': 'source-run'}}})
            yield ModelStreamEvent.done(request.request_id, 'tool_calls')

    adapter, runtime = Adapter(), FailingRuntime()
    core, store, repository = setup(tmp_path, adapter, runtime=runtime)
    core.completion_check = lambda: partial(family)
    answer = asyncio.run(core.prompt('请完整分析并汇报。', budget={'max_steps': 5, 'timeout_s': 30}))
    assert '同一步已失败 2 次' in answer and failure in answer
    assert 'registered_data' in answer and '下一步建议' in answer
    assert adapter.requests == runtime.calls == 2
    message = next(e.payload for e in reversed(repository.get_branch('session-a'))
                   if e.payload.get('role') == 'assistant')
    assert message['error'] == 'analysis_recovery_limit'
    assert message['completion_check'] == partial(family)
    assert not store.list_active()


def test_budget_message_describes_tool_calls_without_claiming_they_succeeded():
    from workbench.agent.turn_messages import budget_exhausted_message
    text = budget_exhausted_message('en', 'max_steps_exceeded', ['run_operation'], None)
    assert 'Tools called' in text
    assert 'before I could answer or propose anything' not in text
    assert 'confirmed receipts' in text


@pytest.mark.parametrize('error', ['provider_upstream_401', 'provider_error'])
@pytest.mark.parametrize('language', ['en', 'zh'])
def test_provider_failure_does_not_erase_operations_from_earlier_in_the_turn(error, language):
    from workbench.agent.turn_messages import provider_failure_message
    text = provider_failure_message(language, error)
    assert ('evidence are retained' if language == 'en' else '操作与证据仍保留') in text
    assert 'nothing in your data or models was changed' not in text
    assert '没有改动你的数据或模型' not in text


def test_a_budget_stop_without_an_analysis_contract_does_not_invent_one(tmp_path):
    from tests.test_agent_core_restart import Adapter, Runtime
    core, _, _ = setup(tmp_path, Adapter('tool'), runtime=Runtime(tmp_path))
    core.completion_check = lambda: {'status': 'partial',
        'missing': ['completion_contract:select_playbooks_and_source']}
    answer = asyncio.run(core.prompt('Save this value.', budget={'max_steps': 1, 'timeout_s': 30}))
    assert 'step budget ran out' in answer
    assert 'Select the analysis playbooks' not in answer


@pytest.mark.parametrize('stop', ['budget', 'output_limit'])
def test_secondary_completion_read_failure_retains_original_terminal_error(tmp_path, stop):
    from tests.test_agent_core_restart import Adapter, Runtime
    class Limited:
        async def stream(self, request):
            yield ModelStreamEvent.text_delta(request.request_id, 'Recorded draft; not verified.')
            yield ModelStreamEvent.done(request.request_id, 'length')
    core, store, repository = setup(tmp_path,
        Adapter('tool') if stop == 'budget' else Limited(), runtime=Runtime(tmp_path))
    def broken_check():
        raise OSError('evidence could not be read')
    core.completion_check = broken_check
    answer = asyncio.run(core.prompt('Please complete the analysis.', budget={'max_steps': 1, 'timeout_s': 30}))
    message = next(e.payload for e in reversed(repository.get_branch('session-a'))
                   if e.payload.get('role') == 'assistant')
    assert message['error'] == ('max_steps_exceeded' if stop == 'budget' else 'provider_output_limit')
    assert message['stop_reason'] == 'error'
    assert 'completion_check' not in message
    assert message['completion_check_error']['type'] == 'OSError'
    assert 'Completion verification could not run' in answer
    assert 'OSError' in answer and not store.list_active()
