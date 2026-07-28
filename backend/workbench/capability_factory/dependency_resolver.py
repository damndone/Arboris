"""Offline dependency resolution against an immutable index snapshot."""

from __future__ import annotations

import re
from dataclasses import fields, is_dataclass
from dataclasses import dataclass
from urllib.parse import urlsplit

from ..custom_capability.canonical import domain_digest
from .dependency_contract import DependencyContractError, DependencyLock, DependencyRequirement
from .contracts import _digest, _sequence, _text


class DependencyResolutionError(ValueError):
    """Raised when a lock cannot be derived deterministically."""


_DISTRIBUTION = re.compile(r"^[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*$")


def _plain(value):
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class DependencyResolutionPolicy:
    policy_id: str
    revision: int
    allowed_origins: tuple[str, ...]
    python_version: str
    operating_system: str
    architecture: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "policy_id", _text(self.policy_id, "policy_id"))
        if not isinstance(self.revision, int) or isinstance(self.revision, bool) or self.revision < 1:
            raise DependencyResolutionError("policy revision must be positive")
        origins = _sequence(self.allowed_origins, "allowed_origins")
        if any(not item.startswith("https://") for item in origins):
            raise DependencyResolutionError("allowed origins must use https")
        object.__setattr__(self, "allowed_origins", tuple(item.rstrip("/") for item in origins))
        object.__setattr__(self, "python_version", _text(self.python_version, "python_version"))
        object.__setattr__(self, "operating_system", _text(self.operating_system, "operating_system"))
        object.__setattr__(self, "architecture", _text(self.architecture, "architecture"))

    @property
    def content_digest(self) -> str:
        return domain_digest("workbench.capability_factory.dependency_policy/v1", _plain(self))


@dataclass(frozen=True, slots=True)
class ArtifactCandidate:
    distribution: str
    version: str
    artifact_digest: str
    url: str
    python_tag: str
    platform_tag: str

    def __post_init__(self) -> None:
        distribution = _text(self.distribution, "distribution")
        if not _DISTRIBUTION.fullmatch(distribution):
            raise DependencyResolutionError("artifact distribution is invalid")
        object.__setattr__(self, "distribution", distribution.lower().replace("_", "-").replace(".", "-"))
        object.__setattr__(self, "version", _text(self.version, "version"))
        try:
            object.__setattr__(self, "artifact_digest", _digest(self.artifact_digest, "artifact_digest"))
        except ValueError as error:
            raise DependencyResolutionError(str(error)) from error
        url = _text(self.url, "url")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise DependencyResolutionError("artifact URL must be an https URL without query or fragment")
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "python_tag", _text(self.python_tag, "python_tag"))
        object.__setattr__(self, "platform_tag", _text(self.platform_tag, "platform_tag"))


@dataclass(frozen=True, slots=True)
class IndexSnapshot:
    snapshot_ref: str
    artifacts: tuple[ArtifactCandidate, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_ref", _digest(self.snapshot_ref, "snapshot_ref"))
        artifacts = tuple(self.artifacts)
        if any(not isinstance(item, ArtifactCandidate) for item in artifacts):
            raise DependencyResolutionError("index snapshot contains invalid artifacts")
        identities = {(item.distribution, item.version, item.artifact_digest) for item in artifacts}
        if len(identities) != len(artifacts):
            raise DependencyResolutionError("index snapshot contains duplicate artifacts")
        object.__setattr__(self, "artifacts", artifacts)


class DependencyResolver:
    """Resolve exact requirements without contacting an index or importing code."""

    def resolve(
        self,
        *,
        requirements: tuple[DependencyRequirement, ...],
        snapshot: IndexSnapshot,
        policy: DependencyResolutionPolicy,
    ) -> DependencyLock:
        if not requirements or not isinstance(snapshot, IndexSnapshot) or not isinstance(policy, DependencyResolutionPolicy):
            raise DependencyResolutionError("requirements, snapshot, and policy are required")
        selected: list[DependencyRequirement] = []
        for requirement in requirements:
            matches = [
                item
                for item in snapshot.artifacts
                if item.distribution == requirement.distribution
                and item.version == requirement.version
                and item.artifact_digest == requirement.artifact_digest
                and item.python_tag == requirement.python_tag
                and item.platform_tag == requirement.platform_tag
                and self._origin(item.url) in policy.allowed_origins
            ]
            if len(matches) != 1:
                raise DependencyResolutionError(
                    f"requirement {requirement.distribution} has {len(matches)} exact candidates"
                )
            selected.append(requirement)
        return DependencyLock(
            lock_id=f"lock.{snapshot.snapshot_ref[:16]}",
            revision=1,
            requirements=tuple(selected),
            resolver_policy_digest=policy.content_digest,
            python_version=policy.python_version,
            operating_system=policy.operating_system,
            architecture=policy.architecture,
        )

    @staticmethod
    def _origin(url: str) -> str:
        parsed = urlsplit(url)
        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


__all__ = [
    "ArtifactCandidate",
    "DependencyResolutionError",
    "DependencyResolutionPolicy",
    "DependencyResolver",
    "IndexSnapshot",
]
