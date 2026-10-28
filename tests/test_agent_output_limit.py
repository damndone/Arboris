"""A provider output cap is a visible incomplete turn, never an executed tool."""
import asyncio

import pytest

from tests.test_agent_core_restart import CALL, Runtime, setup
from workbench.agent.model import ModelStreamEvent


@pytest.mark.parametrize('with_tool,with_text', [(False, True), (True, True), (True, False)])
def test_length_retains_the_draft_but_fails_without_executing_or_retrying(tmp_path, with_tool, with_text):
    class Limited:
        requests = 0

        async def stream(self, request):
            self.requests += 1
            if with_text:
                yield ModelStreamEvent.text_delta(request.request_id, '已读取数据来源，但报告尚未写完。')
            if with_tool:
                yield ModelStreamEvent.tool_call_delta(request.request_id, CALL)
            yield ModelStreamEvent.done(request.request_id, 'length')

    adapter = Limited()
    core, store, repository = setup(tmp_path, adapter, runtime=Runtime(tmp_path))
    answer = asyncio.run(core.prompt('请分析并汇报。', budget={'max_steps': 3, 'timeout_s': 30}))
    assert adapter.requests == 1 and not (tmp_path / 'effects.txt').exists()
    if with_text:
        assert '已读取数据来源' in answer
    assert '输出上限' in answer
    assert '没有写完' in answer and '连接中断' not in answer
    messages = [entry.payload for entry in repository.get_branch('session-a')
                if entry.entry_type == 'message' and entry.payload.get('role') == 'assistant']
    assert messages[-1]['stop_reason'] == 'error'
    assert messages[-1]['error'] == 'provider_output_limit'
