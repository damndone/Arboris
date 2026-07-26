"""Immutable dependency and bundle-admission contracts for CF2."""

from __future__ import annotations

import re
from dataclasses import fields, is_dataclass
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from ..custom_capability.canonical import domain_digest
from .contracts import _digest, _freeze, _positive_int, _sequence, _text


class DependencyContractError(ValueError):
    """Raised when a dependency reference is mutable or unsafe."""


_DISTRIBUTION = re.compile(r"^[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*$")
_EXACT_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){2,3}(?:[-.][A-Za-z0-9]+)*$")
_STATUS = frozenset({"quarantined", "validated", "admitted", "rejected", "revoked"})
_SCOPES = frozenset({"project", "profile", "global"})


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, MappingProxyType):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _origin(value: Any) -> str:
    text = _text(value, "index_origin")
    parsed = urlsplit(text)
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise DependencyContractError("index_origin must be an https origin without query or fragment")
    return text.rstrip("/")


@dataclass(frozen=True, slots=True)
class DependencyRequirement:
    distribution: str
    version: str
    artifact_digest: str
    python_tag: str
    platform_tag: str
    index_origin: str

    def __post_init__(self) -> None:
        distribution = _text(self.distribution, "distribution")
        if not _DISTRIBUTION.fullmatch(distribution):
            raise DependencyContractError("distribution has an invalid normalized name")
        object.__setattr__(self, "distribution", distribution.lower().replace("_", "-").replace(".", "-"))
        version = _text(self.version, "version")
        if not _EXACT_VERSION.fullmatch(version):
            raise DependencyContractError("version must be an exact pinned version")
        object.__setattr__(self, "version", version)
        try:
            object.__setattr__(self, "artifact_digest", _digest(self.artifact_digest, "artifact_digest"))
        except ValueError as error:
            raise DependencyContractError(str(error)) from error
        object.__setattr__(self, "python_tag", _text(self.python_tag, "python_tag"))
        object.__setattr__(self, "platform_tag", _text(self.platform_tag, "platform_tag"))
        object.__setattr__(self, "index_origin", _origin(self.index_origin))

    @property
    def content_digest(self) -> str:
        return domain_digest("workbench.capability_factory.dependency_requirement/v1", _plain(self))


@dataclass(frozen=True, slots=True)
class DependencyLock:
    lock_id: str
    revision: int
    requirements: tuple[DependencyRequirement, ...]
    resolver_policy_digest: str
    python_version: str
    operating_system: str
    architecture: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "lock_id", _text(self.lock_id, "lock_id"))
        object.__setattr__(self, "revision", _positive_int(self.revision, "revision"))
        requirements = tuple(self.requirements)
        if not requirements or any(not isinstance(item, DependencyRequirement) for item in requirements):
            raise DependencyContractError("requirements must contain DependencyRequirement values")
        identities = {(item.distribution, item.version) for item in requirements}
        if len(identities) != len(requirements):
            raise DependencyContractError("dependency lock contains duplicate distributions")
        object.__setattr__(self, "requirements", requirements)
        try:
            object.__setattr__(self, "resolver_policy_digest", _digest(self.resolver_policy_digest, "resolver_policy_digest"))
        except ValueError as error:
            raise DependencyContractError(str(error)) from error
        object.__setattr__(self, "python_version", _text(self.python_version, "python_version"))
        object.__setattr__(self, "operating_system", _text(self.operating_system, "operating_system"))
        object.__setattr__(self, "architecture", _text(self.architecture, "architecture"))

    @property
    def content_digest(self) -> str:
        return domain_digest("workbench.capability_factory.dependency_lock/v1", _plain(self))


@dataclass(frozen=True, slots=True)
class BundleAdmission:
    bundle_ref: str
    status: str
    scope: str
    validity_ref: str
    reason_code: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "bundle_ref", _digest(self.bundle_ref, "bundle_ref"))
        if self.status not in _STATUS:
            raise DependencyContractError("unsupported bundle admission status")
        if self.scope not in _SCOPES:
            raise DependencyContractError("unsupported bundle admission scope")
        object.__setattr__(self, "validity_ref", _digest(self.validity_ref, "validity_ref"))
        object.__setattr__(self, "reason_code", _text(self.reason_code, "reason_code"))

    @property
    def content_digest(self) -> str:
        return domain_digest("workbench.capability_factory.bundle_admission/v1", _plain(self))


__all__ = ["BundleAdmission", "DependencyContractError", "DependencyLock", "DependencyRequirement"]
