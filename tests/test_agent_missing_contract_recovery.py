"""A full-analysis request whose plan saved no completion contract resumes on its own.

2026-11-10, five NVIDIA positions (binary_logit, Ask): nine user nudges ("请继续，把这项分析做完")
followed an answer whose delivery check had only completion_contract:select_playbooks_and_source
missing. That item carried no recovery action, so the bounded completion recovery never ran and
the turn waited for the person; the M0.5 threshold allows zero nudges in Ask. A plain question
with no contract stays quiet: nothing is forced into a plan.
"""
from __future__ import annotations

from dataclasses import replace

from tests.test_agent_plan_criteria import approved_plan
from tests.test_agent_completion import fixture as completion_fixture
from workbench.agent.delivery import delivery_check

MISSING_CONTRACT = 'completion_contract:select_playbooks_and_source'


def _plan_without_contract(tmp_path, scope):
    contract, evidence = completion_fixture(tmp_path)
    plan, _ = approved_plan(tmp_path, contract, evidence)
    requirements = {**plan.task_requirements, 'status': 'verified', 'scope': scope}
    return replace(plan, completion=None, completion_evidence=None, task_requirements=requirements)


def test_a_full_analysis_without_a_contract_gets_the_bounded_recovery(tmp_path):
    checked = delivery_check(tmp_path, _plan_without_contract(tmp_path, 'analysis'))
    assert checked['status'] == 'partial' and MISSING_CONTRACT in checked['missing']
    assert checked['recovery_action'] == 'inspect_and_repair'
    assert checked['recovery_question_sha256']
    assert checked['next_step'].startswith('No completion contract was saved. Call update_plan with completion')


def test_a_focused_question_without_a_contract_stays_quiet(tmp_path):
    checked = delivery_check(tmp_path, _plan_without_contract(tmp_path, 'question'))
    assert MISSING_CONTRACT in checked['missing'] and 'recovery_action' not in checked


def test_unverified_requirements_do_not_trigger_recovery(tmp_path):
    plan = _plan_without_contract(tmp_path, 'analysis')
    plan = replace(plan, task_requirements={**plan.task_requirements, 'status': 'unverified'})
    assert 'recovery_action' not in delivery_check(tmp_path, plan)


def test_no_plan_at_all_stays_quiet(tmp_path):
    assert 'recovery_action' not in delivery_check(tmp_path, None)


def _requirements(scope, text="Please run a full analysis of income and home ownership."):
    from workbench.canonical import sha256_canonical
    source = {'kind': 'user_message', 'session_id': 's', 'entry_id': 'e', 'sha256': sha256_canonical(text)}
    return {'version': 'agent.task-requirements/v1', 'status': 'verified', 'scope': scope, 'estimands': [],
            'sources': [source], 'latest_request': source, 'request_chain_sha256': 'c' * 64, 'cursor': None}


def test_before_any_plan_a_full_analysis_request_gets_the_recovery(tmp_path):
    from workbench.canonical import sha256_canonical
    checked = delivery_check(tmp_path, None, requirements=_requirements('analysis'))
    assert checked['recovery_action'] == 'inspect_and_repair'
    assert checked['recovery_question_sha256'] == sha256_canonical(
        "Please run a full analysis of income and home ownership.")
    assert 'recovery_action' not in delivery_check(tmp_path, None, requirements=_requirements('question'))


def test_the_recovery_answers_a_nudge_but_not_a_later_focused_question(tmp_path):
    from types import SimpleNamespace
    from workbench.agent.recovery import prepare_completion_recovery
    from workbench.agent.session import JsonlSessionRepository

    checked = delivery_check(tmp_path, None, requirements=_requirements('analysis'))
    for question, resumes in [("Please run a full analysis of income and home ownership.", True),
                              ("请继续，把这项分析做完。全部完成后，请回复「分析完成」并给出最终总结。", True),
                              ("What is the income coefficient?", False)]:
        repository = JsonlSessionRepository(tmp_path / question[:4].encode().hex() / "workbench")
        repository.create_session("s1", role="chain", chain_id="c1")
        entry = repository.append("s1", "message", {"role": "assistant", "content": "Here is what I found."})
        core = SimpleNamespace(_user_text=question, repository=repository, session_id="s1",
                               _active_command_id="cmd-1", _has_step_left=lambda: True)
        payload = {"stop_reason": "stop", "tool_calls": None, "completion_check": checked}
        assert prepare_completion_recovery(core, payload, entry) is resumes, question
        if resumes:
            note = next(e for e in repository.get_branch("s1")
                        if e.payload.get("message_type") == "completion_recovery").payload["content"]
            assert "No completion contract was saved. Call update_plan with completion" in note


def test_no_plan_recovery_tracks_a_later_explicit_full_analysis_request(tmp_path):
    from workbench.agent.session import JsonlSessionRepository
    from workbench.agent.task_requirements import RequirementBinder
    from workbench.canonical import sha256_canonical

    repository = JsonlSessionRepository(tmp_path / 'workbench')
    repository.create_session('s', role='chain', chain_id='c')
    binder = RequirementBinder(repository)
    first = 'Please run a full analysis of income.'
    second = 'Please run a full analysis of home ownership.'
    repository.append('s', 'message', {'role': 'user', 'content': first, 'command_id': 'first'})
    requirements = binder.bind('s', None)
    repository.append('s', 'message', {'role': 'user', 'content': second, 'command_id': 'second'})
    requirements = binder.bind('s', requirements)
    assert requirements['sources'][-1]['sha256'] == sha256_canonical(first)
    checked = delivery_check(tmp_path, None, session_id='s', requirements=requirements)
    assert checked['recovery_question_sha256'] == sha256_canonical(second)

    repository.append('s', 'message', {'role': 'user', 'content': 'What is a coefficient?', 'command_id': 'third'})
    requirements = binder.bind('s', requirements)
    checked = delivery_check(tmp_path, None, session_id='s', requirements=requirements)
    assert checked['recovery_question_sha256'] != sha256_canonical('What is a coefficient?')
