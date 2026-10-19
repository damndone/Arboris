"""The actual tool surface keeps custom instructions inside the egress policy."""
import asyncio
import json

from workbench.agent.skill_tools import skill_tool_definitions
from workbench.agent.tools import ToolRegistry
from workbench import egress
from workbench.llm.config import LLMConfig


def catalog(tmp_path):
    from workbench.agent.skills import SkillCatalog
    root = tmp_path / "project"
    for base, name, body in [(root / "skills", "private-guide", "PRIVATE_SKILL_BODY"),
                             (tmp_path / "builtins", "public-guide", "PUBLIC_SKILL_BODY")]:
        directory = base / name
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Use {name}.\n---\n{body}\n")
    return root, SkillCatalog(root, builtin_root=tmp_path / "builtins", personal_root=tmp_path / "personal")


def invoke(definitions, tool, arguments, session="s"):
    registry = ToolRegistry()
    for definition in definitions:
        registry.register(definition)
    return asyncio.run(registry.execute({"tool_call_id": "call", "tool_id": tool, "arguments": arguments}, session_id=session)).to_payload()


def test_both_product_contexts_publish_the_same_skill_owners(tmp_path):
    from workbench.agent.context_tools import NodeOperationContextProvider
    provider = NodeOperationContextProvider(tmp_path)
    expected = {"inspect_builtin_skills", "inspect_custom_skills"}
    assert expected <= {tool.tool_id for tool in provider.global_tool_definitions(session_id="s")}
    assert expected <= {tool.tool_id for tool in provider.tool_definitions(chain_id="c", session_id="s")}


def test_builtin_index_is_lazy_and_cannot_load_private_content(tmp_path):
    root, source = catalog(tmp_path)
    definitions = skill_tool_definitions(root, session_id="s", catalog=source)
    descriptors = json.dumps([d.descriptor() for d in definitions])
    assert "public-guide" in descriptors and "private-guide" not in descriptors
    assert "PUBLIC_SKILL_BODY" not in descriptors and "PRIVATE_SKILL_BODY" not in descriptors
    result = invoke(definitions, "inspect_builtin_skills", {"action": "index"})
    assert result["ok"]
    assert {item["source"] for item in result["output"]["skills"]} == {"builtin"}
    assert str(root) not in json.dumps(result)
    refused = invoke(definitions, "inspect_builtin_skills", {"action": "load", "selector": "project:private-guide"})
    assert refused["ok"] is False and "PRIVATE_SKILL_BODY" not in json.dumps(refused)
    loaded = invoke(definitions, "inspect_builtin_skills", {"action": "load", "selector": "public-guide"})
    assert loaded["ok"] and "PUBLIC_SKILL_BODY" in loaded["output"]["content"]
    assert loaded["output"]["content_role"] == "untrusted_data"
    assert invoke(definitions, "inspect_builtin_skills", {"action": "index"}, session="other")["ok"] is False


def test_custom_skill_content_is_withheld_from_remote_until_explicit_policy(tmp_path):
    root, source = catalog(tmp_path)
    definitions = skill_tool_definitions(root, session_id="s", catalog=source)
    result = invoke(definitions, "inspect_custom_skills", {"action": "load", "selector": "project:private-guide"})
    assert result["ok"]
    messages = [{"role": "assistant", "content": "", "tool_calls": [{"id": "call", "type": "function",
                 "function": {"name": "inspect_custom_skills", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "call", "content": json.dumps(result)}]
    remote = LLMConfig(base_url="https://api.deepseek.com", api_key="unused", model="unused", provider_id="deepseek")
    with egress.egress_project(root):
        outgoing = egress.guard_outgoing_messages(messages, base_url=remote.base_url, provider_id=remote.provider_id, model=remote.model)
    assert "PRIVATE_SKILL_BODY" not in json.dumps(outgoing)
    assert "egress_withheld" in json.dumps(outgoing)
    egress.save_policy(root, egress.EgressPolicy(providers={"deepseek": egress.REMOTE_DEFAULT_ALLOW | {"skill"}}))
    with egress.egress_project(root):
        outgoing = egress.guard_outgoing_messages(messages, base_url=remote.base_url, provider_id=remote.provider_id, model=remote.model)
    assert "PRIVATE_SKILL_BODY" in json.dumps(outgoing)


def test_project_skill_is_used_and_disabled_through_the_real_product_registry(tmp_path):
    from workbench.agent.context_tools import NodeOperationContextProvider
    root, _source = catalog(tmp_path)
    definitions = NodeOperationContextProvider(root).global_tool_definitions(session_id="s")
    call = {"action": "load", "selector": "project:private-guide"}
    loaded = invoke(definitions, "inspect_custom_skills", call)
    assert loaded["ok"] and "PRIVATE_SKILL_BODY" in loaded["output"]["content"]
    (root / "skills" / "disabled.json").write_text(json.dumps({
        "schema": "workbench.skills.v1", "disabled": ["project:private-guide"]}))
    disabled = invoke(definitions, "inspect_custom_skills", call)
    assert disabled["ok"] is False and disabled["output"] is None
    assert "SKILL_DISABLED" in json.dumps(disabled)
    assert str(root) not in json.dumps(disabled)


def test_loaded_content_version_and_model_payload_limit_are_enforced(tmp_path):
    root, source = catalog(tmp_path)
    definitions = skill_tool_definitions(root, session_id="s", catalog=source)
    path = root / "skills" / "private-guide" / "SKILL.md"
    original = invoke(definitions, "inspect_custom_skills", {"action": "load", "selector": "private-guide"})
    version = original["output"]["version_sha256"]
    path.write_text(path.read_text() + "Changed\n")
    mismatch = invoke(definitions, "inspect_custom_skills", {
        "action": "load", "selector": "private-guide", "expected_version": version})
    assert not mismatch["ok"] and "SKILL_VERSION" in json.dumps(mismatch)
    path.write_text(path.read_text() + "X" * 22_000)
    overlarge = invoke(definitions, "inspect_custom_skills", {"action": "load", "selector": "private-guide"})
    assert not overlarge["ok"] and "SKILL_TOOL_LIMIT" in json.dumps(overlarge)
    assert len(json.dumps(overlarge)) < 1000


def test_real_provider_wire_withholds_custom_but_keeps_public_builtin(monkeypatch, tmp_path):
    from tests.test_egress import _conversation, _send, REMOTE
    root, source = catalog(tmp_path)
    definitions = skill_tool_definitions(root, session_id="s", catalog=source)
    for tool, selector, body in [("inspect_builtin_skills", "public-guide", "PUBLIC_SKILL_BODY"),
                                 ("inspect_custom_skills", "project:private-guide", "PRIVATE_SKILL_BODY")]:
        result = invoke(definitions, tool, {"action": "load", "selector": selector})
        with egress.egress_project(root):
            wire = json.dumps(_send(monkeypatch, _conversation(tool, result), REMOTE))
        assert (body in wire) is (tool == "inspect_builtin_skills")
