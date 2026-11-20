"""Bind an already-computed focused answer without requiring a user nudge or a full analysis."""
from __future__ import annotations

import asyncio
import pytest

from tests.test_read_only_analysis import FINGERPRINT, _Fixture, _explore
from tests.test_data_column_cast import _register_source_node_identity
from workbench.agent.delivery import delivery_check
from workbench.agent.model import ModelStreamEvent
from workbench.canonical import sha256_canonical

QUESTION = "Give me a table of the region frequencies and explain it. Please finish this task."


def _runtime(tmp_path):
    runtime = _Fixture(tmp_path)
    _register_source_node_identity(runtime.project_root, runtime.run_id)
    async def runner(proposal):
        record = runtime.orchestrator.confirm_proposal(proposal.proposal_id, revision=proposal.revision,
            fingerprint=proposal.fingerprint, actor_type="read_only_policy",
            current_context_fingerprint=proposal.preconditions["context_fingerprint"],
            current_active_head_run_id=runtime.run_id)
        return await runtime.orchestrator.execute_confirmed_operation(record.record_id,
            project_root=runtime.project_root,
            current_context_fingerprint=proposal.preconditions["context_fingerprint"],
            current_active_head_run_id=runtime.run_id)
    runtime.orchestrator.read_only_runner = runner
    return runtime


def _operation(runtime, request):
    return ModelStreamEvent.tool_call_delta(request.request_id, {
        "tool_call_id": "compute", "tool_id": "run_operation", "arguments": {
            "operation_id": "operation.multi_step", "operation_version": "v1",
            "target": {"run_id": runtime.run_id, "node_ref": "stage:source", "artifact_id": runtime.artifact_id},
            "preconditions": {"context_version": "node-operation-context/v1", "context_fingerprint": FINGERPRINT,
                              "active_head_run_id": runtime.run_id, "owner_resolution": "single_candidate"},
            "changes": {"steps": [_explore("tab", "region")]},
            "evidence_refs": ["registered source"], "expected_effect": ["Tabulate regions."], "risks": [],
        }})


def _prompt(runtime, question, *, compute=False, continuation=False):
    class Adapter:
        requests = []
        async def stream(self, request):
            self.requests.append(request)
            if compute and len(self.requests) == 1:
                yield _operation(runtime, request)
                yield ModelStreamEvent.done(request.request_id, "tool_calls")
            else:
                yield ModelStreamEvent.text_delta(request.request_id, "Here is the answer.")
                yield ModelStreamEvent.done(request.request_id)
    core = runtime.orchestrator._chains["chain-a"][1]
    core.adapter = adapter = Adapter()
    budget = {"max_steps": 2 if compute else 1, "timeout_s": 30}
    asyncio.run(core.continue_(budget=budget) if continuation else core.prompt(question, budget=budget))
    if compute:
        assert runtime.orchestrator.operation_store.list_records()[-1].status == "completed"
    return adapter


def test_computed_focused_answer_gets_recovery_but_does_not_pass_without_its_contract(tmp_path):
    runtime = _runtime(tmp_path)
    _prompt(runtime, QUESTION, compute=True)
    checked = runtime.orchestrator._completion_check("chain-session")

    assert checked["status"] == "partial"
    assert checked["missing"] == ["completion_contract:select_playbooks_and_source"]
    assert checked["recovery_action"] == "inspect_and_repair"
    assert checked["recovery_scope"] == "question"
    assert 'scope: "question"' in checked["next_step"] and "playbooks: []" in checked["next_step"]
    assert runtime.orchestrator.plan_store.current("chain-session") is None


@pytest.mark.parametrize("question", [
    "Give me a table of the region frequencies and explain it.",
    "Do not finish this analysis yet. What do the frequencies show?",
    "不要做完这项分析。频数说明了什么？",
    'What does "finish this task" mean in the analysis plan?',
])
def test_a_plain_computed_question_stays_quiet(tmp_path, question):
    """Replaying 55 recorded focused questions, 50 were resumed for a contract nobody asked for."""
    runtime = _runtime(tmp_path)
    _prompt(runtime, question, compute=True)
    checked = runtime.orchestrator._completion_check("chain-session")

    assert checked["missing"] == ["completion_contract:select_playbooks_and_source"]
    assert "recovery_action" not in checked and "recovery_scope" not in checked


@pytest.mark.parametrize("text, asked", [
    ("我要一张表和一段话说明收入每增加 1 万元，拥有住房的概率变化多少。请完成。", True),
    ("请把支撑这句话的分析做完。", True),
    ("Please finish this task.", True),
    ("Complete the table for the memo.", True),
    ("What is the correlation between wage and education?", False),
    ("这个系数显著吗？", False),
    ("Is the analysis complete?", False),
    ("已经完成了吗？", False),
])
def test_finish_request_wording(text, asked):
    from workbench.agent.task_requirements import asks_to_finish

    assert asks_to_finish(text) is asked


