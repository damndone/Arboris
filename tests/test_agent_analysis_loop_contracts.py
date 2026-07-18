import math
from decimal import Decimal, localcontext

import pytest

from workbench.analysis_loop.canonical import (
    CanonicalJSONError,
    canonical_json_v1,
    numeric_equal,
    numbers_equal,
    sha256_canonical,
)
from workbench.analysis_loop.contracts import (
    ComparePayload,
    PacketConflictError,
    PacketEnvelope,
    ensure_packet_idempotent,
    plan_diff_logical_key,
    validation_packet_logical_key,
    compare_packet_logical_key,
)
from workbench.analysis_loop.policy import ols_cluster_policy_v1
from workbench.analysis_loop.policy import OLSClusterPolicyV1


def test_canonical_json_v1_normalizes_keys_unicode_and_negative_zero():
    decomposed = "e\u0301"
    composed = "é"
    first = {"z": -0.0, decomposed: "cafe\u0301"}
    second = {composed: "café", "z": 0}

    assert canonical_json_v1(first) == canonical_json_v1(second)
    assert canonical_json_v1(first) == '{"z":0,"é":"café"}'
    assert sha256_canonical(first) == sha256_canonical(second)
    assert sha256_canonical({"field": None}) != sha256_canonical({})


def test_canonical_json_v1_uses_one_number_text_for_equal_int_and_float_values():
    assert canonical_json_v1(1) == canonical_json_v1(1.0) == "1"
    assert canonical_json_v1(1e-6) == "0.000001"
    assert canonical_json_v1(1e-7) == "1e-7"
    assert canonical_json_v1(1e20) == "100000000000000000000"
    assert canonical_json_v1(1e21) == "1e+21"
    assert canonical_json_v1(10**21) == str(10**21)
    assert canonical_json_v1(9007199254740993) == "9007199254740993"
    assert canonical_json_v1(9007199254740992.0) == "9007199254740992"
    assert canonical_json_v1(9007199254740993) != canonical_json_v1(9007199254740992.0)


def test_canonical_json_v1_rejects_non_finite_numbers_and_hash_is_sha256_hex():
    for value in (math.nan, math.inf, -math.inf, {"x": math.nan}):
        with pytest.raises(CanonicalJSONError):
            canonical_json_v1(value)
        with pytest.raises(CanonicalJSONError):
            sha256_canonical(value)

    digest = sha256_canonical({"hello": "世界"})
    assert len(digest) == 64
    assert digest == digest.lower()
    assert all(char in "0123456789abcdef" for char in digest)


@pytest.mark.parametrize(
    "value",
    ["\ud800", {"nested": "\ud800"}, ["valid", "\ud800"], {"\ud800": "value"}],
)
def test_canonical_json_v1_rejects_lone_surrogates_before_utf8_encoding(value):
    with pytest.raises(CanonicalJSONError):
        canonical_json_v1(value)
    with pytest.raises(CanonicalJSONError):
        sha256_canonical(value)


def test_canonical_json_v1_keeps_unicode_scalar_values_stable():
    value = {"text": "世界🙂"}
    assert canonical_json_v1(value) == '{"text":"世界🙂"}'
    assert sha256_canonical(value) == sha256_canonical({"text": "世界🙂"})


def test_canonical_json_v1_preserves_all_digits_for_huge_integer_paths():
    first = 10**100 + 1
    second = 10**100 + 2
    assert canonical_json_v1(first) == str(first)
    assert canonical_json_v1(second) == str(second)
    assert sha256_canonical(first) != sha256_canonical(second)


def test_canonical_json_v1_float_scientific_format_ignores_low_decimal_precision():
    first = 1.23456789e100
    second = 1.23456889e100
    expected_first = canonical_json_v1(first)
    expected_second = canonical_json_v1(second)
    assert expected_first != expected_second

    with localcontext() as context:
        context.prec = 5
        assert canonical_json_v1(first) == expected_first
        assert canonical_json_v1(second) == expected_second
        assert sha256_canonical(first) != sha256_canonical(second)


