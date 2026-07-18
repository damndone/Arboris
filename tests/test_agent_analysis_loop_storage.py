from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from workbench.analysis_loop.storage import (
    TerminalPacketConflictError,
    ValidationPacketStore,
)
from workbench.analysis_loop.validation import ValidationCheck, ValidationPacket


def _packet(*, status: str = "complete", logical_key: str = "validation:one") -> ValidationPacket:
    return ValidationPacket(
        status=status,
        overall_status="passed" if status == "complete" else "unknown",
        terminal=status != "pending",
        checks=(
            ValidationCheck(
                check_id="execution.integrity",
                status="pass",
                severity="info",
                expected=True,
                observed=True,
            ),
        ),
        logical_key=logical_key,
        child_run_id="run-child",
        source_run_id="run-source",
        plan_hash="plan-hash",
        executed_payload_hash="payload-hash",
        artifact_manifest_hash="artifact-hash",
        validation_policy_version="validation_policy_v1",
        schema_version="validation_packet_v1",
    )


def test_validation_store_reuses_terminal_and_rejects_overwrite(tmp_path: Path) -> None:
    store = ValidationPacketStore(tmp_path)
    first = store.persist_terminal_packet(_packet())

    assert store.persist_terminal_packet(_packet()) == first
    assert store.get_terminal_packet(first.logical_key) == first
    assert len(store.list_terminal_packets()) == 1

    with pytest.raises(TerminalPacketConflictError):
        store.persist_terminal_packet(replace(_packet(), plan_hash="other-plan-hash"))


def test_validation_store_does_not_terminalize_pending_packets(tmp_path: Path) -> None:
    store = ValidationPacketStore(tmp_path)
    pending = store.build_packet(
        logical_key="validation:pending",
        builder=lambda: _packet(status="pending", logical_key="validation:pending"),
    )

    assert pending.status == "pending"
    assert store.get_terminal_packet("validation:pending") is None
    assert store.list_build_attempts(logical_key="validation:pending")[0]["status"] == "pending"


def test_validation_store_records_transient_build_failures_without_terminal(tmp_path: Path) -> None:
    store = ValidationPacketStore(tmp_path)

    def fail() -> ValidationPacket:
        raise ValueError("artifact not ready")

    with pytest.raises(ValueError):
        store.build_packet(logical_key="validation:failed", builder=fail)

    assert store.get_terminal_packet("validation:failed") is None
    attempts = store.list_build_attempts(logical_key="validation:failed")
    assert attempts[0]["status"] == "failed"
    assert attempts[0]["error"]["message"] == "artifact not ready"
