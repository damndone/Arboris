"""One-release holdout seal and server-owned append-only access ledger."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any

from workbench.canonical import CanonicalJSONError, sha256_canonical
from workbench.contracts.common.envelope import ContractError, freeze_json, thaw_json


HOLDOUT_SCHEMA_V1 = "holdout-seal.v1"
_SHA256 = set("0123456789abcdef")
_REQUIRED_DEVELOPMENT_HASHES = frozenset(
    {
        "code", "config", "contract", "data", "split", "feature_recipe",
        "candidate_search", "calibration", "threshold", "decision_policy",
    }
)


class HoldoutContractError(ContractError):
    """A holdout state or ledger boundary failure."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


class HoldoutSealStatusV1(str, Enum):
    SEALED = "sealed"
    RELEASED = "released"
    CLOSED = "closed"


class HoldoutAccessKindV1(str, Enum):
    DECLARED_EVALUATION = "declared_evaluation"
    REPEAT_EVALUATION = "repeat_evaluation"
    PARTIAL_METRIC = "partial_metric"
    SUBGROUP_QUERY = "subgroup_query"
    SHIFT_QUERY = "shift_query"
    AD_HOC_QUERY = "ad_hoc_query"
    REOPEN_ATTEMPT = "reopen_attempt"


def _error(code: str, message: str) -> HoldoutContractError:
    return HoldoutContractError(code, message)


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        raise _error("HOLDOUT_TEXT_INVALID", f"{name} must be an exact non-empty string")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in _SHA256 for char in value):
        raise _error("HOLDOUT_DIGEST_INVALID", f"{name} must be a lowercase SHA-256 digest")
    return value


