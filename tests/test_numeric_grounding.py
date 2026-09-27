"""Every number the Agent shows must come from a result (agent.numeric_grounding)."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from workbench.agent import numeric_grounding as grounding
from workbench.agent.core import AgentCore
from workbench.agent.events import AgentEventStream
from workbench.agent.model import ModelRequest, ModelStreamEvent
from workbench.agent.session import JsonlSessionRepository
from workbench.agent.tools import ToolDefinition, ToolRegistry


def _tool(content: object, name: str = "inspect_operation_artifact") -> dict:
    return {"role": "tool", "name": name, "content": json.dumps({"ok": True, "output": content})}


RESULT = _tool({"p_value": 0.098491234, "mean_men": 5.1234, "mean_women": 4.0221, "t": -1.6602})


@pytest.mark.parametrize(
    "reply",
    [
        "p = 0.098",
        "p = 0.0985",
        "p = 0.09849",
        "t 统计量为-1.66",  # Chinese character directly before the number
        "男性平均工资5.12，女性4.02。",
        "p 约为 9.8%",  # a proportion written as a percentage
        "不显著（p > 0.05）",  # a threshold, not a claim about a result
        "在 0.05 的显著性水平下",
        "p 值远低于 0.05",
        "p is well below 0.05",
        "p is less than 0.01",
        "样本 176 人，3 个检验",  # small integers are prose
        "GSS 2022 的数据",  # years are prose
    ],
)
def test_correctly_copied_or_rounded_numbers_pass(reply: str) -> None:
    assert grounding.check(reply, [RESULT]) == ()


@pytest.mark.parametrize(
    ("reply", "bad"),
    [
        ("p = 0.099", "0.099"),  # rounded twice: 0.09849 -> 0.0985 -> 0.099
        ("两组差 1.100", "1.100"),  # mental arithmetic (5.1234 - 4.0221 = 1.1013)
        ("系数为0.52", "0.52"),  # invented
        ("p = 0.05", "0.05"),  # a conventional value stated as a result
    ],
)
def test_wrong_rounding_arithmetic_and_invention_are_found(reply: str, bad: str) -> None:
    findings = grounding.check(reply, [RESULT])
    assert [finding.text for finding in findings] == [bad]


def test_findings_name_the_closest_real_values() -> None:
    (finding,) = grounding.check("p = 0.099", [RESULT])
    assert finding.closest[0] == "0.098491234"


def test_the_agents_own_words_and_the_correction_are_not_evidence() -> None:
    messages = [
        RESULT,
        {"role": "assistant", "content": "p = 0.099"},
        {"role": "system", "name": grounding.CHECK_MESSAGE_NAME, "content": "0.099 does not match"},
    ]
    assert [finding.text for finding in grounding.check("p = 0.099", messages)] == ["0.099"]


def test_the_users_own_numbers_are_evidence() -> None:
    messages = [{"role": "user", "content": "用 0.07 作为阈值"}]
    assert grounding.check("阈值 0.07", messages) == ()


def test_a_calculation_counts_only_when_its_operands_come_from_results() -> None:
    honest = _tool(grounding.calculate([{"label": "gap", "expression": "5.1234 - 4.0221"}]), name="calculate")
    assert grounding.check("两组差 1.1013", [RESULT, honest]) == ()
    assert grounding.check("两组差 1.101", [RESULT, honest]) == ()
    assert [f.text for f in grounding.check("两组差 1.100", [RESULT, honest])] == ["1.100"]

    laundered = _tool(grounding.calculate([{"expression": "5.1234 - 3.9"}]), name="calculate")
    assert [f.text for f in grounding.check("两组差 1.2234", [RESULT, laundered])] == ["1.2234"]


def test_calculate_evaluates_arithmetic_and_refuses_anything_else() -> None:
    result = grounding.calculate(
        [
            {"label": "odds ratio", "expression": "exp(0.4312)"},
            {"expression": "(5.1234 - 4.0221) / 4.0221 * 100"},
            {"expression": "2^3"},
            {"expression": "__import__('os')"},
            {"expression": "1 / 0"},
        ]
    )["results"]
    assert float(result[0]["value"]) == math.exp(0.4312)
    assert result[0]["operands"] == ["0.4312"]
    assert float(result[1]["value"]) == (5.1234 - 4.0221) / 4.0221 * 100
    assert result[2]["value"] == "8.0"
    assert "error" in result[3] and "error" in result[4]


class ScriptedAdapter:
    """Replies in order; a reply that is a dict becomes a tool call."""

    def __init__(self, replies: list[object]) -> None:
        self.replies = replies
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        reply = self.replies.pop(0)
        if isinstance(reply, dict):
            yield ModelStreamEvent.tool_call_delta(request.request_id, reply)
            yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")
            return
        yield ModelStreamEvent.text_delta(request.request_id, str(reply))
        yield ModelStreamEvent.done(request.request_id)


def _agent(tmp_path: Path, replies: list[object]) -> tuple[AgentCore, ScriptedAdapter, JsonlSessionRepository, AgentEventStream]:
    repository = JsonlSessionRepository(tmp_path / "workbench")
    repository.create_session("s", chain_id="c", role="chain")
    events = AgentEventStream(tmp_path / "workbench")
    tools = ToolRegistry()

    async def result(arguments, context):
        return {"p_value": 0.098491234, "mean_men": 5.1234, "mean_women": 4.0221}

    tools.register(ToolDefinition(tool_id="inspect_result", version="v1", input_schema={"type": "object"}, side_effect="none", handler=result))
    adapter = ScriptedAdapter(replies)
    agent = AgentCore(repository, events, adapter, session_id="s", tools=tools.descriptors(), tool_runtime=tools)
    return agent, adapter, repository, events


INSPECT = {"tool_call_id": "call-1", "tool_id": "inspect_result", "arguments": {}}


def test_a_draft_with_a_wrong_number_is_withdrawn_and_rewritten(tmp_path: Path) -> None:
    agent, adapter, repository, events = _agent(tmp_path, [INSPECT, "p 值为 0.099。", "p 值为 0.098。"])

    reply = asyncio.run(agent.prompt("男女工资有差别吗"))

    assert reply == "p 值为 0.098。"
    assistant = [e.payload for e in repository.get_branch("s") if e.payload.get("role") == "assistant"]
    assert assistant[-2]["stop_reason"] == "revised"
    assert assistant[-2]["numeric_check"]["unverified"][0]["text"] == "0.099"
    assert assistant[-1]["stop_reason"] == "stop" and "numeric_check" not in assistant[-1]
    correction = adapter.requests[-1].messages[-1]
    assert correction["name"] == grounding.CHECK_MESSAGE_NAME and "0.099" in correction["content"]
    # A new user turn: DeepSeek's thinking mode refuses a second answer inside
    # a turn that used tools unless its private reasoning is sent back.
    assert correction["role"] == "user"
    # Never shown as something the user said.
    assert [e.payload["content"] for e in repository.get_branch("s") if e.payload.get("role") == "user"] == ["男女工资有差别吗"]
    assert "numeric_check" in [event.event_type for event in events.replay("s")]


def test_a_rewrite_that_still_fails_is_shown_with_a_warning(tmp_path: Path) -> None:
    agent, adapter, repository, _events = _agent(tmp_path, [INSPECT, "两组差 1.100。", "两组差 1.100。"])

    reply = asyncio.run(agent.prompt("差多少"))

    assert reply.startswith("两组差 1.100。")
    assert "Workbench 数字核对" in reply and "1.100" in reply.split("\n\n")[-1]
    final = repository.get_branch("s")[-1].payload
    assert final["numeric_check"]["unverified"][0]["text"] == "1.100"
    assert len(adapter.requests) == 3  # one inspection, one draft, one rewrite: never a loop


def test_a_correct_reply_is_not_touched(tmp_path: Path) -> None:
    agent, adapter, repository, _events = _agent(tmp_path, [INSPECT, "p = 0.0985"])
    assert asyncio.run(agent.prompt("p?")) == "p = 0.0985"
    assert len(adapter.requests) == 2


def test_hashes_and_identifiers_are_not_numbers() -> None:
    messages = [
        _tool({"run_id": "run-1e99999999", "sha256": "7e4096ab1e999999999", "artifact": "a3.5e2x"}),
        RESULT,
    ]
    assert grounding.check("p = 0.0985", messages) == ()
    assert [f.text for f in grounding.check("值为 3.5", messages)] == ["3.5"]


def test_a_check_that_cannot_run_says_so_instead_of_passing(tmp_path: Path, monkeypatch) -> None:
    agent, _adapter, repository, _events = _agent(tmp_path, [INSPECT, "p = 0.0985"])

    def broken(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(grounding, "check", broken)
    reply = asyncio.run(agent.prompt("p?"))
    assert reply.startswith("p = 0.0985") and "could not check the numbers" in reply
    assert repository.get_branch("s")[-1].payload["numeric_check"] == {"error": "the numeric check could not run"}


INCOME = _tool({"male": 33761.832590660866, "female": 23116.92048788945, "n": 4149, "valid": 2344})


@pytest.mark.parametrize("reply", ["男性 33,762 美元", "男性 33762", "约 34,000 美元", "4149 行中 2344 行有效", "均值 33,761.83"])
def test_large_whole_numbers_are_checked_at_the_precision_written(reply: str) -> None:
    assert grounding.check(reply, [INCOME]) == ()


@pytest.mark.parametrize(("reply", "bad"), [("男性 33,700 美元", "33,700"), ("少了 1805 行", "1805"), ("约 35,000", "35,000")])
def test_wrong_large_whole_numbers_are_found(reply: str, bad: str) -> None:
    assert [finding.text for finding in grounding.check(reply, [INCOME])] == [bad]
