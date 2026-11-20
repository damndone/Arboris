"""References match the authoritative tool; the prompt carries the most used one, the rest load on demand."""
import json

from workbench.agent.context_tools_support.node_tools import _step_vocabulary_view
from workbench.agent.operations import OperationRegistry
from workbench.agent.protocol import INLINE_REFERENCE_STEP_IDS, REFERENCE_STEP_IDS, chain_agent_protocol, step_reference
from workbench.agent.workflow_contracts import workflow_step_vocabulary


def _reference_lines(protocol):
    found = {}
    for line in protocol.splitlines():
        head, _, body = line.strip().partition(": ")
        if head in REFERENCE_STEP_IDS and body.startswith("{"):
            found[head] = json.loads(body)
    return found


def test_reference_is_authoritative_and_the_protocol_carries_only_the_most_used_step():
    protocol = chain_agent_protocol(OperationRegistry())
    rendered = step_reference()
    assert _reference_lines(protocol) == {name: rendered[name] for name in INLINE_REFERENCE_STEP_IDS}
    assert set(INLINE_REFERENCE_STEP_IDS) < set(REFERENCE_STEP_IDS)
    assert set(rendered) == set(REFERENCE_STEP_IDS)
    tool = _step_vocabulary_view(workflow_step_vocabulary(), REFERENCE_STEP_IDS)["step_operations"]
    for operation_id, spec in rendered.items():
        # Only empty values and a summary repeated as ui_description are left out.
        dropped = set(tool[operation_id]) - set(spec)
        assert all(tool[operation_id][key] in (None, [], {}, "") or key == "ui_description" for key in dropped)
        assert all(tool[operation_id][key] == value for key, value in spec.items())
    assert rendered == step_reference()


def test_every_reference_step_is_registered_and_carries_its_fields():
    steps = workflow_step_vocabulary()["step_operations"]
    for operation_id in REFERENCE_STEP_IDS:
        assert operation_id in steps
        spec = step_reference()[operation_id]
        assert set(spec.get("required", [])) <= set(spec["fields"])


def test_the_protocol_directs_one_lookup_for_missing_contracts():
    protocol = chain_agent_protocol(OperationRegistry())
    assert "missing step specifications" in protocol
    assert "step_operation_ids (up to 12) in one call" in protocol
    assert "only for steps without a Fields line or a Step reference entry" in protocol


def test_contract_lookup_description_matches_the_on_demand_protocol():
    from workbench.agent.context_tools_support.tool_specs import chain_tool_specs

    tool = chain_tool_specs(top_level_operation_ids=["operation.multi_step"])["inspect_operation_contract"]
    steps = tool["input_schema"]["properties"]["step_operation_ids"]
    assert steps["description"] == (
        "operation.multi_step only: the step operations you will use. Their full "
        "specifications are returned; without this you get a one-line index of every step.")
    assert {key: value for key, value in steps.items() if key != "description"} == {
        "type": "array", "items": {"type": "string"}, "maxItems": 12}
    assert tool["side_effect"] == "none"
    assert tool["scope_requirements"] == ("project", "chain")
