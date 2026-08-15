"""Immutable references and fail-closed resolution for public contracts."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from workbench.canonical import sha256_canonical


CONTRACT_REF_INVALID = "CONTRACT_REF_INVALID"
CONTRACT_VERSION_INVALID = "CONTRACT_VERSION_INVALID"
CONTRACT_DUPLICATE = "CONTRACT_DUPLICATE"
CONTRACT_UNRESOLVED = "CONTRACT_UNRESOLVED"
CONTRACT_DIGEST_MISMATCH = "CONTRACT_DIGEST_MISMATCH"
CONTRACT_MAJOR_INCOMPATIBLE = "CONTRACT_MAJOR_INCOMPATIBLE"

_ERROR_MESSAGES = {
    CONTRACT_REF_INVALID: "contract reference is invalid",
    CONTRACT_VERSION_INVALID: "contract semantic version is invalid",
    CONTRACT_DUPLICATE: "contract reference identity is duplicated",
    CONTRACT_UNRESOLVED: "contract reference is unresolved",
    CONTRACT_DIGEST_MISMATCH: "contract digest does not match",
    CONTRACT_MAJOR_INCOMPATIBLE: "contract major version is incompatible",
}
_SEMANTIC_VERSION_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_MAX_SEMANTIC_VERSION_COMPONENT = 2_147_483_647
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_REF_FIELDS = frozenset(
    {"kind", "logical_id", "semantic_version", "contract_digest"}
)


class ContractRefError(ValueError):
    """A contract reference failure with a stable machine-readable code."""

    def __init__(self, code: str) -> None:
        if code not in _ERROR_MESSAGES:
            raise ValueError("unknown contract reference error code")
        self.code = code
        super().__init__(f"{code}: {_ERROR_MESSAGES[code]}")


def parse_semantic_version(value: object) -> tuple[int, int]:
    """Parse canonical ``MAJOR.MINOR`` without coercion or normalization."""

    if type(value) is not str:
        raise ContractRefError(CONTRACT_VERSION_INVALID)
    match = _SEMANTIC_VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise ContractRefError(CONTRACT_VERSION_INVALID)
    components = match.groups()
    max_component = str(_MAX_SEMANTIC_VERSION_COMPONENT)
    if any(
        len(component) > len(max_component)
        or (len(component) == len(max_component) and component > max_component)
        for component in components
    ):
        raise ContractRefError(CONTRACT_VERSION_INVALID)
    return int(components[0]), int(components[1])


def canonical_contract_digest(value: Any) -> str:
    """Return the lowercase SHA-256 digest of canonical JSON v1."""

    return sha256_canonical(value)


def _require_identifier(value: object) -> None:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        raise ContractRefError(CONTRACT_REF_INVALID)


@dataclass(frozen=True)
class ContractRefV1:
    kind: str
    logical_id: str
    semantic_version: str
    contract_digest: str

    def __post_init__(self) -> None:
        _require_identifier(self.kind)
        _require_identifier(self.logical_id)
        parse_semantic_version(self.semantic_version)
        if (
            type(self.contract_digest) is not str
            or _SHA256_PATTERN.fullmatch(self.contract_digest) is None
        ):
            raise ContractRefError(CONTRACT_REF_INVALID)

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "logical_id": self.logical_id,
            "semantic_version": self.semantic_version,
            "contract_digest": self.contract_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ContractRefV1":
        if not isinstance(value, Mapping):
            raise ContractRefError(CONTRACT_REF_INVALID)
        if any(type(key) is not str for key in value):
            raise ContractRefError(CONTRACT_REF_INVALID)
        if set(value) != _REF_FIELDS:
            raise ContractRefError(CONTRACT_REF_INVALID)
        return cls(
            kind=value["kind"],  # type: ignore[arg-type]
            logical_id=value["logical_id"],  # type: ignore[arg-type]
            semantic_version=value["semantic_version"],  # type: ignore[arg-type]
            contract_digest=value["contract_digest"],  # type: ignore[arg-type]
        )


class ContractRefResolverV1:
    """Resolve exact contract identities without fallback or replacement."""

    def __init__(self, refs: Iterable[ContractRefV1]) -> None:
        refs_by_key: dict[tuple[str, str, str], ContractRefV1] = {}
        for ref in refs:
            if type(ref) is not ContractRefV1:
                raise ContractRefError(CONTRACT_REF_INVALID)
            key = (ref.kind, ref.logical_id, ref.semantic_version)
            if key in refs_by_key:
                raise ContractRefError(CONTRACT_DUPLICATE)
            refs_by_key[key] = ref
        self._refs = MappingProxyType(refs_by_key)

    def resolve(self, ref: ContractRefV1) -> ContractRefV1:
        if type(ref) is not ContractRefV1:
            raise ContractRefError(CONTRACT_REF_INVALID)

        key = (ref.kind, ref.logical_id, ref.semantic_version)
        available = self._refs.get(key)
        if available is not None:
            if available.contract_digest != ref.contract_digest:
                raise ContractRefError(CONTRACT_DIGEST_MISMATCH)
            return available

        same_identity = tuple(
            candidate
            for candidate in self._refs.values()
            if candidate.kind == ref.kind and candidate.logical_id == ref.logical_id
        )
        if not same_identity:
            raise ContractRefError(CONTRACT_UNRESOLVED)

        requested_major, _ = parse_semantic_version(ref.semantic_version)
        available_majors = {
            parse_semantic_version(candidate.semantic_version)[0]
            for candidate in same_identity
        }
        if requested_major not in available_majors:
            raise ContractRefError(CONTRACT_MAJOR_INCOMPATIBLE)
        raise ContractRefError(CONTRACT_UNRESOLVED)
