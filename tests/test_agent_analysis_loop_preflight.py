from __future__ import annotations

import unicodedata

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")

from workbench.analysis_loop.contracts import (
    ClusterPreflightResult,
    ComparisonTarget,
    IntentValidationResult,
    SourceValidationResult,
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
    RecoveryAction,
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


def test_source_status_complete_is_not_a_valid_completed_source_terminal() -> None:
    result = validate_source_contract(_source(status="complete"))

    assert result.valid is False
    assert result.code == "SOURCE_NOT_COMPLETED"


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


@pytest.mark.parametrize(
    ("run_inputs", "code"),
    [
        (
            {"form": {"model_type": "ols"}, "payload_hash": "payload-hash"},
            "SOURCE_WIRE_COVARIANCE_MISSING",
        ),
        (
            {"form": {"model_type": "ols", "covariance": "robust"}},
            "SOURCE_WIRE_COVARIANCE_UNSUPPORTED",
        ),
        (
            {
                "covariance": "clustered",
                "form": {"model_type": "ols", "covariance": "unadjusted"},
            },
            "SOURCE_WIRE_COVARIANCE_CONFLICT",
        ),
    ],
)
def test_source_run_inputs_prove_explicit_unadjusted_wire_covariance(
    run_inputs: dict[str, object], code: str
) -> None:
    result = validate_source_contract(_source(run_inputs=run_inputs))

    assert result.valid is False
    assert result.code == code


def test_matching_top_level_and_form_wire_covariance_is_allowed() -> None:
    result = validate_source_contract(
        _source(
            run_inputs={
                "covariance": "unadjusted",
                "form": {"model_type": "ols", "covariance": "unadjusted"},
            }
        )
    )

    assert result.valid is True


@pytest.mark.parametrize(
    ("run_inputs", "code"),
    [
        (
            {"form": {"covariance": "unadjusted"}, "payload_hash": "payload-hash"},
            "SOURCE_MODEL_MISMATCH",
        ),
        (
            {
                "form": {"model_type": "logit", "covariance": "unadjusted"},
                "payload_hash": "payload-hash",
            },
            "SOURCE_MODEL_MISMATCH",
        ),
    ],
)
def test_source_executable_payload_must_explicitly_be_ols(
    run_inputs: dict[str, object], code: str
) -> None:
    result = validate_source_contract(_source(run_inputs=run_inputs))

    assert result.valid is False
    assert result.code == code


@pytest.mark.parametrize("rows", [("r1", "r1", "r2", "r3"), ("r1", "", "r2", "r3"), ()])
def test_source_analysis_row_ids_must_be_non_empty_and_unique(rows: tuple[str, ...]) -> None:
    result = validate_source_contract(_source(analysis_row_ids=rows))

    assert result.valid is False
    assert result.code == "SOURCE_ANALYSIS_ROWS_UNSTABLE"


@pytest.mark.parametrize(
    "artifact",
    [
        {"artifact_id": "ols-result"},
        {"artifact_id": "ols-result", "stable_result_ids": ["coef:treatment"]},
        {
            "artifact_id": "ols-result",
            "stable_result_ids": ["coef:treatment", "coef:treatment"],
        },
        {
            "artifact_id": "ols-result",
            "stable_result_ids": ["coef:treatment", 7],
        },
    ],
)
def test_source_requires_complete_unique_non_empty_artifact_result_ids(
    artifact: dict[str, object],
) -> None:
    result = validate_source_contract(_source(result_artifact=artifact))

    assert result.valid is False
    assert result.code in {"SOURCE_RESULT_IDS_MISSING", "SOURCE_RESULT_IDS_UNSTABLE"}


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


def test_cluster_preflight_normalizes_unicode_nfc_and_nfd_group_identity() -> None:
    nfc = "é"
    nfd = unicodedata.normalize("NFD", nfc)
    source = _source()
    result = preflight_cluster_variable(
        source,
        cluster_variable="firm_id",
        cluster_values=[nfc, nfd, nfc, nfd],
        model_row_ids=list(source.analysis_row_ids),
    )

    assert result.valid is False
    assert result.code == "CLUSTER_COUNT_TOO_LOW"
    assert result.cluster_count == 1


@pytest.mark.parametrize("source", [None, object()])
def test_cluster_preflight_invalid_source_returns_structured_failure(source: object) -> None:
    result = preflight_cluster_variable(
        source,  # type: ignore[arg-type]
        cluster_variable="firm_id",
        cluster_values=["a", "a", "b", "b"],
        model_row_ids=["r1", "r2", "r3", "r4"],
    )

    assert result.valid is False
    assert result.status == "fail"
    assert result.severity == "error"
    assert result.code == "SOURCE_CONTRACT_UNSUPPORTED"
    assert result.evidence
    assert result.invariants


@pytest.mark.parametrize("cluster_values", [None, "aabb", b"aabb", 42, object()])
def test_cluster_preflight_rejects_scalar_or_non_sequence_cluster_values(
    cluster_values: object,
) -> None:
    result = preflight_cluster_variable(
        _source(),
        cluster_variable="firm_id",
        cluster_values=cluster_values,  # type: ignore[arg-type]
        model_row_ids=["r1", "r2", "r3", "r4"],
    )

    assert result.valid is False
    assert result.status == "fail"
    assert result.code == "CLUSTER_VALUES_INVALID"
    assert result.evidence["received_type"]
    assert result.invariants


@pytest.mark.parametrize("missing", [pd.NA, pd.NaT])
def test_pandas_nullable_missing_values_are_audited_as_missing(
    missing: object,
) -> None:
    result = preflight_cluster_variable(
        _source(),
        cluster_variable="firm_id",
        cluster_values=["a", missing, "b", "b"],
        model_row_ids=["r1", "r2", "r3", "r4"],
    )

    assert result.valid is False
    assert result.code == "CLUSTER_VARIABLE_MISSING_VALUES"
    assert result.missing_count == 1
    assert list(result.evidence["missing_positions"]) == [1]


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


@pytest.mark.parametrize(
    ("factory", "field"),
    [
        (lambda: {"action_id": "a", "operation_id": "model.rerun", "allowed_model": "ols", "source_covariance": "unadjusted", "target_covariance": "clustered", "required_fields": "cluster_variable", "covariance_only": True, "field_mapping": {"cluster_variable": "entity_col"}, "policy_version": "ols_cluster_policy_v1"}, "required_fields"),
        (lambda: {"valid": True, "status": "pass", "severity": "info", "code": "OK", "evidence": {}, "reason_codes": "OK"}, "reason_codes"),
    ],
)
def test_malformed_json_sequence_fields_are_not_split_into_characters(
    factory: object, field: str
) -> None:
    payload = factory()  # type: ignore[operator]
    if field == "required_fields":
        with pytest.raises(TypeError):
            RecoveryAction.from_dict(payload)
    else:
        with pytest.raises(TypeError):
            SourceValidationResult.from_dict(payload)


@pytest.mark.parametrize("contract_type", [ClusterPreflightResult, IntentValidationResult])
def test_malformed_reason_codes_are_rejected_by_new_contract_from_dict(contract_type: type) -> None:
    if contract_type is ClusterPreflightResult:
        valid = preflight_cluster_variable(
            _source(),
            cluster_variable="firm_id",
            cluster_values=["a", "a", "b", "b"],
            model_row_ids=["r1", "r2", "r3", "r4"],
        ).to_dict()
    else:
        valid = validate_clustered_intent(
            _source(),
            action_id="ols.use_clustered_covariance_v1",
            patch={"covariance": "clustered", "cluster_variable": "firm_id"},
            requested_result_id=None,
            cluster_values=["a", "a", "b", "b"],
            model_row_ids=["r1", "r2", "r3", "r4"],
        ).to_dict()
    valid["reason_codes"] = "not-a-sequence"

    with pytest.raises(TypeError):
        contract_type.from_dict(valid)


@pytest.mark.parametrize("field", ["result_ids", "analysis_row_ids"])
def test_source_contract_rejects_scalar_sequence_fields_without_splitting_strings(
    field: str,
) -> None:
    with pytest.raises(TypeError):
        SourceRunContract(**_source().__dict__ | {field: "not-a-sequence"})

    encoded = _source().to_dict() | {field: "not-a-sequence"}
    with pytest.raises(TypeError):
        SourceRunContract.from_dict(encoded)


def test_python_and_numpy_integer_values_share_one_cluster_identity() -> None:
    source = _source()
    result = preflight_cluster_variable(
        source,
        cluster_variable="integer_id",
        cluster_values=[1, np.int64(1), 1, np.int64(1)],
        model_row_ids=list(source.analysis_row_ids),
    )

    assert result.valid is False
    assert result.code == "CLUSTER_COUNT_TOO_LOW"
    assert result.cluster_count == 1


@pytest.mark.parametrize("invalid_policy", [None, object()])
def test_invalid_cluster_policy_returns_machine_readable_failure(invalid_policy: object) -> None:
    values, rows = _aligned_values()

    result = preflight_cluster_variable(
        _source(),
        cluster_variable="firm_id",
        cluster_values=values,
        model_row_ids=rows,
        policy=invalid_policy,  # type: ignore[arg-type]
    )

    assert result.valid is False
    assert result.status == "fail"
    assert result.code == "CLUSTER_POLICY_INVALID"
    assert result.evidence["policy_error"]


@pytest.mark.parametrize("invalid_action_id", [None, "", 123, []])
def test_invalid_action_ids_fail_closed_with_safe_diagnostic_identity(
    invalid_action_id: object,
) -> None:
    values, rows = _aligned_values()

    result = validate_clustered_intent(
        _source(),
        action_id=invalid_action_id,  # type: ignore[arg-type]
        patch={"covariance": "clustered", "cluster_variable": "firm_id"},
        requested_result_id=None,
        cluster_values=values,
        model_row_ids=rows,
    )

    assert result.valid is False
    assert result.code == "RECOVERY_ACTION_UNSUPPORTED"
    assert isinstance(result.action_id, str)
    assert result.action_id
    assert all(value is False for value in result.side_effects.values())


def test_cluster_preflight_accepts_numpy_pandas_one_dimensional_vectors() -> None:
    source = _source()
    row_ids = np.asarray(source.analysis_row_ids)

    for values in (
        np.asarray(["a", "a", "b", "b"], dtype=object),
        pd.Series(["a", "a", "b", "b"], dtype="string"),
        pd.Categorical(["a", "a", "b", "b"]),
    ):
        result = preflight_cluster_variable(
            source,
            cluster_variable="firm_id",
            cluster_values=values,
            model_row_ids=row_ids,
        )

        assert result.valid is True
        assert result.cluster_count == 2
        assert result.value_type == "string"


@pytest.mark.parametrize(
    "cluster_values",
    [
        None,
        "aabb",
        b"aabb",
        bytearray(b"aabb"),
        {"a": 1},
        1,
        np.asarray("aabb"),
        np.asarray([["a", "b"]]),
    ],
)
def test_cluster_preflight_rejects_non_vector_cluster_values(cluster_values: object) -> None:
    result = preflight_cluster_variable(
        _source(),
        cluster_variable="firm_id",
        cluster_values=cluster_values,  # type: ignore[arg-type]
        model_row_ids=np.asarray(["r1", "r2", "r3", "r4"]),
    )

    assert result.valid is False
    assert result.code == "CLUSTER_VALUES_INVALID"
    assert result.status == "fail"
    assert "received_type" in result.evidence
    assert result.invariants["cluster_field_is_group_vector_only"] is True


@pytest.mark.parametrize(
    "model_row_ids", [None, "r1r2r3r4", b"r1r2r3r4", {"r1": 1}, np.asarray("r1")]
)
def test_cluster_preflight_rejects_non_vector_row_ids(model_row_ids: object) -> None:
    result = preflight_cluster_variable(
        _source(),
        cluster_variable="firm_id",
        cluster_values=np.asarray(["a", "a", "b", "b"]),
        model_row_ids=model_row_ids,  # type: ignore[arg-type]
    )

    assert result.valid is False
    assert result.code == "CLUSTER_ROW_IDS_INVALID"
    assert result.status == "fail"


def test_cluster_preflight_accepts_numpy_string_scalars() -> None:
    result = preflight_cluster_variable(
        _source(),
        cluster_variable="firm_id",
        cluster_values=[np.str_("a"), np.str_("a"), np.str_("b"), np.str_("b")],
        model_row_ids=np.asarray(["r1", "r2", "r3", "r4"]),
    )

    assert result.valid is True
    assert result.value_type == "string"


def test_cluster_preflight_requires_boolean_all_singleton_clusters() -> None:
    result = preflight_cluster_variable(
        _source(),
        cluster_variable="firm_id",
        cluster_values=["a", "a", "b", "b"],
        model_row_ids=["r1", "r2", "r3", "r4"],
    )
    payload = result.to_dict()
    payload["all_singleton_clusters"] = "false"

    with pytest.raises(TypeError):
        ClusterPreflightResult.from_dict(payload)
    with pytest.raises(TypeError):
        ClusterPreflightResult(**result.__dict__ | {"all_singleton_clusters": "false"})  # type: ignore[arg-type]


def test_intent_validation_requires_string_message() -> None:
    result = validate_clustered_intent(
        _source(),
        action_id="ols.use_clustered_covariance_v1",
        patch={"covariance": "clustered", "cluster_variable": "firm_id"},
        requested_result_id=None,
        cluster_values=["a", "a", "b", "b"],
        model_row_ids=["r1", "r2", "r3", "r4"],
    )
    payload = result.to_dict()
    payload["message"] = 123

    with pytest.raises(TypeError):
        IntentValidationResult.from_dict(payload)
    with pytest.raises(TypeError):
        IntentValidationResult(**result.__dict__ | {"message": 123})  # type: ignore[arg-type]
