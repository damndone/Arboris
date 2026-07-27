"""CF4 execution authorization control-plane primitives.

This module records a server-created, one-time authorization for the narrow
``confirm_and_execute`` option mode.  It deliberately stops before Draft, Run,
Graph, Artifact, process, or network handling.  Those consumers must claim
the durable receipt before they create any external side effect.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterator, Mapping

from ..agent.storage import read_jsonl
from ..custom_capability.canonical import domain_digest


OPTION_EXECUTION_AUTHORIZATION_CONTRACT_VERSION = "OptionExecutionAuthorization@1.0"
_RECORD_TYPE = "option_execution_authorization"
_JOURNAL_NAME = "option-execution-authorizations.jsonl"
_MAX_TEXT = 512
_MAX_REASON = 256
_HEX = frozenset("0123456789abcdef")
_STATUSES = frozenset(
    {
        "issued",
        "rejected",
        "claimed",
        "invalidated",
        "dispatch_reserved",
        "running",
        "dispatch_unknown",
        "failed",
        "consumed",
    }
)
_TRANSITIONS = {
    "issued": frozenset({"rejected", "claimed"}),
    "claimed": frozenset({"invalidated", "dispatch_reserved", "failed", "dispatch_unknown"}),
    "dispatch_reserved": frozenset({"running", "failed", "dispatch_unknown"}),
    "running": frozenset({"dispatch_unknown", "failed", "consumed"}),
    "dispatch_unknown": frozenset(),
    "rejected": frozenset(),
    "invalidated": frozenset(),
    "failed": frozenset(),
    "consumed": frozenset(),
}
_TRANSITION_METADATA_LIMIT = 8
_TRANSITION_VALUE_LIMIT = 256


class ExecutionAuthorizationError(ValueError):
    """Base class for fail-closed authorization errors."""

    code = "CAPABILITY_OPTION_EXECUTION_RECEIPT_INVALID"


class ExecutionAuthorizationReplay(ExecutionAuthorizationError):
    """The authorization or idempotency key was reused with another payload."""

    code = "CAPABILITY_OPTION_EXECUTION_REPLAY_MISMATCH"


class ExecutionAuthorizationRejected(ExecutionAuthorizationError):
    """The authorization could not be claimed and was durably rejected."""

    code = "CAPABILITY_OPTION_EXECUTION_REJECTED"


class ExecutionAuthorizationTransitionError(ExecutionAuthorizationError):
    """A receipt transition violates the explicit lifecycle contract."""

    code = "CAPABILITY_OPTION_EXECUTION_TRANSITION_INVALID"


class ExecutionAuthorizationInvalidated(ExecutionAuthorizationRejected):
    """A claimed authorization lost its binding before dispatch reservation."""

    code = "CAPABILITY_OPTION_EXECUTION_INVALIDATED"


def _text(value: Any, field: str, *, maximum: int = _MAX_TEXT) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ExecutionAuthorizationError(f"{field} must be a bounded non-empty string")
    if any(ord(char) < 0x20 for char in value):
        raise ExecutionAuthorizationError(f"{field} contains a control character")
    return value


def _identifier(value: Any, field: str) -> str:
    text = _text(value, field)
    if (
        Path(text).name != text
        or text in {".", ".."}
        or "/" in text
        or "\\" in text
    ):
        raise ExecutionAuthorizationError(f"{field} must be path-safe")
    return text


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ExecutionAuthorizationError(f"{field} must be a positive integer")
    return value


def _digest(value: Any, field: str) -> str:
    text = _text(value, field, maximum=64)
    if len(text) != 64 or any(char not in _HEX for char in text):
        raise ExecutionAuthorizationError(f"{field} must be a lowercase SHA-256 digest")
    return text


def _draft_hash(value: Any) -> str:
    text = _text(value, "draft_hash", maximum=71)
    if not text.startswith("sha256:") or len(text) != 71:
        raise ExecutionAuthorizationError("draft_hash must be a sha256-prefixed digest")
    if any(char not in _HEX for char in text[7:]):
        raise ExecutionAuthorizationError("draft_hash must be a lowercase SHA-256 digest")
    return text


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ExecutionAuthorizationError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _time_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ExecutionAuthorizationError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ExecutionAuthorizationError(f"{field} must be an ISO-8601 timestamp") from error
    return _utc(parsed, field)


def _transition_metadata(
    value: Mapping[str, Any] | tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    if isinstance(value, Mapping):
        items = tuple(value.items())
    elif isinstance(value, tuple):
        items = value
    else:
        raise ExecutionAuthorizationTransitionError(
            "transition_metadata must be a mapping"
        )
    if len(items) > _TRANSITION_METADATA_LIMIT:
        raise ExecutionAuthorizationTransitionError(
            "transition_metadata exceeds the bounded field limit"
        )
    normalized: list[tuple[str, str]] = []
    for key, item in items:
        normalized_key = _identifier(key, "transition_metadata key")
        normalized_value = _text(
            item,
            f"transition_metadata[{normalized_key}]",
            maximum=_TRANSITION_VALUE_LIMIT,
        )
        normalized.append((normalized_key, normalized_value))
    if len({key for key, _ in normalized}) != len(normalized):
        raise ExecutionAuthorizationTransitionError(
            "transition_metadata keys must be unique"
        )
    return tuple(sorted(normalized))


def _derived_transition_id(
    authorization_id: str,
    target_status: str,
    prior_receipt_digest: str,
) -> str:
    return domain_digest(
        "workbench.capability_factory.authorization_transition/v1",
        {
            "authorization_id": authorization_id,
            "target_status": target_status,
            "prior_receipt_digest": prior_receipt_digest,
        },
    )


@dataclass(frozen=True, slots=True)
class OptionExecutionAuthorization:
    """Immutable snapshot of an authorization and its current journal state."""

    authorization_id: str
    notebook_id: str
    option_id: str
    option_revision: int
    binding_revision: int
    capability_resolution_binding_ref: str
    materialization_id: str
    draft_id: str
    draft_hash: str
    run_intent_id: str
    capability_ref: str
    bundle_ref: str
    evidence_ref: str
    admission_ref: str
    runtime_policy_ref: str
    freshness_cursor_ref: str
    input_graph_fingerprint: str
    freshness_dependency_fingerprint: str
    operation_id: str
    execution_mode: str
    risk_level: str
    artifact_contract_ref: str
    consumer_projection_ref: str
    idempotency_key: str
    issued_at: datetime
    expires_at: datetime
    status: str = "issued"
    claim_owner_id: str | None = None
    lease_epoch: int | None = None
    lease_expires_at: datetime | None = None
    rejection_reason: str | None = None
    transition_id: str | None = None
    prior_receipt_digest: str | None = None
    transition_metadata: tuple[tuple[str, str], ...] = ()

    _KEYS = frozenset(
        {
            "contract_version",
            "authorization_id",
            "notebook_id",
            "option_id",
            "option_revision",
            "binding_revision",
            "capability_resolution_binding_ref",
            "materialization_id",
            "draft_id",
            "draft_hash",
            "run_intent_id",
            "capability_ref",
            "bundle_ref",
            "evidence_ref",
            "admission_ref",
            "runtime_policy_ref",
            "freshness_cursor_ref",
            "input_graph_fingerprint",
            "freshness_dependency_fingerprint",
            "operation_id",
            "execution_mode",
            "risk_level",
            "artifact_contract_ref",
            "consumer_projection_ref",
            "idempotency_key",
            "issued_at",
            "expires_at",
            "status",
            "claim_owner_id",
            "lease_epoch",
            "lease_expires_at",
            "rejection_reason",
            "transition_id",
            "prior_receipt_digest",
            "transition_metadata",
            "payload_digest",
            "receipt_digest",
        }
    )
    _LEGACY_KEYS = _KEYS - {
        "transition_id",
        "prior_receipt_digest",
        "transition_metadata",
        "receipt_digest",
    }

    def __post_init__(self) -> None:
        object.__setattr__(self, "authorization_id", _identifier(self.authorization_id, "authorization_id"))
        for field in (
            "notebook_id",
            "option_id",
            "materialization_id",
            "draft_id",
            "run_intent_id",
        ):
            object.__setattr__(self, field, _identifier(getattr(self, field), field))
        object.__setattr__(self, "option_revision", _positive_int(self.option_revision, "option_revision"))
        object.__setattr__(self, "binding_revision", _positive_int(self.binding_revision, "binding_revision"))
        for field in (
            "capability_resolution_binding_ref",
            "capability_ref",
            "bundle_ref",
            "evidence_ref",
            "admission_ref",
            "runtime_policy_ref",
            "freshness_cursor_ref",
            "artifact_contract_ref",
            "consumer_projection_ref",
        ):
            object.__setattr__(self, field, _digest(getattr(self, field), field))
        object.__setattr__(self, "draft_hash", _draft_hash(self.draft_hash))
        object.__setattr__(self, "input_graph_fingerprint", _text(self.input_graph_fingerprint, "input_graph_fingerprint"))
        object.__setattr__(self, "freshness_dependency_fingerprint", _text(self.freshness_dependency_fingerprint, "freshness_dependency_fingerprint"))
        object.__setattr__(self, "operation_id", _text(self.operation_id, "operation_id"))
        if self.execution_mode != "confirm_and_execute":
            raise ExecutionAuthorizationError(
                "execution_mode must be confirm_and_execute for this authorization"
            )
        if self.risk_level != "low":
            raise ExecutionAuthorizationError("only low-risk options may use confirm_and_execute")
        object.__setattr__(self, "idempotency_key", _text(self.idempotency_key, "idempotency_key"))
        issued_at = _utc(self.issued_at, "issued_at")
        expires_at = _utc(self.expires_at, "expires_at")
        if expires_at <= issued_at:
            raise ExecutionAuthorizationError("expires_at must be after issued_at")
        object.__setattr__(self, "issued_at", issued_at)
        object.__setattr__(self, "expires_at", expires_at)
        if self.status not in _STATUSES:
            raise ExecutionAuthorizationError(f"unsupported authorization status: {self.status}")
        if self.claim_owner_id is not None:
            object.__setattr__(self, "claim_owner_id", _identifier(self.claim_owner_id, "claim_owner_id"))
        if self.lease_epoch is not None:
            object.__setattr__(self, "lease_epoch", _positive_int(self.lease_epoch, "lease_epoch"))
        if self.lease_expires_at is not None:
            object.__setattr__(self, "lease_expires_at", _utc(self.lease_expires_at, "lease_expires_at"))
        if self.rejection_reason is not None:
            object.__setattr__(self, "rejection_reason", _text(self.rejection_reason, "rejection_reason", maximum=_MAX_REASON))
        if self.transition_id is not None:
            object.__setattr__(self, "transition_id", _identifier(self.transition_id, "transition_id"))
        if self.prior_receipt_digest is not None:
            object.__setattr__(self, "prior_receipt_digest", _digest(self.prior_receipt_digest, "prior_receipt_digest"))
        object.__setattr__(self, "transition_metadata", _transition_metadata(self.transition_metadata))
        if self.status == "issued" and any(
            value is not None
            for value in (
                self.claim_owner_id,
                self.lease_epoch,
                self.lease_expires_at,
                self.rejection_reason,
                self.transition_id,
                self.prior_receipt_digest,
            )
        ):
            raise ExecutionAuthorizationError("issued authorization cannot carry transition metadata")
        if self.status == "issued" and self.transition_metadata:
            raise ExecutionAuthorizationError("issued authorization cannot carry transition metadata")
        if self.status == "claimed":
            if self.claim_owner_id is None or self.lease_epoch is None or self.lease_expires_at is None:
                raise ExecutionAuthorizationError("claimed authorization requires lease metadata")
            if self.rejection_reason is not None:
                raise ExecutionAuthorizationError("claimed authorization cannot carry rejection_reason")
        if self.status == "rejected":
            if self.rejection_reason is None:
                raise ExecutionAuthorizationError("rejected authorization requires rejection_reason")
            if any(value is not None for value in (self.claim_owner_id, self.lease_epoch, self.lease_expires_at)):
                raise ExecutionAuthorizationError("rejected authorization cannot carry lease metadata")
        if self.status == "invalidated":
            if self.rejection_reason is None:
                raise ExecutionAuthorizationError("invalidated authorization requires rejection_reason")
            if self.claim_owner_id is None or self.lease_epoch is None or self.lease_expires_at is None:
                raise ExecutionAuthorizationError("invalidated authorization requires claim metadata")
        if self.status in {"dispatch_reserved", "running", "dispatch_unknown", "failed", "consumed"}:
            if self.claim_owner_id is None or self.lease_epoch is None or self.lease_expires_at is None:
                raise ExecutionAuthorizationError(f"{self.status} authorization requires claim metadata")
            if self.transition_id is None or self.prior_receipt_digest is None:
                raise ExecutionAuthorizationError(f"{self.status} authorization requires transition provenance")
            if self.status in {"dispatch_unknown", "failed"} and self.rejection_reason is None:
                raise ExecutionAuthorizationError(f"{self.status} authorization requires rejection_reason")
            if self.status in {"dispatch_reserved", "running", "consumed"} and self.rejection_reason is not None:
                raise ExecutionAuthorizationError(f"{self.status} authorization cannot carry rejection_reason")

    @property
    def contract_version(self) -> str:
        return OPTION_EXECUTION_AUTHORIZATION_CONTRACT_VERSION

    def _payload(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "notebook_id": self.notebook_id,
            "option_id": self.option_id,
            "option_revision": self.option_revision,
            "binding_revision": self.binding_revision,
            "capability_resolution_binding_ref": self.capability_resolution_binding_ref,
            "materialization_id": self.materialization_id,
            "draft_id": self.draft_id,
            "draft_hash": self.draft_hash,
            "run_intent_id": self.run_intent_id,
            "capability_ref": self.capability_ref,
            "bundle_ref": self.bundle_ref,
            "evidence_ref": self.evidence_ref,
            "admission_ref": self.admission_ref,
            "runtime_policy_ref": self.runtime_policy_ref,
            "freshness_cursor_ref": self.freshness_cursor_ref,
            "input_graph_fingerprint": self.input_graph_fingerprint,
            "freshness_dependency_fingerprint": self.freshness_dependency_fingerprint,
            "operation_id": self.operation_id,
            "execution_mode": self.execution_mode,
            "risk_level": self.risk_level,
            "artifact_contract_ref": self.artifact_contract_ref,
            "consumer_projection_ref": self.consumer_projection_ref,
            "idempotency_key": self.idempotency_key,
            "issued_at": _time_text(self.issued_at),
            "expires_at": _time_text(self.expires_at),
        }

    @property
    def payload_digest(self) -> str:
        return domain_digest("workbench.capability_factory.option_execution_authorization/v1", self._payload())

    def _receipt_payload(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "authorization_id": self.authorization_id,
            "status": self.status,
            "claim_owner_id": self.claim_owner_id,
            "lease_epoch": self.lease_epoch,
            "lease_expires_at": None if self.lease_expires_at is None else _time_text(self.lease_expires_at),
            "rejection_reason": self.rejection_reason,
            "transition_id": self.transition_id,
            "prior_receipt_digest": self.prior_receipt_digest,
            "transition_metadata": dict(self.transition_metadata),
            "payload_digest": self.payload_digest,
        }

    @property
    def receipt_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.option_execution_authorization_receipt/v1",
            self._receipt_payload(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "authorization_id": self.authorization_id,
            "status": self.status,
            "claim_owner_id": self.claim_owner_id,
            "lease_epoch": self.lease_epoch,
            "lease_expires_at": None if self.lease_expires_at is None else _time_text(self.lease_expires_at),
            "rejection_reason": self.rejection_reason,
            "transition_id": self.transition_id,
            "prior_receipt_digest": self.prior_receipt_digest,
            "transition_metadata": dict(self.transition_metadata),
            "payload_digest": self.payload_digest,
            "receipt_digest": self.receipt_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OptionExecutionAuthorization":
        if not isinstance(value, Mapping) or set(value) not in {cls._KEYS, cls._LEGACY_KEYS}:
            raise ExecutionAuthorizationError("option execution authorization has an unknown or missing field")
        if value["contract_version"] != OPTION_EXECUTION_AUTHORIZATION_CONTRACT_VERSION:
            raise ExecutionAuthorizationError("contract_version is unsupported")
        result = cls(
            authorization_id=value["authorization_id"],
            notebook_id=value["notebook_id"],
            option_id=value["option_id"],
            option_revision=value["option_revision"],
            binding_revision=value["binding_revision"],
            capability_resolution_binding_ref=value["capability_resolution_binding_ref"],
            materialization_id=value["materialization_id"],
            draft_id=value["draft_id"],
            draft_hash=value["draft_hash"],
            run_intent_id=value["run_intent_id"],
            capability_ref=value["capability_ref"],
            bundle_ref=value["bundle_ref"],
            evidence_ref=value["evidence_ref"],
            admission_ref=value["admission_ref"],
            runtime_policy_ref=value["runtime_policy_ref"],
            freshness_cursor_ref=value["freshness_cursor_ref"],
            input_graph_fingerprint=value["input_graph_fingerprint"],
            freshness_dependency_fingerprint=value["freshness_dependency_fingerprint"],
            operation_id=value["operation_id"],
            execution_mode=value["execution_mode"],
            risk_level=value["risk_level"],
            artifact_contract_ref=value["artifact_contract_ref"],
            consumer_projection_ref=value["consumer_projection_ref"],
            idempotency_key=value["idempotency_key"],
            issued_at=_parse_time(value["issued_at"], "issued_at"),
            expires_at=_parse_time(value["expires_at"], "expires_at"),
            status=value["status"],
            claim_owner_id=value["claim_owner_id"],
            lease_epoch=value["lease_epoch"],
            lease_expires_at=(
                None
                if value["lease_expires_at"] is None
                else _parse_time(value["lease_expires_at"], "lease_expires_at")
            ),
            rejection_reason=value["rejection_reason"],
            transition_id=value.get("transition_id"),
            prior_receipt_digest=value.get("prior_receipt_digest"),
            transition_metadata=value.get("transition_metadata", {}),
        )
        if value["payload_digest"] != result.payload_digest:
            raise ExecutionAuthorizationError("option execution authorization payload digest mismatch")
        if "receipt_digest" in value and value["receipt_digest"] != result.receipt_digest:
            raise ExecutionAuthorizationError("option execution authorization receipt digest mismatch")
        return result


class OptionExecutionAuthorizationStore:
    """Append-only journal with atomic idempotent issue and claim operations."""

    def __init__(
        self,
        root: Path | str,
        *,
        clock: Callable[[], datetime] | None = None,
        create: bool = True,
    ) -> None:
        self.root = Path(root)
        self.directory = self.root / "option-execution-authorizations"
        if create:
            self.directory.mkdir(parents=True, exist_ok=True)
        self.journal = self.directory / _JOURNAL_NAME
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()

    def issue(self, authorization: OptionExecutionAuthorization) -> OptionExecutionAuthorization:
        if not isinstance(authorization, OptionExecutionAuthorization):
            raise ExecutionAuthorizationError("authorization must be OptionExecutionAuthorization")
        if authorization.status != "issued":
            raise ExecutionAuthorizationError("only issued authorizations can be stored")
        with self._lock, self._journal_lock():
            now = _utc(self._clock(), "clock")
            if authorization.issued_at > now or authorization.expires_at <= now:
                raise ExecutionAuthorizationRejected("authorization is outside its validity window")
            records = self._records()
            current_by_id = self._latest_by_id(records)
            existing_for_key = next(
                (
                    current
                    for current in current_by_id.values()
                    if current.idempotency_key == authorization.idempotency_key
                ),
                None,
            )
            if existing_for_key is not None:
                if existing_for_key.payload_digest != authorization.payload_digest:
                    raise ExecutionAuthorizationReplay(
                        "idempotency key is already bound to another payload"
                    )
                return existing_for_key
            existing = current_by_id.get(authorization.authorization_id)
            if existing is not None:
                if existing.payload_digest != authorization.payload_digest:
                    raise ExecutionAuthorizationReplay(
                        "authorization id is already bound to another payload"
                    )
                return existing
            self._append_locked(authorization)
            return authorization

    def read(self, authorization_id: str) -> OptionExecutionAuthorization:
        identifier = _identifier(authorization_id, "authorization_id")
        with self._lock:
            current = self._latest_by_id(self._records()).get(identifier)
        if current is None:
            raise KeyError(f"unknown option execution authorization: {identifier}")
        return current

    def history(self, authorization_id: str) -> tuple[OptionExecutionAuthorization, ...]:
        identifier = _identifier(authorization_id, "authorization_id")
        with self._lock:
            return tuple(
                record
                for record in self._records()
                if record.authorization_id == identifier
            )

    def claim(
        self,
        authorization_id: str,
        *,
        idempotency_key: str,
        current_binding_ref: str,
        current_freshness_cursor_ref: str,
        owner_id: str,
        lease_seconds: int,
    ) -> OptionExecutionAuthorization:
        identifier = _identifier(authorization_id, "authorization_id")
        key = _text(idempotency_key, "idempotency_key")
        binding = _digest(current_binding_ref, "current_binding_ref")
        freshness = _digest(current_freshness_cursor_ref, "current_freshness_cursor_ref")
        owner = _identifier(owner_id, "owner_id")
        lease = _positive_int(lease_seconds, "lease_seconds")

        with self._lock, self._journal_lock():
            current = self._latest_by_id(self._records()).get(identifier)
            if current is None:
                raise ExecutionAuthorizationRejected("authorization was not found")
            if current.idempotency_key != key:
                raise ExecutionAuthorizationReplay("idempotency key does not match authorization")
            if current.status == "claimed":
                if binding != current.capability_resolution_binding_ref:
                    invalidated = replace(
                        current,
                        status="invalidated",
                        rejection_reason="binding",
                        transition_id=_derived_transition_id(
                            current.authorization_id,
                            "invalidated",
                            current.receipt_digest,
                        ),
                        prior_receipt_digest=current.receipt_digest,
                    )
                    self._append_locked(invalidated)
                    raise ExecutionAuthorizationInvalidated(
                        "authorization claim invalidated: binding"
                    )
                if freshness != current.freshness_cursor_ref:
                    invalidated = replace(
                        current,
                        status="invalidated",
                        rejection_reason="freshness",
                        transition_id=_derived_transition_id(
                            current.authorization_id,
                            "invalidated",
                            current.receipt_digest,
                        ),
                        prior_receipt_digest=current.receipt_digest,
                    )
                    self._append_locked(invalidated)
                    raise ExecutionAuthorizationInvalidated(
                        "authorization claim invalidated: freshness"
                    )
                return current
            if current.status == "rejected":
                raise ExecutionAuthorizationRejected(
                    f"authorization was rejected: {current.rejection_reason}"
                )
            if current.status == "invalidated":
                raise ExecutionAuthorizationInvalidated(
                    f"authorization was invalidated: {current.rejection_reason}"
                )
            now = _utc(self._clock(), "clock")
            reason = None
            if now >= current.expires_at:
                reason = "expired"
            elif binding != current.capability_resolution_binding_ref:
                reason = "binding"
            elif freshness != current.freshness_cursor_ref:
                reason = "freshness"
            if reason is not None:
                rejected = replace(
                    current,
                    status="rejected",
                    rejection_reason=reason,
                    transition_id=_derived_transition_id(
                        current.authorization_id,
                        "rejected",
                        current.receipt_digest,
                    ),
                    prior_receipt_digest=current.receipt_digest,
                )
                self._append_locked(rejected)
                raise ExecutionAuthorizationRejected(
                    f"authorization claim rejected: {reason}"
                )
            claimed = replace(
                current,
                status="claimed",
                claim_owner_id=owner,
                lease_epoch=1,
                lease_expires_at=now + timedelta(seconds=lease),
                transition_id=_derived_transition_id(
                    current.authorization_id,
                    "claimed",
                    current.receipt_digest,
                ),
                prior_receipt_digest=current.receipt_digest,
            )
            self._append_locked(claimed)
            return claimed

    def transition(
        self,
        authorization_id: str,
        *,
        transition_id: str,
        idempotency_key: str,
        expected_status: str,
        target_status: str,
        owner_id: str,
        lease_epoch: int,
        prior_receipt_digest: str,
        metadata: Mapping[str, Any],
    ) -> OptionExecutionAuthorization:
        """Apply one explicit post-claim lifecycle transition.

        This is intentionally a receipt-only operation.  It does not reserve a
        process or create any product run; a later supervisor must consume the
        returned immutable state and perform any cross-journal reconciliation.
        """
        identifier = _identifier(authorization_id, "authorization_id")
        transition = _identifier(transition_id, "transition_id")
        key = _text(idempotency_key, "idempotency_key")
        expected = _text(expected_status, "expected_status")
        target = _text(target_status, "target_status")
        owner = _identifier(owner_id, "owner_id")
        epoch = _positive_int(lease_epoch, "lease_epoch")
        prior = _digest(prior_receipt_digest, "prior_receipt_digest")
        normalized_metadata = _transition_metadata(metadata)

        if expected not in _STATUSES or target not in _STATUSES:
            raise ExecutionAuthorizationTransitionError(
                "transition source or target status is unsupported"
            )
        if target not in _TRANSITIONS[expected]:
            raise ExecutionAuthorizationTransitionError(
                f"transition {expected} -> {target} is not permitted"
            )
        if target in {"invalidated", "dispatch_unknown", "failed"} and not dict(normalized_metadata).get("reason"):
            raise ExecutionAuthorizationTransitionError(
                f"{target} transition requires a bounded reason"
            )

        with self._lock, self._journal_lock():
            records = self._records()
            current = self._latest_by_id(records).get(identifier)
            if current is None:
                raise ExecutionAuthorizationRejected("authorization was not found")

            existing = next(
                (
                    record
                    for record in reversed(records)
                    if record.authorization_id == identifier
                    and record.transition_id == transition
                ),
                None,
            )
            if existing is not None:
                if (
                    existing.idempotency_key != key
                    or existing.status != target
                    or existing.prior_receipt_digest != prior
                    or existing.claim_owner_id != owner
                    or existing.lease_epoch != epoch
                    or existing.transition_metadata != normalized_metadata
                ):
                    raise ExecutionAuthorizationReplay(
                        "transition id is already bound to another receipt transition"
                    )
                return current

            if current.idempotency_key != key:
                raise ExecutionAuthorizationReplay(
                    "idempotency key does not match authorization"
                )
            if current.status != expected:
                raise ExecutionAuthorizationTransitionError(
                    f"transition expected {expected}, current status is {current.status}"
                )
            if current.receipt_digest != prior:
                raise ExecutionAuthorizationTransitionError(
                    "prior receipt digest does not match current receipt"
                )
            if current.claim_owner_id != owner or current.lease_epoch != epoch:
                raise ExecutionAuthorizationTransitionError(
                    "lease owner or lease epoch does not match current receipt"
                )
            if current.lease_expires_at is None:
                raise ExecutionAuthorizationTransitionError(
                    "current receipt has no lease expiry"
                )
            now = _utc(self._clock(), "clock")
            if now >= current.lease_expires_at and target not in {"dispatch_unknown", "failed"}:
                raise ExecutionAuthorizationTransitionError(
                    "lease expired before receipt transition"
                )
            reason = dict(normalized_metadata).get("reason")
            next_record = replace(
                current,
                status=target,
                rejection_reason=reason if target in {"invalidated", "dispatch_unknown", "failed"} else None,
                transition_id=transition,
                prior_receipt_digest=prior,
                transition_metadata=normalized_metadata,
            )
            self._append_locked(next_record)
            return next_record

    def take_over_lease(
        self,
        authorization_id: str,
        *,
        owner_id: str,
        transition_id: str,
        lease_seconds: int,
        reason: str,
    ) -> OptionExecutionAuthorization:
        """Recover the same authorization under a strictly newer lease epoch."""

        identifier = _identifier(authorization_id, "authorization_id")
        owner = _identifier(owner_id, "owner_id")
        transition = _identifier(transition_id, "transition_id")
        lease = _positive_int(lease_seconds, "lease_seconds")
        bounded_reason = _text(reason, "reason", maximum=_MAX_REASON)
        with self._lock, self._journal_lock():
            records = self._records()
            current = self._latest_by_id(records).get(identifier)
            if current is None:
                raise ExecutionAuthorizationRejected("authorization was not found")
            if current.status not in {"claimed", "dispatch_reserved", "running"}:
                raise ExecutionAuthorizationTransitionError(
                    f"lease takeover is not valid for authorization status {current.status}"
                )
            existing = next(
                (
                    record
                    for record in reversed(records)
                    if record.authorization_id == identifier
                    and record.transition_id == transition
                ),
                None,
            )
            if existing is not None:
                if (
                    existing.claim_owner_id != owner
                    or dict(existing.transition_metadata).get("reason") != bounded_reason
                ):
                    raise ExecutionAuthorizationReplay(
                        "lease takeover id is already bound to another owner or reason"
                    )
                return existing
            if current.lease_expires_at is None:
                raise ExecutionAuthorizationTransitionError("current receipt has no lease expiry")
            now = _utc(self._clock(), "clock")
            if now < current.lease_expires_at:
                raise ExecutionAuthorizationTransitionError("lease is still active")
            next_record = replace(
                current,
                claim_owner_id=owner,
                lease_epoch=(current.lease_epoch or 0) + 1,
                lease_expires_at=now + timedelta(seconds=lease),
                transition_id=transition,
                prior_receipt_digest=current.receipt_digest,
                rejection_reason=None,
                transition_metadata={"reason": bounded_reason},
            )
            self._append_locked(next_record)
            return next_record

    def _records(self) -> list[OptionExecutionAuthorization]:
        if not self.journal.exists():
            return []
        values = read_jsonl(self.journal)
        records: list[OptionExecutionAuthorization] = []
        for value in values:
            if set(value) != {"record_type", "authorization"}:
                raise ExecutionAuthorizationError("authorization journal record shape is invalid")
            if value["record_type"] != _RECORD_TYPE:
                raise ExecutionAuthorizationError("authorization journal record type is invalid")
            records.append(OptionExecutionAuthorization.from_dict(value["authorization"]))
        return records

    @staticmethod
    def _latest_by_id(
        records: list[OptionExecutionAuthorization],
    ) -> dict[str, OptionExecutionAuthorization]:
        latest: dict[str, OptionExecutionAuthorization] = {}
        for record in records:
            latest[record.authorization_id] = record
        return latest

    def _append_locked(self, authorization: OptionExecutionAuthorization) -> None:
        existing = self.journal.read_bytes() if self.journal.exists() else b""
        value = {"record_type": _RECORD_TYPE, "authorization": authorization.to_dict()}
        line = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(existing)
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.journal)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    @contextmanager
    def _journal_lock(self) -> Iterator[None]:
        lock_path = self.directory / f".{_JOURNAL_NAME}.lock"
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


__all__ = [
    "ExecutionAuthorizationError",
    "ExecutionAuthorizationInvalidated",
    "ExecutionAuthorizationReplay",
    "ExecutionAuthorizationRejected",
    "ExecutionAuthorizationTransitionError",
    "OPTION_EXECUTION_AUTHORIZATION_CONTRACT_VERSION",
    "OptionExecutionAuthorization",
    "OptionExecutionAuthorizationStore",
]
