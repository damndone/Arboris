"""A refused step names everything wrong with it at once, so one retry can fix it."""
from workbench.agent.workflow_contract_parts.validation import _schema_mismatch

SCHEMA = {
    "type": "object",
    "required": ["input_mode", "column_bindings"],
    "additionalProperties": False,
    "properties": {
        "input_mode": {"enum": ["frame"]},
        "column_bindings": {
            "type": "object",
            "required": ["columns"],
            "additionalProperties": False,
            "properties": {"columns": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
        },
        "options": {"type": "object"},
    },
}


def test_every_problem_is_named_in_one_refusal():
    message = _schema_mismatch(
        {"input_mode": "raw", "column_bindings": {"outcome": "y"}, "alternative": "greater"}, SCHEMA, "test.evidence field",
    )
    assert "test.evidence field.input_mode must be one of: frame" in message
    assert "test.evidence field.column_bindings.columns is required" in message
    assert "test.evidence field.column_bindings.outcome is not a field here; allowed: columns" in message
    assert "test.evidence field.alternative is not a field here" in message


def test_a_single_problem_reads_as_before():
    assert _schema_mismatch({"column_bindings": {"columns": ["a"]}}, SCHEMA, "s") == "s.input_mode is required"


def test_a_long_list_of_problems_is_bounded():
    schema = {"type": "object", "additionalProperties": False, "properties": {"a": {}}}
    message = _schema_mismatch({f"k{i}": 1 for i in range(40)}, schema, "s")
    assert message.count("is not a field here") <= 8


def test_a_real_step_reports_all_its_fields_together():
    from workbench.agent.workflow_contract_parts.validation import _validate_step_spec
    from workbench.contracts.common.errors import OperationValidationError

    try:
        _validate_step_spec("test.evidence", {"input_mode": "raw", "column_bindings": {"outcome": "y"}, "options": {}})
    except OperationValidationError as error:
        assert "input_mode must be one of: frame" in str(error)
        assert "column_bindings" in str(error)
    else:
        raise AssertionError("the step should have been refused")
