from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")

from workbench.analysis_loop.contracts import (
    ComparisonTarget,
    IntentValidationResult,
    SourceRunContract,
)
from workbench.analysis_loop.preflight import (
    preflight_cluster_variable,
    resolve_comparison_target,
    validate_clustered_intent,
    validate_source_contract,
)
from workbench.analysis_loop.recovery import (
    RECOVERY_ACTION_REGISTRY,
    RECOVERY_ACTIONS,
    get_recovery_action,
)


def _source(**overrides: object) -> SourceRunContract:
    values: dict[str, object] = {
        "run_id": "run-source",
        "status": "completed",
        "model": "ols",
        "covariance": "unadjusted",
        "result_artifact": {
            "artifact_id": "ols-result",
            "stable_result_ids": ["coef:treatment", "coef:control"],
        },
        "run_inputs": {
            "form": {"model_type": "ols", "covariance": "unadjusted"},
            "payload_hash": "payload-hash",
        },
        "lineage": {"node_ref": "model:ols", "source_run_id": "run-source"},
        "contract_version": "ols_result_contract_v1",
        "result_ids": ("coef:treatment", "coef:control"),
        "primary_estimand": {
            "result_id": "coef:treatment",
            "role": "primary",
            "label": "Treatment",
        },
        "result_labels": {"coef:treatment": "Treatment", "coef:control": "Control"},
        "dataset_schema": {
            "firm_id": {"dtype": "string"},
            "integer_id": {"dtype": "int64"},
            "category_id": {"dtype": "category"},
            "bool_id": {"dtype": "bool"},
            "float_id": {"dtype": "float64"},
            "firm_name": {"dtype": "string"},
        },
        "analysis_row_ids": ("r1", "r2", "r3", "r4"),
    }
    values.update(overrides)
    return SourceRunContract(**values)


def _aligned_values() -> tuple[list[str], list[str]]:
    return ["a", "a", "b", "b"], ["r1", "r2", "r3", "r4"]


def test_completed_explicit_unadjusted_supported_source_passes() -> None:
    result = validate_source_contract(_source())

    assert result.valid is True
    assert result.code == "SOURCE_CONTRACT_SUPPORTED"
    assert result.status == "pass"
    assert result.evidence["contract_version"] == "ols_result_contract_v1"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("status", "failed", "SOURCE_NOT_COMPLETED"),
        ("status", "running", "SOURCE_NOT_COMPLETED"),
        ("model", "logit", "SOURCE_MODEL_UNSUPPORTED"),
        ("covariance", "HC1", "SOURCE_COVARIANCE_UNSUPPORTED"),
        ("result_artifact", None, "SOURCE_RESULT_ARTIFACT_MISSING"),
        ("run_inputs", None, "SOURCE_RUN_INPUTS_MISSING"),
        ("lineage", None, "SOURCE_LINEAGE_MISSING"),
        ("contract_version", "ols_result_contract_v0", "SOURCE_CONTRACT_UNSUPPORTED"),
        ("contract_version", None, "SOURCE_CONTRACT_UNSUPPORTED"),
        ("result_ids", (), "SOURCE_RESULT_IDS_MISSING"),
    ],
)
def test_source_contract_rejects_unsupported_or_incomplete_source(
    field: str, value: object, code: str
) -> None:
    result = validate_source_contract(_source(**{field: value}))

    assert result.valid is False
    assert result.code == code
    assert result.status == "fail"


def test_source_contract_does_not_implicitly_migrate_old_artifacts() -> None:
    result = validate_source_contract(
        _source(contract_version="ols_result_contract_v0", result_ids=("coef:treatment",))
    )

    assert result.valid is False
    assert result.code == "SOURCE_CONTRACT_UNSUPPORTED"


def test_primary_target_is_resolved_before_any_user_target() -> None:
    target = resolve_comparison_target(_source(), requested_result_id="coef:control")

    assert isinstance(target, ComparisonTarget)
    assert target.result_id == "coef:treatment"
    assert target.role == "primary"
    assert target.label == "Treatment"
    assert target.resolution_source == "source_primary_estimand"
    assert target.target_hash


def test_exact_user_result_id_is_the_only_fallback_when_primary_is_absent() -> None:
    source = _source(primary_estimand=None)

    target = resolve_comparison_target(source, requested_result_id="coef:control")

    assert isinstance(target, ComparisonTarget)
    assert target.result_id == "coef:control"
    assert target.resolution_source == "user_exact_result_id"
    assert target.role == "coefficient"
    assert target.label == "Control"


@pytest.mark.parametrize("requested", [None, "Treatment", "coef:treat", "missing-id"])
def test_missing_unknown_or_fuzzy_target_is_rejected_without_guessing(requested: str | None) -> None:
    result = resolve_comparison_target(
        _source(primary_estimand=None), requested_result_id=requested
    )

    assert isinstance(result, IntentValidationResult)
    assert result.valid is False
    assert result.code == (
        "COMPARISON_TARGET_REQUIRED" if requested is None else "COMPARISON_TARGET_UNKNOWN"
    )


