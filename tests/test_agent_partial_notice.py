"""One partial-completion notice, in the person's language (free-route round off3, 2026-10-22).

The Agent began its answers with the previous notice and the gate prepended a
new one, so notices stacked; after each confirmation the continuation had no
person text, so a Chinese task got English notices.
"""
import asyncio

from tests.test_agent_core_restart import setup
from workbench.agent.completion import publication
from workbench.agent.model import ModelStreamEvent

PARTIAL = {'status': 'partial', 'missing': ['report:registered_nonempty']}


def test_a_repeated_notice_is_replaced_not_stacked():
    answer = ('Partially complete: required evidence remains unverified.\n- A report with verified result sources is missing.'
              '\n\n## 结论\n密度与租金没有可辨识的线性关联。')
    published = publication(answer, PARTIAL, 'zh')
    assert published.count('部分完成') == 1 and 'Partially complete' not in published
    assert published.endswith('密度与租金没有可辨识的线性关联。')
    only = publication('部分完成：以下必需证据尚未核验。\n- 缺少引用已核验结果的报告。', PARTIAL, 'zh')
    assert only == '部分完成：以下必需证据尚未核验。\n- 缺少引用已核验结果的报告。'


class Adapter:
    async def stream(self, request):
        yield ModelStreamEvent.text_delta(request.request_id, '中期结果如下。')
        yield ModelStreamEvent.done(request.request_id)


def test_a_continuation_answers_in_the_language_of_the_last_request(tmp_path):
    async def scenario():
        core, _, repository = setup(tmp_path, Adapter())
        await core.prompt('请估计密度对租金的影响。', budget={'max_steps': 2, 'timeout_s': 30})
        repository.append('session-a', 'custom_message', {'message_type': 'agent_continuation', 'audience': 'model',
            'model_role': 'user', 'name': 'workbench_continuation', 'content': 'Workbench: the person confirmed your proposal.'})
        await core.continue_(budget={'max_steps': 2, 'timeout_s': 30})
        assert core._user_text == '请估计密度对租金的影响。'
    asyncio.run(scenario())
