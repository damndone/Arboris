from __future__ import annotations

import pytest

from workbench.domain_memory.scope import DomainMemoryScopeError, MemoryScope


def _scope(**kwargs: object) -> MemoryScope:
    values = {
        "namespace_id": "ns-a", "profile_id": "profile-a", "owner_id": "user-a", "organization_id": "org-a",
        "visibility_scope": "private", "promotion_scope": "user",
    }
    values.update(kwargs)
    return MemoryScope(**values)


def test_private_scope_isolated_by_owner_and_namespace() -> None:
    scope = _scope()
    assert scope.can_read(_scope())
    assert not scope.can_read(_scope(owner_id="user-b"))
    assert not scope.can_read(_scope(namespace_id="ns-b"))
    assert MemoryScope.from_dict(scope.to_dict()) == scope


def test_organization_scope_requires_matching_org() -> None:
    scope = _scope(visibility_scope="organization")
    assert scope.can_read(_scope(visibility_scope="organization"))
    assert not scope.can_read(_scope(visibility_scope="organization", organization_id="org-b"))
    with pytest.raises(DomainMemoryScopeError):
        _scope(visibility_scope="organization", organization_id=None)


def test_scope_rejects_path_like_identity() -> None:
    with pytest.raises(DomainMemoryScopeError):
        _scope(owner_id="/tmp/user")
