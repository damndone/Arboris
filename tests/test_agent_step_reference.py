"""The most-used step specifications ride in the cached protocol (v1.9.1 speedup).

In the 198 free-route sessions of 2026-10-22/23, 228 tool calls read operation
contracts, most of them for the same four steps. The reference is generated from
the registry through the contract tool's own view, so it cannot drift from what
inspect_operation_contract returns or from what the validator accepts.
"""
import json

from workbench.agent.context_tools_support.node_tools import _step_vocabulary_view
from workbench.agent.operations import OperationRegistry
from workbench.agent.protocol import REFERENCE_STEP_IDS, chain_agent_protocol, step_reference
from workbench.agent.workflow_contracts import workflow_step_vocabulary


def _reference_lines(protocol):
    found = {}
    for line in protocol.splitlines():
        head, _, body = line.strip().partition(": ")
        if head in REFERENCE_STEP_IDS and body.startswith("{"):
            found[head] = json.loads(body)
    return found


def test_the_protocol_reference_is_what_the_contract_tool_returns():
    protocol = chain_agent_protocol(OperationRegistry())
    rendered = _reference_lines(protocol)
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


def test_the_protocol_tells_the_agent_not_to_reinspect_reference_steps():
    protocol = chain_agent_protocol(OperationRegistry())
    assert "write those steps from the reference without inspecting them" in protocol
    assert "only for steps the reference does not cover" in protocol