def test_cluster_preflight_accepts_integer_string_and_category_values() -> None:
    values, rows = _aligned_values()

    for variable, cluster_values in (
        ("firm_id", values),
        ("integer_id", [1, 1, 2, 2]),
        ("category_id", ["a", "a", "b", "b"]),
    ):
        result = preflight_cluster_variable(
            _source(),
            cluster_variable=variable,
            cluster_values=cluster_values,
            model_row_ids=rows,
        )
        assert result.valid is True
        assert result.status == "warning"
        assert result.cluster_count == 2
        assert result.wire_field == "entity_col"


def test_cluster_preflight_accepts_numpy_integer_values() -> None:
    values, rows = _aligned_values()
    result = preflight_cluster_variable(
        _source(),
        cluster_variable="integer_id",
        cluster_values=[np.int64(1), np.int64(1), np.int64(2), np.int64(2)],
        model_row_ids=rows,
    )

    assert result.valid is True
    assert result.value_type == "integer"


def test_cluster_count_thresholds_are_machine_readable() -> None:
    source = _source(analysis_row_ids=tuple(f"r{i}" for i in range(60)))
    rows = list(source.analysis_row_ids)

    warning = preflight_cluster_variable(
        source,
        cluster_variable="firm_id",
        cluster_values=[f"g{i}" for i in range(2)] * 30,
        model_row_ids=rows,
    )
    passed = preflight_cluster_variable(
        source,
        cluster_variable="firm_id",
        cluster_values=[f"g{i}" for i in range(30)] * 2,
        model_row_ids=rows,
    )

    assert warning.valid is True
    assert warning.status == "warning"
    assert warning.severity == "warning"
    assert warning.cluster_count == 2
    assert passed.valid is True
    assert passed.status == "pass"
    assert passed.severity == "info"
    assert passed.cluster_count == 30


def test_cluster_singletons_are_allowed_but_recorded_and_all_singletons_warn() -> None:
    source = _source(analysis_row_ids=tuple(f"r{i}" for i in range(30)))
    result = preflight_cluster_variable(
        source,
        cluster_variable="firm_id",
        cluster_values=[f"g{i}" for i in range(30)],
        model_row_ids=list(source.analysis_row_ids),
    )

    assert result.valid is True
    assert result.status == "warning"
    assert result.singleton_cluster_count == 30
    assert result.all_singleton_clusters is True
    assert "CLUSTER_ALL_SINGLETONS" in result.reason_codes


@pytest.mark.parametrize(
    ("variable", "values", "code"),
    [
        ("missing_similar_firm", ["a", "a", "b", "b"], "CLUSTER_VARIABLE_NOT_FOUND"),
        ("bool_id", [True, False, True, False], "CLUSTER_TYPE_UNSUPPORTED"),
        ("float_id", [1.0, 1.0, 2.0, 2.0], "CLUSTER_TYPE_UNSUPPORTED"),
        ("firm_id", ["a", None, "b", "b"], "CLUSTER_VARIABLE_MISSING_VALUES"),
        ("firm_id", ["a", float("nan"), "b", "b"], "CLUSTER_VARIABLE_MISSING_VALUES"),
        ("firm_id", ["a", 1, "b", 2], "CLUSTER_TYPE_MIXED"),
        ("firm_id", ["a", "a", "a", "a"], "CLUSTER_COUNT_TOO_LOW"),
    ],
)
def test_cluster_preflight_rejects_unsafe_field_types_and_values(
    variable: str, values: list[object], code: str
) -> None:
    result = preflight_cluster_variable(
        _source(),
        cluster_variable=variable,
        cluster_values=values,
        model_row_ids=list(_source().analysis_row_ids),
    )

    assert result.valid is False
    assert result.status == "fail"
    assert result.code == code
    assert result.evidence["cluster_variable"] == variable


def test_cluster_preflight_requires_exact_analysis_row_set_and_order() -> None:
    values, rows = _aligned_values()

    for bad_rows in (["r2", "r1", "r3", "r4"], ["r1", "r2", "r3"], ["r1", "r2", "r3", "other"]):
        result = preflight_cluster_variable(
            _source(),
            cluster_variable="firm_id",
            cluster_values=values,
            model_row_ids=bad_rows,
        )
        assert result.valid is False
        assert result.code == "CLUSTER_ROW_ALIGNMENT_MISMATCH"


