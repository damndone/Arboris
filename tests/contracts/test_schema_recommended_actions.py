"""Contract test: recommended_actions[] inside a failure_evidence dict."""
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).parent

ACTION_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["key", "label", "severity"],
    "properties": {
        "key": {"type": "string", "minLength": 1},
        "label": {"type": "string", "minLength": 1},
        "severity": {"type": "string", "enum": ["primary", "secondary"]},
        "form_overrides": {"type": "object"},
        "hint": {"type": "string"},
    },
    "additionalProperties": False,
}


def test_action_sample_matches_schema():
    sample = json.loads((ROOT / "recommended_actions.model_fit_failure.sample.json").read_text())
    for action in sample:
        jsonschema.validate(action, ACTION_SCHEMA)


def test_sample_has_a_primary_action():
    sample = json.loads((ROOT / "recommended_actions.model_fit_failure.sample.json").read_text())
    assert any(a["severity"] == "primary" for a in sample), \
        "every recovery story needs at least one primary action"


def test_sample_first_action_provides_form_override():
    """The primary action for MODEL_FIT_FAILED should be a one-click recovery
    (Re-run with auto), so it must carry form_overrides."""
    sample = json.loads((ROOT / "recommended_actions.model_fit_failure.sample.json").read_text())
    primary = next(a for a in sample if a["severity"] == "primary")
    assert "form_overrides" in primary
    assert primary["form_overrides"].get("model_type") == "auto"
