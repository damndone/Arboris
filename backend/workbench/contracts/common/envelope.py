"""Strict, JSON-safe envelopes for versioned cross-seam packets."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any


class ContractError(ValueError):
    """Raised when a public packet violates its locked contract."""


def require_exact_keys(
    value: Mapping[str, object], required: set[str], name: str
) -> None:
    """Reject absent, unexpected, and non-string keys without coercion."""

    if not isinstance(value, Mapping):
        raise ContractError(f"{name} must be a mapping")
    if any(type(key) is not str for key in value):
        raise ContractError(f"{name} mapping keys must be strings")

    unknown = set(value) - required
    missing = required - set(value)
    if unknown:
        raise ContractError(f"unknown {name} field: " + ", ".join(sorted(unknown)))
    if missing:
        raise ContractError(f"missing {name} field: " + ", ".join(sorted(missing)))


def freeze_json(value: Any, path: str = "value") -> Any:
    """Return immutable, recursively finite JSON-compatible storage.

    Contracts retain their supplied semantics exactly: values are never coerced,
    omitted fields are never defaulted, and mapping keys must already be strings.
    """

    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ContractError(f"{path} must contain only finite numbers")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ContractError(f"{path} mapping keys must be strings")
            frozen[key] = freeze_json(item, f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item, f"{path}[]") for item in value)
    raise ContractError(
        f"{path} contains unsupported JSON-compatible leaf {type(value).__name__}"
    )


def thaw_json(value: Any) -> Any:
    """Return a mutable JSON-shaped copy of a frozen contract value."""

    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def _require_non_empty_string(value: Any, field_name: str) -> None:
    if type(value) is not str or not value:
        raise ContractError(f"{field_name} must be a non-empty string")


@dataclass(frozen=True)
class PacketEnvelope:
    """Minimal immutable envelope for a named, versioned contract payload."""

    contract: str
    contract_version: str
    producer_version: str
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        for field_name in ("contract", "contract_version", "producer_version"):
            _require_non_empty_string(getattr(self, field_name), field_name)
        if not isinstance(self.payload, Mapping):
            raise ContractError("payload must be a mapping")
        object.__setattr__(self, "payload", freeze_json(self.payload, "payload"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "contract_version": self.contract_version,
            "producer_version": self.producer_version,
            "payload": thaw_json(self.payload),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PacketEnvelope":
        require_exact_keys(
            value,
            {"contract", "contract_version", "producer_version", "payload"},
            "envelope",
        )
        return cls(
            contract=value["contract"],
            contract_version=value["contract_version"],
            producer_version=value["producer_version"],
            payload=value["payload"],
        )
