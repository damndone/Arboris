"""Contract test: capabilities.sample.json validates against the published schema.

This test is the canonical guard that the schema documented in
docs/api-contracts/capabilities.md stays in lock-step with the sample
fixture used by both backend implementation (slice 2) and frontend
mocks (slice 3).
"""
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).parent

SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["schema_version", "model_types", "imputation_methods"],
    "properties": {
        "schema_version": {"type": "integer", "minimum": 1},
        "editable_stages": {"type": "array", "items": {"type": "string"}},
        "model_types": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["key", "label", "group"],
                "properties": {
                    "key": {"type": "string", "minLength": 1},
                    "label": {"type": "string", "minLength": 1},
                    "group": {"type": "string", "minLength": 1},
                    "description": {"type": "string"},
                    "requires": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "schema_id": {"type": "string"},
                    "params": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["key", "kind"],
                            "properties": {
                                "key": {"type": "string"},
                                "kind": {"type": "string"},
                                "label": {"type": "string"},
                                "role": {"type": "string"},
                                "required": {"type": "boolean"},
                                "value": {},
                                "options": {"type": "array"},
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
            },
        },
        "imputation_methods": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["key", "label"],
                "properties": {
                    "key": {"type": "string", "minLength": 1},
                    "label": {"type": "string", "minLength": 1},
                    "description": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        # V1.5.4.2 (schema_version 2): additive UI groups for
        # prediction/sampling/covariance controls.
        "prediction_models": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["key", "label"],
                "properties": {
                    "key": {"type": "string", "minLength": 1},
                    "label": {"type": "string", "minLength": 1},
                    "description": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "sampling_methods": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["key", "label"],
                "properties": {
                    "key": {"type": "string", "minLength": 1},
                    "label": {"type": "string", "minLength": 1},
                    "description": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "covariance_options": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["key", "label"],
                "properties": {
                    "key": {"type": "string", "minLength": 1},
                    "label": {"type": "string", "minLength": 1},
                    "description": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}


def test_capabilities_sample_matches_schema():
    sample = json.loads((ROOT / "capabilities.sample.json").read_text())
    jsonschema.validate(sample, SCHEMA)


def test_capabilities_sample_has_all_v1532_model_types():
    """The sample must include every V1.5.3.2 backend-supported model type."""
    sample = json.loads((ROOT / "capabilities.sample.json").read_text())
    keys = {m["key"] for m in sample["model_types"]}
    expected = {
        "auto", "ols", "logit", "probit", "poisson", "negative_binomial",
        "panel_ols", "glm:binomial", "glm:poisson", "glm:negative_binomial",
    }
    assert expected.issubset(keys), f"missing: {expected - keys}"


def test_capabilities_sample_has_mice():
    sample = json.loads((ROOT / "capabilities.sample.json").read_text())
    keys = {m["key"] for m in sample["imputation_methods"]}
    assert "mice" in keys


def test_capabilities_groups_are_a_known_set():
    """Group is a UI rendering hint — must be from a small fixed vocabulary."""
    sample = json.loads((ROOT / "capabilities.sample.json").read_text())
    allowed = {"auto", "Linear", "Binary", "Count", "Panel", "GLM", "IV", "DID"}
    groups = {m["group"] for m in sample["model_types"]}
    assert groups.issubset(allowed), f"unknown groups: {groups - allowed}"
