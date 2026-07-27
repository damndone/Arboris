"""Independent, default-off domain-memory controls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..custom_capability.canonical import domain_digest
from .scope import MemoryScope


@dataclass(frozen=True, slots=True)
class DomainMemoryPreferences:
    cross_project_domain_memory_use: bool = False
    cross_project_domain_memory_iteration: bool = False

    def __post_init__(self) -> None:
        if type(self.cross_project_domain_memory_use) is not bool or type(self.cross_project_domain_memory_iteration) is not bool:
            raise ValueError("domain-memory preferences must be booleans")

    def to_dict(self) -> dict[str, bool]:
        return {
            "cross_project_domain_memory_use": self.cross_project_domain_memory_use,
            "cross_project_domain_memory_iteration": self.cross_project_domain_memory_iteration,
        }


@dataclass(frozen=True, slots=True)
class DomainMemoryRequestOverride:
    cross_project_domain_memory_use: bool | None = None
    cross_project_domain_memory_iteration: bool | None = None

    def __post_init__(self) -> None:
        if self.cross_project_domain_memory_use is not None and type(self.cross_project_domain_memory_use) is not bool:
            raise ValueError("use override must be boolean or null")
        if self.cross_project_domain_memory_iteration is not None and type(self.cross_project_domain_memory_iteration) is not bool:
            raise ValueError("iteration override must be boolean or null")


@dataclass(frozen=True, slots=True)
class EffectiveDomainMemoryPreferences:
    use: bool
    iteration: bool
    preference_ref: str
    scope_ref: str
    override_applied: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "use": self.use,
            "iteration": self.iteration,
            "preference_ref": self.preference_ref,
            "scope_ref": self.scope_ref,
            "override_applied": self.override_applied,
        }


def resolve_preferences(
    scope: MemoryScope, global_preferences: DomainMemoryPreferences, override: DomainMemoryRequestOverride | None = None
) -> EffectiveDomainMemoryPreferences:
    if not isinstance(scope, MemoryScope):
        raise ValueError("scope is required")
    if not isinstance(global_preferences, DomainMemoryPreferences):
        raise ValueError("global_preferences is required")
    override = override or DomainMemoryRequestOverride()
    use = global_preferences.cross_project_domain_memory_use if override.cross_project_domain_memory_use is None else override.cross_project_domain_memory_use
    iteration = global_preferences.cross_project_domain_memory_iteration if override.cross_project_domain_memory_iteration is None else override.cross_project_domain_memory_iteration
    values = {"scope": scope.to_dict(), "use": use, "iteration": iteration}
    return EffectiveDomainMemoryPreferences(
        use=use,
        iteration=iteration,
        preference_ref=domain_digest("workbench.domain-memory.preference/v1", values),
        scope_ref=scope.scope_ref,
        override_applied=override.cross_project_domain_memory_use is not None or override.cross_project_domain_memory_iteration is not None,
    )


__all__ = ["DomainMemoryPreferences", "DomainMemoryRequestOverride", "EffectiveDomainMemoryPreferences", "resolve_preferences"]
