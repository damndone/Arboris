"""Completion recovery resumes on any request to finish the analysis and gives the gate's next step."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from workbench.agent.recovery import prepare_completion_recovery
from workbench.agent.session import JsonlSessionRepository
from workbench.canonical import sha256_canonical

ORIGINAL = "请完整分析密度与租金的关系。"
COMPOSE = {"operation_id": "report.compose", "spec": {"result_refs": [
    {"run_id": "r1", "artifact_id": "ols_1", "role": "primary"}]}}


def _core(tmp_path, question):
    repo = JsonlSessionRepository(tmp_path / "workbench")
    repo.create_session("s1", role="chain", chain_id="c1")
    entry = repo.append("s1", "message", {"role": "assistant", "content": "分析完成"})
    core = SimpleNamespace(_user_text=question, repository=repo, session_id="s1",
                           _active_command_id="cmd-1", _has_step_left=lambda: True)
    payload = {"stop_reason": "stop", "tool_calls": None, "completion_check": {
        "status": "partial", "recovery_action": "inspect_and_repair", "missing": ["report:registered_nonempty"],
        "recovery_question_sha256": sha256_canonical(ORIGINAL), "compose_report": COMPOSE,
        "next_step": "No report covers the bound results yet. Propose compose_report exactly as given."}}
    return core, payload, entry


@pytest.mark.parametrize("question, resumes", [
    ("请继续，把这项分析做完。全部完成后，请回复「分析完成」并给出最终总结。", True),
    ('Please continue and finish the analysis. When everything is done, reply "ANALYSIS COMPLETE".', True),
    (ORIGINAL, True),
    ("继续，但只告诉我系数", False),
    ("教育的系数是多少？", False),
    ("请停止分析", False),
])
def test_recovery_resumes_on_finishing_requests_only(tmp_path, question, resumes):
    core, payload, entry = _core(tmp_path, question)
    assert prepare_completion_recovery(core, payload, entry) is resumes


def test_recovery_note_carries_the_gates_next_step(tmp_path):
    core, payload, entry = _core(tmp_path, ORIGINAL)
    assert prepare_completion_recovery(core, payload, entry)
    note = next(e for e in core.repository.get_branch("s1")
                if e.payload.get("message_type") == "completion_recovery").payload["content"]
    assert "Propose compose_report exactly as given" in note
    assert '"operation_id": "report.compose"' in note