def test_numbers_equal_uses_absolute_relative_tolerance_and_special_values():
    assert numbers_equal(10.0, 10.000001, atol=1e-6)
    assert not numbers_equal(10.0, 10.000002, atol=1e-6)
    assert numbers_equal(1_000_000.0, 1_000_001.0, rtol=1e-6)
    assert numbers_equal(-0.0, 0.0)
    assert not numbers_equal(math.nan, math.nan)
    assert numbers_equal(math.inf, math.inf)
    assert not numbers_equal(math.inf, -math.inf)


def test_numbers_equal_handles_arbitrarily_large_integers_without_overflow():
    value = 10**1000
    assert numbers_equal(value, value)
    assert numbers_equal(value, value + 1, atol=1.0)
    assert not numbers_equal(value, value + 2, atol=1.0)


def test_numbers_equal_rejects_bool_and_decimal_like_operands():
    for invalid in (True, False, Decimal("1")):
        with pytest.raises(TypeError, match="int or float"):
            numbers_equal(invalid, 1)
        with pytest.raises(TypeError, match="int or float"):
            numbers_equal(1, invalid)

    assert numeric_equal is numbers_equal


def _envelope(status: str = "complete") -> PacketEnvelope:
    return PacketEnvelope(
        packet_type="validation",
        schema_version="analysis-loop.packet.v1",
        status=status,
        source={"run_id": "source-1"},
        child={"run_id": "child-1"},
        operation={"action_id": "fit"},
        execution={"engine": "statsmodels"},
        logical_key="logical-key-1",
        input_fingerprints={"dataset": "a" * 64},
        policy_versions={"validation": "v1"},
        timestamps={"created_at": "2026-07-17T00:00:00Z"},
        reasons=("ok",),
        payload={"value": 1},
    )


def test_packet_envelope_round_trips_all_fields_and_validates_status():
    packet = _envelope()
    restored = PacketEnvelope.from_dict(packet.to_dict())

    assert restored == packet
    assert restored.to_dict() == packet.to_dict()

    with pytest.raises(ValueError, match="status"):
        _envelope("running")


def test_compare_payload_rejects_pending_but_accepts_terminal_compare_statuses():
    for status in ("complete", "partial", "not_comparable", "blocked_by_integrity"):
        payload = ComparePayload(compare_status=status, payload={"estimate": 1})
        assert ComparePayload.from_dict(payload.to_dict()) == payload

    with pytest.raises(ValueError, match="compare_status"):
        ComparePayload(compare_status="pending")


def test_compare_payload_rejects_reserved_compare_status_in_nested_payload():
    with pytest.raises(ValueError, match="compare_status"):
        ComparePayload(compare_status="complete", payload={"compare_status": "partial"})

    with pytest.raises(ValueError, match="compare_status"):
        ComparePayload(compare_status="complete", payload={"compare_status": "complete"})


def test_logical_keys_bind_exact_declared_inputs():
    plan_key = plan_diff_logical_key(
        source_run_id="run-1",
        source_context_fingerprint="ctx-1",
        action_id="patch",
        canonical_patch_hash="patch-1",
        comparison_target_hash="target-1",
        schema_version="v1",
    )
    assert plan_key == plan_diff_logical_key(
        source_run_id="run-1",
        source_context_fingerprint="ctx-1",
        action_id="patch",
        canonical_patch_hash="patch-1",
        comparison_target_hash="target-1",
        schema_version="v1",
    )
    assert plan_key == sha256_canonical(
        ["run-1", "ctx-1", "patch", "patch-1", "target-1", "v1"]
    )
    assert plan_key != plan_diff_logical_key(
        source_run_id="run-2",
        source_context_fingerprint="ctx-1",
        action_id="patch",
        canonical_patch_hash="patch-1",
        comparison_target_hash="target-1",
        schema_version="v1",
    )

    assert validation_packet_logical_key(
        child_run_id="child-1",
        executed_payload_hash="payload-1",
        artifact_manifest_hash="manifest-1",
        validation_policy_version="policy-1",
        schema_version="v1",
    ) != validation_packet_logical_key(
        child_run_id="child-1",
        executed_payload_hash="payload-2",
        artifact_manifest_hash="manifest-1",
        validation_policy_version="policy-1",
        schema_version="v1",
    )
    assert compare_packet_logical_key(
        source_run_id="source-1",
        child_run_id="child-1",
        comparison_target_set_hash="targets-1",
        strategy_version="strategy-1",
        schema_version="v1",
    ) != compare_packet_logical_key(
        source_run_id="source-1",
        child_run_id="child-1",
        comparison_target_set_hash="targets-2",
        strategy_version="strategy-1",
        schema_version="v1",
    )