def test_results_from_another_session_do_not_turn_a_plain_question_into_a_plan(tmp_path):
    runtime = _runtime(tmp_path)
    _prompt(runtime, QUESTION, compute=True)
    requirements = runtime.orchestrator._bind_task_requirements("chain-session", None)
    assert "recovery_action" not in delivery_check(runtime.project_root, None, session_id="other",
                                                 requirements=requirements)
    assert "recovery_action" not in delivery_check(runtime.project_root, None, requirements=requirements)


def test_new_question_cannot_recover_from_an_older_commands_computed_result(tmp_path):
    runtime = _runtime(tmp_path)
    _prompt(runtime, QUESTION, compute=True)
    _prompt(runtime, "Explain what standard deviation means.")
    assert "recovery_action" not in runtime.orchestrator._completion_check("chain-session")


def test_focused_recovery_requires_a_real_user_command_binding(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.repository.append("chain-session", "message", {"role": "user", "content": QUESTION})
    assert runtime.propose([_explore("tab", "region")])["executed"] is True
    assert "recovery_action" not in runtime.orchestrator._completion_check("chain-session")


def test_journaled_continuation_results_belong_to_the_same_substantive_question(tmp_path):
    from workbench.agent.protocol import CONTINUATION_NOTE
    from workbench.agent.turn_journal import TurnJournal
    from workbench.agent.turn_store import TurnStore

    runtime = _runtime(tmp_path)
    core = runtime.orchestrator._chains['chain-a'][1]
    core.turn_journal = TurnJournal(TurnStore(runtime.project_root), runtime.repository, session_id='chain-session')
    _prompt(runtime, QUESTION)
    runtime.repository.append('chain-session', 'custom_message', {
        'audience': 'model', 'model_role': 'user', 'name': 'workbench_continuation', 'content': CONTINUATION_NOTE})
    _prompt(runtime, None, compute=True, continuation=True)
    checked = runtime.orchestrator._completion_check('chain-session')
    assert checked['recovery_action'] == 'inspect_and_repair'
    assert checked['recovery_question_sha256'] == sha256_canonical(QUESTION)

    _prompt(runtime, 'Explain what a coefficient means.')
    assert 'recovery_action' not in runtime.orchestrator._completion_check('chain-session')


@pytest.mark.parametrize("prior_question", [False, True])
def test_focused_recovery_resumes_the_same_command_and_binds_existing_results(tmp_path, prior_question):
    runtime = _runtime(tmp_path)
    if prior_question:
        _prompt(runtime, "Explain what a frequency table means.")
    core = runtime.orchestrator._chains["chain-a"][1]
    records = runtime.project_root / "workbench" / "operation-records"
    before = None

    class Adapter:
        def __init__(self):
            self.requests = []

        async def stream(self, request):
            nonlocal before
            self.requests.append(request)
            if len(self.requests) == 1:
                yield _operation(runtime, request)
                yield ModelStreamEvent.done(request.request_id, "tool_calls")
            elif len(self.requests) == 3:
                before = {path.name: path.read_bytes() for path in records.glob("oprec_*.jsonl")}
                assert before
                check = runtime.orchestrator._completion_check("chain-session")
                assert check["recovery_question_sha256"] == sha256_canonical(QUESTION)
                note = next(m["content"] for m in request.messages if m.get("name") == "workbench_completion_recovery")
                assert len(note) <= 6000
                assert "focused question" in note and "Do not add" in note
                assert "iv.ar_confidence" not in note
                assert "Call inspect_analysis_completion" not in note  # the exact next step is already supplied
                yield ModelStreamEvent.tool_call_delta(request.request_id, {
                    "tool_call_id": "bind-question", "tool_id": "update_plan", "arguments": {
                        "question": QUESTION,
                        "steps": [{"step_id": "tab", "title": "Tabulate regions", "operation_ids": ["statistical.explore"]}],
                        "completion": {"scope": "question", "playbooks": [], "source": {
                            "run_id": runtime.run_id, "artifact_id": runtime.artifact_id}},
                    }})
                yield ModelStreamEvent.done(request.request_id, "tool_calls")
            else:
                yield ModelStreamEvent.text_delta(request.request_id, "The requested frequency table is available.")
                yield ModelStreamEvent.done(request.request_id)

    adapter = Adapter()
    core.adapter = adapter
    asyncio.run(core.prompt(QUESTION, budget={"max_steps": 4, "timeout_s": 30}))

    assert len(adapter.requests) == 4
    assert runtime.orchestrator._completion_check("chain-session")["status"] == "requirements_met"
    plan = runtime.orchestrator.plan_store.current("chain-session")
    assert plan.completion["scope"] == "question" and plan.completion["playbooks"] == []
    assert {path.name: path.read_bytes() for path in records.glob("oprec_*.jsonl")} == before
    repairs = [e for e in runtime.repository.get_branch("chain-session")
               if e.payload.get("message_type") == "completion_recovery"]
    assert len(repairs) == 1 and repairs[0].payload["attempt"] == 1 and repairs[0].payload["limit"] == 2
