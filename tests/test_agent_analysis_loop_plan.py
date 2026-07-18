from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from workbench.analysis_loop.contracts import SourceRunContract
from workbench.analysis_loop.plan import (
    PlanDiff,
    PlanBindingError,
    PlanValidationError,
    build_plan_diff,
    confirmed_payload_hash_for_plan,
    validate_confirmation_binding,
)
from workbench.analysis_loop.storage import PlanDiffStore, TerminalPacketConflictError


ACTION_ID = "ols.use_clustered_covariance_v1"


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
            "payload_hash": "payload-source",
        },
        "lineage": {"node_ref": "model:ols", "source_run_id": "run-source"},
        "contract_version": "ols_result_contract_v1",
        "result_ids": ("coef:treatment", "coef:control"),
        "primary_estimand": {
            "result_id": "coef:treatment",
            "role": "primary",
            "label": "Treatment",
        },
        "result_labels": {
            "coef:treatment": "Treatment",
            "coef:control": "Control",
        },
        "dataset_schema": {
            "firm_id": {"dtype": "string"},
            "x": {"dtype": "float64"},
        },
        "analysis_row_ids": ("r1", "r2", "r3", "r4"),
    }
    values.update(overrides)
    return SourceRunContract(**values)


def _intent(**patch_overrides: object) -> dict[str, object]:
    patch: dict[str, object] = {
        "covariance": "clustered",
        "cluster_variable": "firm_id",
    }
    patch.update(patch_overrides)
    return {"action_id": ACTION_ID, "patch": patch}


def _build_plan(
    *,
    source: SourceRunContract | None = None,
    intent: dict[str, object] | None = None,
    requested_result_id: str | None = "coef:treatment",
    source_context_fingerprint: str = "ctx:source-v1",
) -> PlanDiff:
    return build_plan_diff(
        source=source or _source(),
        intent=intent or _intent(),
        requested_result_id=requested_result_id,
        cluster_values=["a", "a", "b", "b"],
        model_row_ids=["r1", "r2", "r3", "r4"],
        source_context_fingerprint=source_context_fingerprint,
        source_identity={
            "run_id": "run-source",
            "node_ref": "model:ols",
            "node_hash": "node-hash-source",
        },
    )


def test_build_plan_diff_canonicalizes_product_and_wire_patches() -> None:
    plan = _build_plan()

    assert plan.action_id == ACTION_ID
    assert plan.operation_id == "model.rerun"
    assert plan.source_identity == {
        "run_id": "run-source",
        "node_ref": "model:ols",
        "node_hash": "node-hash-source",
    }
    assert plan.target_identity["result_id"] == "coef:treatment"
    assert plan.source_context_fingerprint == "ctx:source-v1"
    assert plan.product_patch == {
        "covariance": "clustered",
        "cluster_variable": "firm_id",
    }
    assert plan.canonical_patch == plan.product_patch
    assert plan.wire_patch == {
        "covariance": "clustered",
        "entity_col": "firm_id",
    }
    assert plan.canonical_patch_hash
    assert plan.plan_hash
    assert plan.logical_key
    assert plan.strategy_version
    assert plan.policy_version == "ols_cluster_policy_v1"
    assert plan.schema_version


def test_plan_diff_records_covariance_only_invariants() -> None:
    plan = _build_plan()

    expected_true = {
        "dataset_unchanged",
        "sample_unchanged",
        "analysis_sample_unchanged",
        "point_estimation_unchanged",
        "coefficient_schema_unchanged",
        "formula_unchanged",
        "rows_unchanged",
        "y_unchanged",
        "X_unchanged",
        "point_estimates_unchanged",
        "only_inference_config_changes",
        "covariance_only",
    }
    assert expected_true <= set(plan.invariants)
    assert all(plan.invariants[key] is True for key in expected_true)
    assert plan.invariants["wire_field"] == "entity_col"


