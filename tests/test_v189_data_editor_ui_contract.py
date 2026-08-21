from __future__ import annotations

import pytest

from workbench.http.data_operation_routes import _bounded_data_profile_projection


def test_profile_projection_keeps_only_bounded_data_editor_fields() -> None:
    profile = _bounded_data_profile_projection(
        {
            "schema_version": "data-profile.v1",
            "source": {
                "run_id": "run-1",
                "node_id": "node-1",
                "artifact_id": "artifact-1",
                "source_path": "/private/raw.csv",
            },
            "variables": [
                {
                    "name": "score",
                    "label": "Score label",
                    "measurement_level": "scale",
                    "missingness": {"count": 1, "rate": 0.25},
                    "user_missing_values": [-99],
                    "value_labels": {"1": "Yes"},
                    "sample_values": [1, 2, 3],
                    "raw_rows": [{"score": 1}],
                    "source_artifact_path": "/private/raw.csv",
                }
            ],
            "raw_artifact_json": {"rows": [{"score": 1}]},
        }
    )

    assert profile == {
        "schema_version": "data-profile.v1",
        "source": {"run_id": "run-1", "node_id": "node-1", "artifact_id": "artifact-1"},
        "variables": [
            {
                "name": "score",
                "label": "Score label",
                "measurement_level": "scale",
                "missingness": {"count": 1, "rate": 0.25},
                "user_missing_values": [-99],
                "value_labels": {"1": "Yes"},
                "sample_values": [1, 2, 3],
            }
        ],
    }
    assert "source_artifact_path" not in repr(profile)
    assert "raw_rows" not in repr(profile)


def test_profile_projection_fails_closed_for_untrusted_variable_payload() -> None:
    with pytest.raises(ValueError, match="not scalar"):
        _bounded_data_profile_projection(
            {
                "schema_version": "data-profile.v1",
                "source": {"run_id": "run-1", "node_id": "node-1", "artifact_id": "artifact-1"},
                "variables": [
                    {
                        "name": "score",
                        "label": "Score label",
                        "measurement_level": "scale",
                        "missingness": {"count": 1, "rate": 0.25},
                        "user_missing_values": [{"raw": "-99"}],
                        "value_labels": {"1": "Yes"},
                        "sample_values": [1, 2, 3],
                    }
                ],
            }
        )


def test_profile_projection_normalizes_canonical_typed_columns() -> None:
    profile = _bounded_data_profile_projection(
        {
            "dataset_ref": {
                "run_id": "run-1",
                "node_id": "node-1",
                "artifact_id": "artifact-1",
                "content_sha256": "a" * 64,
            },
            "columns": [
                {
                    "name": "score",
                    "observed": {
                        "dtype": "float64",
                        "row_count": 4,
                        "missing_count": 1,
                        "missing_rate": 0.25,
                        "unique_count": 3,
                        "unique_ratio": 0.75,
                        "sample_values": [1.0, 2.0],
                    },
                    "declared": {
                        "variable_label": "Score label",
                        "value_labels": {"1": "Yes"},
                        "measurement_level": "scale",
                        "user_missing_values": [-99],
                    },
                    "inferred": {"confirmed": False},
                    "source_path": "/private/raw.csv",
                }
            ],
        }
    )

    assert profile == {
        "schema_version": "data-profile.v1",
        "source": {"run_id": "run-1", "node_id": "node-1", "artifact_id": "artifact-1"},
        "variables": [
            {
                "name": "score",
                "label": "Score label",
                "measurement_level": "scale",
                "missingness": {"count": 1, "rate": 0.25},
                "user_missing_values": [-99],
                "value_labels": {"1": "Yes"},
                "sample_values": [1.0, 2.0],
            }
        ],
    }
    assert "source_path" not in repr(profile)


