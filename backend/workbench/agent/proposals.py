"""Immutable proposal revisions and confirmation gates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterable
from uuid import uuid4

from .storage import append_jsonl_atomic, read_jsonl


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProposalError(RuntimeError):
    """Base class for proposal lifecycle failures."""


class ProposalConfirmationError(ProposalError):
    """The requested proposal revision cannot be confirmed."""


class ProposalStaleError(ProposalError):
    """The proposal preconditions changed before confirmation."""


@dataclass(frozen=True)
class ProposalRevision:
    proposal_id: str
    operation_id: str
    operation_version: str
    revision: int
    session_id: str
    chain_id: str
    command_id: str | None
    target: dict[str, Any]
    preconditions: dict[str, Any]
    changes: dict[str, Any]
    evidence_refs: tuple[str, ...]
    expected_effect: tuple[str, ...]
    risks: tuple[str, ...]
    created_at: str
    fingerprint: str
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": "revision",
            "proposal_id": self.proposal_id,
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "revision": self.revision,
            "session_id": self.session_id,
            "chain_id": self.chain_id,
            "command_id": self.command_id,
            "target": self.target,
            "preconditions": self.preconditions,
            "changes": self.changes,
            "evidence_refs": list(self.evidence_refs),
            "expected_effect": list(self.expected_effect),
            "risks": list(self.risks),
            "created_at": self.created_at,
            "fingerprint": self.fingerprint,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProposalRevision":
        return cls(
            proposal_id=str(value["proposal_id"]),
            operation_id=str(value["operation_id"]),
            operation_version=str(value["operation_version"]),
            revision=int(value["revision"]),
            session_id=str(value["session_id"]),
            chain_id=str(value["chain_id"]),
            command_id=value.get("command_id"),
            target=dict(value.get("target") or {}),
            preconditions=dict(value.get("preconditions") or {}),
            changes=dict(value.get("changes") or {}),
            evidence_refs=tuple(str(item) for item in value.get("evidence_refs", [])),
            expected_effect=tuple(str(item) for item in value.get("expected_effect", [])),
            risks=tuple(str(item) for item in value.get("risks", [])),
            created_at=str(value["created_at"]),
            fingerprint=str(value["fingerprint"]),
            status=str(value.get("status", "pending")),
        )


@dataclass(frozen=True)
class ProposalConfirmation:
    proposal_id: str
    operation_id: str
    operation_version: str
    revision: int
    fingerprint: str
    session_id: str
    chain_id: str
    command_id: str | None
    target: dict[str, Any]
    preconditions: dict[str, Any]
    actor_type: str
    confirmed_at: str
    status: str
    changes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": "confirmation",
            "proposal_id": self.proposal_id,
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "revision": self.revision,
            "fingerprint": self.fingerprint,
            "session_id": self.session_id,
            "chain_id": self.chain_id,
            "command_id": self.command_id,
            "target": self.target,
            "preconditions": self.preconditions,
            "actor_type": self.actor_type,
            "confirmed_at": self.confirmed_at,
            "status": self.status,
            "changes": self.changes,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProposalConfirmation":
        return cls(
            proposal_id=str(value["proposal_id"]),
            operation_id=str(value["operation_id"]),
            operation_version=str(value["operation_version"]),
            revision=int(value["revision"]),
            fingerprint=str(value["fingerprint"]),
            session_id=str(value["session_id"]),
            chain_id=str(value["chain_id"]),
            command_id=value.get("command_id"),
            target=dict(value.get("target") or {}),
            preconditions=dict(value.get("preconditions") or {}),
            actor_type=str(value["actor_type"]),
            confirmed_at=str(value["confirmed_at"]),
            status=str(value["status"]),
            changes=dict(value.get("changes") or {}),
        )


@dataclass(frozen=True)
class ProposalDecision:
    """An append-only user disposition for a proposal before execution."""

    proposal_id: str
    operation_id: str
    operation_version: str
    revision: int
    fingerprint: str
    session_id: str
    chain_id: str
    command_id: str | None
    target: dict[str, Any]
    preconditions: dict[str, Any]
    actor_type: str
    decided_at: str
    status: str
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": "decision",
            "proposal_id": self.proposal_id,
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "revision": self.revision,
            "fingerprint": self.fingerprint,
            "session_id": self.session_id,
            "chain_id": self.chain_id,
            "command_id": self.command_id,
            "target": self.target,
            "preconditions": self.preconditions,
            "actor_type": self.actor_type,
            "decided_at": self.decided_at,
            "status": self.status,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ProposalDecision":
        return cls(
            proposal_id=str(value["proposal_id"]),
            operation_id=str(value["operation_id"]),
            operation_version=str(value["operation_version"]),
            revision=int(value["revision"]),
            fingerprint=str(value["fingerprint"]),
            session_id=str(value["session_id"]),
            chain_id=str(value["chain_id"]),
            command_id=value.get("command_id"),
            target=dict(value.get("target") or {}),
            preconditions=dict(value.get("preconditions") or {}),
            actor_type=str(value["actor_type"]),
            decided_at=str(value["decided_at"]),
            status=str(value["status"]),
            reason=value.get("reason"),
        )


class ProposalStore:
    """Project-local append-only proposal and confirmation store."""

    def __init__(self, root: Path | str, *, create: bool = True) -> None:
        self.root = Path(root)
        self.proposals_dir = self.root / "proposals"
        if create:
            self.proposals_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def create(
        self,
        *,
        session_id: str,
        chain_id: str,
        operation_id: str,
        target: dict[str, Any],
        preconditions: dict[str, Any],
        changes: dict[str, Any],
        evidence_refs: Iterable[str],
        expected_effect: Iterable[str],
        risks: Iterable[str],
        operation_version: str = "v1",
        command_id: str | None = None,
        proposal_id: str | None = None,
    ) -> ProposalRevision:
        proposal_id = proposal_id or f"proposal_{uuid4().hex}"
        with self._lock:
            path = self._path(proposal_id)
            if path.exists():
                raise ProposalConfirmationError(f"proposal already exists: {proposal_id}")
            proposal = self._build_revision(
                proposal_id=proposal_id,
                operation_id=operation_id,
                operation_version=operation_version,
                revision=1,
                session_id=session_id,
                chain_id=chain_id,
                command_id=command_id,
                target=target,
                preconditions=preconditions,
                changes=changes,
                evidence_refs=evidence_refs,
                expected_effect=expected_effect,
                risks=risks,
            )
            append_jsonl_atomic(path, proposal.to_dict())
            return proposal

    def revise(
        self,
        proposal_id: str,
        *,
        base_revision: int,
        changes: dict[str, Any],
        expected_effect: Iterable[str] | None = None,
        risks: Iterable[str] | None = None,
    ) -> ProposalRevision:
        with self._lock:
            latest = self.latest_revision(proposal_id)
            if latest.revision != base_revision:
                raise ProposalConfirmationError("proposal revision is not current")
            if self.latest_status(proposal_id) != "pending":
                raise ProposalConfirmationError("proposal is no longer editable")
            revised = self._build_revision(
                proposal_id=latest.proposal_id,
                operation_id=latest.operation_id,
                operation_version=latest.operation_version,
                revision=latest.revision + 1,
                session_id=latest.session_id,
                chain_id=latest.chain_id,
                command_id=latest.command_id,
                target=latest.target,
                preconditions=latest.preconditions,
                changes=changes,
                evidence_refs=latest.evidence_refs,
                expected_effect=expected_effect or latest.expected_effect,
                risks=risks or latest.risks,
            )
            append_jsonl_atomic(self._path(proposal_id), revised.to_dict())
            return revised

    def confirm(
        self,
        proposal_id: str,
        *,
        revision: int,
        fingerprint: str,
        actor_type: str,
        current_context_fingerprint: str | None,
        current_active_head_run_id: str | None,
    ) -> ProposalConfirmation:
        with self._lock:
            latest = self.latest_revision(proposal_id)
            status = self.latest_status(proposal_id)
            if revision != latest.revision:
                raise ProposalConfirmationError("proposal revision is not current")
            if fingerprint != latest.fingerprint:
                raise ProposalConfirmationError("proposal fingerprint mismatch")
            if status == "confirmed":
                existing = self.latest_confirmation(proposal_id)
                if existing is not None:
                    return existing
            if status != "pending":
                raise ProposalConfirmationError(f"proposal is {status}")

            expected_context = latest.preconditions.get("context_fingerprint")
            expected_head = latest.preconditions.get("active_head_run_id")
            if (
                expected_context is not None
                and current_context_fingerprint != expected_context
            ) or (
                expected_head is not None
                and current_active_head_run_id != expected_head
            ):
                stale = ProposalConfirmation(
                    proposal_id=latest.proposal_id,
                    operation_id=latest.operation_id,
                    operation_version=latest.operation_version,
                    revision=latest.revision,
                    fingerprint=latest.fingerprint,
                    session_id=latest.session_id,
                    chain_id=latest.chain_id,
                    command_id=latest.command_id,
                    target=latest.target,
                    preconditions=latest.preconditions,
                    actor_type=actor_type,
                    confirmed_at=_now(),
                    status="stale",
                    changes=latest.changes,
                )
                append_jsonl_atomic(self._path(proposal_id), stale.to_dict())
                raise ProposalStaleError("proposal preconditions changed")

            confirmation = ProposalConfirmation(
                proposal_id=latest.proposal_id,
                operation_id=latest.operation_id,
                operation_version=latest.operation_version,
                revision=latest.revision,
                fingerprint=latest.fingerprint,
                session_id=latest.session_id,
                chain_id=latest.chain_id,
                command_id=latest.command_id,
                target=latest.target,
                preconditions=latest.preconditions,
                actor_type=actor_type,
                confirmed_at=_now(),
                status="confirmed",
                changes=latest.changes,
            )
            append_jsonl_atomic(self._path(proposal_id), confirmation.to_dict())
            return confirmation

    def decline(
        self,
        proposal_id: str,
        *,
        actor_type: str,
        reason: str | None = None,
    ) -> ProposalDecision:
        with self._lock:
            latest = self.latest_revision(proposal_id)
            status = self.latest_status(proposal_id)
            if status == "declined":
                existing = self.latest_decision(proposal_id)
                if existing is not None:
                    return existing
            if status != "pending":
                raise ProposalConfirmationError(f"proposal is {status}")
            decision = ProposalDecision(
                proposal_id=latest.proposal_id,
                operation_id=latest.operation_id,
                operation_version=latest.operation_version,
                revision=latest.revision,
                fingerprint=latest.fingerprint,
                session_id=latest.session_id,
                chain_id=latest.chain_id,
                command_id=latest.command_id,
                target=latest.target,
                preconditions=latest.preconditions,
                actor_type=actor_type,
                decided_at=_now(),
                status="declined",
                reason=reason,
            )
            append_jsonl_atomic(self._path(proposal_id), decision.to_dict())
            return decision

    def latest_revision(self, proposal_id: str) -> ProposalRevision:
        revisions = self.revisions(proposal_id)
        if not revisions:
            raise KeyError(f"unknown proposal: {proposal_id}")
        return revisions[-1]

    def latest_revisions_for_session(self, session_id: str) -> list[ProposalRevision]:
        """Return the latest immutable revision for proposals owned by a session."""

        if not session_id or Path(session_id).name != session_id:
            raise ValueError("session_id must be a non-empty path-safe identifier")
        with self._lock:
            revisions: list[ProposalRevision] = []
            for path in sorted(self.proposals_dir.glob("*.jsonl")):
                proposal_id = path.stem
                try:
                    revision = self.latest_revision(proposal_id)
                except (KeyError, ValueError):
                    continue
                if revision.session_id == session_id:
                    revisions.append(revision)
        return sorted(revisions, key=lambda item: (item.created_at, item.proposal_id))

    def revisions(self, proposal_id: str) -> list[ProposalRevision]:
        return [
            ProposalRevision.from_dict(item)
            for item in read_jsonl(self._path(proposal_id))
            if item.get("record_type") == "revision"
        ]

    def latest_confirmation(self, proposal_id: str) -> ProposalConfirmation | None:
        confirmations = [
            ProposalConfirmation.from_dict(item)
            for item in read_jsonl(self._path(proposal_id))
            if item.get("record_type") == "confirmation"
        ]
        return confirmations[-1] if confirmations else None

    def latest_decision(self, proposal_id: str) -> ProposalDecision | None:
        decisions = [
            ProposalDecision.from_dict(item)
            for item in read_jsonl(self._path(proposal_id))
            if item.get("record_type") == "decision"
        ]
        return decisions[-1] if decisions else None

    def validate_confirmation_preconditions(
        self,
        proposal_id: str,
        *,
        current_context_fingerprint: str | None,
        current_active_head_run_id: str | None,
    ) -> ProposalConfirmation:
        with self._lock:
            confirmation = self.latest_confirmation(proposal_id)
            if confirmation is None or confirmation.status != "confirmed":
                raise ProposalConfirmationError("proposal is not confirmed")
            expected_context = confirmation.preconditions.get("context_fingerprint")
            expected_head = confirmation.preconditions.get("active_head_run_id")
            if (
                expected_context is not None
                and current_context_fingerprint != expected_context
            ) or (
                expected_head is not None
                and current_active_head_run_id != expected_head
            ):
                raise ProposalStaleError("proposal preconditions changed")
            return confirmation

    def latest_status(self, proposal_id: str) -> str:
        latest = self.latest_revision(proposal_id)
        records = read_jsonl(self._path(proposal_id))
        for item in reversed(records):
            if item.get("record_type") in {"confirmation", "decision"}:
                return str(item.get("status", "pending"))
        return latest.status

    def _path(self, proposal_id: str) -> Path:
        if not proposal_id or Path(proposal_id).name != proposal_id:
            raise ValueError("proposal_id must be path-safe")
        return self.proposals_dir / f"{proposal_id}.jsonl"

    @staticmethod
    def _build_revision(
        *,
        proposal_id: str,
        operation_id: str,
        operation_version: str,
        revision: int,
        session_id: str,
        chain_id: str,
        command_id: str | None,
        target: dict[str, Any],
        preconditions: dict[str, Any],
        changes: dict[str, Any],
        evidence_refs: Iterable[str],
        expected_effect: Iterable[str],
        risks: Iterable[str],
    ) -> ProposalRevision:
        evidence = tuple(str(item) for item in evidence_refs)
        effects = tuple(str(item) for item in expected_effect)
        risk_items = tuple(str(item) for item in risks)
        identity = {
            "proposal_id": proposal_id,
            "operation_id": operation_id,
            "operation_version": operation_version,
            "revision": revision,
            "target": target,
            "preconditions": preconditions,
            "changes": changes,
            "evidence_refs": evidence,
            "expected_effect": effects,
            "risks": risk_items,
        }
        canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, default=list)
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return ProposalRevision(
            proposal_id=proposal_id,
            operation_id=operation_id,
            operation_version=operation_version,
            revision=revision,
            session_id=session_id,
            chain_id=chain_id,
            command_id=command_id,
            target=dict(target),
            preconditions=dict(preconditions),
            changes=dict(changes),
            evidence_refs=evidence,
            expected_effect=effects,
            risks=risk_items,
            created_at=_now(),
            fingerprint=fingerprint,
        )