@pytest.mark.parametrize(
    ("intent", "code"),
    [
        ({"action_id": ACTION_ID, "patch": {"covariance": "clustered", "cluster_variable": "firm_id"}, "extra": True}, "INTENT_EXTRA_FIELDS"),
        ({"action_id": ACTION_ID, "patch": {"covariance": "clustered", "cluster_variable": "firm_id", "extra": "x"}}, "INTENT_PATCH_NOT_COVARIANCE_ONLY"),
        ({"action_id": ACTION_ID, "patch": {"covariance": "clustered", "entity_col": "firm_id"}}, "ENTITY_COL_GUESS_FORBIDDEN"),
        ({"action_id": ACTION_ID, "patch": {"covariance": "unadjusted", "cluster_variable": "firm_id"}}, "COVARIANCE_DIRECTION_UNSUPPORTED"),
    ],
)
def test_build_plan_diff_rejects_untrusted_or_unsupported_intent(
    intent: dict[str, object], code: str
) -> None:
    with pytest.raises(PlanValidationError) as exc_info:
        _build_plan(intent=intent)

    assert exc_info.value.code == code


def test_build_plan_diff_rejects_ambiguous_target_without_side_effects() -> None:
    source = _source(primary_estimand=None)

    with pytest.raises(PlanValidationError) as exc_info:
        _build_plan(source=source, requested_result_id=None)

    assert exc_info.value.code == "COMPARISON_TARGET_REQUIRED"


def test_build_plan_diff_does_not_guess_entity_col_from_untrusted_input() -> None:
    with pytest.raises(PlanValidationError) as exc_info:
        _build_plan(intent={"action_id": ACTION_ID, "patch": {"covariance": "clustered", "entity_col": "firm_id"}})

    assert exc_info.value.code == "ENTITY_COL_GUESS_FORBIDDEN"


def test_plan_diff_serialization_round_trip_is_immutable() -> None:
    plan = _build_plan()

    restored = PlanDiff.from_dict(plan.to_dict())

    assert restored == plan
    with pytest.raises(TypeError):
        restored.invariants["formula_unchanged"] = False  # type: ignore[index]


def test_plan_diff_store_returns_the_same_terminal_packet_for_a_logical_key(
    tmp_path: Path,
) -> None:
    store = PlanDiffStore(tmp_path)
    plan = _build_plan()

    first = store.persist_terminal_plan(plan)
    second = store.persist_terminal_plan(plan)

    assert first == second
    assert first.plan_diff == plan
    assert store.get_terminal_packet(plan.logical_key) == first
    assert len(store.list_terminal_packets()) == 1


def test_plan_diff_store_keeps_build_failures_as_attempts_only(tmp_path: Path) -> None:
    store = PlanDiffStore(tmp_path)

    def fail() -> PlanDiff:
        raise PlanValidationError("bad intent", code="INTENT_PATCH_NOT_COVARIANCE_ONLY")

    with pytest.raises(PlanValidationError):
        store.build_plan(logical_key="failed-logical-key", builder=fail)

    assert store.get_terminal_packet("failed-logical-key") is None
    attempts = store.list_build_attempts(logical_key="failed-logical-key")
    assert len(attempts) == 1
    assert attempts[0]["status"] == "failed"
    assert attempts[0]["error"]["code"] == "INTENT_PATCH_NOT_COVARIANCE_ONLY"


def test_plan_diff_store_never_overwrites_a_terminal_packet(tmp_path: Path) -> None:
    store = PlanDiffStore(tmp_path)
    plan = _build_plan()
    store.persist_terminal_plan(plan)

    conflicting = replace(
        plan,
        wire_patch={"covariance": "clustered", "entity_col": "other_firm_id"},
    )
    with pytest.raises(TerminalPacketConflictError):
        store.persist_terminal_plan(conflicting)


