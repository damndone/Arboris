"""Safe, default-off local bootstrap for Workbench domain memory.

This module owns only local storage construction and canonical scope derivation.
It deliberately does not accept a scope from an HTTP request, perform retrieval,
or enable memory use for any project.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path

from .candidate_store import MemoryCandidateStore
from .conflicts import ConflictStore
from .review_service import MemoryReviewService
from .root_resolver import DomainMemoryRootError, resolve_domain_memory_root
from .scope import MemoryScope
from .service import DomainMemoryService
from .store import DomainMemoryStore


_LOCAL_NAMESPACE_ID = "workbench-local"
_LOCAL_PROFILE_ID = "default"
_GLOBAL_LIBRARY_OWNER_ID = "global-library"
_LOCAL_MEMORY_ROOT_ENV = "WORKBENCH_DOMAIN_MEMORY_ROOT"


class LocalDomainMemoryRuntimeError(ValueError):
    """The local memory runtime cannot establish a safe storage boundary."""


@dataclass(frozen=True, slots=True)
class LocalMemoryScopeResolver:
    """Resolve local global and project scopes without retaining raw paths."""

    global_scope: MemoryScope

    def project_scope(self, project_root: Path | str) -> MemoryScope:
        try:
            canonical = Path(project_root).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise LocalDomainMemoryRuntimeError("project root is unavailable") from error
        if not canonical.is_dir():
            raise LocalDomainMemoryRuntimeError("project root must be a directory")
        digest = hashlib.sha256(os.fsencode(canonical)).hexdigest()
        return MemoryScope(
            namespace_id=_LOCAL_NAMESPACE_ID,
            profile_id=_LOCAL_PROFILE_ID,
            owner_id=f"project-{digest}",
            organization_id=None,
            visibility_scope="private",
            promotion_scope="user",
        )


@dataclass(frozen=True, slots=True)
class LocalDomainMemoryRuntime:
    """The empty local global library installed during normal application start."""

    base_dir: Path
    scope_resolver: LocalMemoryScopeResolver
    candidate_store: MemoryCandidateStore
    service: DomainMemoryService
    review_service: MemoryReviewService


def default_local_domain_memory_base_dir() -> Path:
    """Return the user-owned local store root, honoring an explicit test override."""

    configured = os.environ.get(_LOCAL_MEMORY_ROOT_ENV)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".config" / "workbench" / "domain-memory"


def _make_private(directory: Path) -> None:
    try:
        stat_result = directory.stat()
        if stat_result.st_uid != os.geteuid():
            raise LocalDomainMemoryRuntimeError("local memory directory must be owned by this user")
        os.chmod(directory, 0o700)
    except OSError as error:
        raise LocalDomainMemoryRuntimeError("local memory directory could not be made private") from error


def bootstrap_local_domain_memory_runtime(
    base_dir: Path | str | None = None,
) -> LocalDomainMemoryRuntime:
    """Create the empty local global library or reject an unsafe/corrupt boundary.

    The runtime starts with no approved content and no enabled preferences.  A
    later Settings action may opt a project into using a separately resolved
    scope, but no request may supply that scope directly.
    """

    root = (Path(base_dir) if base_dir is not None else default_local_domain_memory_base_dir()).expanduser()
    global_scope = MemoryScope(
        namespace_id=_LOCAL_NAMESPACE_ID,
        profile_id=_LOCAL_PROFILE_ID,
        owner_id=_GLOBAL_LIBRARY_OWNER_ID,
        organization_id=None,
        visibility_scope="private",
        promotion_scope="user",
    )
    try:
        store_root = resolve_domain_memory_root(root, global_scope)
        _make_private(root)
        _make_private(store_root)
        store = DomainMemoryStore(store_root, global_scope, create=False)
        candidate_store = MemoryCandidateStore(store_root, global_scope, create=False)
        # Force a bounded journal parse now: corruption is a no-memory state,
        # never a deferred exception after a user enables the feature.
        store.list_content()
        candidate_store.pending(global_scope)
        conflict_store = ConflictStore(store_root, global_scope, create=False)
        conflict_store._read()
        service = DomainMemoryService(store, candidate_store)
        review_service = MemoryReviewService(service, candidate_store, conflict_store)
    except (DomainMemoryRootError, OSError, ValueError) as error:
        raise LocalDomainMemoryRuntimeError("local memory runtime is not safe") from error
    return LocalDomainMemoryRuntime(
        base_dir=root,
        scope_resolver=LocalMemoryScopeResolver(global_scope),
        candidate_store=candidate_store,
        service=service,
        review_service=review_service,
    )


__all__ = [
    "LocalDomainMemoryRuntime",
    "LocalDomainMemoryRuntimeError",
    "LocalMemoryScopeResolver",
    "bootstrap_local_domain_memory_runtime",
    "default_local_domain_memory_base_dir",
]
