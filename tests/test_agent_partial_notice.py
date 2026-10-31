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
    assert published.startswith('## 结论') and '密度与租金没有可辨识的线性关联。' in published
    only = publication('部分完成：以下必需证据尚未核验。\n- 缺少引用已核验结果的报告。', PARTIAL, 'zh')
    assert only.startswith('**部分完成，还缺：**')
    assert '下一步' in only and '报告' in only


def test_a_rejected_completion_keeps_findings_but_not_its_success_claim():
    answer = ('分析完成。\n\n已执行 IV 拟合，结果尚不能支持摘要中的因果表述。\n'
              '诊断显示工具变量较弱，需要稳健推断。')
    result = {**PARTIAL, 'verified_artifacts': [
        {'run_id': 'fit-run', 'artifact_id': 'iv-fit', 'sha256': 'a' * 64}]}
    published = publication(answer, result, 'zh')
    assert published.startswith('已执行 IV 拟合') and '分析完成' not in published
    assert '已执行 IV 拟合' in published and '工具变量较弱' in published
    # The answer comes first; ids travel as message sources, not prose.
    assert 'fit-run' not in published and '**下一步：**' in published
    assert published.count('部分完成') == 1
    assert publication(published, result, 'zh') == published


def test_missing_contract_explains_how_to_resume_without_discarding_existing_work():
    result = {'status': 'partial', 'missing': ['completion_contract:select_playbooks_and_source']}
    published = publication('分析完成。', result, 'zh')
    assert '数据来源' in published and '分析计划' in published
    assert '已有结果' in published and '不需要重算' in published
    assert '**下一步：**' in published and len(published) < 3000


def test_completion_claim_across_newlines_cannot_be_reassembled():
    published = publication('The analysis\nis complete.\nThe sensitivity comparison is still pending.', PARTIAL, 'en')
    assert 'The analysis\nis complete' not in published
    assert 'sensitivity comparison is still pending' in published


def test_changed_check_replaces_previous_machine_advice_and_artifact_references():
    old = {**PARTIAL, 'verified_artifacts': [{'run_id': 'old-run', 'artifact_id': 'old-fit'}]}
    first = publication('分析完成。\n已取得拟合结果，但还需敏感性对照。', old, 'zh')
    new = {'status': 'partial', 'missing': ['completion_contract:select_playbooks_and_source']}
    second = publication(first, new, 'zh')
    assert 'old-run/old-fit' not in second
    assert '缺少引用已核验结果的报告' not in second
    assert second.count('**下一步：**') == 1
    assert '已取得拟合结果' in second


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