def _proposal_binding_payload(plan: PlanDiff) -> dict[str, object]:
    return {
        "proposal_id": "proposal-analysis-1",
        "revision": 1,
        "operation_version": "v1",
        "target": {
            "run_id": "run-source",
            "node_ref": "model:ols",
            "node_hash": "node-hash-source",
            "forest_node_key": "node-hash-source",
            "target_hash": plan.target_identity["target_hash"],
        },
        "preconditions": {
            "context_version": "node-operation-context/v1",
            "context_fingerprint": plan.source_context_fingerprint,
            "active_head_run_id": "run-source",
            "owner_resolution": "active_head_contains_node",
            "plan_logical_key": plan.logical_key,
            "plan_hash": plan.plan_hash,
            "canonical_patch_hash": plan.canonical_patch_hash,
            "target_hash": plan.target_identity["target_hash"],
            "source_context_fingerprint": plan.source_context_fingerprint,
        },
        "changes": plan.wire_patch,
    }


def test_confirmed_payload_hash_is_derived_from_plan_and_exact_proposal_payload() -> None:
    plan = _build_plan()
    payload = _proposal_binding_payload(plan)

    first = confirmed_payload_hash_for_plan(plan, **payload)
    second = confirmed_payload_hash_for_plan(
        plan,
        **{**payload, "preconditions": {**payload["preconditions"], "confirmed_payload_hash": "ignored"}},
    )

    assert first == second
    assert len(first) == 64


def test_confirmation_binding_rejects_stale_plan_before_other_checks() -> None:
    plan = _build_plan()
    payload = _proposal_binding_payload(plan)
    confirmed_hash = confirmed_payload_hash_for_plan(plan, **payload)

    with pytest.raises(PlanBindingError) as exc_info:
        validate_confirmation_binding(
            plan,
            bound_plan_hash="stale-plan-hash",
            bound_canonical_patch_hash=plan.canonical_patch_hash,
            bound_target_hash=plan.target_identity["target_hash"],
            bound_source_context_fingerprint=plan.source_context_fingerprint,
            current_source_context_fingerprint=plan.source_context_fingerprint,
            confirmed_payload_hash=confirmed_hash,
            **payload,
        )

    assert exc_info.value.code == "STALE_PLAN"


def test_confirmation_binding_rejects_source_context_fingerprint_mismatch() -> None:
    plan = _build_plan()
    payload = _proposal_binding_payload(plan)
    confirmed_hash = confirmed_payload_hash_for_plan(plan, **payload)

    with pytest.raises(PlanBindingError) as exc_info:
        validate_confirmation_binding(
            plan,
            bound_plan_hash=plan.plan_hash,
            bound_canonical_patch_hash=plan.canonical_patch_hash,
            bound_target_hash=plan.target_identity["target_hash"],
            bound_source_context_fingerprint=plan.source_context_fingerprint,
            current_source_context_fingerprint="ctx:changed",
            confirmed_payload_hash=confirmed_hash,
            **payload,
        )

    assert exc_info.value.code == "CONTEXT_FINGERPRINT_MISMATCH"


def test_confirmation_binding_rejects_confirmed_payload_hash_mismatch() -> None:
    plan = _build_plan()
    payload = _proposal_binding_payload(plan)

    with pytest.raises(PlanBindingError) as exc_info:
        validate_confirmation_binding(
            plan,
            bound_plan_hash=plan.plan_hash,
            bound_canonical_patch_hash=plan.canonical_patch_hash,
            bound_target_hash=plan.target_identity["target_hash"],
            bound_source_context_fingerprint=plan.source_context_fingerprint,
            current_source_context_fingerprint=plan.source_context_fingerprint,
            confirmed_payload_hash="wrong-confirmed-payload-hash",
            **payload,
        )

    assert exc_info.value.code == "CONFIRMED_PAYLOAD_MISMATCH"


def test_confirmation_binding_accepts_exact_plan_context_and_payload() -> None:
    plan = _build_plan()
    payload = _proposal_binding_payload(plan)
    confirmed_hash = confirmed_payload_hash_for_plan(plan, **payload)

    assert (
        validate_confirmation_binding(
            plan,
            bound_plan_hash=plan.plan_hash,
            bound_canonical_patch_hash=plan.canonical_patch_hash,
            bound_target_hash=plan.target_identity["target_hash"],
            bound_source_context_fingerprint=plan.source_context_fingerprint,
            current_source_context_fingerprint=plan.source_context_fingerprint,
            confirmed_payload_hash=confirmed_hash,
            **payload,
        )
        is None
    )
