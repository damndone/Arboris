"""Immutable proposal revisions and confirmation gates."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
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


_PROPOSAL_STORE_PROCESS_GENERATION = object()
_PROPOSAL_STORE_CAPABILITY_LOCK = RLock()
_PROPOSAL_STORE_ISSUER_ADMISSIONS: dict[
    int, tuple[object, str, object, object, int, object, object, object]
] = {}
_PROPOSAL_STORE_CAPABILITY_ADMISSIONS: dict[
    int,
    tuple[
        object,
        object,
        object,
        str,
        object,
        object | None,
        object,
        object,
        int,
        object,
        tuple[int, int],
    ],
] = {}


class ProposalStoreCapabilityError(ProposalError):
    """A raw or forged ProposalStore was supplied where server admission is required."""


class ProposalStoreCapabilityIssuerV1:
    """A process-local server issuer for proposal-store capabilities.

    The issuer owns a random nonce and a registry admission. A capability is
    usable only while its exact issuer object, nonce, process generation, and
    store-root identity all match the server registry snapshot.
    """

    __slots__ = (
        "_issuer_nonce",
        "_mutation_admission",
        "_process_id",
        "_generation",
        "_owner_identity",
        "_authority_secret",
    )

    def __init__(self) -> None:
        self._issuer_nonce = secrets.token_hex(32)
        self._mutation_admission: object | None = None
        self._process_id = os.getpid()
        self._generation = _PROPOSAL_STORE_PROCESS_GENERATION
        self._owner_identity: object | None = None
        self._authority_secret: object | None = None

    def _require_live(self) -> None:
        with _PROPOSAL_STORE_CAPABILITY_LOCK:
            admission = _PROPOSAL_STORE_ISSUER_ADMISSIONS.get(id(self))
        if (
            admission is None
            or admission[0] is not self
            or admission[1] != self._issuer_nonce
            or admission[3] is not self._mutation_admission
            or admission[4] != self._process_id
            or admission[5] is not self._generation
            or admission[6] is not self._owner_identity
            or admission[7] is not self._authority_secret
            or self._process_id != os.getpid()
        ):
            raise ProposalStoreCapabilityError(
                "server proposal capability issuer is not current"
            )

    def _issue_store(
        self,
        root: Path | str,
        *,
        service_admission: object,
    ) -> "ProposalStoreCapabilityV1":
        self._require_live()
        self._require_service_admission(service_admission)
        return ProposalStoreCapabilityV1._issue(
            ProposalStore(root),
            issuer=self,
            service_admission=service_admission,
        )

    def _register_service_admission(self) -> object:
        """Reject caller attempts to create a service-entry handle."""

        raise ProposalStoreCapabilityError(
            "service-entry handles are issued by server-owned authority"
        )

    def _require_service_admission(self, service_admission: object) -> None:
        with _PROPOSAL_STORE_CAPABILITY_LOCK:
            current = _PROPOSAL_STORE_ISSUER_ADMISSIONS.get(id(self))
        if (
            current is None
            or current[0] is not self
            or current[1] != self._issuer_nonce
            or current[2] is not service_admission
            or type(service_admission) is not _ProposalStoreServiceEntryV1
            or service_admission._issuer_nonce != self._issuer_nonce
            or service_admission._owner_identity is not self._owner_identity
            or service_admission._authority_secret is not self._authority_secret
            or service_admission._process_id != self._process_id
            or service_admission._generation is not self._generation
        ):
            raise ProposalStoreCapabilityError(
                "server proposal capability service admission is required"
            )

    def _grant_mutation_admission(self) -> None:
        """Reject caller attempts to upgrade an issuer."""

        raise ProposalStoreCapabilityError(
            "mutation admission is issued by server-owned authority"
        )


class _ProposalStoreServiceEntryV1:
    """Opaque service-entry handle issued only by the server authority."""

    __slots__ = (
        "_entry_nonce",
        "_issuer_nonce",
        "_owner_identity",
        "_authority_secret",
        "_process_id",
        "_generation",
    )

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("service-entry handles are issued by server admission")

    def __copy__(self) -> "_ProposalStoreServiceEntryV1":
        raise TypeError("service-entry handles cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> "_ProposalStoreServiceEntryV1":
        raise TypeError("service-entry handles cannot be copied")

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("service-entry handles cannot be serialized")

    def __reduce_ex__(self, _protocol: int) -> tuple[object, ...]:
        raise TypeError("service-entry handles cannot be serialized")


class _ProposalStoreServerAuthorityV1:
    """Process-local authority that alone can register issuers and handles."""

    __slots__ = ("_authority_secret", "_process_id", "_generation")

    def __init__(self) -> None:
        self._authority_secret = object()
        self._process_id = os.getpid()
        self._generation = _PROPOSAL_STORE_PROCESS_GENERATION

    def issue(self) -> tuple[ProposalStoreCapabilityIssuerV1, object]:
        if self._process_id != os.getpid() or self._generation is not _PROPOSAL_STORE_PROCESS_GENERATION:
            raise ProposalStoreCapabilityError("server proposal authority is not current")
        issuer = object.__new__(ProposalStoreCapabilityIssuerV1)
        issuer._issuer_nonce = secrets.token_hex(32)
        issuer._mutation_admission = object()
        issuer._process_id = self._process_id
        issuer._generation = self._generation
        issuer._owner_identity = object()
        issuer._authority_secret = self._authority_secret
        service_entry = object.__new__(_ProposalStoreServiceEntryV1)
        service_entry._entry_nonce = secrets.token_hex(32)
        service_entry._issuer_nonce = issuer._issuer_nonce
        service_entry._owner_identity = issuer._owner_identity
        service_entry._authority_secret = self._authority_secret
        service_entry._process_id = self._process_id
        service_entry._generation = self._generation
        with _PROPOSAL_STORE_CAPABILITY_LOCK:
            _PROPOSAL_STORE_ISSUER_ADMISSIONS[id(issuer)] = (
                issuer,
                issuer._issuer_nonce,
                service_entry,
                issuer._mutation_admission,
                issuer._process_id,
                issuer._generation,
                issuer._owner_identity,
                self._authority_secret,
            )
        return issuer, service_entry


_PROPOSAL_STORE_SERVER_AUTHORITY = _ProposalStoreServerAuthorityV1()


def _issue_server_owned_proposal_store_authority() -> tuple[ProposalStoreCapabilityIssuerV1, object]:
    """Return one issuer and its opaque server-issued service-entry handle."""

    return _PROPOSAL_STORE_SERVER_AUTHORITY.issue()


# The HTTP route owns this exact issuer identity. It is intentionally shared
# with the orchestrator's default route binding, while every capability still
# carries its own nonce/root/process snapshot in the registry.
(
    DEFAULT_ROUTE_PROPOSAL_STORE_ISSUER,
    _DEFAULT_ROUTE_PROPOSAL_STORE_SERVICE_ADMISSION,
) = _issue_server_owned_proposal_store_authority()


def issue_route_proposal_store(root: Path | str) -> "ProposalStoreCapabilityV1":
    """Issue the route capability through the server-owned service entrance."""

    return ProposalStore._issue_server_capability(
        root,
        issuer=DEFAULT_ROUTE_PROPOSAL_STORE_ISSUER,
        service_admission=_DEFAULT_ROUTE_PROPOSAL_STORE_SERVICE_ADMISSION,
    )


class ProposalStoreCapabilityV1:
    """A non-serializable, server-issued view of one ProposalStore.

    ``ProposalStore`` remains the append-only file implementation used by
    historical persistence code.  Compiler and route authority seams accept
    this capability instead of trusting a caller-created store merely because
    it has the same Python type or points at a complete JSONL file.
    """

    __slots__ = (
        "_store",
        "_issuer",
        "_issuer_nonce",
        "_service_admission",
        "_mutation_admission",
        "_root_identity",
        "_process_id",
        "_generation",
        "_owner_identity",
        "_authority_secret",
    )

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("proposal store capabilities are issued by server admission")

    @classmethod
    def _issue(
        cls,
        store: "ProposalStore",
        *,
        issuer: ProposalStoreCapabilityIssuerV1,
        service_admission: object,
    ) -> "ProposalStoreCapabilityV1":
        if type(store) is not ProposalStore or type(issuer) is not ProposalStoreCapabilityIssuerV1:
            raise ProposalStoreCapabilityError("server proposal store admission is invalid")
        issuer._require_live()
        issuer._require_service_admission(service_admission)
        capability = object.__new__(cls)
        process_id = os.getpid()
        generation = _PROPOSAL_STORE_PROCESS_GENERATION
        for name, value in (
            ("_store", store),
            ("_issuer", issuer),
            ("_issuer_nonce", issuer._issuer_nonce),
            ("_service_admission", service_admission),
            ("_mutation_admission", issuer._mutation_admission),
            ("_root_identity", store._root_identity),
            ("_process_id", process_id),
            ("_generation", generation),
            ("_owner_identity", issuer._owner_identity),
            ("_authority_secret", issuer._authority_secret),
        ):
            object.__setattr__(capability, name, value)
        with _PROPOSAL_STORE_CAPABILITY_LOCK:
            _PROPOSAL_STORE_CAPABILITY_ADMISSIONS[id(capability)] = (
                capability,
                store,
                issuer,
                issuer._issuer_nonce,
                service_admission,
                issuer._mutation_admission,
                issuer._owner_identity,
                issuer._authority_secret,
                process_id,
                generation,
                store._root_identity,
            )
        return capability

    def _require_admitted(
        self,
        issuer: ProposalStoreCapabilityIssuerV1 | None = None,
    ) -> "ProposalStore":
        if type(self) is not ProposalStoreCapabilityV1:
            raise ProposalStoreCapabilityError("server proposal store capability is required")
        with _PROPOSAL_STORE_CAPABILITY_LOCK:
            admission = _PROPOSAL_STORE_CAPABILITY_ADMISSIONS.get(id(self))
        if admission is None or admission[0] is not self:
            raise ProposalStoreCapabilityError("proposal store capability was not server-admitted")
        (
            _capability,
            store,
            admitted_issuer,
            issuer_nonce,
            service_admission,
            mutation_admission,
            owner_identity,
            authority_secret,
            process_id,
            generation,
            root_identity,
        ) = admission
        if issuer is not None and issuer is not admitted_issuer:
            raise ProposalStoreCapabilityError(
                "proposal store capability issuer binding changed"
            )
        admitted_issuer._require_live()
        if (
            self._store is not store
            or self._issuer is not admitted_issuer
            or self._issuer_nonce != issuer_nonce
            or self._service_admission is not service_admission
            or self._mutation_admission is not mutation_admission
            or self._owner_identity is not owner_identity
            or self._authority_secret is not authority_secret
            or self._root_identity != store._root_identity
            or self._root_identity != root_identity
            or self._process_id != process_id
            or self._generation is not generation
            or process_id != os.getpid()
        ):
            raise ProposalStoreCapabilityError("server proposal store capability binding changed")
        try:
            root_info = store.root.resolve().stat()
        except (OSError, RuntimeError) as exc:
            raise ProposalStoreCapabilityError("server proposal store root is unavailable") from exc
        if (int(root_info.st_dev), int(root_info.st_ino)) != store._root_identity:
            raise ProposalStoreCapabilityError("server proposal store root identity changed")
        return store

    def _require_mutation_admitted(self) -> "ProposalStore":
        """Require a live server issuer before any proposal mutation."""

        store = self._require_admitted()
        if self._issuer._mutation_admission is None:
            raise ProposalStoreCapabilityError(
                "proposal store capability mutation admission is required"
            )
        return store

    @property
    def root(self) -> Path:
        return self._require_admitted().root

    def create(self, *args: object, **kwargs: object) -> ProposalRevision:
        store = self._require_mutation_admitted()
        preconditions = kwargs.get("preconditions")
        if type(preconditions) is dict:
            server_compilation = preconditions.get("server_compilation")
            if type(server_compilation) is dict:
                server_preconditions = dict(preconditions)
                server_compilation = dict(server_compilation)
                # The confirmation identity is issued by this admitted server
                # capability. A caller may describe the compilation record,
                # but cannot choose the receipt identity bound to it.
                server_compilation["confirmation_id"] = f"confirmation:{uuid4().hex}"
                server_preconditions["server_compilation"] = server_compilation
                kwargs["preconditions"] = server_preconditions
        return store.create(*args, **kwargs)

    def revise(self, *args: object, **kwargs: object) -> ProposalRevision:
        return self._require_mutation_admitted().revise(*args, **kwargs)

    def confirm(self, *args: object, **kwargs: object) -> ProposalConfirmation:
        return self._require_mutation_admitted().confirm(*args, **kwargs)

    def decline(self, *args: object, **kwargs: object) -> ProposalDecision:
        return self._require_mutation_admitted().decline(*args, **kwargs)

    def latest_revision(self, *args: object, **kwargs: object) -> ProposalRevision:
        return self._require_admitted().latest_revision(*args, **kwargs)

    def latest_revisions_for_session(self, *args: object, **kwargs: object) -> list[ProposalRevision]:
        return self._require_admitted().latest_revisions_for_session(*args, **kwargs)

    def revisions(self, *args: object, **kwargs: object) -> list[ProposalRevision]:
        return self._require_admitted().revisions(*args, **kwargs)

    def latest_confirmation(self, *args: object, **kwargs: object) -> ProposalConfirmation | None:
        return self._require_admitted().latest_confirmation(*args, **kwargs)

    def latest_decision(self, *args: object, **kwargs: object) -> ProposalDecision | None:
        return self._require_admitted().latest_decision(*args, **kwargs)

    def validate_confirmation_preconditions(self, *args: object, **kwargs: object) -> ProposalConfirmation:
        return self._require_admitted().validate_confirmation_preconditions(*args, **kwargs)

    def latest_status(self, *args: object, **kwargs: object) -> str:
        return self._require_admitted().latest_status(*args, **kwargs)

    def __copy__(self) -> "ProposalStoreCapabilityV1":
        raise TypeError("proposal store capabilities cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> "ProposalStoreCapabilityV1":
        raise TypeError("proposal store capabilities cannot be copied")

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("proposal store capabilities cannot be serialized")

    def __reduce_ex__(self, _protocol: int) -> tuple[object, ...]:
        raise TypeError("proposal store capabilities cannot be serialized")


class ProposalStore:
    """Project-local append-only proposal and confirmation store."""

    def __init__(self, root: Path | str, *, create: bool = True) -> None:
        self.root = Path(root)
        self.proposals_dir = self.root / "proposals"
        if create:
            self.proposals_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        try:
            root_info = self.root.resolve().stat()
        except (OSError, RuntimeError) as exc:
            raise ProposalStoreCapabilityError("proposal store root is unavailable") from exc
        if not self.root.resolve().is_dir():
            raise ProposalStoreCapabilityError("proposal store root must be a directory")
        self._root_identity = (int(root_info.st_dev), int(root_info.st_ino))

    @classmethod
    def _issue_server_capability(
        cls,
        root: Path | str,
        *,
        issuer: ProposalStoreCapabilityIssuerV1,
        service_admission: object,
    ) -> ProposalStoreCapabilityV1:
        """Issue a capability through an exact server-owned issuer registry."""

        if type(issuer) is not ProposalStoreCapabilityIssuerV1:
            raise ProposalStoreCapabilityError("server proposal capability issuer is required")
        return issuer._issue_store(root, service_admission=service_admission)

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