def test_every_logical_key_component_changes_its_key():
    plan = {
        "source_run_id": "run-1",
        "source_context_fingerprint": "ctx-1",
        "action_id": "patch",
        "canonical_patch_hash": "patch-1",
        "comparison_target_hash": "target-1",
        "schema_version": "v1",
    }
    baseline = plan_diff_logical_key(**plan)
    for field in plan:
        changed = plan | {field: f"changed-{field}"}
        assert plan_diff_logical_key(**changed) != baseline

    validation = {
        "child_run_id": "child-1",
        "executed_payload_hash": "payload-1",
        "artifact_manifest_hash": "manifest-1",
        "validation_policy_version": "policy-1",
        "schema_version": "v1",
    }
    baseline = validation_packet_logical_key(**validation)
    for field in validation:
        changed = validation | {field: f"changed-{field}"}
        assert validation_packet_logical_key(**changed) != baseline

    compare = {
        "source_run_id": "source-1",
        "child_run_id": "child-1",
        "comparison_target_set_hash": "targets-1",
        "strategy_version": "strategy-1",
        "schema_version": "v1",
    }
    baseline = compare_packet_logical_key(**compare)
    for field in compare:
        changed = compare | {field: f"changed-{field}"}
        assert compare_packet_logical_key(**changed) != baseline


def test_packet_idempotence_does_not_overwrite_terminal_packet():
    existing = _envelope("complete")
    same = PacketEnvelope.from_dict(existing.to_dict())
    changed = PacketEnvelope.from_dict(existing.to_dict() | {"payload": {"value": 2}})

    assert ensure_packet_idempotent(existing, same) is existing
    with pytest.raises(PacketConflictError):
        ensure_packet_idempotent(existing, changed)


def test_pending_packet_can_advance_only_with_same_packet_identity():
    existing = _envelope("pending")
    same = PacketEnvelope.from_dict(existing.to_dict())
    assert ensure_packet_idempotent(existing, same) is existing

    changed_pending = PacketEnvelope.from_dict(
        existing.to_dict() | {"payload": {"value": 2}}
    )
    with pytest.raises(PacketConflictError, match="pending"):
        ensure_packet_idempotent(existing, changed_pending)

    terminal = PacketEnvelope.from_dict(
        existing.to_dict() | {"status": "complete", "payload": {"value": 2}}
    )
    assert ensure_packet_idempotent(existing, terminal) is terminal

    for field in ("packet_type", "schema_version", "logical_key"):
        changed = PacketEnvelope.from_dict(
            existing.to_dict() | {field: f"different-{field}"}
        )
        with pytest.raises(PacketConflictError, match="identity"):
            ensure_packet_idempotent(existing, changed)


def test_ensure_packet_idempotent_documents_identity_and_replacement_semantics():
    doc = ensure_packet_idempotent.__doc__ or ""
    assert "identity" in doc
    assert "terminal" in doc
    assert "pending" in doc
    assert "content" in doc


def test_packet_envelope_requires_every_field_and_preserves_empty_values():
    value = _envelope("pending").to_dict()
    value.update(
        {
            "source": {},
            "child": {},
            "operation": {},
            "execution": {},
            "input_fingerprints": {},
            "policy_versions": {},
            "timestamps": {},
            "reasons": [],
            "payload": {},
        }
    )
    restored = PacketEnvelope.from_dict(value)
    assert restored.source == {}
    assert restored.reasons == ()
    assert restored.payload == {}

    fields = (
        "packet_type",
        "schema_version",
        "status",
        "source",
        "child",
        "operation",
        "execution",
        "logical_key",
        "input_fingerprints",
        "policy_versions",
        "timestamps",
        "reasons",
        "payload",
    )
    for field in fields:
        with pytest.raises((KeyError, TypeError, ValueError), match=field):
            PacketEnvelope.from_dict({key: item for key, item in value.items() if key != field})
        with pytest.raises((TypeError, ValueError), match=field):
            PacketEnvelope.from_dict(value | {field: None})


