"""Main and Chain expose one research Agent identity with explicit scopes."""
import pytest
import asyncio

from tests.test_agent_identity import config
from workbench.agent.identity import identity_text
from workbench.agent.protocol import CHAIN_AGENT_PROTOCOL, MAIN_AGENT_PROTOCOL


@pytest.mark.parametrize("role", ["chain", "main"])
def test_identity_names_one_research_agent_and_explains_its_scope(role):
    text = identity_text(role, config())
    assert "you are the Arboris Agent" in text
    assert "Workbench Chain Agent" not in text and "Workbench Global Agent" not in text
    assert ("Current scope: selected chain" if role == "chain" else "Current scope: project") in text


def test_both_protocols_use_the_same_agent_identity():
    for protocol in (CHAIN_AGENT_PROTOCOL, MAIN_AGENT_PROTOCOL):
        assert "You are the Arboris Agent" in protocol
        assert "You are the Workbench Chain Agent" not in protocol
        assert "You are the Workbench Global Agent" not in protocol


@pytest.mark.parametrize("role", ["chain", "main"])
def test_existing_session_refreshes_identity_once_on_new_commands(tmp_path, role):
    from tests.test_read_only_analysis import _Fixture
    from workbench.agent.model import ModelStreamEvent
    from workbench.agent.runtime_adapter import headless_runtime_scope
    from workbench.cli_agent import run_headless

    fixture = _Fixture(tmp_path)
    session = f"{role}-session"
    repository = fixture.repository
    repository.append(session, "custom_message", {
        "name": "workbench_agent_identity", "message_type": "agent_identity", "audience": "model",
        "content": "Legacy scope-specific identity.",
    })
    requests = []

    class Answer:
        async def stream(self, request):
            requests.append(request)
            yield ModelStreamEvent.text_delta(request.request_id, "Hello.")
            yield ModelStreamEvent.done(request.request_id)

    async def run():
        with headless_runtime_scope(adapter_factory=lambda settings: Answer(), config=config()):
            for _ in range(2):
                await run_headless(fixture.project_root, "Hello", session_id=session, on_event=lambda event: None)

    asyncio.run(run())
    for request in requests:
        latest = [message for message in request.messages if message.get("name") == "workbench_agent_identity"][-1]
        assert "you are the Arboris Agent" in latest["content"]
    identities = [entry for entry in repository.get_branch(session)
                  if entry.payload.get("name") == "workbench_agent_identity"]
    assert len(identities) == 2  # Keep the old audit entry; append just one revision.
    assert identities[0].payload["content"] == "Legacy scope-specific identity."