def _refs(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise _error("HOLDOUT_ARRAY_INVALID", f"{name} must be an array")
    refs = tuple(_text(item, f"{name}[]") for item in value)
    if len(set(refs)) != len(refs):
        raise _error("HOLDOUT_DUPLICATE_REF", f"{name} contains duplicate refs")
    return refs


def _parse_access_kind(value: object) -> HoldoutAccessKindV1:
    if type(value) is not str:
        raise _error("HOLDOUT_ENUM_INVALID", "kind is invalid")
    try:
        return HoldoutAccessKindV1(value)
    except ValueError as exc:
        raise _error("HOLDOUT_ENUM_INVALID", "kind is invalid") from exc


def _parse_status(value: object) -> HoldoutSealStatusV1:
    if type(value) is not str:
        raise _error("HOLDOUT_ENUM_INVALID", "status is invalid")
    try:
        return HoldoutSealStatusV1(value)
    except ValueError as exc:
        raise _error("HOLDOUT_ENUM_INVALID", "status is invalid") from exc


def _wire(value: object, required: set[str], name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise _error("HOLDOUT_NESTED_DICT_REQUIRED", f"{name} must be a built-in dict")
    if any(type(key) is not str for key in value) or set(value) != required:
        raise _error("HOLDOUT_SCHEMA_INVALID", f"{name} fields are not exact")
    return value


def _wire_boundary(function):
    @wraps(function)
    def wrapped(cls, value):
        try:
            return function(cls, value)
        except HoldoutContractError:
            raise
        except (AttributeError, CanonicalJSONError, ContractError, RecursionError, TypeError, ValueError) as exc:
            raise _error("HOLDOUT_WIRE_INVALID", "holdout wire value is invalid") from exc

    return wrapped


def _frozen_hashes(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise _error("HOLDOUT_NESTED_DICT_REQUIRED", "development_hashes must be a mapping")
    if any(type(key) is not str for key in value):
        raise _error("HOLDOUT_HASH_SET_INVALID", "development_hashes keys must be strings")
    keys = set(value)
    if keys != _REQUIRED_DEVELOPMENT_HASHES:
        missing = _REQUIRED_DEVELOPMENT_HASHES - keys
        extra = keys - _REQUIRED_DEVELOPMENT_HASHES
        raise _error("HOLDOUT_HASH_SET_INVALID", f"development_hashes exact set required; missing={sorted(missing)} extra={sorted(extra)}")
    normalized = {key: _digest(item, f"development_hashes.{key}") for key, item in value.items()}
    try:
        return freeze_json(normalized, "development_hashes")
    except (AttributeError, CanonicalJSONError, ContractError, RecursionError, TypeError, ValueError) as exc:
        raise _error("HOLDOUT_HASH_SET_INVALID", "development_hashes are not safely serializable") from exc


@dataclass(frozen=True)
class HoldoutAccessRequestV1:
    access_id: str
    principal_ref: str
    kind: HoldoutAccessKindV1
    metric_refs: tuple[str, ...]
    metric_bundle_digest: str

    def __post_init__(self) -> None:
        _text(self.access_id, "access_id")
        _text(self.principal_ref, "principal_ref")
        if type(self.kind) is not HoldoutAccessKindV1:
            raise _error("HOLDOUT_ENUM_INVALID", "kind is invalid")
        object.__setattr__(self, "metric_refs", _refs(self.metric_refs, "metric_refs"))
        if not self.metric_refs:
            raise _error("HOLDOUT_METRICS_REQUIRED", "metric_refs must not be empty")
        _digest(self.metric_bundle_digest, "metric_bundle_digest")

    @property
    def request_digest(self) -> str:
        return sha256_canonical(
            {
                "access_id": self.access_id,
                "principal_ref": self.principal_ref,
                "kind": self.kind.value,
                "metric_refs": list(self.metric_refs),
                "metric_bundle_digest": self.metric_bundle_digest,
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "access_id": self.access_id,
            "principal_ref": self.principal_ref,
            "kind": self.kind.value,
            "metric_refs": list(self.metric_refs),
            "metric_bundle_digest": self.metric_bundle_digest,
            "request_digest": self.request_digest,
        }

    @classmethod
    @_wire_boundary
    def from_dict(cls, value: dict[str, object]) -> "HoldoutAccessRequestV1":
        value = _wire(value, {"access_id", "principal_ref", "kind", "metric_refs", "metric_bundle_digest", "request_digest"}, "holdout_access_request")
        raw_metrics = value["metric_refs"]
        if type(raw_metrics) is not list:
            raise _error("HOLDOUT_ARRAY_INVALID", "metric_refs must be a built-in list")
        request = cls(
            access_id=value["access_id"],  # type: ignore[arg-type]
            principal_ref=value["principal_ref"],  # type: ignore[arg-type]
            kind=_parse_access_kind(value["kind"]),
            metric_refs=_refs(raw_metrics, "metric_refs"),
            metric_bundle_digest=value["metric_bundle_digest"],  # type: ignore[arg-type]
        )
        if value["request_digest"] != request.request_digest:
            raise _error("HOLDOUT_DIGEST_MISMATCH", "request_digest does not match access request")
        return request


@dataclass(frozen=True)
class HoldoutAccessLedgerEntryV1:
    access_id: str
    principal_ref: str
    kind: HoldoutAccessKindV1
    metric_refs: tuple[str, ...]
    metric_bundle_digest: str
    request_digest: str
    decision: str
    reason_code: str
    state_before: HoldoutSealStatusV1
    state_after: HoldoutSealStatusV1

    def __post_init__(self) -> None:
        _text(self.access_id, "access_id")
        _text(self.principal_ref, "principal_ref")
        if type(self.kind) is not HoldoutAccessKindV1:
            raise _error("HOLDOUT_ENUM_INVALID", "kind is invalid")
        object.__setattr__(self, "metric_refs", _refs(self.metric_refs, "metric_refs"))
        _digest(self.metric_bundle_digest, "metric_bundle_digest")
        _digest(self.request_digest, "request_digest")
        expected = sha256_canonical(
            {
                "access_id": self.access_id,
                "principal_ref": self.principal_ref,
                "kind": self.kind.value,
                "metric_refs": list(self.metric_refs),
                "metric_bundle_digest": self.metric_bundle_digest,
            }
        )
        if self.request_digest != expected:
            raise _error("HOLDOUT_DIGEST_MISMATCH", "ledger request_digest does not match request fields")
        if self.decision not in {"allowed", "rejected"}:
            raise _error("HOLDOUT_DECISION_INVALID", "decision is invalid")
        _text(self.reason_code, "reason_code")
        if type(self.state_before) is not HoldoutSealStatusV1 or type(self.state_after) is not HoldoutSealStatusV1:
            raise _error("HOLDOUT_ENUM_INVALID", "ledger state is invalid")

    @classmethod
    def from_request(cls, request: HoldoutAccessRequestV1, *, decision: str, reason_code: str, state_before: HoldoutSealStatusV1, state_after: HoldoutSealStatusV1) -> "HoldoutAccessLedgerEntryV1":
        return cls(
            access_id=request.access_id,
            principal_ref=request.principal_ref,
            kind=request.kind,
            metric_refs=request.metric_refs,
            metric_bundle_digest=request.metric_bundle_digest,
            request_digest=request.request_digest,
            decision=decision,
            reason_code=reason_code,
            state_before=state_before,
            state_after=state_after,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "access_id": self.access_id,
            "principal_ref": self.principal_ref,
            "kind": self.kind.value,
            "metric_refs": list(self.metric_refs),
            "metric_bundle_digest": self.metric_bundle_digest,
            "request_digest": self.request_digest,
            "decision": self.decision,
            "reason_code": self.reason_code,
            "state_before": self.state_before.value,
            "state_after": self.state_after.value,
        }

    @classmethod
    @_wire_boundary
    def from_dict(cls, value: dict[str, object]) -> "HoldoutAccessLedgerEntryV1":
        value = _wire(
            value,
            {"access_id", "principal_ref", "kind", "metric_refs", "metric_bundle_digest", "request_digest", "decision", "reason_code", "state_before", "state_after"},
            "holdout_ledger_entry",
        )
        raw_metrics = value["metric_refs"]
        if type(raw_metrics) is not list:
            raise _error("HOLDOUT_ARRAY_INVALID", "ledger metric_refs must be a built-in list")
        return cls(
            access_id=value["access_id"],  # type: ignore[arg-type]
            principal_ref=value["principal_ref"],  # type: ignore[arg-type]
            kind=_parse_access_kind(value["kind"]),
            metric_refs=_refs(raw_metrics, "metric_refs"),
            metric_bundle_digest=value["metric_bundle_digest"],  # type: ignore[arg-type]
            request_digest=value["request_digest"],  # type: ignore[arg-type]
            decision=value["decision"],  # type: ignore[arg-type]
            reason_code=value["reason_code"],  # type: ignore[arg-type]
            state_before=_parse_status(value["state_before"]),
            state_after=_parse_status(value["state_after"]),
        )


@dataclass(frozen=True)
class HoldoutReleaseDecisionV1:
    allowed: bool
    reason_code: str
    seal: "HoldoutSealV1"

    def __post_init__(self) -> None:
        if type(self.allowed) is not bool:
            raise _error("HOLDOUT_BOOLEAN_INVALID", "allowed must be an exact boolean")
        _text(self.reason_code, "reason_code")
        if type(self.seal) is not HoldoutSealV1:
            raise _error("HOLDOUT_SEAL_INVALID", "decision seal is invalid")


@dataclass(frozen=True)
class HoldoutSealV1:
    seal_id: str
    principal_ref: str
    development_hashes: Mapping[str, str]
    metric_release_bundle_ref: str
    metric_bundle_digest: str
    metric_refs: tuple[str, ...]
    status: str = HoldoutSealStatusV1.SEALED.value
    transition_history: tuple[str, ...] = (HoldoutSealStatusV1.SEALED.value,)
    access_ledger: tuple[HoldoutAccessLedgerEntryV1, ...] = ()
    _issuer_token: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _text(self.seal_id, "seal_id")
        _text(self.principal_ref, "principal_ref")
        object.__setattr__(self, "development_hashes", _frozen_hashes(self.development_hashes))
        _text(self.metric_release_bundle_ref, "metric_release_bundle_ref")
        _digest(self.metric_bundle_digest, "metric_bundle_digest")
        object.__setattr__(self, "metric_refs", _refs(self.metric_refs, "metric_refs"))
        if not self.metric_refs:
            raise _error("HOLDOUT_METRICS_REQUIRED", "metric_refs must not be empty")
        current_status = _parse_status(self.status)
        history = tuple(self.transition_history)
        if not history or history[0] != HoldoutSealStatusV1.SEALED.value:
            raise _error("HOLDOUT_STATE_INVALID", "holdout history must start at sealed")
        history_statuses = tuple(_parse_status(item) for item in history)
        if history_statuses[-1] is not current_status:
            raise _error("HOLDOUT_STATE_INVALID", "current status must equal transition history tail")
        if current_status is HoldoutSealStatusV1.SEALED and history_statuses != (HoldoutSealStatusV1.SEALED,):
            raise _error("HOLDOUT_STATE_INVALID", "sealed state cannot have a release history")
        if current_status is HoldoutSealStatusV1.RELEASED and history_statuses != (HoldoutSealStatusV1.SEALED, HoldoutSealStatusV1.RELEASED):
            raise _error("HOLDOUT_STATE_INVALID", "released state must follow sealed")
        if current_status is HoldoutSealStatusV1.CLOSED and history_statuses != (HoldoutSealStatusV1.SEALED, HoldoutSealStatusV1.RELEASED, HoldoutSealStatusV1.CLOSED):
            raise _error("HOLDOUT_STATE_INVALID", "closed state must follow a recorded release")
        object.__setattr__(self, "transition_history", tuple(status.value for status in history_statuses))
        if not isinstance(self.access_ledger, (tuple, list)):
            raise _error("HOLDOUT_ARRAY_INVALID", "access_ledger must be an array")
        ledger = tuple(self.access_ledger)
        if any(type(entry) is not HoldoutAccessLedgerEntryV1 for entry in ledger):
            raise _error("HOLDOUT_LEDGER_INVALID", "access_ledger contains an invalid entry")
        if len({entry.access_id for entry in ledger}) != len(ledger):
            raise _error("HOLDOUT_DUPLICATE_ACCESS", "access_ledger access IDs must be unique")
        object.__setattr__(self, "access_ledger", ledger)

    @property
    def seal_digest(self) -> str:
        return sha256_canonical(
            {
                "seal_id": self.seal_id,
                "principal_ref": self.principal_ref,
                "development_hashes": dict(self.development_hashes),
                "metric_release_bundle_ref": self.metric_release_bundle_ref,
                "metric_bundle_digest": self.metric_bundle_digest,
                "metric_refs": list(self.metric_refs),
            }
        )

    @property
    def state_digest(self) -> str:
        return sha256_canonical(
            {
                "seal_digest": self.seal_digest,
                "status": self.status,
                "transition_history": list(self.transition_history),
                "access_ledger": [entry.to_dict() for entry in self.access_ledger],
            }
        )

    def authorize_access(self, request: HoldoutAccessRequestV1) -> HoldoutReleaseDecisionV1:
        if type(request) is not HoldoutAccessRequestV1:
            raise _error("HOLDOUT_REQUEST_REQUIRED", "holdout access requires a typed request")
        before = _parse_status(self.status)
        allowed = False
        reason = "HOLDOUT_LEDGER_CLOSED"
        after = before
        if request.principal_ref != self.principal_ref:
            reason = "HOLDOUT_PRINCIPAL_SCOPE_MISMATCH"
        elif before is not HoldoutSealStatusV1.SEALED:
            reason = "HOLDOUT_LEDGER_CLOSED"
        elif request.metric_bundle_digest != self.metric_bundle_digest:
            reason = "HOLDOUT_METRIC_BUNDLE_MISMATCH"
        elif request.kind is not HoldoutAccessKindV1.DECLARED_EVALUATION:
            reason = {
                HoldoutAccessKindV1.REPEAT_EVALUATION: "HOLDOUT_REPEAT_FORBIDDEN",
                HoldoutAccessKindV1.PARTIAL_METRIC: "HOLDOUT_PARTIAL_METRIC_FORBIDDEN",
                HoldoutAccessKindV1.SUBGROUP_QUERY: "HOLDOUT_SUBGROUP_NOT_DECLARED",
                HoldoutAccessKindV1.SHIFT_QUERY: "HOLDOUT_SHIFT_NOT_DECLARED",
                HoldoutAccessKindV1.AD_HOC_QUERY: "HOLDOUT_AD_HOC_FORBIDDEN",
                HoldoutAccessKindV1.REOPEN_ATTEMPT: "HOLDOUT_REOPEN_FORBIDDEN",
                HoldoutAccessKindV1.DECLARED_EVALUATION: "HOLDOUT_REQUEST_INVALID",
            }[request.kind]
        elif request.metric_refs != self.metric_refs:
            reason = "HOLDOUT_METRIC_BUNDLE_MISMATCH"
        else:
            allowed = True
            reason = "HOLDOUT_RELEASE_ALLOWED"
            after = HoldoutSealStatusV1.CLOSED
        entry = HoldoutAccessLedgerEntryV1.from_request(
            request,
            decision="allowed" if allowed else "rejected",
            reason_code=reason,
            state_before=before,
            state_after=after,
        )
        next_history = self.transition_history
        if allowed:
            next_history = (HoldoutSealStatusV1.SEALED.value, HoldoutSealStatusV1.RELEASED.value, HoldoutSealStatusV1.CLOSED.value)
        next_seal = HoldoutSealV1(
            seal_id=self.seal_id,
            principal_ref=self.principal_ref,
            development_hashes=dict(self.development_hashes),
            metric_release_bundle_ref=self.metric_release_bundle_ref,
            metric_bundle_digest=self.metric_bundle_digest,
            metric_refs=self.metric_refs,
            status=after.value,
            transition_history=next_history,
            access_ledger=(*self.access_ledger, entry),
            _issuer_token=self._issuer_token,
        )
        return HoldoutReleaseDecisionV1(allowed=allowed, reason_code=reason, seal=next_seal)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": HOLDOUT_SCHEMA_V1,
            "seal_id": self.seal_id,
            "principal_ref": self.principal_ref,
            "development_hashes": dict(self.development_hashes),
            "metric_release_bundle_ref": self.metric_release_bundle_ref,
            "metric_bundle_digest": self.metric_bundle_digest,
            "metric_refs": list(self.metric_refs),
            "status": self.status,
            "transition_history": list(self.transition_history),
            "access_ledger": [entry.to_dict() for entry in self.access_ledger],
            "seal_digest": self.seal_digest,
            "state_digest": self.state_digest,
        }

    @classmethod
    @_wire_boundary
    def from_dict(cls, value: dict[str, object]) -> "HoldoutSealV1":
        value = _wire(
            value,
            {"schema_version", "seal_id", "principal_ref", "development_hashes", "metric_release_bundle_ref", "metric_bundle_digest", "metric_refs", "status", "transition_history", "access_ledger", "seal_digest", "state_digest"},
            "holdout_seal",
        )
        if value["schema_version"] != HOLDOUT_SCHEMA_V1:
            raise _error("HOLDOUT_SCHEMA_INVALID", "holdout schema_version is invalid")
        raw_hashes = value["development_hashes"]
        raw_metrics = value["metric_refs"]
        raw_history = value["transition_history"]
        raw_ledger = value["access_ledger"]
        if type(raw_hashes) is not dict or type(raw_metrics) is not list or type(raw_history) is not list or type(raw_ledger) is not list:
            raise _error("HOLDOUT_NESTED_DICT_REQUIRED", "holdout nested values must be built-in containers")
        if any(type(item) is not dict for item in raw_ledger):
            raise _error("HOLDOUT_NESTED_DICT_REQUIRED", "ledger entries must be built-in dicts")
        seal = cls(
            seal_id=value["seal_id"],  # type: ignore[arg-type]
            principal_ref=value["principal_ref"],  # type: ignore[arg-type]
            development_hashes=raw_hashes,
            metric_release_bundle_ref=value["metric_release_bundle_ref"],  # type: ignore[arg-type]
            metric_bundle_digest=value["metric_bundle_digest"],  # type: ignore[arg-type]
            metric_refs=_refs(raw_metrics, "metric_refs"),
            status=value["status"],  # type: ignore[arg-type]
            transition_history=tuple(raw_history),  # type: ignore[arg-type]
            access_ledger=tuple(HoldoutAccessLedgerEntryV1.from_dict(item) for item in raw_ledger),
        )
        if value["seal_digest"] != seal.seal_digest or value["state_digest"] != seal.state_digest:
            raise _error("HOLDOUT_DIGEST_MISMATCH", "holdout seal or state digest does not match")
        return seal


@dataclass(frozen=True, init=False)
class ServerHoldoutSealReferenceV1:
    seal_id: str
    state_digest: str
    _issuer_token: object

    @classmethod
    def _issue(cls, seal: HoldoutSealV1, token: object) -> "ServerHoldoutSealReferenceV1":
        value = object.__new__(cls)
        object.__setattr__(value, "seal_id", seal.seal_id)
        object.__setattr__(value, "state_digest", seal.state_digest)
        object.__setattr__(value, "_issuer_token", token)
        return value

    def to_dict(self) -> dict[str, str]:
        return {"seal_id": self.seal_id, "state_digest": self.state_digest}


class HoldoutSealStoreV1:
    """Server-owned one-time consume/CAS seam for holdout releases."""

    def __init__(self) -> None:
        self._issuer_token = object()
        self._current: dict[str, HoldoutSealV1] = {}

    def issue(self, seal: HoldoutSealV1) -> ServerHoldoutSealReferenceV1:
        if type(seal) is not HoldoutSealV1:
            raise _error("HOLDOUT_SERVER_SEAL_REQUIRED", "store issue requires a typed seal")
        if seal.seal_id in self._current:
            raise _error("HOLDOUT_DUPLICATE_SEAL", "seal is already issued by this store")
        object.__setattr__(seal, "_issuer_token", self._issuer_token)
        self._current[seal.seal_id] = seal
        return ServerHoldoutSealReferenceV1._issue(seal, self._issuer_token)

    def resolve(self, reference: ServerHoldoutSealReferenceV1) -> HoldoutSealV1:
        if type(reference) is not ServerHoldoutSealReferenceV1 or reference._issuer_token is not self._issuer_token:
            raise _error("HOLDOUT_SERVER_REFERENCE_REQUIRED", "holdout consume requires a server-owned reference")
        seal = self._current.get(reference.seal_id)
        if seal is None:
            raise _error("HOLDOUT_SERVER_SEAL_UNRESOLVED", "server holdout seal is unavailable")
        return seal

    def consume(self, reference: ServerHoldoutSealReferenceV1, request: HoldoutAccessRequestV1) -> HoldoutReleaseDecisionV1:
        if type(request) is not HoldoutAccessRequestV1:
            raise _error("HOLDOUT_REQUEST_REQUIRED", "holdout consume requires a typed request")
        current = self.resolve(reference)
        if reference.state_digest != current.state_digest:
            before = _parse_status(current.status)
            if any(entry.access_id == request.access_id for entry in current.access_ledger):
                raise _error("HOLDOUT_DUPLICATE_ACCESS", "access id is already in the append-only ledger")
            entry = HoldoutAccessLedgerEntryV1.from_request(
                request,
                decision="rejected",
                reason_code="HOLDOUT_STALE_STATE",
                state_before=before,
                state_after=before,
            )
            denied = HoldoutSealV1(
                seal_id=current.seal_id,
                principal_ref=current.principal_ref,
                development_hashes=dict(current.development_hashes),
                metric_release_bundle_ref=current.metric_release_bundle_ref,
                metric_bundle_digest=current.metric_bundle_digest,
                metric_refs=current.metric_refs,
                status=current.status,
                transition_history=current.transition_history,
                access_ledger=(*current.access_ledger, entry),
                _issuer_token=self._issuer_token,
            )
            self._current[current.seal_id] = denied
            return HoldoutReleaseDecisionV1(allowed=False, reason_code="HOLDOUT_STALE_STATE", seal=denied)
        decision = current.authorize_access(request)
        self._current[current.seal_id] = decision.seal
        return decision


__all__ = [
    "HOLDOUT_SCHEMA_V1",
    "HoldoutAccessKindV1",
    "HoldoutAccessLedgerEntryV1",
    "HoldoutAccessRequestV1",
    "HoldoutContractError",
    "HoldoutReleaseDecisionV1",
    "HoldoutSealStatusV1",
    "HoldoutSealStoreV1",
    "HoldoutSealV1",
    "ServerHoldoutSealReferenceV1",
]
