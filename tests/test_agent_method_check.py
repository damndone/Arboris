"""A reply whose estimate rests only on a fit whose family does not serve the outcome is withdrawn once."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from tests.test_numeric_grounding import ScriptedAdapter
from workbench.agent import method_check
from workbench.agent.core import AgentCore
from workbench.agent.events import AgentEventStream
from workbench.agent.session import JsonlSessionRepository
from workbench.agent.tools import ToolDefinition, ToolRegistry

UNSERVED = {"check_id": "outcome.type_served", "status": "caution", "blinding": "outcome_distribution",
            "summary": "The outcome is binary, and ols is declared for continuous outcomes.",
            "evidence": {"outcome_type": "binary", "family": "ols", "families_serving_outcome_type": ["glm", "logit", "probit"],
                         "default_family_for_outcome_type": "logit"}}
SEED = {"result_summary": {"checks": [UNSERVED], "model_identity": {"model_family": "ols", "y_variable": "owns_home"},
                           "coefficient_rows": [{"variable": "income_k", "estimate": 0.013042478}]}}
LOGIT = {"result_summary": {"checks": [], "model_identity": {"model_family": "logit", "y_variable": "owns_home"},
                            "coefficient_rows": [{"variable": "income_k", "estimate": 0.0616}]}}


def _tool(content):
    return {"role": "tool", "tool_call_id": "c", "content": json.dumps(content)}


def test_an_answer_resting_on_the_unserved_fit_alone_is_found():
    messages = [{"role": "user", "content": "收入的作用？"}, _tool(SEED)]
    assert method_check.finding("系数为 0.01304。", messages)["family"] == "ols"


def test_an_answer_that_also_read_a_serving_fit_passes():
    messages = [{"role": "user", "content": "收入的作用？"}, _tool(SEED), _tool(LOGIT)]
    assert method_check.finding("LPM 0.01304，Logit 0.0616。", messages) is None


def test_a_reply_with_no_number_from_the_unserved_fit_passes():
    messages = [{"role": "user", "content": "收入的作用？"}, _tool(SEED)]
    assert method_check.finding("你想要概率尺度还是对数几率尺度？", messages) is None
    assert method_check.finding("", messages) is None


def test_the_correction_names_the_serving_families_the_rerun_and_a_refusal():
    text = method_check.correction_message(UNSERVED["evidence"], new_specification_denied=True)
    assert "glm, logit, probit" in text and "model.rerun" in text and "model_type logit" in text
    assert "model.genesis) is refused" in text
    assert "refused" not in method_check.correction_message(UNSERVED["evidence"], new_specification_denied=False)


def _agent(tmp_path: Path, replies, *, denied=False):
    repository = JsonlSessionRepository(tmp_path / "workbench")
    repository.create_session("s", chain_id="c", role="chain")
    events = AgentEventStream(tmp_path / "workbench")
    tools = ToolRegistry()

    async def seed(arguments, context):
        return SEED

    tools.register(ToolDefinition(tool_id="inspect_result_summary", version="v1", input_schema={"type": "object"},
                                  side_effect="none", handler=seed))
    adapter = ScriptedAdapter(replies)
    agent = AgentCore(repository, events, adapter, session_id="s", tools=tools.descriptors(), tool_runtime=tools)
    agent.operation_denied = lambda operation_id: denied and operation_id == "model.genesis"
    return agent, adapter, repository, events


INSPECT = {"tool_call_id": "call-1", "tool_id": "inspect_result_summary", "arguments": {}}


def test_the_draft_goes_back_once_inside_the_turn_and_the_person_never_sees_it(tmp_path):
    agent, adapter, repository, events = _agent(
        tmp_path, [INSPECT, "收入每增加 1 千元，概率增加 0.01304。", "需要先用 Logit 重新拟合，我来提出 model.rerun。"], denied=True)
    reply = asyncio.run(agent.prompt("收入每增加 1 千元，拥有住房的概率变化多少？"))
    assert reply.startswith("需要先用 Logit")
    assistant = [e.payload for e in repository.get_branch("s") if e.payload.get("role") == "assistant"]
    assert assistant[-2]["stop_reason"] == "revised" and assistant[-2]["method_check"]["unserved"]["family"] == "ols"
    correction = adapter.requests[-1].messages[-1]
    assert correction["role"] == "user" and correction["name"] == method_check.MESSAGE_NAME
    assert "model.genesis) is refused" in correction["content"]
    assert [e.payload["content"] for e in repository.get_branch("s") if e.payload.get("role") == "user"] == [
        "收入每增加 1 千元，拥有住房的概率变化多少？"]
    assert method_check.MESSAGE_NAME in [event.event_type for event in events.replay("s")]


def test_a_second_draft_on_the_same_fit_is_shown_rather_than_looped(tmp_path):
    agent, adapter, _repository, _events = _agent(
        tmp_path, [INSPECT, "概率增加 0.01304。", "这里不能重新拟合，所以只能报告线性概率模型：0.01304。"])
    reply = asyncio.run(agent.prompt("概率变化多少？"))
    assert reply.startswith("这里不能重新拟合") and len(adapter.requests) == 3
