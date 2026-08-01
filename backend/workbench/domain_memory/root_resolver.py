"""Resolve an explicit memory scope to a non-symlink storage boundary."""

from __future__ import annotations

import os
from pathlib import Path

from .scope import DomainMemoryScopeError, MemoryScope


class DomainMemoryRootError(DomainMemoryScopeError):
    """The domain-memory root cannot be safely resolved."""


_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _reject_symlink_ancestors(path: Path) -> None:
    """Reject a requested boundary when any caller-controlled ancestor is a link."""

    current = Path(path.anchor)
    for segment in path.parts[1:]:
        current = current / segment
        if current.is_symlink():
            raise DomainMemoryRootError("memory base directory must not traverse symlinks")


def resolve_domain_memory_root(base_dir: Path | str, scope: MemoryScope, *, create: bool = True) -> Path:
    if not isinstance(scope, MemoryScope):
        raise DomainMemoryRootError("scope is required")
    base = Path(base_dir).expanduser()
    if not base.is_absolute():
        raise DomainMemoryRootError("memory base directory must be absolute")
    _reject_symlink_ancestors(base)
    if base.is_symlink() or (base.exists() and not base.is_dir()):
        raise DomainMemoryRootError("memory base directory must be a real directory")
    if not base.exists():
        if not create:
            raise DomainMemoryRootError("memory base directory is unavailable")
        base.mkdir(parents=True, exist_ok=True)
    current = base
    segments = [scope.namespace_id, scope.profile_id]
    segments.append(scope.organization_id if scope.visibility_scope == "organization" else scope.owner_id)
    for segment in segments:
        current = current / segment
        if current.exists():
            if current.is_symlink() or not current.is_dir():
                raise DomainMemoryRootError("memory scope path must not contain symlinks")
        elif create:
            current.mkdir()
        else:
            raise DomainMemoryRootError("memory scope path is unavailable")
    try:
        fd = os.open(os.fspath(current), os.O_RDONLY | os.O_DIRECTORY | _O_NOFOLLOW)
    except OSError as error:
        raise DomainMemoryRootError("memory scope path could not be safely opened") from error
    else:
        os.close(fd)
    return current


__all__ = ["DomainMemoryRootError", "resolve_domain_memory_root"]
