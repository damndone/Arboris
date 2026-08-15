"""Server-owned materialization and provider-context egress contracts.

The egress boundary carries only opaque materialization references and digests.
The provider-facing receipt is issued only after the server materializer has
redacted and revalidated the actual payload.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from functools import wraps
from typing import Any

from workbench.canonical import CanonicalJSONError, canonical_json_v1, sha256_canonical
from workbench.contracts.common.contract_ref import ContractRefV1
from workbench.contracts.common.envelope import ContractError, freeze_json, thaw_json


EGRESS_SCHEMA_V1 = "context-egress-gateway.v1"
EGRESS_RECEIPT_SCHEMA_V1 = "context-egress-receipt.v1"
MATERIALIZATION_SCHEMA_V1 = "context-materialization-result.v1"
_MAX_JSON_SAFE_INTEGER = 9_007_199_254_740_991
_SHA256 = re.compile(r"[0-9a-f]{64}")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_ISSUED_RECEIPTS: dict[tuple[int, str], object] = {}
_MATERIALIZATION_ISSUANCES: dict[tuple[int, str], object] = {}


class EgressContractError(ContractError):
    """A provider-bound context boundary failure."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


class SensitivityClassV1(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


_SENSITIVITY_RANK = {
    SensitivityClassV1.PUBLIC: 0,
    SensitivityClassV1.INTERNAL: 1,
    SensitivityClassV1.RESTRICTED: 2,
    SensitivityClassV1.UNKNOWN: 3,
}
_SENSITIVE_KEY_MARKERS = (
    "secret",
    "password",
    "credential",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "private_key",
    "authorization",
    "email",
    "phone",
    "ssn",
    "address",
    "prompt",
    "instruction",
    "system_message",
    "user_message",
)
_SECRET_VALUE_MARKERS = ("raw:", "secret:", "token:", "bearer ", "sk-")


def _error(code: str, message: str) -> EgressContractError:
    return EgressContractError(code, message)


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        raise _error("EGRESS_TEXT_INVALID", f"{name} must be an exact non-empty string")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise _error("EGRESS_DIGEST_INVALID", f"{name} must be a lowercase SHA-256 digest")
    return value


def _timestamp(value: object, name: str) -> datetime:
    if type(value) is not str or not value or value != value.strip():
        raise _error("EGRESS_TIMESTAMP_INVALID", f"{name} must be timezone-aware")
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _error("EGRESS_TIMESTAMP_INVALID", f"{name} must be timezone-aware") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _error("EGRESS_TIMESTAMP_INVALID", f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _now(clock: Callable[[], datetime] | None, at: str | None = None) -> datetime:
    if at is not None:
        return _timestamp(at, "at")
    current = datetime.now(UTC) if clock is None else clock()
    if type(current) is not datetime or current.tzinfo is None or current.utcoffset() is None:
        raise _error("EGRESS_CLOCK_INVALID", "clock must return an aware datetime")
    return current.astimezone(UTC)


def _policy_ref(value: object) -> ContractRefV1:
    if type(value) is not ContractRefV1:
        raise _error("EGRESS_POLICY_INVALID", "policy_ref must be ContractRefV1")
    return value


def _parse_policy_ref(value: object) -> ContractRefV1:
    if type(value) is not dict:
        raise _error("EGRESS_NESTED_DICT_REQUIRED", "policy ref must be a built-in dict")
    try:
        return ContractRefV1.from_dict(value)
    except (AttributeError, CanonicalJSONError, ContractError, RecursionError, TypeError, ValueError) as exc:
        raise _error("EGRESS_POLICY_INVALID", "policy ref is invalid") from exc


def _parse_sensitivity(value: object) -> SensitivityClassV1:
    if type(value) is not str:
        raise _error("EGRESS_SENSITIVITY_INVALID", "sensitivity is invalid")
    try:
        return SensitivityClassV1(value)
    except ValueError as exc:
        raise _error("EGRESS_SENSITIVITY_INVALID", "sensitivity is invalid") from exc


def _refs(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise _error("EGRESS_ARRAY_INVALID", f"{name} must be an array")
    normalized = tuple(_text(item, f"{name}[]") for item in value)
    if len(set(normalized)) != len(normalized):
        raise _error("EGRESS_DUPLICATE_REF", f"{name} contains duplicate refs")
    return normalized


def _wire_refs(value: object, name: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise _error("EGRESS_ARRAY_INVALID", f"{name} must be a built-in list")
    return _refs(value, name)


def _validate_json(value: object, name: str, active: set[int] | None = None) -> None:
    if value is None or type(value) in {str, bool}:
        return
    if type(value) is int:
        if not -_MAX_JSON_SAFE_INTEGER <= value <= _MAX_JSON_SAFE_INTEGER:
            raise _error("EGRESS_CONTEXT_INVALID", f"{name} contains a nonportable integer")
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise _error("EGRESS_CONTEXT_INVALID", f"{name} contains a non-finite number")
        return
    if not isinstance(value, (Mapping, list, tuple)):
        raise _error("EGRESS_CONTEXT_INVALID", f"{name} contains an unsupported value")
    active_ids = active if active is not None else set()
    value_id = id(value)
    if value_id in active_ids:
        raise _error("EGRESS_CONTEXT_INVALID", f"{name} must be acyclic JSON")
    active_ids.add(value_id)
    try:
        if isinstance(value, Mapping):
            if any(type(key) is not str for key in value):
                raise _error("EGRESS_CONTEXT_INVALID", f"{name} keys must be strings")
            children = value.values()
        else:
            children = value
        for child in children:
            _validate_json(child, f"{name}[]", active_ids)
    finally:
        active_ids.remove(value_id)


def _frozen_mapping(value: object, name: str) -> Mapping[str, Any]:
    if type(value) is not dict:
        raise _error("EGRESS_NESTED_DICT_REQUIRED", f"{name} must be a built-in dict")
    _validate_json(value, name)
    try:
        canonical_json_v1(value)
        frozen = freeze_json(value, name)
    except (AttributeError, CanonicalJSONError, ContractError, RecursionError, OverflowError, TypeError, ValueError) as exc:
        raise _error("EGRESS_CONTEXT_INVALID", f"{name} must be canonical JSON") from exc
    if not isinstance(frozen, Mapping):
        raise _error("EGRESS_CONTEXT_INVALID", f"{name} must be an object")
    return frozen


def _plain(value: object) -> object:
    try:
        return thaw_json(value)
    except (AttributeError, CanonicalJSONError, ContractError, RecursionError, TypeError, ValueError) as exc:
        raise _error("EGRESS_CONTEXT_INVALID", "context is not safely serializable") from exc


def _budget(value: object, name: str) -> int:
    if type(value) is not int or not 0 < value <= _MAX_JSON_SAFE_INTEGER:
        raise _error("EGRESS_BUDGET_INVALID", f"{name} must be a positive JSON-safe integer")
    return value


def _wire(value: object, required: set[str], name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise _error("EGRESS_NESTED_DICT_REQUIRED", f"{name} must be a built-in dict")
    if any(type(key) is not str for key in value) or set(value) != required:
        raise _error("EGRESS_SCHEMA_INVALID", f"{name} fields are not exact")
    return value


def _wire_boundary(function):
    @wraps(function)
    def wrapped(cls, value):
        try:
            return function(cls, value)
        except EgressContractError:
            raise
        except (AttributeError, CanonicalJSONError, ContractError, RecursionError, TypeError, ValueError) as exc:
            raise _error("EGRESS_WIRE_INVALID", "egress wire value is invalid") from exc

    return wrapped


def _classify_and_redact(value: object, path: str = "context") -> tuple[object, SensitivityClassV1, tuple[str, ...]]:
    """Deterministically redact PII/secret-like leaves and report evidence."""

    if isinstance(value, Mapping):
        output: dict[str, object] = {}
        observed = SensitivityClassV1.PUBLIC
        redacted: list[str] = []
        for key, child in value.items():
            lowered = key.casefold()
            sensitive_key = any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS)
            if sensitive_key:
                output[key] = "[REDACTED]"
                redacted.append(f"field:{path}.{key}")
                observed = SensitivityClassV1.RESTRICTED
                continue
            redacted_child, child_sensitivity, child_refs = _classify_and_redact(child, f"{path}.{key}")
            output[key] = redacted_child
            redacted.extend(child_refs)
            if _SENSITIVITY_RANK[child_sensitivity] > _SENSITIVITY_RANK[observed]:
                observed = child_sensitivity
        return output, observed, tuple(redacted)
    if type(value) is list:
        values: list[object] = []
        observed = SensitivityClassV1.PUBLIC
        redacted: list[str] = []
        for index, child in enumerate(value):
            redacted_child, child_sensitivity, child_refs = _classify_and_redact(child, f"{path}[{index}]")
            values.append(redacted_child)
            redacted.extend(child_refs)
            if _SENSITIVITY_RANK[child_sensitivity] > _SENSITIVITY_RANK[observed]:
                observed = child_sensitivity
        return values, observed, tuple(redacted)
    if type(value) is tuple:
        values: list[object] = []
        observed = SensitivityClassV1.PUBLIC
        redacted: list[str] = []
        for index, child in enumerate(value):
            redacted_child, child_sensitivity, child_refs = _classify_and_redact(child, f"{path}[{index}]")
            values.append(redacted_child)
            redacted.extend(child_refs)
            if _SENSITIVITY_RANK[child_sensitivity] > _SENSITIVITY_RANK[observed]:
                observed = child_sensitivity
        return tuple(values), observed, tuple(redacted)
    if type(value) is str:
        lowered = value.casefold()
        if _EMAIL.fullmatch(value) or any(lowered.startswith(marker) for marker in _SECRET_VALUE_MARKERS):
            return "[REDACTED]", SensitivityClassV1.RESTRICTED, (f"value:{path}",)
    return value, SensitivityClassV1.PUBLIC, ()


@dataclass(frozen=True)
class ContextMaterializationResultV1:
    """Opaque server materializer result; raw source context never crosses the seam."""

    result_ref: str
    materializer_ref: ContractRefV1
    redaction_policy_ref: ContractRefV1
    selected_refs: tuple[str, ...]
    redacted_refs: tuple[str, ...]
    observed_sensitivity: SensitivityClassV1
    materialized_context_digest: str
    materialized_payload_digest: str
    materialized_context: Mapping[str, Any]
    _issuer_token: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _text(self.result_ref, "result_ref")
        if type(self.materializer_ref) is not ContractRefV1 or type(self.redaction_policy_ref) is not ContractRefV1:
            raise _error("EGRESS_MATERIALIZER_REF_INVALID", "materializer and redaction refs are invalid")
        object.__setattr__(self, "selected_refs", _refs(self.selected_refs, "selected_refs"))
        object.__setattr__(self, "redacted_refs", _refs(self.redacted_refs, "redacted_refs"))
        if type(self.observed_sensitivity) is not SensitivityClassV1:
            raise _error("EGRESS_SENSITIVITY_INVALID", "observed sensitivity is invalid")
        object.__setattr__(self, "materialized_context", _frozen_mapping(dict(_plain(self.materialized_context)), "materialized_context"))
        actual = sha256_canonical(_plain(self.materialized_context))
        _digest(self.materialized_context_digest, "materialized_context_digest")
        _digest(self.materialized_payload_digest, "materialized_payload_digest")
        if self.materialized_context_digest != actual or self.materialized_payload_digest != actual:
            raise _error("EGRESS_MATERIALIZATION_DIGEST_MISMATCH", "materializer result digest does not match payload")

    @property
    def reference(self) -> str:
        return self.result_ref

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": MATERIALIZATION_SCHEMA_V1,
            "result_ref": self.result_ref,
            "materializer_ref": self.materializer_ref.to_dict(),
            "redaction_policy_ref": self.redaction_policy_ref.to_dict(),
            "selected_refs": list(self.selected_refs),
            "redacted_refs": list(self.redacted_refs),
            "observed_sensitivity": self.observed_sensitivity.value,
            "materialized_context_digest": self.materialized_context_digest,
            "materialized_payload_digest": self.materialized_payload_digest,
        }


class ContextMaterializationStoreV1:
    """Server-owned deterministic materializer and result store."""

    def __init__(self, *, materializer_ref: ContractRefV1, redaction_policy_ref: ContractRefV1) -> None:
        if type(materializer_ref) is not ContractRefV1 or type(redaction_policy_ref) is not ContractRefV1:
            raise _error("EGRESS_MATERIALIZER_REF_INVALID", "server materializer refs are required")
        self.materializer_ref = materializer_ref
        self.redaction_policy_ref = redaction_policy_ref
        self._issuer_token = object()
        self._results: dict[str, ContextMaterializationResultV1] = {}

    def materialize(self, context: dict[str, object], *, selected_refs: tuple[str, ...]) -> ContextMaterializationResultV1:
        if type(context) is not dict:
            raise _error("EGRESS_NESTED_DICT_REQUIRED", "source context must be a built-in dict")
        _validate_json(context, "source_context")
        try:
            canonical_json_v1(context)
        except (AttributeError, CanonicalJSONError, RecursionError, TypeError, ValueError) as exc:
            raise _error("EGRESS_CONTEXT_INVALID", "source context must be canonical JSON") from exc
        selected = _refs(selected_refs, "selected_refs")
        if not selected:
            raise _error("EGRESS_SELECTION_INVALID", "selected_refs must not be empty")
        if any(ref not in context for ref in selected):
            raise _error("EGRESS_SELECTION_INVALID", "every selected ref must resolve in the source context")
        unselected = set(context).difference(selected)
        if unselected:
            raise _error(
                "EGRESS_UNSELECTED_CONTENT_FORBIDDEN",
                "source context contains fields that were not selected",
            )
        selected_context = {ref: context[ref] for ref in selected}
        redacted, observed, redacted_refs = _classify_and_redact(selected_context)
        frozen = _frozen_mapping(redacted, "materialized_context")
        digest = sha256_canonical(_plain(frozen))
        result = ContextMaterializationResultV1(
            result_ref=f"materialization:{len(self._results) + 1}",
            materializer_ref=self.materializer_ref,
            redaction_policy_ref=self.redaction_policy_ref,
            selected_refs=selected,
            redacted_refs=redacted_refs,
            observed_sensitivity=observed,
            materialized_context_digest=digest,
            materialized_payload_digest=digest,
            materialized_context=frozen,
            _issuer_token=self._issuer_token,
        )
        self._results[result.result_ref] = result
        _MATERIALIZATION_ISSUANCES[(id(self._issuer_token), result.result_ref)] = result
        return result

    @classmethod
    def is_server_issued(cls, result: object) -> bool:
        return (
            type(result) is ContextMaterializationResultV1
            and result._issuer_token is not None
            and _MATERIALIZATION_ISSUANCES.get((id(result._issuer_token), result.result_ref)) is result
        )

    def resolve(self, result_ref: str) -> ContextMaterializationResultV1:
        if type(result_ref) is not str:
            raise _error("EGRESS_MATERIALIZATION_AUTHORITY_REQUIRED", "materialization ref is invalid")
        result = self._results.get(result_ref)
        if result is None or result._issuer_token is not self._issuer_token or not self.is_server_issued(result):
            raise _error("EGRESS_MATERIALIZATION_AUTHORITY_REQUIRED", "materialization result is not server-owned")
        actual = sha256_canonical(_plain(result.materialized_context))
        if actual != result.materialized_payload_digest or actual != result.materialized_context_digest:
            raise _error("EGRESS_MATERIALIZATION_DIGEST_MISMATCH", "stored materialization payload changed")
        return result


@dataclass(frozen=True)
class ContextEgressPolicyV1:
    policy_ref: ContractRefV1
    destination: str
    provider_ref: str
    allowed_sensitivity: tuple[SensitivityClassV1, ...]
    max_token_budget: int
    max_row_budget: int
    max_time_budget_ms: int
    allow_raw_rows: bool = False
    allow_raw_secrets: bool = False

    def __post_init__(self) -> None:
        _policy_ref(self.policy_ref)
        if self.destination not in {"local", "remote"}:
            raise _error("EGRESS_DESTINATION_INVALID", "destination must be local or remote")
        _text(self.provider_ref, "provider_ref")
        if not isinstance(self.allowed_sensitivity, (tuple, list)) or not self.allowed_sensitivity:
            raise _error("EGRESS_POLICY_INVALID", "allowed_sensitivity must not be empty")
        sensitivity = tuple(self.allowed_sensitivity)
        if any(type(item) is not SensitivityClassV1 for item in sensitivity):
            raise _error("EGRESS_POLICY_INVALID", "allowed_sensitivity contains an invalid value")
        object.__setattr__(self, "allowed_sensitivity", sensitivity)
        _budget(self.max_token_budget, "max_token_budget")
        _budget(self.max_row_budget, "max_row_budget")
        _budget(self.max_time_budget_ms, "max_time_budget_ms")
        if type(self.allow_raw_rows) is not bool or type(self.allow_raw_secrets) is not bool:
            raise _error("EGRESS_BOOLEAN_INVALID", "raw-content policy values must be exact booleans")
        if self.destination == "remote" and (self.allow_raw_rows or self.allow_raw_secrets):
            raise _error("EGRESS_RAW_CONTENT_FORBIDDEN", "remote policy cannot allow raw rows or secrets")

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_ref": self.policy_ref.to_dict(),
            "destination": self.destination,
            "provider_ref": self.provider_ref,
            "allowed_sensitivity": [item.value for item in self.allowed_sensitivity],
            "max_token_budget": self.max_token_budget,
            "max_row_budget": self.max_row_budget,
            "max_time_budget_ms": self.max_time_budget_ms,
            "allow_raw_rows": self.allow_raw_rows,
            "allow_raw_secrets": self.allow_raw_secrets,
        }

    @classmethod
    @_wire_boundary
    def from_dict(cls, value: dict[str, object]) -> "ContextEgressPolicyV1":
        value = _wire(
            value,
            {
                "policy_ref", "destination", "provider_ref", "allowed_sensitivity",
                "max_token_budget", "max_row_budget", "max_time_budget_ms",
                "allow_raw_rows", "allow_raw_secrets",
            },
            "egress_policy",
        )
        raw_ref = value["policy_ref"]
        raw_sensitivity = value["allowed_sensitivity"]
        if type(raw_ref) is not dict or type(raw_sensitivity) is not list:
            raise _error("EGRESS_NESTED_DICT_REQUIRED", "policy nested values must be built-in containers")
        return cls(
            policy_ref=_parse_policy_ref(raw_ref),
            destination=value["destination"],  # type: ignore[arg-type]
            provider_ref=value["provider_ref"],  # type: ignore[arg-type]
            allowed_sensitivity=tuple(_parse_sensitivity(item) for item in raw_sensitivity),
            max_token_budget=value["max_token_budget"],  # type: ignore[arg-type]
            max_row_budget=value["max_row_budget"],  # type: ignore[arg-type]
            max_time_budget_ms=value["max_time_budget_ms"],  # type: ignore[arg-type]
            allow_raw_rows=value["allow_raw_rows"],  # type: ignore[arg-type]
            allow_raw_secrets=value["allow_raw_secrets"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class ContextEgressGatewayV1:
    request_id: str
    destination: str
    provider_ref: str
    sensitivity_policy_ref: ContractRefV1
    sensitivity: SensitivityClassV1
    selected_refs: tuple[str, ...]
    redacted_refs: tuple[str, ...]
    token_budget: int
    row_budget: int
    time_budget_ms: int
    purpose_ref: str
    materialization_result_ref: str
    materialized_context_digest: str
    requested_at: str
    expires_at: str

    def __post_init__(self) -> None:
        _text(self.request_id, "request_id")
        if self.destination not in {"local", "remote"}:
            raise _error("EGRESS_DESTINATION_INVALID", "destination must be local or remote")
        _text(self.provider_ref, "provider_ref")
        _policy_ref(self.sensitivity_policy_ref)
        if type(self.sensitivity) is not SensitivityClassV1:
            raise _error("EGRESS_SENSITIVITY_INVALID", "sensitivity is invalid")
        selected = _refs(self.selected_refs, "selected_refs")
        redacted = _refs(self.redacted_refs, "redacted_refs")
        if any(ref.casefold().startswith(("raw:", "secret:", "prompt:")) for ref in selected):
            raise _error("EGRESS_RAW_CONTENT_FORBIDDEN", "raw secrets and prompts cannot be selected")
        if set(selected).intersection(redacted):
            raise _error("EGRESS_SELECTION_INVALID", "a ref cannot be both selected and redacted")
        object.__setattr__(self, "selected_refs", selected)
        object.__setattr__(self, "redacted_refs", redacted)
        _budget(self.token_budget, "token_budget")
        _budget(self.row_budget, "row_budget")
        _budget(self.time_budget_ms, "time_budget_ms")
        _text(self.purpose_ref, "purpose_ref")
        _text(self.materialization_result_ref, "materialization_result_ref")
        _digest(self.materialized_context_digest, "materialized_context_digest")
        requested = _timestamp(self.requested_at, "requested_at")
        expires = _timestamp(self.expires_at, "expires_at")
        if expires <= requested:
            raise _error("EGRESS_EXPIRY_INVALID", "expires_at must be after requested_at")

    @classmethod
    def from_materialization_result(
        cls,
        result: ContextMaterializationResultV1,
        *,
        request_id: str,
        destination: str,
        provider_ref: str,
        sensitivity_policy_ref: ContractRefV1,
        sensitivity: SensitivityClassV1,
        token_budget: int,
        row_budget: int,
        time_budget_ms: int,
        purpose_ref: str,
        requested_at: str,
        expires_at: str,
    ) -> "ContextEgressGatewayV1":
        if type(result) is not ContextMaterializationResultV1 or not ContextMaterializationStoreV1.is_server_issued(result):
            raise _error("EGRESS_MATERIALIZATION_AUTHORITY_REQUIRED", "gateway requires a server materialization result")
        return cls(
            request_id=request_id,
            destination=destination,
            provider_ref=provider_ref,
            sensitivity_policy_ref=sensitivity_policy_ref,
            sensitivity=sensitivity,
            selected_refs=result.selected_refs,
            redacted_refs=result.redacted_refs,
            token_budget=token_budget,
            row_budget=row_budget,
            time_budget_ms=time_budget_ms,
            purpose_ref=purpose_ref,
            materialization_result_ref=result.result_ref,
            materialized_context_digest=result.materialized_payload_digest,
            requested_at=requested_at,
            expires_at=expires_at,
        )

    @classmethod
    def from_materialized_context(cls, **_: object) -> "ContextEgressGatewayV1":
        raise _error(
            "EGRESS_MATERIALIZATION_AUTHORITY_REQUIRED",
            "direct caller materialized context is not an authority; use server materializer result",
        )

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": EGRESS_SCHEMA_V1,
            "request_id": self.request_id,
            "destination": self.destination,
            "provider_ref": self.provider_ref,
            "sensitivity_policy_ref": self.sensitivity_policy_ref.to_dict(),
            "sensitivity": self.sensitivity.value,
            "selected_refs": list(self.selected_refs),
            "redacted_refs": list(self.redacted_refs),
            "token_budget": self.token_budget,
            "row_budget": self.row_budget,
            "time_budget_ms": self.time_budget_ms,
            "purpose_ref": self.purpose_ref,
            "materialization_result_ref": self.materialization_result_ref,
            "materialized_context_digest": self.materialized_context_digest,
            "requested_at": self.requested_at,
            "expires_at": self.expires_at,
        }

    @property
    def request_digest(self) -> str:
        return sha256_canonical(self._payload())

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        payload = self._payload()
        if include_digest:
            payload["request_digest"] = self.request_digest
        return payload

    @classmethod
    @_wire_boundary
    def from_dict(cls, value: dict[str, object]) -> "ContextEgressGatewayV1":
        value = _wire(
            value,
            {
                "schema_version", "request_id", "destination", "provider_ref", "sensitivity_policy_ref",
                "sensitivity", "selected_refs", "redacted_refs", "token_budget", "row_budget",
                "time_budget_ms", "purpose_ref", "materialization_result_ref", "materialized_context_digest",
                "requested_at", "expires_at", "request_digest",
            },
            "egress_gateway",
        )
        if value["schema_version"] != EGRESS_SCHEMA_V1:
            raise _error("EGRESS_SCHEMA_INVALID", "gateway schema_version is invalid")
        raw_policy = value["sensitivity_policy_ref"]
        if type(raw_policy) is not dict:
            raise _error("EGRESS_NESTED_DICT_REQUIRED", "sensitivity_policy_ref must be a built-in dict")
        gateway = cls(
            request_id=value["request_id"],  # type: ignore[arg-type]
            destination=value["destination"],  # type: ignore[arg-type]
            provider_ref=value["provider_ref"],  # type: ignore[arg-type]
            sensitivity_policy_ref=_parse_policy_ref(raw_policy),
            sensitivity=_parse_sensitivity(value["sensitivity"]),
            selected_refs=_wire_refs(value["selected_refs"], "selected_refs"),
            redacted_refs=_wire_refs(value["redacted_refs"], "redacted_refs"),
            token_budget=value["token_budget"],  # type: ignore[arg-type]
            row_budget=value["row_budget"],  # type: ignore[arg-type]
            time_budget_ms=value["time_budget_ms"],  # type: ignore[arg-type]
            purpose_ref=value["purpose_ref"],  # type: ignore[arg-type]
            materialization_result_ref=value["materialization_result_ref"],  # type: ignore[arg-type]
            materialized_context_digest=value["materialized_context_digest"],  # type: ignore[arg-type]
            requested_at=value["requested_at"],  # type: ignore[arg-type]
            expires_at=value["expires_at"],  # type: ignore[arg-type]
        )
        if value["request_digest"] != gateway.request_digest:
            raise _error("EGRESS_DIGEST_MISMATCH", "request_digest does not match gateway fields")
        return gateway


@dataclass(frozen=True)
class ContextEgressReceiptV1:
    receipt_id: str
    gateway_request_digest: str
    destination: str
    provider_ref: str
    sensitivity_policy_ref: ContractRefV1
    sensitivity: SensitivityClassV1
    selected_refs: tuple[str, ...]
    redacted_refs: tuple[str, ...]
    token_budget: int
    row_budget: int
    time_budget_ms: int
    purpose_ref: str
    materialization_result_ref: str
    materialized_context_digest: str
    materialized_payload_digest: str
    issued_at: str
    expires_at: str
    _issuer_token: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _text(self.receipt_id, "receipt_id")
        _digest(self.gateway_request_digest, "gateway_request_digest")
        if self.destination not in {"local", "remote"}:
            raise _error("EGRESS_DESTINATION_INVALID", "destination must be local or remote")
        _text(self.provider_ref, "provider_ref")
        _policy_ref(self.sensitivity_policy_ref)
        if type(self.sensitivity) is not SensitivityClassV1:
            raise _error("EGRESS_SENSITIVITY_INVALID", "sensitivity is invalid")
        object.__setattr__(self, "selected_refs", _refs(self.selected_refs, "selected_refs"))
        object.__setattr__(self, "redacted_refs", _refs(self.redacted_refs, "redacted_refs"))
        _budget(self.token_budget, "token_budget")
        _budget(self.row_budget, "row_budget")
        _budget(self.time_budget_ms, "time_budget_ms")
        _text(self.purpose_ref, "purpose_ref")
        _text(self.materialization_result_ref, "materialization_result_ref")
        _digest(self.materialized_context_digest, "materialized_context_digest")
        _digest(self.materialized_payload_digest, "materialized_payload_digest")
        if self.materialized_context_digest != self.materialized_payload_digest:
            raise _error("EGRESS_MATERIALIZATION_DIGEST_MISMATCH", "receipt context and payload digests differ")
        issued = _timestamp(self.issued_at, "issued_at")
        expires = _timestamp(self.expires_at, "expires_at")
        if expires <= issued:
            raise _error("EGRESS_EXPIRY_INVALID", "expires_at must be after issued_at")

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": EGRESS_RECEIPT_SCHEMA_V1,
            "receipt_id": self.receipt_id,
            "gateway_request_digest": self.gateway_request_digest,
            "destination": self.destination,
            "provider_ref": self.provider_ref,
            "sensitivity_policy_ref": self.sensitivity_policy_ref.to_dict(),
            "sensitivity": self.sensitivity.value,
            "selected_refs": list(self.selected_refs),
            "redacted_refs": list(self.redacted_refs),
            "token_budget": self.token_budget,
            "row_budget": self.row_budget,
            "time_budget_ms": self.time_budget_ms,
            "purpose_ref": self.purpose_ref,
            "materialization_result_ref": self.materialization_result_ref,
            "materialized_context_digest": self.materialized_context_digest,
            "materialized_payload_digest": self.materialized_payload_digest,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }

    @property
    def receipt_digest(self) -> str:
        return sha256_canonical(self._payload())

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "receipt_digest": self.receipt_digest}

    @classmethod
    @_wire_boundary
    def from_dict(cls, value: dict[str, object]) -> "ContextEgressReceiptV1":
        value = _wire(
            value,
            {
                "schema_version", "receipt_id", "gateway_request_digest", "destination", "provider_ref",
                "sensitivity_policy_ref", "sensitivity", "selected_refs", "redacted_refs", "token_budget",
                "row_budget", "time_budget_ms", "purpose_ref", "materialization_result_ref",
                "materialized_context_digest", "materialized_payload_digest", "issued_at", "expires_at",
                "receipt_digest",
            },
            "egress_receipt",
        )
        if value["schema_version"] != EGRESS_RECEIPT_SCHEMA_V1:
            raise _error("EGRESS_SCHEMA_INVALID", "receipt schema_version is invalid")
        raw_policy = value["sensitivity_policy_ref"]
        if type(raw_policy) is not dict:
            raise _error("EGRESS_NESTED_DICT_REQUIRED", "receipt policy ref must be a built-in dict")
        receipt = cls(
            receipt_id=value["receipt_id"],  # type: ignore[arg-type]
            gateway_request_digest=value["gateway_request_digest"],  # type: ignore[arg-type]
            destination=value["destination"],  # type: ignore[arg-type]
            provider_ref=value["provider_ref"],  # type: ignore[arg-type]
            sensitivity_policy_ref=_parse_policy_ref(raw_policy),
            sensitivity=_parse_sensitivity(value["sensitivity"]),
            selected_refs=_wire_refs(value["selected_refs"], "selected_refs"),
            redacted_refs=_wire_refs(value["redacted_refs"], "redacted_refs"),
            token_budget=value["token_budget"],  # type: ignore[arg-type]
            row_budget=value["row_budget"],  # type: ignore[arg-type]
            time_budget_ms=value["time_budget_ms"],  # type: ignore[arg-type]
            purpose_ref=value["purpose_ref"],  # type: ignore[arg-type]
            materialization_result_ref=value["materialization_result_ref"],  # type: ignore[arg-type]
            materialized_context_digest=value["materialized_context_digest"],  # type: ignore[arg-type]
            materialized_payload_digest=value["materialized_payload_digest"],  # type: ignore[arg-type]
            issued_at=value["issued_at"],  # type: ignore[arg-type]
            expires_at=value["expires_at"],  # type: ignore[arg-type]
        )
        if value["receipt_digest"] != receipt.receipt_digest:
            raise _error("EGRESS_DIGEST_MISMATCH", "receipt_digest does not match receipt fields")
        return receipt


class ContextEgressReceiptIssuerV1:
    """Server policy issuer and verifier for provider-sendable receipts."""

    def __init__(
        self,
        policy: ContextEgressPolicyV1,
        *,
        materializer_store: ContextMaterializationStoreV1 | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if type(policy) is not ContextEgressPolicyV1:
            raise _error("EGRESS_POLICY_REQUIRED", "a server egress policy is required")
        if materializer_store is not None and type(materializer_store) is not ContextMaterializationStoreV1:
            raise _error("EGRESS_MATERIALIZER_REQUIRED", "materializer store is invalid")
        self.policy = policy
        self.materializer_store = materializer_store
        self.clock = clock
        self._issuer_token = object()
        self._receipts: dict[str, ContextEgressReceiptV1] = {}

    def _check_gateway(self, gateway: ContextEgressGatewayV1, *, at: str | None = None) -> ContextMaterializationResultV1:
        if type(gateway) is not ContextEgressGatewayV1:
            raise _error("EGRESS_GATEWAY_REQUIRED", "provider context must pass through the gateway")
        if self.materializer_store is None:
            raise _error("EGRESS_MATERIALIZATION_AUTHORITY_REQUIRED", "egress issuer requires a server materializer store")
        result = self.materializer_store.resolve(gateway.materialization_result_ref)
        if gateway.sensitivity_policy_ref != self.policy.policy_ref:
            raise _error("EGRESS_POLICY_MISMATCH", "gateway policy ref does not match server policy")
        if gateway.destination != self.policy.destination or gateway.provider_ref != self.policy.provider_ref:
            raise _error("EGRESS_SCOPE_MISMATCH", "destination/provider is outside the declared policy")
        if gateway.sensitivity not in self.policy.allowed_sensitivity:
            raise _error("EGRESS_SENSITIVITY_DENIED", "sensitivity is outside the declared policy")
        if _SENSITIVITY_RANK[gateway.sensitivity] < _SENSITIVITY_RANK[result.observed_sensitivity]:
            raise _error("EGRESS_SENSITIVITY_CONFLICT", "declared sensitivity is lower than materializer observation")
        if gateway.selected_refs != result.selected_refs or gateway.redacted_refs != result.redacted_refs:
            raise _error("EGRESS_MATERIALIZATION_SCOPE_MISMATCH", "gateway refs differ from materializer result")
        if gateway.materialized_context_digest != result.materialized_payload_digest:
            raise _error("EGRESS_MATERIALIZATION_DIGEST_MISMATCH", "receipt/gateway digest differs from actual materialized payload")
        if gateway.token_budget > self.policy.max_token_budget or gateway.row_budget > self.policy.max_row_budget or gateway.time_budget_ms > self.policy.max_time_budget_ms:
            raise _error("EGRESS_BUDGET_EXCEEDED", "egress budget exceeds policy")
        current = _now(self.clock, at)
        requested = _timestamp(gateway.requested_at, "requested_at")
        expires = _timestamp(gateway.expires_at, "expires_at")
        if current < requested:
            raise _error("EGRESS_NOT_YET_VALID", "egress request is not yet valid")
        if current >= expires:
            raise _error("EGRESS_EXPIRED", "egress request is expired")
        return result

    def issue(self, gateway: ContextEgressGatewayV1, *, at: str | None = None) -> ContextEgressReceiptV1:
        result = self._check_gateway(gateway, at=at)
        issued_at = _now(self.clock, at).isoformat()
        receipt = ContextEgressReceiptV1(
            receipt_id=f"egress-receipt:{gateway.request_id}",
            gateway_request_digest=gateway.request_digest,
            destination=gateway.destination,
            provider_ref=gateway.provider_ref,
            sensitivity_policy_ref=gateway.sensitivity_policy_ref,
            sensitivity=gateway.sensitivity,
            selected_refs=gateway.selected_refs,
            redacted_refs=gateway.redacted_refs,
            token_budget=gateway.token_budget,
            row_budget=gateway.row_budget,
            time_budget_ms=gateway.time_budget_ms,
            purpose_ref=gateway.purpose_ref,
            materialization_result_ref=result.result_ref,
            materialized_context_digest=result.materialized_context_digest,
            materialized_payload_digest=result.materialized_payload_digest,
            issued_at=issued_at,
            expires_at=gateway.expires_at,
            _issuer_token=self._issuer_token,
        )
        self._receipts[receipt.receipt_digest] = receipt
        _ISSUED_RECEIPTS[(id(self._issuer_token), receipt.receipt_digest)] = receipt
        return receipt

    def require(self, gateway: ContextEgressGatewayV1, receipt: ContextEgressReceiptV1, *, at: str | None = None) -> None:
        result = self._check_gateway(gateway, at=at)
        if type(receipt) is not ContextEgressReceiptV1:
            raise _error("EGRESS_RECEIPT_REQUIRED", "provider context requires an egress receipt")
        if receipt._issuer_token is not self._issuer_token or self._receipts.get(receipt.receipt_digest) is not receipt:
            raise _error("EGRESS_RECEIPT_REQUIRED", "receipt was not issued by this egress policy")
        if receipt.gateway_request_digest != gateway.request_digest:
            raise _error("EGRESS_DIGEST_MISMATCH", "receipt does not match gateway request")
        if (
            receipt.destination != gateway.destination
            or receipt.provider_ref != gateway.provider_ref
            or receipt.sensitivity_policy_ref != gateway.sensitivity_policy_ref
            or receipt.sensitivity is not gateway.sensitivity
            or receipt.selected_refs != gateway.selected_refs
            or receipt.redacted_refs != gateway.redacted_refs
            or receipt.token_budget != gateway.token_budget
            or receipt.row_budget != gateway.row_budget
            or receipt.time_budget_ms != gateway.time_budget_ms
            or receipt.purpose_ref != gateway.purpose_ref
            or receipt.materialization_result_ref != result.result_ref
            or receipt.materialized_context_digest != result.materialized_context_digest
            or receipt.materialized_payload_digest != result.materialized_payload_digest
        ):
            raise _error("EGRESS_SCOPE_MISMATCH", "receipt scope or materialized payload digest mismatches")
        current = _now(self.clock, at)
        issued = _timestamp(receipt.issued_at, "issued_at")
        expires = _timestamp(receipt.expires_at, "expires_at")
        if current < issued:
            raise _error("EGRESS_NOT_YET_VALID", "egress receipt is not yet valid")
        if current >= expires:
            raise _error("EGRESS_EXPIRED", "egress receipt is expired")


def require_context_egress_receipt(
    gateway: ContextEgressGatewayV1,
    receipt: object,
    *,
    issuer: ContextEgressReceiptIssuerV1 | None = None,
    at: str | None = None,
) -> ContextEgressReceiptV1:
    if type(gateway) is not ContextEgressGatewayV1 or type(receipt) is not ContextEgressReceiptV1:
        raise _error("EGRESS_RECEIPT_REQUIRED", "provider context requires an egress receipt")
    if type(issuer) is not ContextEgressReceiptIssuerV1:
        raise _error(
            "EGRESS_SERVER_ISSUER_REQUIRED",
            "provider context receipt verification requires the current server egress issuer",
        )
    issuer.require(gateway, receipt, at=at)
    return receipt


__all__ = [
    "ContextEgressGatewayV1",
    "ContextEgressPolicyV1",
    "ContextEgressReceiptIssuerV1",
    "ContextEgressReceiptV1",
    "ContextMaterializationResultV1",
    "ContextMaterializationStoreV1",
    "EGRESS_RECEIPT_SCHEMA_V1",
    "EGRESS_SCHEMA_V1",
    "EgressContractError",
    "MATERIALIZATION_SCHEMA_V1",
    "SensitivityClassV1",
    "require_context_egress_receipt",
]
