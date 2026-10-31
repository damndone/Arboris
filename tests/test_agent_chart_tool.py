"""A chart in the conversation plots only numbers the Agent received from a tool."""
import asyncio

from workbench.agent.chart_tool import chart_tool
from workbench.agent.session import JsonlSessionRepository
from workbench.agent.tools import ToolRegistry


def _run(tmp_path, points, **extra):
    repository = JsonlSessionRepository(tmp_path / "workbench")
    repository.create_session("s", chain_id="c", role="chain")
    repository.append("s", "message", {"role": "tool", "name": "inspect_result", "tool_call_id": "a",
                                       "content": '{"estimate": 0.32828, "ci": [0.2858, 0.3708]}'})
    repository.append("s", "message", {"role": "assistant", "content": "It might be 0.9."})
    registry = ToolRegistry()
    registry.register(chart_tool(tmp_path, session_id="s"))
    return asyncio.run(registry.execute({"tool_call_id": "c", "tool_id": "show_chart", "arguments": {
        "kind": "coefficients", "title": "T", "points": points, **extra}}, session_id="s"))


def test_values_from_a_tool_result_are_drawn_rounded_or_exact(tmp_path):
    result = _run(tmp_path, [{"label": "IV", "y": 0.328, "low": 0.2858, "high": 0.3708}], reference=0)
    assert result.ok and result.output["chart"]["points"][0]["y"] == 0.328


def test_a_number_from_nowhere_or_the_agents_own_words_is_refused(tmp_path):
    result = _run(tmp_path, [{"y": 0.9}])
    assert not result.ok and "0.9" in result.error_details[0]["message"]


def test_an_inverted_interval_and_a_fifth_series_are_refused(tmp_path):
    assert not _run(tmp_path, [{"y": 0.32828, "low": 0.3708, "high": 0.2858}]).ok
    assert not _run(tmp_path / "b", [{"y": 0.32828, "series": name} for name in "abcde"]).ok
