"""Immutable, canonical contracts for the server-owned local identity authority."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..canonical import canonical_json_v1, sha256_canonical
from ..contracts.common.envelope import freeze_json, thaw_json

LOCAL_PROFILE_IDENTITY_CONTRACT = "local-profile-identity/v1"
PROJECT_IDENTITY_REVISION_CONTRACT = "project-identity-revision/v1"


class IdentityContractError(ValueError):
    """A persisted identity record is not the exact supported contract."""


def _require_opaque_id(value: object, field_name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise IdentityContractError(f"{field_name} must be a non-empty opaque id")
    return value


def _require_revision(value: object, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise IdentityContractError(f"{field_name} must be a positive integer")
    return value


def _require_exact_mapping(
    value: object, *, fields: set[str], field_name: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IdentityContractError(f"{field_name} must be a mapping")
    if any(type(key) is not str for key in value):
        raise IdentityContractError(f"{field_name} keys must be strings")
    unknown = set(value) - fields
    missing = fields - set(value)
    if unknown:
        raise IdentityContractError(
            f"unknown {field_name} field(s): {', '.join(sorted(unknown))}"
        )
    if missing:
        raise IdentityContractError(
            f"missing {field_name} field(s): {', '.join(sorted(missing))}"
        )
    return value


def _freeze_root_binding(value: object) -> Any:
    raw = _require_exact_mapping(
        value,
        fields={"binding_key", "canonical_path", "device", "inode"},
        field_name="root_binding",
    )
    _require_opaque_id(raw["binding_key"], "root_binding.binding_key")
    canonical_path = raw["canonical_path"]
    if type(canonical_path) is not str or not canonical_path.startswith("/"):
        raise IdentityContractError(
            "root_binding.canonical_path must be an absolute path"
        )
    for field_name in ("device", "inode"):
        value = raw[field_name]
        if type(value) is not int or value < 0:
            raise IdentityContractError(
                f"root_binding.{field_name} must be a non-negative integer"
            )
    return freeze_json(dict(raw), "root_binding")


@dataclass(frozen=True)
class LocalProfileIdentity:
    """A stable server-issued local profile identity.

    The identity has no path, display name, client claim, or data fingerprint.
    Those values therefore cannot become an accidental identity producer.
    """

    profile_id: str
    revision: int = 1
    contract_version: str = LOCAL_PROFILE_IDENTITY_CONTRACT

    def __post_init__(self) -> None:
        _require_opaque_id(self.profile_id, "profile_id")
        _require_revision(self.revision, "revision")
        if self.contract_version != LOCAL_PROFILE_IDENTITY_CONTRACT:
            raise IdentityContractError(
                f"unsupported local profile contract: {self.contract_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "profile_id": self.profile_id,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LocalProfileIdentity":
        raw = _require_exact_mapping(
            value,
            fields={"contract_version", "profile_id", "revision"},
            field_name="local_profile_identity",
        )
        return cls(
            profile_id=raw["profile_id"],
            revision=raw["revision"],
            contract_version=raw["contract_version"],
        )

    @property
    def canonical_json(self) -> str:
        return canonical_json_v1(self.to_dict())

    @property
    def content_hash(self) -> str:
        return sha256_canonical(self.to_dict())

    @property
    def identity_hash(self) -> str:
        return self.content_hash

    @property
    def record_hash(self) -> str:
        return self.content_hash


@dataclass(frozen=True)
class ProjectIdentityRevision:
    """One immutable revision binding a project id to an observed root."""

    project_id: str
    profile_id: str
    revision: int
    root_binding: Mapping[str, Any]
    previous_revision: int | None = None
    contract_version: str = PROJECT_IDENTITY_REVISION_CONTRACT

    def __post_init__(self) -> None:
        _require_opaque_id(self.project_id, "project_id")
        _require_opaque_id(self.profile_id, "profile_id")
        _require_revision(self.revision, "revision")
        if self.previous_revision is not None:
            _require_revision(self.previous_revision, "previous_revision")
            if self.previous_revision >= self.revision:
                raise IdentityContractError(
                    "previous_revision must be lower than revision"
                )
        if self.contract_version != PROJECT_IDENTITY_REVISION_CONTRACT:
            raise IdentityContractError(
                f"unsupported project identity contract: {self.contract_version!r}"
            )
        object.__setattr__(self, "root_binding", _freeze_root_binding(self.root_binding))

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "previous_revision": self.previous_revision,
            "profile_id": self.profile_id,
            "project_id": self.project_id,
            "revision": self.revision,
            "root_binding": thaw_json(self.root_binding),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProjectIdentityRevision":
        raw = _require_exact_mapping(
            value,
            fields={
                "contract_version",
                "previous_revision",
                "profile_id",
                "project_id",
                "revision",
                "root_binding",
            },
            field_name="project_identity_revision",
        )
        return cls(
            project_id=raw["project_id"],
            profile_id=raw["profile_id"],
            revision=raw["revision"],
            previous_revision=raw["previous_revision"],
            root_binding=raw["root_binding"],
            contract_version=raw["contract_version"],
        )

    @property
    def canonical_json(self) -> str:
        return canonical_json_v1(self.to_dict())

    @property
    def content_hash(self) -> str:
        return sha256_canonical(self.to_dict())

    @property
    def identity_hash(self) -> str:
        return self.content_hash

    @property
    def record_hash(self) -> str:
        return self.content_hash


__all__ = [
    "IDENTITY_CONTRACTS",
    "LOCAL_PROFILE_IDENTITY_CONTRACT",
    "PROJECT_IDENTITY_REVISION_CONTRACT",
    "IdentityContractError",
    "LocalProfileIdentity",
    "ProjectIdentityRevision",
]

IDENTITY_CONTRACTS = {
    "local_profile": LOCAL_PROFILE_IDENTITY_CONTRACT,
    "project_revision": PROJECT_IDENTITY_REVISION_CONTRACT,
}
