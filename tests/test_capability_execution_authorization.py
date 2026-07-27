from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from workbench.capability_factory.execution_authorization import (
    ExecutionAuthorizationInvalidated,
    ExecutionAuthorizationReplay,
    ExecutionAuthorizationRejected,
    OptionExecutionAuthorization,
    OptionExecutionAuthorizationStore,
)


_REFS = {
    "binding": "a" * 64,
    "capability": "b" * 64,
    "bundle": "c" * 64,
    "evidence": "d" * 64,
    "admission": "e" * 64,
    "policy": "f" * 64,
    "freshness": "1" * 64,
    "artifact": "2" * 64,
    "projection": "3" * 64,
}


def _clock(value: datetime):
    return lambda: value


def _authorization(
    *,
    now: datetime,
    authorization_id: str = "auth_1",
    idempotency_key: str = "idem_1",
    draft_hash: str = "sha256:" + "4" * 64,
    expires_in: int = 300,
) -> OptionExecutionAuthorization:
    return OptionExecutionAuthorization(
        authorization_id=authorization_id,
        notebook_id="notebook_1",
        option_id="option_1",
        option_revision=2,
        binding_revision=3,
        capability_resolution_binding_ref=_REFS["binding"],
        materialization_id="materialization_1",
        draft_id="draft_1",
        draft_hash=draft_hash,
        run_intent_id="run_intent_1",
        capability_ref=_REFS["capability"],
        bundle_ref=_REFS["bundle"],
        evidence_ref=_REFS["evidence"],
        admission_ref=_REFS["admission"],
        runtime_policy_ref=_REFS["policy"],
        freshness_cursor_ref=_REFS["freshness"],
        input_graph_fingerprint="graph-fingerprint-1",
        freshness_dependency_fingerprint="freshness-fingerprint-1",
        operation_id="fit",
        execution_mode="confirm_and_execute",
        risk_level="low",
        artifact_contract_ref=_REFS["artifact"],
        consumer_projection_ref=_REFS["projection"],
        idempotency_key=idempotency_key,
        issued_at=now,
        expires_at=now + timedelta(seconds=expires_in),
    )


def test_authorization_is_immutable_and_binds_the_exact_payload() -> None:
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)
    original = _authorization(now=now)

    restored = OptionExecutionAuthorization.from_dict(original.to_dict())

    assert restored == original
    assert len(original.payload_digest) == 64
    assert original.execution_mode == "confirm_and_execute"
    with pytest.raises((AttributeError, TypeError)):
        original.option_revision = 4  # type: ignore[misc]

    changed = _authorization(now=now, draft_hash="sha256:" + "5" * 64)
    assert changed.payload_digest != original.payload_digest

    with pytest.raises(ValueError, match="contract_version"):
        OptionExecutionAuthorization.from_dict(
            {**original.to_dict(), "contract_version": "OptionExecutionAuthorization@9.0"}
        )


def test_materialize_only_cannot_issue_execution_authorization() -> None:
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="confirm_and_execute"):
        OptionExecutionAuthorization.from_dict(
            {
                **_authorization(now=now).to_dict(),
                "execution_mode": "materialize_only",
            }
        )


def test_issue_is_idempotent_and_rejects_same_key_with_changed_payload(tmp_path: Path) -> None:
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)
    store = OptionExecutionAuthorizationStore(tmp_path, clock=_clock(now))
    first = _authorization(now=now)

    issued = store.issue(first)
    retried = store.issue(first)

    assert retried == issued
    assert len(store.history(first.authorization_id)) == 1

    with pytest.raises(ExecutionAuthorizationReplay):
        store.issue(_authorization(now=now, draft_hash="sha256:" + "5" * 64))


def test_claim_is_atomic_idempotent_and_binds_freshness(tmp_path: Path) -> None:
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)
    first_store = OptionExecutionAuthorizationStore(tmp_path, clock=_clock(now))
    second_store = OptionExecutionAuthorizationStore(tmp_path, clock=_clock(now))
    authorization = _authorization(now=now)
    first_store.issue(authorization)

    claimed = first_store.claim(
        authorization.authorization_id,
        idempotency_key=authorization.idempotency_key,
        current_binding_ref=authorization.capability_resolution_binding_ref,
        current_freshness_cursor_ref=authorization.freshness_cursor_ref,
        owner_id="executor_a",
        lease_seconds=30,
    )
    repeated = second_store.claim(
        authorization.authorization_id,
        idempotency_key=authorization.idempotency_key,
        current_binding_ref=authorization.capability_resolution_binding_ref,
        current_freshness_cursor_ref=authorization.freshness_cursor_ref,
        owner_id="executor_b",
        lease_seconds=30,
    )

    assert claimed.status == "claimed"
    assert claimed.claim_owner_id == "executor_a"
    assert repeated == claimed
    assert len(second_store.history(authorization.authorization_id)) == 2

    with pytest.raises(ExecutionAuthorizationReplay):
        second_store.claim(
            authorization.authorization_id,
            idempotency_key="wrong-key",
            current_binding_ref=authorization.capability_resolution_binding_ref,
            current_freshness_cursor_ref=authorization.freshness_cursor_ref,
            owner_id="executor_c",
            lease_seconds=30,
        )

    with pytest.raises(ExecutionAuthorizationInvalidated, match="freshness"):
        second_store.claim(
            authorization.authorization_id,
            idempotency_key=authorization.idempotency_key,
            current_binding_ref=authorization.capability_resolution_binding_ref,
            current_freshness_cursor_ref="8" * 64,
            owner_id="executor_b",
            lease_seconds=30,
        )
    assert second_store.read(authorization.authorization_id).status == "invalidated"


@pytest.mark.parametrize(
    ("binding", "freshness", "expected"),
    [
        ("9" * 64, _REFS["freshness"], "binding"),
        (_REFS["binding"], "8" * 64, "freshness"),
    ],
)
def test_claim_rejects_stale_binding_without_claiming(
    tmp_path: Path, binding: str, freshness: str, expected: str
) -> None:
    now = datetime(2026, 7, 26, tzinfo=timezone.utc)
    store = OptionExecutionAuthorizationStore(tmp_path, clock=_clock(now))
    authorization = _authorization(now=now)
    store.issue(authorization)

    with pytest.raises(ExecutionAuthorizationRejected, match=expected):
        store.claim(
            authorization.authorization_id,
            idempotency_key=authorization.idempotency_key,
            current_binding_ref=binding,
            current_freshness_cursor_ref=freshness,
            owner_id="executor_a",
            lease_seconds=30,
        )

    current = store.read(authorization.authorization_id)
    assert current.status == "rejected"
    assert current.claim_owner_id is None
    assert len(store.history(authorization.authorization_id)) == 2


def test_expiry_is_rejected_and_never_creates_a_claim(tmp_path: Path) -> None:
    issued_at = datetime(2026, 7, 26, tzinfo=timezone.utc)
    now = issued_at + timedelta(seconds=301)
    current_time = [issued_at]
    store = OptionExecutionAuthorizationStore(tmp_path, clock=lambda: current_time[0])
    authorization = _authorization(now=issued_at)
    store.issue(authorization)
    current_time[0] = now

    with pytest.raises(ExecutionAuthorizationRejected, match="expired"):
        store.claim(
            authorization.authorization_id,
            idempotency_key=authorization.idempotency_key,
            current_binding_ref=authorization.capability_resolution_binding_ref,
            current_freshness_cursor_ref=authorization.freshness_cursor_ref,
            owner_id="executor_a",
            lease_seconds=30,
        )

    assert store.read(authorization.authorization_id).status == "rejected"
