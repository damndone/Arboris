"""Package-local, sensitivity-aware data context contribution.

This module only projects a bounded data profile into the existing C0 context
materialization and egress contracts.  It does not send data, compile
instructions, or mint operation/capability references.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from workbench.canonical import canonical_json_v1, sha256_canonical
from workbench.contracts.agent.context_egress import (
    ContextEgressGatewayV1 as C0ContextEgressGatewayV1,
    ContextEgressPolicyV1 as C0ContextEgressPolicyV1,
    ContextEgressReceiptIssuerV1 as C0ContextEgressReceiptIssuerV1,
    ContextEgressReceiptV1 as C0ContextEgressReceiptV1,
    ContextMaterializationStoreV1,
    EgressContractError,
    SensitivityClassV1,
    require_context_egress_receipt,
)
from workbench.contracts.common.contract_ref import ContractRefV1, canonical_contract_digest
from workbench.contracts.common.envelope import ContractError


DATA_CONTEXT_SCHEMA_V1 = "data-context-egress.v1"
DATA_CONTEXT_POLICY_VERSION_V1 = "1.0"
DATA_CONTEXT_RECEIPT_SCHEMA_V1 = "data-context-egress-receipt.v1"

_SAFE_ROLES = frozenset(
    {"actual", "feature", "group", "id", "prediction", "target", "time", "weight"}
)
_ROLE_ALIASES = {"identifier": "id", "outcome": "target", "response": "target"}
_AGGREGATE_FIELDS = ("count", "min", "max", "mean", "std")
_SENSITIVITY_MARKERS = (
    "access_token",
    "account_id",
    "api_key",
    "apikey",
    "authorization",
    "customer_id",
    "credential",
    "email",
    "password",
    "phone",
    "private_key",
    "secret",
    "ssn",
    "user_id",
)
_OPAQUE_REF_RE = re.compile(r"[a-z0-9]+(?:[-.:/][a-z0-9]+)*")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_DATASET_IDENTITY_FIELDS = (
    "run_id",
    "node_id",
    "artifact_id",
    "content_sha256",
    "schema_revision",
    "metadata_revision",
)


class DataContextEgressError(ContractError):
    """A fail-closed package-local data context boundary error."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


def _error(code: str, message: str) -> DataContextEgressError:
    return DataContextEgressError(code, message)


