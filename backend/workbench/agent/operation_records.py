"""Operation records: the durable record of a confirmed operation and its append-only store."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from .proposals import ProposalConfirmation
from ..jsonl_store import append_jsonl_atomic, read_jsonl
from .operation_definitions import OperationRecordTransitionError, _now


@dataclass(frozen=True)
class OperationRecord:
    record_id: str
    operation_id: str
    operation_version: str
    proposal_id: str
    proposal_revision: int
    proposal_fingerprint: str
    agent_session_id: str
    chain_id: str
    command_id: str | None
    target: dict[str, Any]
    preconditions: dict[str, Any]
    actor_type: str
    status: str
    confirmation: dict[str, Any]
    execution: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    diff_ref: dict[str, Any] | None = None
    verification: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    changes: dict[str, Any] = field(default_factory=dict)
    # The domain effect and its read-model projection have separate durable
    # states.  A crash after domain commit must be recoverable without
    # re-running the effect or mistaking an unfinished projection for a second
    # execution.
    effect_status: str = "pending"
    projection_status: str = "pending"
    created_at: str = ""
    updated_at: str = ""
    workflow_id: str | None = None
    workflow_confirmation_id: str | None = None
    workflow_step_id: str | None = None
    workflow_plan_fingerprint: str | None = None
    confirmation_mode: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": "state",
            "record_id": self.record_id,
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "proposal_id": self.proposal_id,
            "proposal_revision": self.proposal_revision,
            "proposal_fingerprint": self.proposal_fingerprint,
            "agent_session_id": self.agent_session_id,
            "chain_id": self.chain_id,
            "command_id": self.command_id,
            "target": self.target,
            "preconditions": self.preconditions,
            "actor_type": self.actor_type,
            "status": self.status,
            "confirmation": self.confirmation,
            "execution": self.execution,
            "outputs": self.outputs,
            "diff_ref": self.diff_ref,
            "verification": self.verification,
            "error": self.error,
            "changes": self.changes,
            "effect_status": self.effect_status,
            "projection_status": self.projection_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "workflow_id": self.workflow_id,
            "workflow_confirmation_id": self.workflow_confirmation_id,
            "workflow_step_id": self.workflow_step_id,
            "workflow_plan_fingerprint": self.workflow_plan_fingerprint,
            "confirmation_mode": self.confirmation_mode,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "OperationRecord":
        return cls(
            record_id=str(value["record_id"]),
            operation_id=str(value["operation_id"]),
            operation_version=str(value["operation_version"]),
            proposal_id=str(value["proposal_id"]),
            proposal_revision=int(value["proposal_revision"]),
            proposal_fingerprint=str(value["proposal_fingerprint"]),
            agent_session_id=str(value["agent_session_id"]),
            chain_id=str(value["chain_id"]),
            command_id=value.get("command_id"),
            target=dict(value.get("target") or {}),
            preconditions=dict(value.get("preconditions") or {}),
            actor_type=str(value["actor_type"]),
            status=str(value["status"]),
            confirmation=dict(value.get("confirmation") or {}),
            execution=dict(value.get("execution") or {}),
            outputs=dict(value.get("outputs") or {}),
            diff_ref=dict(value["diff_ref"]) if value.get("diff_ref") else None,
            verification=dict(value.get("verification") or {}),
            error=dict(value["error"]) if value.get("error") else None,
            changes=dict(value.get("changes") or {}),
            effect_status=str(value.get("effect_status") or "pending"),
            projection_status=str(value.get("projection_status") or "pending"),
            created_at=str(value["created_at"]),
            updated_at=str(value["updated_at"]),
            workflow_id=value.get("workflow_id"),
            workflow_confirmation_id=value.get("workflow_confirmation_id"),
            workflow_step_id=value.get("workflow_step_id"),
            workflow_plan_fingerprint=value.get("workflow_plan_fingerprint"),
            confirmation_mode=value.get("confirmation_mode"),
        )


class OperationRecordStore:
    """Persist lifecycle states without overwriting completed history."""

    def __init__(self, root: Path | str, *, create: bool = True) -> None:
        self.root = Path(root)
        self.records_dir = self.root / "operation-records"
        if create:
            self.records_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def create_pending(
        self,
        confirmation: ProposalConfirmation,
        *,
        command_id: str | None = None,
        workflow_authorization: dict[str, str] | None = None,
    ) -> OperationRecord:
        with self._lock:
            record_id = self._record_id(confirmation, command_id=command_id)
            path = self._path(record_id)
            if path.exists():
                return self.get(record_id)
            now = _now()
            record = OperationRecord(
                record_id=record_id,
                operation_id=confirmation.operation_id,
                operation_version=confirmation.operation_version,
                proposal_id=confirmation.proposal_id,
                proposal_revision=confirmation.revision,
                proposal_fingerprint=confirmation.fingerprint,
                agent_session_id=confirmation.session_id,
                chain_id=confirmation.chain_id,
                command_id=command_id or confirmation.command_id,
                target=confirmation.target,
                preconditions=confirmation.preconditions,
                actor_type=confirmation.actor_type,
                status="pending",
                confirmation=confirmation.to_dict(),
                changes=dict(getattr(confirmation, "changes", {}) or {}),
                workflow_id=(workflow_authorization or {}).get("workflow_id"),
                workflow_confirmation_id=(workflow_authorization or {}).get(
                    "workflow_confirmation_id"
                ),
                workflow_step_id=(workflow_authorization or {}).get("workflow_step_id"),
                workflow_plan_fingerprint=(workflow_authorization or {}).get(
                    "workflow_plan_fingerprint"
                ),
                confirmation_mode=(workflow_authorization or {}).get("confirmation_mode"),
                created_at=now,
                updated_at=now,
            )
            append_jsonl_atomic(path, record.to_dict())
            return record

    def bind_risk_authorization(
        self,
        record_id: str,
        authorization_id: str,
    ) -> OperationRecord:
        """Durably bind a high-risk grant before its token is consumed."""

        if not authorization_id:
            raise ValueError("authorization_id is required")
        with self._lock:
            current = self.get(record_id)
            existing = current.execution.get("risk_authorization_id")
            if existing is not None and existing != authorization_id:
                # A grant may expire or be rejected after this pending record
                # was created. Reauthorization is safe until execution is
                # claimed; after a claim, changing the authorization binding
                # would make recovery ambiguous and must fail closed.
                if current.execution.get("execution_key") is not None:
                    raise OperationRecordTransitionError(
                        f"operation already has another risk authorization: {record_id}"
                    )
            if existing == authorization_id:
                return current
            return self.append_status(
                record_id,
                current.status,
                execution={
                    **current.execution,
                    "risk_authorization_id": authorization_id,
                },
            )

    def claim_execution(
        self,
        record_id: str,
        *,
        execution_key: str,
        lease_owner: str,
        lease_seconds: int = 300,
    ) -> OperationRecord:
        """Claim one operation execution idempotently under the store lock."""

        from .execution import OperationClaimConflict

        if not execution_key or not lease_owner:
            raise ValueError("execution_key and lease_owner are required")
        with self._lock:
            current = self.get(record_id)
            if current.status in {"completed", "failed", "stale", "cancelled"}:
                raise OperationClaimConflict(
                    f"terminal operation cannot be claimed: {record_id}"
                )
            existing_key = current.execution.get("execution_key")
            if existing_key is not None:
                if existing_key == execution_key:
                    existing_owner = current.execution.get("claim_owner")
                    if (
                        existing_owner
                        and existing_owner != lease_owner
                        and current.status != "recovering"
                    ):
                        raise OperationClaimConflict(
                            f"operation is already owned by {existing_owner}"
                        )
                    if existing_owner != lease_owner:
                        now = datetime.now(timezone.utc)
                        execution = {
                            **current.execution,
                            "claim_owner": lease_owner,
                            "claimed_at": now.isoformat(),
                            "lease_expires_at": (
                                now + timedelta(seconds=lease_seconds)
                            ).isoformat(),
                        }
                        return self.append_status(
                            record_id,
                            current.status,
                            execution=execution,
                        )
                    return current
                raise OperationClaimConflict(
                    f"operation already claimed by execution key: {existing_key}"
                )
            now = datetime.now(timezone.utc)
            execution = {
                **current.execution,
                "execution_key": execution_key,
                "claim_owner": lease_owner,
                "claimed_at": now.isoformat(),
                "lease_expires_at": (
                    now + timedelta(seconds=lease_seconds)
                ).isoformat(),
                "bindings": {},
            }
            return self.append_status(
                record_id,
                "submitted",
                execution=execution,
            )

    def bind_effect(
        self,
        record_id: str,
        *,
        execution_key: str,
        bindings: dict[str, str],
    ) -> OperationRecord:
        """Persist effect ids only after verifying the claimed execution key."""

        from .execution import OperationClaimConflict

        with self._lock:
            current = self.get(record_id)
            if current.execution.get("execution_key") != execution_key:
                raise OperationClaimConflict(
                    f"effect binding does not match execution key: {record_id}"
                )
            existing = dict(current.execution.get("bindings") or {})
            for key, value in bindings.items():
                if key in existing and existing[key] != value:
                    raise OperationClaimConflict(
                        f"effect binding already exists for {key}: {record_id}"
                    )
            existing.update({str(key): str(value) for key, value in bindings.items()})
            execution = {**current.execution, "bindings": existing}
            return self.append_status(
                record_id,
                current.status,
                execution=execution,
            )

    def append_status(
        self,
        record_id: str,
        status: str,
        *,
        execution: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
        diff_ref: dict[str, Any] | None = None,
        verification: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        effect_status: str | None = None,
        projection_status: str | None = None,
    ) -> OperationRecord:
        with self._lock:
            current = self.get(record_id)
            has_payload = any(
                value is not None
                for value in (
                    execution,
                    outputs,
                    diff_ref,
                    verification,
                    error,
                    effect_status,
                    projection_status,
                )
            )
            if status == current.status and not has_payload:
                return current
            allowed = {
                "pending": {"submitted", "running", "completed", "failed", "stale", "cancelled", "recovering"},
                "submitted": {"running", "completed", "failed", "stale", "cancelled", "recovering"},
                "running": {"completed", "failed", "stale", "cancelled", "recovering"},
                "recovering": {"submitted", "running", "completed", "failed", "stale", "cancelled"},
                "completed": set(),
                "failed": set(),
                "stale": set(),
                "cancelled": set(),
            }
            if status != current.status and status not in allowed.get(current.status, set()):
                raise OperationRecordTransitionError(
                    f"invalid operation record transition: {current.status} -> {status}"
                )
            updated = OperationRecord(
                **{
                    **current.__dict__,
                    "status": status,
                    "execution": execution if execution is not None else current.execution,
                    "outputs": outputs if outputs is not None else current.outputs,
                    "diff_ref": diff_ref if diff_ref is not None else current.diff_ref,
                    "verification": verification if verification is not None else current.verification,
                    "error": error if error is not None else current.error,
                    "effect_status": (
                        effect_status
                        if effect_status is not None
                        else current.effect_status
                    ),
                    "projection_status": (
                        projection_status
                        if projection_status is not None
                        else current.projection_status
                    ),
                    "updated_at": _now(),
                }
            )
            if updated == current:
                return current
            append_jsonl_atomic(self._path(record_id), updated.to_dict())
            return updated

    def get(self, record_id: str) -> OperationRecord:
        records = [
            OperationRecord.from_dict(item)
            for item in read_jsonl(self._path(record_id))
            if item.get("record_type") == "state"
        ]
        if not records:
            raise KeyError(f"unknown operation record: {record_id}")
        return records[-1]

    def list_records(self) -> list[OperationRecord]:
        with self._lock:
            return [self.get(path.stem) for path in sorted(self.records_dir.glob("oprec_*.jsonl"))]

    def _path(self, record_id: str) -> Path:
        if not record_id or Path(record_id).name != record_id:
            raise ValueError("record_id must be path-safe")
        return self.records_dir / f"{record_id}.jsonl"

    @staticmethod
    def _record_id(confirmation: ProposalConfirmation, *, command_id: str | None) -> str:
        identity = {
            "operation_id": confirmation.operation_id,
            "proposal_id": confirmation.proposal_id,
            "proposal_revision": confirmation.revision,
            "proposal_fingerprint": confirmation.fingerprint,
            "active_head_run_id": confirmation.preconditions.get("active_head_run_id"),
        }
        encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return f"oprec_{hashlib.sha256(encoded).hexdigest()[:24]}"
