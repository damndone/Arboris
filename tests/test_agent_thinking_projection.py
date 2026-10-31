"""The model's thinking reaches the transcript folded beside its step, never the event stream."""
from workbench.agent.session import JsonlSessionRepository
from workbench.http import agent_route_projection as projection


def test_the_transcript_carries_stored_thinking_and_omits_empty_thinking(tmp_path):
    repository = JsonlSessionRepository(tmp_path)
    repository.create_session("s", chain_id="c", role="chain")
    repository.append("s", "message", {"role": "user", "content": "Why?"})
    repository.append("s", "message", {"role": "assistant", "content": "Because.", "stop_reason": "stop",
                                       "reasoning_content": "Check the residuals first."})
    repository.append("s", "message", {"role": "assistant", "content": "Again.", "stop_reason": "stop",
                                       "reasoning_content": "  "})
    messages = projection._messages(repository, "s")
    assert messages[1]["reasoning"] == "Check the residuals first."
    assert "reasoning" not in messages[2] and "reasoning_content" not in messages[1]


def test_a_chosen_context_limit_replaces_the_default_summary_point():
    from workbench.agent.compaction import CompactionPolicy

    assert CompactionPolicy.from_config(1_000_000).threshold == 200_000
    chosen = CompactionPolicy.from_config(512_000, explicit_limit=512_000)
    assert chosen.threshold == 512_000 - chosen.reserve


def test_the_breakdown_names_what_the_next_request_holds():
    parts = {part["label"]: part["tokens"] for part in projection._context_breakdown([
        {"role": "user", "content": "x" * 400},
        {"role": "tool", "content": "y" * 800},
        {"role": "user", "name": "workbench_agent_protocol", "content": "z" * 400},
        {"role": "assistant", "content": "a", "reasoning_content": "b" * 400},
    ])}
    assert parts["Tool results"] > parts["Messages"] > 0
    assert parts["System prompt"] > 0 and parts["Thinking"] > 0