def _read(value: object, key: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _first(value: object, *keys: str) -> object:
    for key in keys:
        direct = _read(value, key, None)
        if direct is not None:
            return direct
    for nested_name in ("observed", "declared", "inferred", "metadata"):
        nested = _read(value, nested_name, None)
        if nested is None:
            continue
        for key in keys:
            nested_value = _read(nested, key, None)
            if nested_value is not None:
                return nested_value
    return None


def _bounded_text(value: object, name: str, limit: int) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise _error("DATA_PROFILE_INVALID", f"{name} must be a non-empty string")
    if len(value) <= limit:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    prefix_length = max(1, limit - len(digest) - 1)
    return f"{value[:prefix_length]}-{digest}"[:limit]


def _digest_ref(value: object) -> str:
    if isinstance(value, str):
        payload = value
    else:
        payload = repr(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _server_owned_dataset_identity(profile: object) -> dict[str, str]:
    """Require the immutable dataset identity carried by a server profile."""

    raw = _read(profile, "dataset_ref", None)
    if raw is None or isinstance(raw, (str, bytes, ContractRefV1)):
        raise _error(
            "DATA_PROFILE_IDENTITY_INVALID",
            "data context requires a server-owned dataset identity",
        )
    identity: dict[str, str] = {}
    for field_name in _DATASET_IDENTITY_FIELDS:
        value = _read(raw, field_name, None)
        if type(value) is not str or not value or value != value.strip() or "\x00" in value:
            raise _error(
                "DATA_PROFILE_IDENTITY_INVALID",
                f"dataset identity field dataset_ref.{field_name} is invalid",
            )
        identity[field_name] = value
    if _SHA256_RE.fullmatch(identity["content_sha256"]) is None:
        raise _error(
            "DATA_PROFILE_IDENTITY_INVALID",
            "dataset_ref.content_sha256 must be a lowercase SHA-256 digest",
        )
    return identity


def _opaque(prefix: str, *parts: object) -> str:
    material = "-".join(_digest_ref(part)[:16] for part in parts)
    value = f"{prefix}{material}"
    if _OPAQUE_REF_RE.fullmatch(value) is None:
        raise _error("DATA_EGRESS_REFERENCE_INVALID", "derived context reference is not opaque")
    return value


def _contract_ref(kind: str, logical_id: str, payload: Mapping[str, object] | None = None) -> ContractRefV1:
    contract_payload: dict[str, object] = {
        "kind": kind,
        "logical_id": logical_id,
        "version": DATA_CONTEXT_POLICY_VERSION_V1,
    }
    if payload:
        contract_payload["policy"] = dict(payload)
    return ContractRefV1(
        kind=kind,
        logical_id=logical_id,
        semantic_version=DATA_CONTEXT_POLICY_VERSION_V1,
        contract_digest=canonical_contract_digest(contract_payload),
    )


def _positive_int(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise _error("DATA_POLICY_INVALID", f"{name} must be a positive integer")
    return value


def _bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise _error("DATA_POLICY_INVALID", f"{name} must be a boolean")
    return value


def _finite_number(value: object) -> int | float | None:
    if value is None:
        return None
    if type(value) is bool or type(value) not in {int, float}:
        return None
    if type(value) is float and not math.isfinite(value):
        return None
    return value


def _sensitivity(value: object) -> SensitivityClassV1:
    if isinstance(value, SensitivityClassV1):
        return value
    if type(value) is not str:
        return SensitivityClassV1.UNKNOWN
    normalized = value.casefold().strip()
    if normalized in {"sensitive", "pii", "secret"}:
        return SensitivityClassV1.RESTRICTED
    try:
        return SensitivityClassV1(normalized)
    except ValueError:
        return SensitivityClassV1.UNKNOWN


def _roles(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        values: Sequence[object] = (value,)
    elif isinstance(value, (list, tuple, set, frozenset)):
        values = tuple(value)
    else:
        return ()
    result: list[str] = []
    for item in values:
        if type(item) is not str:
            continue
        role = _ROLE_ALIASES.get(item.casefold().strip(), item.casefold().strip())
        if role in _SAFE_ROLES and role not in result:
            result.append(role)
    return tuple(result)


def _dtype(value: object) -> str:
    if type(value) is not str:
        return "scalar"
    lowered = value.casefold()
    if "bool" in lowered:
        return "boolean"
    if "int" in lowered:
        return "integer"
    if any(token in lowered for token in ("float", "double", "decimal", "number")):
        return "number"
    if any(token in lowered for token in ("id", "uuid", "reference")):
        return "reference"
    return "scalar"


def _aggregate(value: object) -> dict[str, int | float | None]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int | float | None] = {}
    for field_name in _AGGREGATE_FIELDS:
        item = _finite_number(value.get(field_name))
        if item is not None:
            result[field_name] = item
    return result


@dataclass(frozen=True)
class _Column:
    name: str
    sensitivity: SensitivityClassV1
    direct_identifier: bool
    roles: tuple[str, ...]
    dtype: str
    aggregates: Mapping[str, int | float | None]
    ref: str


def _column_specs(profile: object) -> list[tuple[str | None, object]]:
    raw = _read(profile, "columns", None)
    if raw is None:
        raw = _read(profile, "schema", None)
    if isinstance(raw, Mapping):
        return [(key if type(key) is str else None, value) for key, value in raw.items()]
    if isinstance(raw, (list, tuple)):
        return [(None, value) for value in raw]
    raise _error("DATA_PROFILE_INVALID", "profile columns must be a mapping or list")


def _normalize_columns(profile: object, dataset_digest: str, max_string_length: int) -> tuple[_Column, ...]:
    profile_aggregates = _read(profile, "aggregates", {})
    if not isinstance(profile_aggregates, Mapping):
        profile_aggregates = {}
    columns: list[_Column] = []
    seen: set[str] = set()
    for mapping_name, spec in _column_specs(profile):
        if isinstance(spec, str):
            candidate_name: object = spec
            spec = {}
        else:
            candidate_name = _first(spec, "name", "column", "column_name", "label")
        if candidate_name is None:
            candidate_name = mapping_name
        if type(candidate_name) is not str or not candidate_name:
            raise _error("DATA_PROFILE_INVALID", "every column needs a name")
        name = _bounded_text(candidate_name, "column name", max_string_length)
        if name in seen:
            raise _error("DATA_PROFILE_INVALID", "profile contains duplicate column names")
        seen.add(name)

        sensitivity = _sensitivity(_first(spec, "sensitivity", "sensitivity_class"))
        role_values = _first(spec, "role_candidates", "roles")
        if role_values is None:
            inferred = _read(spec, "inferred", None)
            role_values = _first(inferred, "role_candidates", "roles")
        roles = _roles(role_values)
        lowered_name = name.casefold()
        direct_identifier = bool(_first(spec, "direct_identifier", "is_identifier"))
        direct_identifier = direct_identifier or "id" in roles
        direct_identifier = direct_identifier or any(marker in lowered_name for marker in _SENSITIVITY_MARKERS)

        aggregate_value = _first(spec, "aggregates", "aggregate")
        if aggregate_value is None:
            aggregate_value = profile_aggregates.get(candidate_name, profile_aggregates.get(name))
        aggregate = _aggregate(aggregate_value)
        columns.append(
            _Column(
                name=name,
                sensitivity=sensitivity,
                direct_identifier=direct_identifier,
                roles=roles,
                dtype=_dtype(_first(spec, "dtype", "type")),
                aggregates=aggregate,
                ref=_opaque("column:", dataset_digest, name),
            )
        )
    if not columns:
        raise _error("DATA_PROFILE_INVALID", "profile must contain at least one column")
    return tuple(columns)


def _profile_digest(profile: object, dataset_ref: str, row_count: int, columns: Sequence[_Column], available_rows: int) -> str:
    payload = {
        "dataset_ref": dataset_ref,
        "row_count": row_count,
        "available_rows": available_rows,
        "columns": [
            {
                "name": column.name,
                "sensitivity": column.sensitivity.value,
                "direct_identifier": column.direct_identifier,
                "roles": list(column.roles),
                "dtype": column.dtype,
                "aggregates": dict(column.aggregates),
            }
            for column in columns
        ],
    }
    del profile
    return sha256_canonical(payload)


@dataclass(frozen=True, init=False)
class ContextEgressPolicyV1:
    """Typed package-local policy that composes into the C0 policy seam."""

    destination: str
    provider_ref: str
    policy_ref: ContractRefV1
    max_items: int
    max_string_length: int
    max_token_budget: int
    max_row_budget: int
    max_time_budget_ms: int
    allow_raw_rows: bool
    allow_sensitive_columns: bool
    allow_unknown_columns: bool
    allow_direct_identifiers: bool
    allow_free_text: bool
    allowed_sections: tuple[str, ...]
    confirmation_required: bool

    def __init__(
        self,
        destination: str,
        *,
        provider_ref: str = "provider:data-context",
        policy_ref: ContractRefV1 | None = None,
        max_items: int = 128,
        max_string_length: int = 128,
        max_token_budget: int = 4096,
        max_row_budget: int = 128,
        max_time_budget_ms: int = 5000,
        allow_raw_rows: bool = False,
        allow_sensitive_columns: bool = False,
        allow_unknown_columns: bool = False,
        allow_direct_identifiers: bool = False,
        allow_free_text: bool = False,
        allowed_sections: Sequence[str] | None = None,
        confirmation_required: bool = True,
        allow_sensitive: bool | None = None,
        allow_unknown: bool | None = None,
    ) -> None:
        if destination not in {"local", "remote"}:
            raise _error("DATA_POLICY_INVALID", "destination must be local or remote")
        if type(provider_ref) is not str or not provider_ref.startswith("provider:"):
            raise _error("DATA_POLICY_INVALID", "provider_ref must be a typed provider reference")
        if allow_sensitive is not None:
            allow_sensitive_columns = allow_sensitive
        if allow_unknown is not None:
            allow_unknown_columns = allow_unknown
        for name, value in (
            ("allow_raw_rows", allow_raw_rows),
            ("allow_sensitive_columns", allow_sensitive_columns),
            ("allow_unknown_columns", allow_unknown_columns),
            ("allow_direct_identifiers", allow_direct_identifiers),
            ("allow_free_text", allow_free_text),
            ("confirmation_required", confirmation_required),
        ):
            _bool(value, name)
        if allow_free_text:
            raise _error(
                "DATA_POLICY_UNSUPPORTED",
                "C0 does not support free-text materialization; the policy fails closed",
            )
        if not confirmation_required:
            raise _error(
                "DATA_CONFIRMATION_REQUIRED",
                "data context overrides require the confirmation gate",
            )
        if any(
            (allow_sensitive_columns, allow_unknown_columns, allow_direct_identifiers)
        ):
            raise _error(
                "DATA_POLICY_UNSUPPORTED",
                "sensitive, unknown, and direct-identifier overrides are not open in v1",
            )
        if destination == "remote" and any(
            (
                allow_raw_rows,
                allow_sensitive_columns,
                allow_unknown_columns,
                allow_direct_identifiers,
            )
        ):
            raise _error("DATA_REMOTE_RAW_CONTENT_FORBIDDEN", "remote policy cannot relax raw or sensitive defaults")
        if allowed_sections is None:
            sections = ["schema", "aggregates", "role_candidates"]
            if destination == "local" and allow_raw_rows:
                sections.append("raw_rows")
        else:
            sections = list(allowed_sections)
        allowed = {"schema", "aggregates", "role_candidates", "raw_rows"}
        if not sections or any(type(item) is not str or item not in allowed for item in sections):
            raise _error("DATA_POLICY_INVALID", "allowed_sections contains an unsupported section")
        if len(set(sections)) != len(sections):
            raise _error("DATA_POLICY_INVALID", "allowed_sections contains duplicates")
        if destination == "remote" and "raw_rows" in sections:
            raise _error("DATA_REMOTE_RAW_CONTENT_FORBIDDEN", "remote policy cannot select raw_rows")
        values = {
            "destination": destination,
            "provider_ref": provider_ref,
            "max_items": _positive_int(max_items, "max_items"),
            "max_string_length": _positive_int(max_string_length, "max_string_length"),
            "max_token_budget": _positive_int(max_token_budget, "max_token_budget"),
            "max_row_budget": _positive_int(max_row_budget, "max_row_budget"),
            "max_time_budget_ms": _positive_int(max_time_budget_ms, "max_time_budget_ms"),
            "allow_raw_rows": allow_raw_rows,
            "allow_sensitive_columns": allow_sensitive_columns,
            "allow_unknown_columns": allow_unknown_columns,
            "allow_direct_identifiers": allow_direct_identifiers,
            "allow_free_text": allow_free_text,
            "allowed_sections": tuple(sections),
            "confirmation_required": confirmation_required,
        }
        if policy_ref is None:
            policy_ref = _contract_ref(
                "egress-policy",
                f"data-context.{destination}",
                {key: value for key, value in values.items() if key not in {"provider_ref"}},
            )
        if type(policy_ref) is not ContractRefV1:
            raise _error("DATA_POLICY_INVALID", "policy_ref must be a ContractRefV1")
        object.__setattr__(self, "policy_ref", policy_ref)
        for key, value in values.items():
            object.__setattr__(self, key, value)

    @classmethod
    def default_remote(cls, **overrides: object) -> "ContextEgressPolicyV1":
        return cls(destination="remote", **overrides)

    @classmethod
    def default_local(cls, **overrides: object) -> "ContextEgressPolicyV1":
        return cls(destination="local", **overrides)

    def to_c0_policy(self) -> C0ContextEgressPolicyV1:
        return C0ContextEgressPolicyV1(
            policy_ref=self.policy_ref,
            destination=self.destination,
            provider_ref=self.provider_ref,
            allowed_sensitivity=(
                SensitivityClassV1.PUBLIC,
                SensitivityClassV1.INTERNAL,
                SensitivityClassV1.RESTRICTED,
            ),
            max_token_budget=self.max_token_budget,
            max_row_budget=self.max_row_budget,
            max_time_budget_ms=self.max_time_budget_ms,
            allow_raw_rows=self.allow_raw_rows,
            allow_raw_secrets=False,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": DATA_CONTEXT_POLICY_VERSION_V1,
            "policy_ref": self.policy_ref.to_dict(),
            "destination": self.destination,
            "provider_ref": self.provider_ref,
            "max_items": self.max_items,
            "max_string_length": self.max_string_length,
            "max_token_budget": self.max_token_budget,
            "max_row_budget": self.max_row_budget,
            "max_time_budget_ms": self.max_time_budget_ms,
            "allow_raw_rows": self.allow_raw_rows,
            "allow_sensitive_columns": self.allow_sensitive_columns,
            "allow_unknown_columns": self.allow_unknown_columns,
            "allow_direct_identifiers": self.allow_direct_identifiers,
            "allow_free_text": self.allow_free_text,
            "allowed_sections": list(self.allowed_sections),
            "confirmation_required": self.confirmation_required,
        }


DataContextEgressPolicyV1 = ContextEgressPolicyV1


@dataclass(frozen=True)
class DataContextEgressOmissionV1:
    section: str
    omitted_items: int
    available_items: int
    reason: str
    content_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "section": self.section,
            "omitted_items": self.omitted_items,
            "available_items": self.available_items,
            "reason": self.reason,
            "content_digest": self.content_digest,
        }


@dataclass(frozen=True)
class DataContextEgressReceiptV1:
    provider_location: str
    policy_version: str
    policy_ref: ContractRefV1
    source_profile_digest: str
    materialized_context_digest: str
    materialization_result_ref: str
    gateway_request_digest: str
    gateway_receipt: C0ContextEgressReceiptV1
    available_sections: tuple[str, ...]
    included_sections: tuple[str, ...]
    omissions: tuple[DataContextEgressOmissionV1, ...]
    available_items: int
    included_items: int
    omitted_items: int
    available_row_count: int
    included_row_count: int
    raw_row_count: int
    redacted_columns: tuple[str, ...]

    @property
    def receipt(self) -> C0ContextEgressReceiptV1:
        return self.gateway_receipt

    @property
    def content_digest(self) -> str:
        return self.materialized_context_digest

    @property
    def receipt_digest(self) -> str:
        return self.gateway_receipt.receipt_digest

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": DATA_CONTEXT_RECEIPT_SCHEMA_V1,
            "provider_location": self.provider_location,
            "policy_version": self.policy_version,
            "policy_ref": self.policy_ref.to_dict(),
            "source_profile_digest": self.source_profile_digest,
            "materialized_context_digest": self.materialized_context_digest,
            "materialization_result_ref": self.materialization_result_ref,
            "gateway_request_digest": self.gateway_request_digest,
            "gateway_receipt": self.gateway_receipt.to_dict(),
            "available_sections": list(self.available_sections),
            "included_sections": list(self.included_sections),
            "omissions": [item.to_dict() for item in self.omissions],
            "available_items": self.available_items,
            "included_items": self.included_items,
            "omitted_items": self.omitted_items,
            "available_row_count": self.available_row_count,
            "included_row_count": self.included_row_count,
            "raw_row_count": self.raw_row_count,
            "redacted_columns": list(self.redacted_columns),
            "receipt_digest": self.receipt_digest,
        }


ContextEgressReceiptV1 = DataContextEgressReceiptV1


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _section_digest(value: object) -> str:
    try:
        return sha256_canonical(_plain(value))  # type: ignore[arg-type]
    except (AttributeError, ContractError, TypeError, ValueError):
        return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()


def _section_omission(
    section: str,
    omitted_items: int,
    available_items: int,
    reason: str,
    source: object,
) -> DataContextEgressOmissionV1:
    return DataContextEgressOmissionV1(
        section=section,
        omitted_items=max(0, omitted_items),
        available_items=max(0, available_items),
        reason=reason,
        content_digest=_section_digest(source),
    )


def _column_is_allowed(column: _Column, policy: ContextEgressPolicyV1) -> bool:
    if column.direct_identifier and not policy.allow_direct_identifiers:
        return False
    if column.sensitivity in {
        SensitivityClassV1.UNKNOWN,
        SensitivityClassV1.RESTRICTED,
    }:
        return False
    return True


def _build_materialization_context(
    schema_ref: str,
    row_count: int,
    columns: Sequence[_Column],
    aggregate_entries: Sequence[Mapping[str, object]],
    role_entries: Sequence[Mapping[str, object]],
    raw_rows: Sequence[Mapping[str, object]],
    rows_ref: str,
) -> dict[str, object]:
    context: dict[str, object] = {
        schema_ref: {
            "row_count": row_count,
            "count": len(columns),
            "features": [column.ref for column in columns],
            "schema_ref": schema_ref,
            "bounded": True,
        }
    }
    for entry in aggregate_entries:
        column_ref = entry["column_ref"]
        if type(column_ref) is not str:
            continue
        context[_opaque("metric:", column_ref)] = {
            "feature": column_ref,
            **{
                field_name: entry[field_name]
                for field_name in _AGGREGATE_FIELDS
                if field_name in entry and _finite_number(entry[field_name]) is not None
            },
        }
    for entry in role_entries:
        column_ref = entry["column_ref"]
        role = entry["role"]
        if type(column_ref) is not str or type(role) is not str:
            continue
        role_ref = _opaque("descriptor:", column_ref, role)
        item: dict[str, object] = {"feature": column_ref, "role": role}
        probability = _finite_number(entry.get("probability"))
        if probability is not None:
            item["probability"] = probability
        context[role_ref] = item
    if raw_rows:
        context[rows_ref] = {"rows": [dict(row) for row in raw_rows]}
    return context


def _estimate_tokens(context: Mapping[str, object]) -> int:
    encoded = canonical_json_v1(_plain(context))  # type: ignore[arg-type]
    return max(1, math.ceil(len(encoded) / 4))


@dataclass(frozen=True)
class DataContextPacketV1:
    """Bounded data packet plus the C0 gateway and receipt evidence."""

    data: Mapping[str, object]
    quoted_data: Mapping[str, object]
    instructions: Mapping[str, object]
    provider_context: Mapping[str, object]
    gateway: C0ContextEgressGatewayV1
    egress_receipt: DataContextEgressReceiptV1
    provenance: Mapping[str, object]
    _issuer: C0ContextEgressReceiptIssuerV1 = field(repr=False, compare=False)
    _verification_at: str = field(repr=False, compare=False)

    @property
    def context(self) -> Mapping[str, object]:
        return self.provider_context

    @property
    def receipt(self) -> DataContextEgressReceiptV1:
        return self.egress_receipt

    def to_provider_payload(self) -> dict[str, object]:
        """Return only the C0-materialized context after receipt verification."""

        try:
            require_context_egress_receipt(
                self.gateway,
                self.egress_receipt.gateway_receipt,
                issuer=self._issuer,
                at=self._verification_at,
            )
        except (ContractError, EgressContractError) as exc:
            raise _error("DATA_EGRESS_RECEIPT_REQUIRED", "provider payload requires a valid C0 receipt") from exc
        return {
            "schema_version": DATA_CONTEXT_SCHEMA_V1,
            "context": _plain(self.provider_context),
            "instructions": _plain(self.instructions),
            "receipt_digest": self.egress_receipt.receipt_digest,
        }

    provider_payload = to_provider_payload

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": DATA_CONTEXT_SCHEMA_V1,
            "data": _plain(self.data),
            "quoted_data": _plain(self.quoted_data),
            "instructions": _plain(self.instructions),
            "provider_context": _plain(self.provider_context),
            "gateway": self.gateway.to_dict(),
            "egress_receipt": self.egress_receipt.to_dict(),
            "provenance": _plain(self.provenance),
        }