def test_profile_projection_adapts_canonical_nested_columns_to_bounded_variables() -> None:
    profile = _bounded_data_profile_projection(
        {
            "dataset_ref": {
                "run_id": "run-1",
                "node_id": "node-1",
                "artifact_id": "artifact-1",
                "content_sha256": "a" * 64,
                "schema_revision": "schema:1",
                "metadata_revision": "metadata:1",
            },
            "shape": {"rows": 4, "columns": 1},
            "columns": [
                {
                    "name": "score",
                    "observed": {
                        "dtype": "float64",
                        "row_count": 4,
                        "missing_count": 1,
                        "missing_rate": 0.25,
                        "sample_values": [1.0, None, 3.0],
                        "raw_rows": [{"score": 1.0}],
                        "source_path": "/private/raw.csv",
                    },
                    "declared": {
                        "variable_label": "Score label",
                        "measurement_level": "scale",
                        "user_missing_values": [-99],
                        "value_labels": {"1": "Yes"},
                        "raw_artifact_json": {"rows": [{"score": 1.0}]},
                    },
                    "inferred": {
                        "confirmed": False,
                        "role_candidates": ["outcome"],
                    },
                }
            ],
        }
    )

    assert profile == {
        "schema_version": "data-profile.v1",
        "source": {"run_id": "run-1", "node_id": "node-1", "artifact_id": "artifact-1"},
        "variables": [
            {
                "name": "score",
                "label": "Score label",
                "measurement_level": "scale",
                "missingness": {"count": 1, "rate": 0.25},
                "user_missing_values": [-99],
                "value_labels": {"1": "Yes"},
                "sample_values": [1.0, None, 3.0],
            }
        ],
    }
    assert "raw_rows" not in repr(profile)
    assert "source_path" not in repr(profile)
    assert "raw_artifact_json" not in repr(profile)


def test_profile_projection_preserves_explicit_unknowns_and_safe_empty_values() -> None:
    profile = _bounded_data_profile_projection(
        {
            "dataset_ref": {
                "run_id": "run-1",
                "node_id": "node-1",
                "artifact_id": "artifact-1",
                "content_sha256": "a" * 64,
                "schema_revision": "schema:1",
                "metadata_revision": "metadata:1",
            },
            "columns": [
                {
                    "name": "amount",
                    "observed": {
                        "missing_count": 0,
                        "missing_rate": 0.0,
                        "sample_values": [],
                    },
                    "declared": {
                        "variable_label": "unknown",
                        "measurement_level": "unknown",
                        "user_missing_values": [],
                        "value_labels": None,
                    },
                    "inferred": {"confirmed": False},
                }
            ],
        }
    )

    assert profile["variables"] == [
        {
            "name": "amount",
            "label": "unknown",
            "measurement_level": "unknown",
            "missingness": {"count": 0, "rate": 0.0},
            "user_missing_values": [],
            "value_labels": {},
            "sample_values": [],
        }
    ]


def test_profile_projection_rejects_malformed_nested_column_metadata() -> None:
    with pytest.raises(ValueError, match="nested|observed|declared"):
        _bounded_data_profile_projection(
            {
                "dataset_ref": {
                    "run_id": "run-1",
                    "node_id": "node-1",
                    "artifact_id": "artifact-1",
                },
                "columns": [
                    {
                        "name": "score",
                        "observed": [],
                        "declared": {"variable_label": "Score"},
                    }
                ],
            }
        )


def test_profile_projection_rejects_non_scalar_nested_values() -> None:
    with pytest.raises(ValueError, match="not scalar"):
        _bounded_data_profile_projection(
            {
                "dataset_ref": {
                    "run_id": "run-1",
                    "node_id": "node-1",
                    "artifact_id": "artifact-1",
                },
                "columns": [
                    {
                        "name": "score",
                        "observed": {
                            "missing_count": 1,
                            "missing_rate": 0.5,
                            "sample_values": [{"raw": 1}],
                        },
                        "declared": {
                            "variable_label": "Score",
                            "measurement_level": "scale",
                            "user_missing_values": [],
                            "value_labels": {},
                        },
                        "inferred": {"confirmed": False},
                    }
                ],
            }
        )
