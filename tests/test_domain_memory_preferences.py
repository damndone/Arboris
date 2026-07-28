from __future__ import annotations

from workbench.domain_memory.preferences import DomainMemoryPreferences, DomainMemoryRequestOverride, resolve_preferences
from workbench.domain_memory.scope import MemoryScope


SCOPE = MemoryScope("ns-a", "profile-a", "user-a", "org-a", "private", "user")


def test_both_domain_memory_controls_are_default_off_and_independent() -> None:
    defaults = DomainMemoryPreferences()
    resolved = resolve_preferences(SCOPE, defaults)
    assert resolved.use is False
    assert resolved.iteration is False
    one_run = resolve_preferences(SCOPE, defaults, DomainMemoryRequestOverride(cross_project_domain_memory_use=True))
    assert one_run.use is True
    assert one_run.iteration is False
    assert defaults == DomainMemoryPreferences()


def test_override_is_scoped_and_hashable() -> None:
    a = resolve_preferences(SCOPE, DomainMemoryPreferences(), DomainMemoryRequestOverride(cross_project_domain_memory_iteration=True))
    b = resolve_preferences(MemoryScope("ns-b", "profile-a", "user-a", "org-a", "private", "user"), DomainMemoryPreferences(), DomainMemoryRequestOverride(cross_project_domain_memory_iteration=True))
    assert a.override_applied is True
    assert a.preference_ref != b.preference_ref
