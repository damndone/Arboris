import math

import pytest

from workbench.analysis_loop.canonical import (
    CanonicalJSONError,
    canonical_json_v1,
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


def test_canonical_json_v1_normalizes_keys_unicode_and_negative_zero():
    decomposed = "e\u0301"
    composed = "é"
    first = {"z": -0.0, decomposed: "cafe\u0301"}
    second = {composed: "café", "z": 0}

    assert canonical_json_v1(first) == canonical_json_v1(second)
    assert canonical_json_v1(first) == '{"z":0,"é":"café"}'
    assert sha256_canonical(first) == sha256_canonical(second)
    assert sha256_canonical({"field": None}) != sha256_canonical({})


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


def test_numbers_equal_uses_absolute_relative_tolerance_and_special_values():
    assert numbers_equal(10.0, 10.000001, atol=1e-6)
    assert not numbers_equal(10.0, 10.000002, atol=1e-6)
    assert numbers_equal(1_000_000.0, 1_000_001.0, rtol=1e-6)
    assert numbers_equal(-0.0, 0.0)
    assert not numbers_equal(math.nan, math.nan)
    assert numbers_equal(math.inf, math.inf)
    assert not numbers_equal(math.inf, -math.inf)


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


def test_packet_idempotence_does_not_overwrite_terminal_packet():
    existing = _envelope("complete")
    same = PacketEnvelope.from_dict(existing.to_dict())
    changed = PacketEnvelope.from_dict(existing.to_dict() | {"payload": {"value": 2}})

    assert ensure_packet_idempotent(existing, same) is existing
    with pytest.raises(PacketConflictError):
        ensure_packet_idempotent(existing, changed)


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