def test_packet_envelope_from_dict_rejects_unknown_fields_fail_closed():
    value = _envelope().to_dict()
    with pytest.raises(ValueError, match="extra.*future_field"):
        PacketEnvelope.from_dict(value | {"future_field": "not allowed"})

    with pytest.raises(ValueError, match="extra.*unknown_field"):
        PacketEnvelope.from_dict(value | {"unknown_field": {}})


def test_packet_envelope_from_dict_rejects_wrong_contract_types():
    value = _envelope().to_dict()
    invalid = {
        "packet_type": 1,
        "schema_version": 1,
        "status": 1,
        "source": [],
        "child": [],
        "operation": [],
        "execution": [],
        "logical_key": 1,
        "input_fingerprints": [],
        "policy_versions": [],
        "timestamps": [],
        "reasons": {},
        "payload": [],
    }
    for field, wrong_value in invalid.items():
        with pytest.raises((TypeError, ValueError), match=field):
            PacketEnvelope.from_dict(value | {field: wrong_value})


def test_packet_envelope_rejects_integer_mapping_keys_in_all_json_maps():
    value = _envelope().to_dict()
    fields = (
        "source",
        "child",
        "operation",
        "execution",
        "input_fingerprints",
        "policy_versions",
        "timestamps",
        "payload",
    )
    for field in fields:
        with pytest.raises(TypeError, match=f"{field}.*keys"):
            PacketEnvelope.from_dict(value | {field: {1: "value"}})
        with pytest.raises(TypeError, match=f"{field}.*keys"):
            PacketEnvelope(**(value | {field: {1: "value"}}))


def test_packet_envelope_direct_constructor_matches_from_dict_type_validation():
    value = _envelope().to_dict()
    invalid = {
        "packet_type": 1,
        "schema_version": 1,
        "status": 1,
        "source": [],
        "logical_key": 1,
        "input_fingerprints": {"dataset": 1},
        "reasons": {},
        "payload": [],
    }
    for field, wrong_value in invalid.items():
        with pytest.raises((TypeError, ValueError), match=field):
            PacketEnvelope(**(value | {field: wrong_value}))


def test_compare_payload_direct_and_from_dict_validation_match():
    with pytest.raises(TypeError, match="compare_status"):
        ComparePayload(compare_status=1, payload={})
    with pytest.raises(TypeError, match="compare_status"):
        ComparePayload.from_dict({"compare_status": 1})
    with pytest.raises(TypeError, match="payload"):
        ComparePayload(compare_status="complete", payload=[])
    with pytest.raises(TypeError, match="mapping"):
        ComparePayload.from_dict([])


def test_packet_and_compare_payload_recursively_freeze_inputs_and_thaw_to_json():
    source = {"nested": {"items": [1]}}
    payload = {"nested": {"items": ["x"]}}
    packet = PacketEnvelope.from_dict(
        _envelope().to_dict() | {"source": source, "payload": payload}
    )
    comparison = ComparePayload(compare_status="complete", payload=payload)

    source["nested"]["items"].append(2)
    payload["nested"]["items"].append("y")
    assert packet.source["nested"]["items"] == (1,)
    assert comparison.payload["nested"]["items"] == ("x",)

    with pytest.raises(TypeError):
        packet.source["nested"]["new"] = "blocked"
    with pytest.raises(TypeError):
        comparison.payload["nested"]["new"] = "blocked"

    packet_dict = packet.to_dict()
    compare_dict = comparison.to_dict()
    assert isinstance(packet_dict["source"], dict)
    assert isinstance(packet_dict["source"]["nested"]["items"], list)
    assert isinstance(compare_dict["nested"]["items"], list)
    assert PacketEnvelope.from_dict(packet_dict) == packet
    assert ComparePayload.from_dict(compare_dict) == comparison


