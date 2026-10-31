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
