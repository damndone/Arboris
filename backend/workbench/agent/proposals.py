"""Immutable proposal revisions and confirmation gates."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterable
from uuid import uuid4

from ..jsonl_store import _exclusive_jsonl_lock, append_jsonl_atomic, read_jsonl
from .business_identity import identity_value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProposalError(RuntimeError):
    """Base class for proposal lifecycle failures."""


class ProposalConfirmationError(ProposalError):
    """The requested proposal revision cannot be confirmed."""


class ProposalStaleError(ProposalError):
    """The proposal preconditions changed before confirmation."""


class ProposalAdmissionConflict(ProposalError):
    """A prepared invocation conflicts with its request or durable records."""


class ProposalAdmissionNeedsReconciliation(ProposalError):
    """Admission cannot replay a proposal whose lifecycle has progressed."""


@dataclass(frozen=True)
class ProposalInvocation:
    """Server-owned tool identity, separate from operation preconditions."""

    invocation_id: str
    provider_step: int
    tool_call_id: str

    def __post_init__(self) -> None:
        if (type(self.invocation_id) is not str or not self.invocation_id.strip()
                or len(self.invocation_id) > 512 or type(self.provider_step) is not int
                or self.provider_step < 1 or type(self.tool_call_id) is not str):
            raise ProposalAdmissionConflict("invalid proposal invocation identity")

    def to_dict(self) -> dict[str, Any]:
        return {"invocation_id": self.invocation_id, "provider_step": self.provider_step,
                "tool_call_id": self.tool_call_id}


def _canonical_prepared(value: Any) -> str:
    """Keep JSON types exact; never coerce scope or request fields for replay."""
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ProposalAdmissionConflict("prepared proposal requires string JSON keys")
        for item in value.values():
            _canonical_prepared(item)
    elif type(value) is list:
        for item in value:
            _canonical_prepared(item)
    elif value is not None and type(value) not in {str, int, float, bool}:
        raise ProposalAdmissionConflict("prepared proposal requires JSON values")
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ProposalAdmissionConflict("invalid prepared proposal JSON") from exc


def _prepared_digest(value: Any) -> str:
    return hashlib.sha256(_canonical_prepared(value).encode("utf-8")).hexdigest()


def _unique_prepared_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ProposalAdmissionConflict("duplicate prepared proposal field")
        value[key] = item
    return value


def _read_complete_records(path: Path) -> list[dict[str, Any]]:
    """Prepared admission must not discard a torn final record as absent."""
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw or not raw.endswith("\n"):
            raise ProposalAdmissionConflict("incomplete prepared proposal record")
        records = [json.loads(line, object_pairs_hook=_unique_prepared_object)
                   for line in raw.splitlines()]
        if any(type(row) is not dict for row in records):
            raise ProposalAdmissionConflict("invalid prepared proposal record")
        return records
    except (ValueError, UnicodeError) as exc:
        raise ProposalAdmissionConflict("corrupt prepared proposal record") from exc


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

    @contextmanager
    def _creation_lock(self):
        # All proposal lifecycle writers share this lock. The append primitive
        # takes a different, per-JSONL lock; never re-enter this flock.
        with self._lock, _exclusive_jsonl_lock(self.proposals_dir / "creation"):
            yield

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
        evidence_refs, expected_effect, risks = tuple(evidence_refs), tuple(expected_effect), tuple(risks)
        proposal_id = proposal_id or identity_value(
            owner="agent.proposal.create", slot="proposal_id",
            inputs={"session_id": session_id, "chain_id": chain_id, "operation_id": operation_id,
                    "operation_version": operation_version, "command_id": command_id, "target": target,
                    "preconditions": preconditions, "changes": changes, "evidence_refs": list(evidence_refs),
                    "expected_effect": list(expected_effect), "risks": list(risks)},
            create=lambda: f"proposal_{uuid4().hex}")
        with self._creation_lock():
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

    def create_prepared(
        self,
        *,
        invocation: ProposalInvocation,
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
        """Commit one prepared first revision, or verify its pending replay.

        This lock serializes proposal records only. It is not a fencing token
        for the session, turn store, notifications or concurrent approval.
        """
        request = {
            "session_id": session_id, "chain_id": chain_id, "command_id": command_id,
            "proposal_id": proposal_id, "operation_id": operation_id,
            "operation_version": operation_version, "target": target,
            "preconditions": preconditions, "changes": changes,
            "evidence_refs": list(evidence_refs), "expected_effect": list(expected_effect),
            "risks": list(risks),
        }
        request = json.loads(_canonical_prepared(request))
        key = hashlib.sha256(invocation.invocation_id.encode("utf-8")).hexdigest()
        prepared_path = self.proposals_dir / "prepared" / f"{key}.jsonl"
        with self._creation_lock():
            if prepared_path.exists():
                records = _read_complete_records(prepared_path)
                if len(records) != 1:
                    raise ProposalAdmissionConflict("prepared proposal must contain one record")
                row = records[0]
                if (set(row) != {"schema_version", "invocation", "request", "request_sha256",
                                 "revision", "revision_sha256"}
                        or row["schema_version"] != "agent.prepared_proposal.v1"
                        or _canonical_prepared(row["invocation"]) != _canonical_prepared(invocation.to_dict())
                        or type(row["request"]) is not dict
                        or row["request_sha256"] != _prepared_digest(
                            {"invocation": row["invocation"], "request": row["request"]})
                        or _canonical_prepared(row["request"]) != _canonical_prepared(request)
                        or row["revision_sha256"] != _prepared_digest(row["revision"])):
                    raise ProposalAdmissionConflict("prepared proposal request or scope conflict")
                proposal = self._verified_prepared_revision(row["revision"], request)
            else:
                revision_request = {**request, "proposal_id": proposal_id or identity_value(
                    owner="agent.proposal.prepare", slot="proposal_id",
                    inputs={"invocation": invocation.to_dict(), "request": request},
                    create=lambda: f"proposal_{uuid4().hex}")}
                self._path(revision_request["proposal_id"])
                proposal = self._build_revision(**revision_request, revision=1)
                row = {"schema_version": "agent.prepared_proposal.v1", "invocation": invocation.to_dict(),
                       "request": request, "request_sha256": _prepared_digest(
                           {"invocation": invocation.to_dict(), "request": request}),
                       "revision": proposal.to_dict(), "revision_sha256": _prepared_digest(proposal.to_dict())}
                append_jsonl_atomic(prepared_path, row)
            path = self._path(proposal.proposal_id)
            if path.exists():
                records = _read_complete_records(path)
                if _canonical_prepared(records[0]) != _canonical_prepared(proposal.to_dict()):
                    raise ProposalAdmissionConflict("prepared proposal first revision conflict")
                if len(records) != 1:
                    raise ProposalAdmissionNeedsReconciliation("proposal admission needs_reconciliation")
            else:
                append_jsonl_atomic(path, proposal.to_dict())
            return proposal

    @staticmethod
    def _verified_prepared_revision(value: Any, request: dict[str, Any]) -> ProposalRevision:
        try:
            proposal = ProposalRevision.from_dict(value)
            if (_canonical_prepared(proposal.to_dict()) != _canonical_prepared(value)
                    or proposal.revision != 1 or proposal.status != "pending"
                    or (request["proposal_id"] is not None and proposal.proposal_id != request["proposal_id"])):
                raise ValueError("invalid prepared revision shape")
            datetime.fromisoformat(proposal.created_at)
            for name in ("session_id", "chain_id", "command_id", "operation_id", "operation_version",
                         "target", "preconditions", "changes"):
                if _canonical_prepared(value[name]) != _canonical_prepared(request[name]):
                    raise ValueError("invalid prepared revision scope")
            for name in ("evidence_refs", "expected_effect", "risks"):
                if value[name] != [str(item) for item in request[name]]:
                    raise ValueError("invalid prepared revision sequence")
            identity = {key: value[key] for key in ("proposal_id", "operation_id", "operation_version",
                        "revision", "target", "preconditions", "changes", "evidence_refs", "expected_effect", "risks")}
            fingerprint = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                                    default=list).encode("utf-8")).hexdigest()
            if proposal.fingerprint != fingerprint:
                raise ValueError("invalid prepared revision fingerprint")
            return proposal
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ProposalAdmissionConflict("corrupt prepared proposal revision") from exc

    def revise(
        self,
        proposal_id: str,
        *,
        base_revision: int,
        changes: dict[str, Any],
        expected_effect: Iterable[str] | None = None,
        risks: Iterable[str] | None = None,
    ) -> ProposalRevision:
        with self._creation_lock():
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
                _identity_previous=latest.to_dict(),
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
        with self._creation_lock():
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
            identity_inputs = {"previous": latest.to_dict(), "revision": revision, "fingerprint": fingerprint,
                               "actor_type": actor_type, "current_context_fingerprint": current_context_fingerprint,
                               "current_active_head_run_id": current_active_head_run_id}
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
                    confirmed_at=identity_value(owner="agent.proposal.confirm_stale", slot="confirmed_at",
                                                inputs=identity_inputs, create=_now),
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
                confirmed_at=identity_value(owner="agent.proposal.confirm", slot="confirmed_at",
                                            inputs=identity_inputs, create=_now),
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
        with self._creation_lock():
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
                decided_at=identity_value(owner="agent.proposal.decline", slot="decided_at",
                                          inputs={"previous": latest.to_dict(), "actor_type": actor_type,
                                                  "reason": reason}, create=_now),
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
        _identity_previous: dict[str, Any] | None = None,
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
            created_at=identity_value(owner="agent.proposal.revision", slot="created_at",
                                      inputs={"revision": {**json.loads(canonical), "session_id": session_id,
                                                           "chain_id": chain_id, "command_id": command_id},
                                              "previous": _identity_previous}, create=_now),
            fingerprint=fingerprint,
        )
