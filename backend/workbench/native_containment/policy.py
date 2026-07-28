"""Strict, versioned B1 containment policy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ..capability_factory.contracts import _content_digest, _freeze, _text
from .contracts import ResourceBudget


class ContainmentPolicyError(ValueError):
    """Raised when a policy would create a weaker or ambiguous profile."""


_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_ALLOWED_ENV_NAMES = frozenset(
    {"LANG", "LC_ALL", "PYTHONHASHSEED", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"}
)
_RESOURCE_ENFORCEMENT_MODES = frozenset({"hard_limits", "observed_memory"})


@dataclass(frozen=True, slots=True)
class ContainmentPolicy:
    profile_id: str
    filesystem_mode: str
    network_mode: str
    process_mode: str
    inherited_descriptors: bool
    dependency_tree_writable: bool
    environment_allowlist: Mapping[str, str]
    locale: str
    thread_count: int
    budget: ResourceBudget
    allow_weaker_fallback: bool
    resource_enforcement: str = "hard_limits"

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", _text(self.profile_id, "profile_id"))
        if self.filesystem_mode != "sealed_readonly":
            raise ContainmentPolicyError("filesystem_mode must be sealed_readonly")
        if self.network_mode != "disabled":
            raise ContainmentPolicyError("network_mode must be disabled")
        if self.process_mode != "isolated":
            raise ContainmentPolicyError("process_mode must be isolated")
        if self.inherited_descriptors is not False:
            raise ContainmentPolicyError("inherited_descriptors must be false")
        if self.dependency_tree_writable is not False:
            raise ContainmentPolicyError("dependency tree must be read-only")
        if self.allow_weaker_fallback is not False:
            raise ContainmentPolicyError("weaker containment fallback is forbidden")
        if not isinstance(self.resource_enforcement, str) or self.resource_enforcement not in _RESOURCE_ENFORCEMENT_MODES:
            raise ContainmentPolicyError("resource_enforcement is unsupported")
        if self.profile_id == "strict-readonly-v1" and self.resource_enforcement != "hard_limits":
            raise ContainmentPolicyError("strict-readonly-v1 requires hard_limits resource enforcement")
        if self.profile_id == "darwin-seatbelt-experimental-v1" and self.resource_enforcement != "observed_memory":
            raise ContainmentPolicyError(
                "darwin-seatbelt-experimental-v1 requires observed_memory resource enforcement"
            )
        if self.resource_enforcement == "observed_memory" and self.profile_id != "darwin-seatbelt-experimental-v1":
            raise ContainmentPolicyError("observed_memory is reserved for the explicit Darwin experimental profile")
        object.__setattr__(self, "resource_enforcement", self.resource_enforcement)
        if not isinstance(self.budget, ResourceBudget):
            raise ContainmentPolicyError("budget must be a ResourceBudget")
        if not isinstance(self.thread_count, int) or isinstance(self.thread_count, bool) or self.thread_count != 1:
            raise ContainmentPolicyError("thread_count must be exactly one")
        locale = _text(self.locale, "locale", maximum=64)
        object.__setattr__(self, "locale", locale)
        if not isinstance(self.environment_allowlist, Mapping) or len(self.environment_allowlist) > 32:
            raise ContainmentPolicyError("environment_allowlist must be bounded")
        normalized: dict[str, str] = {}
        for key, value in self.environment_allowlist.items():
            if not isinstance(key, str) or not _ENV_NAME.fullmatch(key) or key not in _ALLOWED_ENV_NAMES:
                raise ContainmentPolicyError("environment_allowlist contains an unapproved variable")
            normalized[key] = _text(value, f"environment_allowlist.{key}", maximum=256)
        if normalized.get("LC_ALL") not in {None, locale} and normalized.get("LANG") not in {None, locale}:
            raise ContainmentPolicyError("environment locale must match policy locale")
        object.__setattr__(self, "environment_allowlist", MappingProxyType(normalized))

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


__all__ = ["ContainmentPolicy", "ContainmentPolicyError"]