def test_ols_cluster_policy_is_immutable_and_has_exact_values():
    policy = ols_cluster_policy_v1
    assert policy.allowed_model == "ols"
    assert policy.allowed_covariance == "clustered"
    assert policy.allowed_cluster_types == ("integer", "string", "category")
    assert policy.reject_boolean is True
    assert policy.reject_float is True
    assert policy.reject_mixed_object is True
    assert policy.reject_null_or_nan is True
    assert policy.hard_min_cluster_count == 2
    assert policy.warning_cluster_count_below == 30
    assert policy.one_way_only is True
    assert policy.allow_singleton_clusters is True
    assert policy.all_singleton_clusters == "warning"
    assert policy.small_sample_correction is True
    assert policy.degrees_of_freedom_correction is True
    assert policy.use_t is False
    assert policy.confidence_level == 0.95
    assert policy.alpha == 0.05
    assert policy.inference_distribution == "normal"
    assert policy.p_value_method == "normal_z"
    assert policy.confidence_interval_method == "normal_z"
    assert policy.effective_degrees_of_freedom == "record_per_target"
    assert policy.engine == "statsmodels"
    assert policy.minimum_engine_version == 0.14

    with pytest.raises((AttributeError, TypeError)):
        policy.use_t = True


def test_ols_cluster_policy_round_trips_and_rejects_non_exact_contract_values():
    assert OLSClusterPolicyV1.from_dict(ols_cluster_policy_v1.to_dict()) == ols_cluster_policy_v1

    invalid_values = {
        "allowed_model": "logit",
        "allowed_covariance": "HC1",
        "allowed_cluster_types": ["integer", "float"],
        "reject_boolean": "false",
        "reject_float": 1,
        "reject_mixed_object": None,
        "reject_null_or_nan": "true",
        "hard_min_cluster_count": "2",
        "warning_cluster_count_below": True,
        "one_way_only": 1,
        "allow_singleton_clusters": "true",
        "all_singleton_clusters": "warn",
        "small_sample_correction": "true",
        "degrees_of_freedom_correction": 1,
        "use_t": "false",
        "confidence_level": "0.95",
        "alpha": True,
        "inference_distribution": "t",
        "p_value_method": "t",
        "confidence_interval_method": "t",
        "effective_degrees_of_freedom": "residual",
        "engine": "numpy",
        "minimum_engine_version": "0.14",
    }
    for field, invalid in invalid_values.items():
        with pytest.raises((TypeError, ValueError), match=field):
            OLSClusterPolicyV1.from_dict(ols_cluster_policy_v1.to_dict() | {field: invalid})

    with pytest.raises(ValueError, match="exact"):
        OLSClusterPolicyV1.from_dict(ols_cluster_policy_v1.to_dict() | {"extra": True})


def test_ols_cluster_policy_direct_constructor_enforces_exact_v1_contract():
    values = ols_cluster_policy_v1.to_dict()
    invalid_values = {
        "allowed_model": "logit",
        "allowed_cluster_types": ["integer", "string", "category"],
        "reject_boolean": "false",
        "confidence_level": "0.95",
    }
    for field, invalid in invalid_values.items():
        with pytest.raises((TypeError, ValueError), match=field):
            OLSClusterPolicyV1(**(values | {field: invalid}))

    with pytest.raises(ValueError, match="allowed_model.*expected.*actual"):
        OLSClusterPolicyV1(**(values | {"allowed_model": "logit"}))


def test_ols_cluster_policy_from_dict_rejects_non_string_mapping_keys_clearly():
    value = ols_cluster_policy_v1.to_dict()
    value[1] = "invalid key"
    with pytest.raises((TypeError, ValueError), match="keys.*strings"):
        OLSClusterPolicyV1.from_dict(value)


def test_packet_conflict_error_documents_all_conflict_semantics():
    doc = PacketConflictError.__doc__ or ""
    assert "identity" in doc
    assert "pending" in doc
    assert "terminal" in doc
