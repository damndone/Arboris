"""Contract test: imputation_summary.json schema.

Note: the existing run_mice_imputation() in backend/workbench/imputation.py
already returns most of this shape (schema_version=1, method='mice',
status, imputed_columns, etc.). V1.5.4.1 adds three method-agnostic fields:
rows_imputed, input_artifact, output_artifact. We do NOT rename existing
fields — the contract is the union of what's already there + the 3 new ones.
"""
import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).parent

SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "schema_version", "method", "status",
        "imputed_columns", "input_artifact", "output_artifact",
    ],
    "properties": {
        "schema_version": {"type": "integer", "minimum": 1},
        "method": {"type": "string", "minLength": 1},
        "status": {"type": "string", "enum": ["completed", "skipped", "failed"]},
        # Method-agnostic core (rows_imputed is new in V1.5.4.1)
        "rows_imputed": {"type": "integer", "minimum": 0},
        "imputed_columns": {"type": "array", "items": {"type": "string"}},
        "input_artifact": {"type": "string", "minLength": 1},
        "output_artifact": {"type": "string"},
        # Method-specific (MICE) — already present in existing summary
        "selected_columns": {"type": "array", "items": {"type": "string"}},
        "skipped_columns": {"type": "array", "items": {"type": "string"}},
        "m": {"type": "integer"},
        "persisted_datasets": {"type": "integer"},
        "pooled_estimates": {"type": "boolean"},
        "max_iter": {"type": "integer"},
        "random_seed": {"type": "integer"},
        "max_missing_rate": {"type": "number"},
        "row_count": {"type": "integer"},
        "warnings": {"type": "array"},
    },
    # Allow future method-specific fields (e.g. knn's `k`, mean_fill's `strategy`).
    "additionalProperties": True,
}


def test_summary_sample_matches_schema():
    sample = json.loads((ROOT / "imputation_summary.mice.sample.json").read_text())
    jsonschema.validate(sample, SCHEMA)


def test_sample_has_completed_mice():
    sample = json.loads((ROOT / "imputation_summary.mice.sample.json").read_text())
    assert sample["method"] == "mice"
    assert sample["status"] == "completed"


def test_sample_carries_new_v1_5_4_1_fields():
    """The whole point of the V1.5.4.1 contract is to add these three fields."""
    sample = json.loads((ROOT / "imputation_summary.mice.sample.json").read_text())
    assert "rows_imputed" in sample
    assert "input_artifact" in sample
    assert "output_artifact" in sample
