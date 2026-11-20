"""The complete operation index stays visible; regularly used steps carry their fields, the rest load on demand.

2026-11-14: with no contract in the prompt, 36 of 55 recorded focused questions needed a contract read
before their first step; with the measured signatures and the statistical.explore reference, 5.
"""
from __future__ import annotations

import copy
import hashlib
import re

from workbench.agent.protocol import (CHAIN_AGENT_PROTOCOL, INLINE_REFERENCE_STEP_IDS, INLINE_SIGNATURE_STEP_IDS,
                                      MAIN_AGENT_PROTOCOL, step_vocabulary_lines)
from workbench.agent.workflow_contracts import workflow_step_vocabulary

STEP_LINE = re.compile(r"^  - ([a-z_]+(?:\.[a-z_0-9]+)+) -> ")


def _lines():
    return {match.group(1): line for line in step_vocabulary_lines().split("\n") if (match := STEP_LINE.match(line))}


def _index_required(text):
    prefix = "  - Index shorthand only: steps without a Required suffix require these field names: "
    default_line = next(line for line in text.splitlines() if line.startswith(prefix))
    default_fields = default_line[len(prefix):].split(".", 1)[0]
    result = {}
    for line in text.splitlines():
        if (match := STEP_LINE.match(line)) and " Fields: " not in line:
            fields = line.rsplit(" Required: ", 1)[1].removesuffix(".") if " Required: " in line else default_fields
            result[match.group(1)] = [] if fields == "none" else fields.split(", ")
    return result


def test_every_step_is_still_listed_by_name():
    assert set(_lines()) == set(workflow_step_vocabulary()["step_operations"])


def test_every_index_entry_uses_the_authoritative_summary_and_required_names():
    lines = _lines()
    vocabulary = workflow_step_vocabulary()["step_operations"]
    assert _index_required(step_vocabulary_lines()) == {
        operation_id: spec["required"] for operation_id, spec in vocabulary.items()
        if operation_id not in INLINE_SIGNATURE_STEP_IDS}
    for operation_id, spec in vocabulary.items():
        summary = lines[operation_id].split(" -> ", 1)[1].rsplit(" Required: ", 1)[0].rsplit(" Fields: ", 1)[0]
        assert summary == spec["summary"]


def test_only_the_measured_steps_carry_their_contract_inline():
    from workbench.agent.workflow_contract_parts.signature import published_step_signature

    lines = _lines()
    assert INLINE_SIGNATURE_STEP_IDS <= set(lines)
    assert {step for step, line in lines.items() if " Fields: " in line} == INLINE_SIGNATURE_STEP_IDS
    for step in INLINE_SIGNATURE_STEP_IDS:
        assert lines[step].endswith(f" Fields: {published_step_signature(step)}.")
    referenced = [match.group(1) for line in step_vocabulary_lines().splitlines()
                  if (match := re.match(r"^      ([\w.]+): \{", line))]
    assert referenced == list(INLINE_REFERENCE_STEP_IDS) == ["statistical.explore"]
    assert not INLINE_SIGNATURE_STEP_IDS & set(INLINE_REFERENCE_STEP_IDS)


def test_index_shorthand_is_not_a_parameter_default_or_a_complete_contract():
    text = step_vocabulary_lines()
    assert "This is not a tool parameter default" in text
    assert "does not replace the complete contract lookup" in text
    assert len(text.encode()) < 37_000  # 24,763 with nothing inline, 53,028 with four references


def test_index_required_shorthand_follows_changed_declarations_and_empty_exceptions(monkeypatch):
    from workbench.agent import workflow_contracts

    vocabulary = copy.deepcopy(workflow_step_vocabulary())
    entries = vocabulary["step_operations"]
    common = [entry for entry in entries.values() if entry["required"] == ["input_mode", "column_bindings", "options"]]
    for entry in common:
        entry["required"] = ["future_required_field"]
    common[0]["required"] = []
    monkeypatch.setattr(workflow_contracts, "workflow_step_vocabulary", lambda: vocabulary)

    assert _index_required(step_vocabulary_lines()) == {
        operation_id: entry["required"] for operation_id, entry in entries.items()
        if operation_id not in INLINE_SIGNATURE_STEP_IDS}


def test_the_agent_is_told_how_to_write_a_step_without_a_signature():
    text = step_vocabulary_lines()
    assert "Required lists field names, not their complete contract" in text
    assert "inspect_operation_contract(step_operation_ids=[...])" in text
    assert "missing contracts in one call" in text
    assert "A Fields line is that step's contract" in text


def test_the_vocabulary_stays_within_its_size():
    assert len(step_vocabulary_lines().encode()) < 37_000


def test_lazy_contract_discovery_keeps_all_other_policy_text_byte_identical():
    # Pin the policy after the intentional server-bound rerun update. Only the two
    # contract-discovery lines and the generated vocabulary are excluded.
    lines = [line for line in CHAIN_AGENT_PROTOCOL.splitlines() if line != "{step_vocabulary}"
             and not line.startswith("- Compose that workflow yourself")
             and not line.startswith("- For operation.multi_step,")]
    assert hashlib.sha256("\n".join(lines).encode()).hexdigest() == "cde1d0cfec6c008ab52c79aee5994ab354c781a703fc0771d5708a81b6f906e0"
    assert hashlib.sha256(MAIN_AGENT_PROTOCOL.encode()).hexdigest() == "981cb1e7beeb411a8ddbc1642dfbf54735ea27d097a8642ac2514dfb64bf1c11"
    assert "Each step is {step_id, operation_id, spec, depends_on}. Field names are exact and unknown fields are rejected." in CHAIN_AGENT_PROTOCOL


def test_source_capability_list_is_exactly_recoverable_from_the_index_and_exceptions():
    vocabulary = workflow_step_vocabulary()
    text = step_vocabulary_lines()
    prefix = "      Every step in the index may declare a source EXCEPT: "
    line = next(line for line in text.splitlines() if line.startswith(prefix))
    excluded = set(line[len(prefix):].removesuffix(".").split(", "))
    assert set(_lines()) - excluded == set(vocabulary["source"]["declarable_by"])
    assert excluded <= set(_lines())
    assert len(line) < 500  # old positive list repeated 143 step ids, 3,382 characters