def test_cluster_preflight_exposes_entity_col_covariance_only_invariants() -> None:
    values, rows = _aligned_values()
    result = preflight_cluster_variable(
        _source(), cluster_variable="firm_id", cluster_values=values, model_row_ids=rows
    )

    assert result.invariants == {
        "covariance_only": True,
        "cluster_field_is_group_vector_only": True,
        "wire_field": "entity_col",
        "formula_unchanged": True,
        "y_unchanged": True,
        "X_unchanged": True,
        "intercept_unchanged": True,
        "weights_unchanged": True,
        "analysis_row_set_unchanged": True,
        "analysis_row_order_unchanged": True,
        "point_estimation_unchanged": True,
        "coefficient_schema_unchanged": True,
    }


def test_recovery_registry_contains_exactly_one_action_and_maps_product_to_wire() -> None:
    assert set(RECOVERY_ACTIONS) == {"ols.use_clustered_covariance_v1"}
    assert RECOVERY_ACTION_REGISTRY.action_ids == ("ols.use_clustered_covariance_v1",)

    action = get_recovery_action("ols.use_clustered_covariance_v1")
    assert action.operation_id == "model.rerun"
    assert action.allowed_model == "ols"
    assert action.source_covariance == "unadjusted"
    assert action.target_covariance == "clustered"
    assert action.required_fields == ("cluster_variable",)
    assert action.covariance_only is True
    assert action.field_mapping == {"cluster_variable": "entity_col"}
    assert action.policy_version == "ols_cluster_policy_v1"


def test_valid_intent_canonicalizes_cluster_variable_to_entity_col_without_side_effects() -> None:
    values, rows = _aligned_values()
    result = validate_clustered_intent(
        _source(),
        action_id="ols.use_clustered_covariance_v1",
        patch={"covariance": "clustered", "cluster_variable": "firm_id"},
        requested_result_id=None,
        cluster_values=values,
        model_row_ids=rows,
    )

    assert result.valid is True
    assert result.code == "INTENT_VALID"
    assert result.canonical_patch == {
        "covariance": "clustered",
        "cluster_variable": "firm_id",
    }
    assert result.wire_patch == {"covariance": "clustered", "entity_col": "firm_id"}
    assert result.comparison_target is not None
    assert result.invariants["covariance_only"] is True
    assert result.side_effects == {
        "execution_key_created": False,
        "effect_created": False,
        "operation_record_created": False,
        "child_created": False,
    }


@pytest.mark.parametrize(
    ("action_id", "patch", "code"),
    [
        ("unknown.action", {"covariance": "clustered", "cluster_variable": "firm_id"}, "RECOVERY_ACTION_UNSUPPORTED"),
        ("ols.use_clustered_covariance_v1", {"covariance": "unadjusted", "cluster_variable": "firm_id"}, "COVARIANCE_DIRECTION_UNSUPPORTED"),
        ("ols.use_clustered_covariance_v1", {"covariance": "clustered", "cluster_variable": "firm_id", "formula": "y ~ x"}, "INTENT_PATCH_NOT_COVARIANCE_ONLY"),
        ("ols.use_clustered_covariance_v1", {"covariance": "clustered", "cluster_variable": "firm_id", "x": ["z"]}, "INTENT_PATCH_NOT_COVARIANCE_ONLY"),
        ("ols.use_clustered_covariance_v1", {"covariance": "clustered", "cluster_variable": "firm_id", "cluster_variables": ["other"]}, "INTENT_PATCH_NOT_COVARIANCE_ONLY"),
    ],
)
def test_invalid_action_or_patch_is_rejected_without_execution_side_effects(
    action_id: str, patch: dict[str, object], code: str
) -> None:
    values, rows = _aligned_values()
    result = validate_clustered_intent(
        _source(),
        action_id=action_id,
        patch=patch,
        requested_result_id=None,
        cluster_values=values,
        model_row_ids=rows,
    )

    assert result.valid is False
    assert result.code == code
    assert all(value is False for value in result.side_effects.values())


def test_new_contracts_round_trip_through_json_compatible_dicts() -> None:
    source = _source()
    source_round_trip = SourceRunContract.from_dict(source.to_dict())
    assert source_round_trip == source

    target = resolve_comparison_target(source, requested_result_id=None)
    assert isinstance(target, ComparisonTarget)
    assert ComparisonTarget.from_dict(target.to_dict()) == target

    values, rows = _aligned_values()
    cluster = preflight_cluster_variable(
        source, cluster_variable="firm_id", cluster_values=values, model_row_ids=rows
    )
    assert type(cluster.to_dict()["evidence"]) is dict
    assert type(cluster.to_dict()["invariants"]) is dict

    intent = validate_clustered_intent(
        source,
        action_id="ols.use_clustered_covariance_v1",
        patch={"covariance": "clustered", "cluster_variable": "firm_id"},
        requested_result_id=None,
        cluster_values=values,
        model_row_ids=rows,
    )
    assert IntentValidationResult.from_dict(intent.to_dict()) == intent
