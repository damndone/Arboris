from __future__ import annotations

from pathlib import Path

import pytest

from workbench.domain_memory.root_resolver import DomainMemoryRootError, resolve_domain_memory_root
from workbench.domain_memory.scope import MemoryScope


def _scope(**kwargs: object) -> MemoryScope:
    values = {
        "namespace_id": "ns-a", "profile_id": "profile-a", "owner_id": "user-a", "organization_id": "org-a",
        "visibility_scope": "private", "promotion_scope": "user",
    }
    values.update(kwargs)
    return MemoryScope(**values)


def test_root_is_explicitly_namespace_and_profile_separated(tmp_path: Path) -> None:
    root = resolve_domain_memory_root(tmp_path / "memory", _scope())
    assert root == tmp_path / "memory" / "ns-a" / "profile-a" / "user-a"
    assert root.is_dir()


def test_root_rejects_relative_or_symlink_base(tmp_path: Path) -> None:
    with pytest.raises(DomainMemoryRootError):
        resolve_domain_memory_root(Path("relative-root"), _scope())
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(DomainMemoryRootError):
        resolve_domain_memory_root(link, _scope())
