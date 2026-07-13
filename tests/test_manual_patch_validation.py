import pytest

from workbench.lineage.manual_patch_validation import (
    ManualPatchValidationError,
    ManualRerunPatch,
    normalize_for_compare,
    validate_manual_patch,
)


def _schema():
    return [
        {
            "key": "covariance",
            "label": "Covariance",
            "kind": "select",
            "editable": True,
            "options": ["clustered", "robust"],
            "value": "clustered",
        },
        {
            "key": "internal_id",
            "label": "Internal",
            "kind": "text",
            "editable": False,
            "value": "locked",
        },
    ]


def _patch(**overrides):
    data = {
        "patch_id": "patch_1",
        "patch_source": "MANUAL_EDIT",
        "source_context_fingerprint": "nocv1:source",
        "editable_schema_version": "schema:v1",
        "target": {
            "owner_run_id": "run_source",
            "op_node_id": "model:ols_1",
            "node_hash": "hash_source",
        },
        "changes": [
            {
                "field_id": "covariance",
                "old_value": "clustered",
                "new_value": "robust",
            }
        ],
    }
    data.update(overrides)
    return ManualRerunPatch(**data)


def test_valid_patch_returns_overrides():
    result = validate_manual_patch(
        patch=_patch(),
        current_values={"covariance": "clustered"},
        editable_schema=_schema(),
        editable_schema_version="schema:v1",
    )
    assert result == {"covariance": "robust"}


def test_columns_patch_accepts_a_reduced_regressor_list():
    schema = _schema() + [
        {
            "key": "x",
            "label": "Regressors (X)",
            "kind": "columns",
            "options": ["x1", "x2"],
            "value": ["x1", "x2"],
        }
    ]
    patch = _patch(
        changes=[
            {"field_id": "x", "old_value": ["x1", "x2"], "new_value": ["x1"]}
        ]
    )
    result = validate_manual_patch(
        patch=patch,
        current_values={"x": ["x1", "x2"]},
        editable_schema=schema,
        editable_schema_version="schema:v1",
    )
    assert result == {"x": ["x1"]}


def test_empty_patch_rejected():
    with pytest.raises(ManualPatchValidationError, match="EMPTY_PATCH"):
        validate_manual_patch(
            patch=_patch(changes=[]),
            current_values={"covariance": "clustered"},
            editable_schema=_schema(),
            editable_schema_version="schema:v1",
        )


def test_duplicate_field_rejected():
    duplicate = [
        {"field_id": "covariance", "old_value": "clustered", "new_value": "robust"},
        {"field_id": "covariance", "old_value": "clustered", "new_value": "robust"},
    ]
    with pytest.raises(ManualPatchValidationError, match="DUPLICATE_FIELD"):
        validate_manual_patch(
            patch=_patch(changes=duplicate),
            current_values={"covariance": "clustered"},
            editable_schema=_schema(),
            editable_schema_version="schema:v1",
        )


def test_noop_after_normalization_rejected():
    with pytest.raises(ManualPatchValidationError, match="NOOP_PATCH"):
        validate_manual_patch(
            patch=_patch(
                changes=[
                    {
                        "field_id": "covariance",
                        "old_value": "clustered",
                        "new_value": "clustered",
                    }
                ],
            ),
            current_values={"covariance": "clustered"},
            editable_schema=_schema(),
            editable_schema_version="schema:v1",
        )


def test_field_value_stale_rejected():
    with pytest.raises(ManualPatchValidationError, match="FIELD_VALUE_STALE"):
        validate_manual_patch(
            patch=_patch(
                changes=[
                    {
                        "field_id": "covariance",
                        "old_value": "clustered",
                        "new_value": "robust",
                    }
                ],
            ),
            current_values={"covariance": "robust"},
            editable_schema=_schema(),
            editable_schema_version="schema:v1",
        )


def test_object_normalization_sorts_keys():
    assert normalize_for_compare({"b": 2, "a": 1}) == normalize_for_compare(
        {"a": 1, "b": 2}
    )