ContextEgressPacketV1 = DataContextPacketV1


class _ImmutableDict(dict[str, object]):
    """JSON-compatible immutable mapping for trusted instruction metadata."""

    def __init__(self, values: Mapping[str, object]) -> None:
        dict.__init__(self, values)

    @staticmethod
    def _reject(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TypeError("immutable mapping")

    __setitem__ = _reject
    __delitem__ = _reject
    clear = _reject
    pop = _reject
    popitem = _reject
    setdefault = _reject
    update = _reject
    __ior__ = _reject


def _normalize_time(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(UTC).replace(microsecond=0)
    if isinstance(value, datetime):
        current = value
    elif type(value) is str:
        try:
            current = datetime.fromisoformat(value)
        except ValueError as exc:
            raise _error("DATA_TIME_INVALID", "requested_at must be ISO-8601") from exc
    else:
        raise _error("DATA_TIME_INVALID", "requested_at must be an aware datetime or ISO-8601 string")
    if current.tzinfo is None or current.utcoffset() is None:
        raise _error("DATA_TIME_INVALID", "requested_at must be timezone-aware")
    return current.astimezone(UTC).replace(microsecond=0)


def compile_data_context(
    *,
    profile: object,
    provider_location: str | None = None,
    policy: ContextEgressPolicyV1 | None = None,
    requested_at: datetime | str | None = None,
    request_id: str | None = None,
) -> DataContextPacketV1:
    """Compile a bounded profile contribution through the existing C0 gateway."""

    if policy is None:
        policy = (
            ContextEgressPolicyV1.default_remote()
            if provider_location in {None, "remote"}
            else ContextEgressPolicyV1.default_local()
        )
    if type(policy) is not ContextEgressPolicyV1:
        raise _error("DATA_POLICY_REQUIRED", "compile_data_context requires the package-local typed policy")
    location = policy.destination if provider_location is None else provider_location
    if location != policy.destination:
        raise _error("DATA_PROVIDER_SCOPE_MISMATCH", "provider location does not match the policy")

    dataset_identity = _server_owned_dataset_identity(profile)
    dataset_identity_digest = sha256_canonical(dataset_identity)
    dataset_ref = f"dataset:{dataset_identity_digest}"
    dataset_digest = _digest_ref(dataset_ref)
    rows_value = _read(profile, "rows", None)
    if rows_value is None:
        rows_value = _read(profile, "raw_rows", ())
    if not isinstance(rows_value, (list, tuple)):
        raise _error("DATA_PROFILE_INVALID", "profile rows must be a list")
    rows = tuple(item for item in rows_value if isinstance(item, Mapping))
    row_count_value = _read(profile, "row_count", len(rows))
    if type(row_count_value) is not int or row_count_value < 0:
        raise _error("DATA_PROFILE_INVALID", "row_count must be a non-negative integer")
    row_count = row_count_value
    columns = _normalize_columns(profile, dataset_digest, policy.max_string_length)
    source_profile_digest = _profile_digest(profile, dataset_ref, row_count, columns, len(rows))

    exposed_columns = tuple(column for column in columns if _column_is_allowed(column, policy))
    redacted_columns = tuple(column.name for column in columns if column not in exposed_columns)
    schema_ref = _opaque("schema:", dataset_digest)
    rows_ref = _opaque("data-ref:rows-", dataset_digest)

    schema_entries = tuple(
        (
            {
                "column_ref": column.ref,
                "label": {"quoted": column.name, "untrusted": True},
                "dtype": column.dtype,
                "sensitivity": column.sensitivity.value,
                "role_candidates": list(column.roles),
            }
            if column in exposed_columns
            else {
                "column_ref": column.ref,
                "label": {"quoted": "[REDACTED]", "untrusted": True, "redacted": True},
                "dtype": "scalar",
                "sensitivity": column.sensitivity.value,
                "role_candidates": [],
                "redacted": True,
            }
        )
        for column in columns
    )
    aggregate_entries = tuple(
        {
            "column_ref": column.ref,
            **dict(column.aggregates),
        }
        for column in exposed_columns
        if column.aggregates
    )
    role_entries = tuple(
        {"column_ref": column.ref, "role": role}
        for column in exposed_columns
        for role in column.roles
    )

    available: dict[str, int] = {
        "schema": len(columns),
        "aggregates": len(aggregate_entries),
        "role_candidates": len(role_entries),
        "raw_rows": len(rows),
    }
    candidates: dict[str, tuple[object, ...]] = {
        "schema": schema_entries,
        "aggregates": aggregate_entries,
        "role_candidates": role_entries,
        "raw_rows": (),
    }
    omissions: list[DataContextEgressOmissionV1] = [
        _section_omission(
            "columns",
            1,
            1,
            "direct_identifier" if column.direct_identifier else "sensitivity_restricted",
            {"column": column.name, "sensitivity": column.sensitivity.value},
        )
        for column in columns
        if column not in exposed_columns
    ]

    # Raw rows are only considered when an explicit local typed policy selected
    # them.  C0 can carry numeric/boolean/null cells; arbitrary strings stay out
    # of the provider context and are recorded as omissions.
    safe_raw_rows: list[dict[str, object]] = []
    unsafe_raw_rows = 0
    if rows and policy.allow_raw_rows and "raw_rows" in policy.allowed_sections:
        for row in rows:
            projected: dict[str, object] = {}
            unsafe = False
            for column in exposed_columns:
                if column.name not in row:
                    continue
                value = row[column.name]
                if value is None or type(value) is bool or type(value) is int:
                    projected[column.ref] = value
                elif type(value) is float and math.isfinite(value):
                    projected[column.ref] = value
                else:
                    unsafe = True
                    break
            if unsafe or not projected:
                unsafe_raw_rows += 1
            else:
                safe_raw_rows.append(projected)
    candidates["raw_rows"] = tuple(safe_raw_rows)
    if len(safe_raw_rows) > policy.max_row_budget:
        omitted_by_row_budget = len(safe_raw_rows) - policy.max_row_budget
        safe_raw_rows = safe_raw_rows[: policy.max_row_budget]
        candidates["raw_rows"] = tuple(safe_raw_rows)
        omissions.append(
            _section_omission(
                "raw_rows",
                omitted_by_row_budget,
                len(rows),
                "row_budget",
                safe_raw_rows,
            )
        )
    if unsafe_raw_rows:
        omissions.append(
            _section_omission(
                "raw_rows",
                unsafe_raw_rows,
                len(rows),
                "untrusted_cell_value",
                rows,
            )
        )
    if rows and not policy.allow_raw_rows:
        omissions.append(
            _section_omission(
                "raw_rows",
                len(rows),
                len(rows),
                "policy_raw_rows_disabled",
                rows,
            )
        )

    included: dict[str, tuple[object, ...]] = {}
    remaining = policy.max_items
    section_order = ("schema", "aggregates", "role_candidates", "raw_rows")
    for section in section_order:
        available_count = available[section]
        if available_count == 0:
            continue
        if section not in policy.allowed_sections:
            omissions.append(
                _section_omission(
                    section,
                    available_count,
                    available_count,
                    "policy_section_not_allowed",
                    candidates[section],
                )
            )
            continue
        values = candidates[section]
        if len(values) != available_count and section == "raw_rows":
            available_count = len(values) + unsafe_raw_rows
        if len(values) > remaining:
            omissions.append(
                _section_omission(section, len(values), available_count, "item_budget", values)
            )
            continue
        if values:
            included[section] = values
            remaining -= len(values)

    def materialization_context() -> dict[str, object]:
        return _build_materialization_context(
            schema_ref,
            row_count,
            tuple(
                column
                for column in exposed_columns
                if any(
                    type(entry) is dict and entry.get("column_ref") == column.ref
                    for entry in included.get("schema", ())
                )
            )
            if "schema" in included
            else (),
            tuple(entry for entry in included.get("aggregates", ()) if isinstance(entry, Mapping)),
            tuple(entry for entry in included.get("role_candidates", ()) if isinstance(entry, Mapping)),
            tuple(entry for entry in included.get("raw_rows", ()) if isinstance(entry, Mapping)),
            rows_ref,
        )

    context = materialization_context()
    token_estimate = _estimate_tokens(context)
    for section in ("raw_rows", "role_candidates", "aggregates"):
        if token_estimate <= policy.max_token_budget:
            break
        values = included.pop(section, None)
        if values:
            omissions.append(
                _section_omission(
                    section,
                    len(values),
                    available[section],
                    "token_budget",
                    values,
                )
            )
            context = materialization_context()
            token_estimate = _estimate_tokens(context)
    if token_estimate > policy.max_token_budget and "schema" in included:
        values = included.pop("schema")
        omissions.append(
            _section_omission("schema", len(values), available["schema"], "token_budget", values)
        )
        context = materialization_context()
        token_estimate = _estimate_tokens(context)
    if token_estimate > policy.max_token_budget:
        raise _error("DATA_EGRESS_BUDGET_EXCEEDED", "C0-safe context cannot fit the token budget")

    included_sections = tuple(section for section in section_order if section in included)
    available_sections = tuple(section for section in section_order if available[section] > 0)
    included_items = sum(len(values) for values in included.values())
    omitted_items = sum(item.omitted_items for item in omissions)

    # Keep the public section shape stable even when every item in a section
    # is redacted or budget-omitted.  An empty section is not evidence that
    # the source had no columns; the receipt/omissions carry that distinction.
    # It also prevents consumers from treating a missing key as permission to
    # fall back to raw profile content.
    data: dict[str, object] = {
        section: list(included.get(section, ()))
        for section in ("schema", "aggregates", "role_candidates")
    }
    if "raw_rows" in included:
        data["raw_rows"] = list(included["raw_rows"])

    quoted_data: dict[str, object] = {
        "schema_labels": [
            entry["label"]
            | {"column_ref": entry["column_ref"]}
            for entry in included.get("schema", ())
            if isinstance(entry, Mapping) and isinstance(entry.get("label"), Mapping)
        ],
        "cells": [],
    }
    if "raw_rows" in included:
        cells: list[dict[str, object]] = []
        for row in included["raw_rows"]:
            if not isinstance(row, Mapping):
                continue
            for column_ref, value in row.items():
                cells.append({"column_ref": column_ref, "value": value, "untrusted": True})
        quoted_data["cells"] = cells

    instructions: Mapping[str, object] = _ImmutableDict(
        {
            "channel": "instructions",
            "trusted": True,
            "operation_refs": (),
            "capability_refs": (),
        }
    )

    current = _normalize_time(requested_at)
    expires = current + timedelta(milliseconds=policy.max_time_budget_ms)
    effective_sensitivity = SensitivityClassV1.PUBLIC
    if redacted_columns or any(column.sensitivity is SensitivityClassV1.RESTRICTED for column in exposed_columns):
        effective_sensitivity = SensitivityClassV1.RESTRICTED
    elif any(column.sensitivity is SensitivityClassV1.INTERNAL for column in exposed_columns):
        effective_sensitivity = SensitivityClassV1.INTERNAL
    c0_policy = policy.to_c0_policy()
    materializer = ContextMaterializationStoreV1(
        materializer_ref=_contract_ref("materializer", "server.context.data-consumer"),
        redaction_policy_ref=_contract_ref(
            "redaction-policy",
            f"data-context.{policy.destination}",
        ),
    )
    try:
        result = materializer.materialize(context, selected_refs=tuple(context))
        generated_request_id = request_id or f"egress-request:{source_profile_digest[:24]}"
        gateway = C0ContextEgressGatewayV1.from_materialization_result(
            result,
            request_id=generated_request_id,
            destination=policy.destination,
            provider_ref=policy.provider_ref,
            sensitivity_policy_ref=policy.policy_ref,
            sensitivity=effective_sensitivity,
            token_budget=token_estimate,
            row_budget=max(1, len(included.get("raw_rows", ()))),
            time_budget_ms=policy.max_time_budget_ms,
            purpose_ref="purpose:data-context",
            requested_at=current.isoformat(),
            expires_at=expires.isoformat(),
        )
        issuer = C0ContextEgressReceiptIssuerV1(
            c0_policy,
            materializer_store=materializer,
            clock=lambda: current,
        )
        c0_receipt = issuer.issue(gateway, at=current.isoformat())
    except (ContractError, EgressContractError, TypeError, ValueError) as exc:
        raise _error("DATA_EGRESS_C0_REJECTED", "C0 rejected the bounded data context") from exc

    provider_context = result.materialized_context
    provenance: Mapping[str, object] = {
        "provider_location": policy.destination,
        "policy_version": DATA_CONTEXT_POLICY_VERSION_V1,
        "policy_ref": policy.policy_ref.to_dict(),
        "source_profile_digest": source_profile_digest,
        "materialization_result_ref": result.result_ref,
        "materialized_context_digest": result.materialized_context_digest,
        "gateway_request_digest": gateway.request_digest,
        "receipt_digest": c0_receipt.receipt_digest,
    }
    egress_receipt = DataContextEgressReceiptV1(
        provider_location=policy.destination,
        policy_version=DATA_CONTEXT_POLICY_VERSION_V1,
        policy_ref=policy.policy_ref,
        source_profile_digest=source_profile_digest,
        materialized_context_digest=result.materialized_context_digest,
        materialization_result_ref=result.result_ref,
        gateway_request_digest=gateway.request_digest,
        gateway_receipt=c0_receipt,
        available_sections=available_sections,
        included_sections=included_sections,
        omissions=tuple(omissions),
        available_items=sum(available.values()),
        included_items=included_items,
        omitted_items=omitted_items,
        available_row_count=len(rows),
        included_row_count=len(included.get("raw_rows", ())),
        raw_row_count=len(included.get("raw_rows", ())) if policy.destination == "local" else 0,
        redacted_columns=redacted_columns,
    )
    return DataContextPacketV1(
        data=data,
        quoted_data=quoted_data,
        instructions=instructions,
        provider_context=provider_context,
        gateway=gateway,
        egress_receipt=egress_receipt,
        provenance=provenance,
        _issuer=issuer,
        _verification_at=current.isoformat(),
    )


ContextEgressGatewayV1 = C0ContextEgressGatewayV1


__all__ = [
    "C0ContextEgressGatewayV1",
    "ContextEgressGatewayV1",
    "ContextEgressPacketV1",
    "ContextEgressPolicyV1",
    "ContextEgressReceiptV1",
    "DataContextEgressError",
    "DataContextEgressOmissionV1",
    "DataContextEgressPolicyV1",
    "DataContextEgressReceiptV1",
    "DataContextPacketV1",
    "DATA_CONTEXT_POLICY_VERSION_V1",
    "DATA_CONTEXT_RECEIPT_SCHEMA_V1",
    "DATA_CONTEXT_SCHEMA_V1",
    "compile_data_context",
]
