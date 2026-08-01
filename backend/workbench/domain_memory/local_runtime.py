"""Safe, default-off local bootstrap for Workbench domain memory.

This module owns only local storage construction and canonical scope derivation.
It deliberately does not accept a scope from an HTTP request, perform retrieval,
or enable memory use for any project.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from threading import RLock

from .candidate_store import MemoryCandidateStore
from .confirmation import MemoryMutationConfirmationRegistry
from .conflicts import ConflictStore
from .local_preferences import LocalMemoryPreferenceStore
from .review_service import MemoryReviewService
from .root_resolver import DomainMemoryRootError, resolve_domain_memory_root
from .scope import MemoryScope
from .service import DomainMemoryService
from .store import DomainMemoryStore, DomainMemoryStoreError
from .preferences import DomainMemoryPreferences
from .retrieval import DomainMemoryRetrieval, RetrievalOmission, RetrievedMemoryHint


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


class MemoryStoreSet:
    """Open only runtime-derived global or project stores under one local root."""

    def __init__(self, base_dir: Path, global_scope: MemoryScope) -> None:
        self.base_dir = base_dir
        self.global_scope = global_scope
        self._services: dict[str, DomainMemoryService] = {}
        self._reviews: dict[str, MemoryReviewService] = {}
        self._lock = RLock()

    def service_for(self, scope: MemoryScope, *, create: bool) -> DomainMemoryService:
        if not isinstance(scope, MemoryScope):
            raise LocalDomainMemoryRuntimeError("memory scope is required")
        with self._lock:
            cached = self._services.get(scope.scope_ref)
            if cached is not None:
                return cached
            try:
                store_root = resolve_domain_memory_root(self.base_dir, scope, create=create)
                _make_private(store_root)
                store = DomainMemoryStore(store_root, scope, create=False)
                candidates = MemoryCandidateStore(store_root, scope, create=False)
                conflicts = ConflictStore(store_root, scope, create=False)
                # Parse now, not after the user has enabled a library.
                store.list_content()
                candidates.pending(scope)
                conflicts._read()
            except (DomainMemoryRootError, OSError, ValueError) as error:
                raise LocalDomainMemoryRuntimeError("local memory store is not safe") from error
            service = DomainMemoryService(store, candidates)
            self._services[scope.scope_ref] = service
            self._reviews[scope.scope_ref] = MemoryReviewService(service, candidates, conflicts)
            return service

    def review_service_for(self, scope: MemoryScope, *, create: bool) -> MemoryReviewService:
        self.service_for(scope, create=create)
        return self._reviews[scope.scope_ref]


@dataclass(frozen=True, slots=True)
class LocalDomainMemoryRuntime:
    """The empty local global library installed during normal application start."""

    base_dir: Path
    scope_resolver: LocalMemoryScopeResolver
    candidate_store: MemoryCandidateStore
    service: DomainMemoryService
    review_service: MemoryReviewService
    stores: MemoryStoreSet
    preferences: LocalMemoryPreferenceStore
    confirmations: MemoryMutationConfirmationRegistry

    def project_scope(self, project_root: Path | str) -> MemoryScope:
        return self.scope_resolver.project_scope(project_root)

    def service_for_project(self, project_root: Path | str, *, create: bool = False) -> DomainMemoryService:
        return self.stores.service_for(self.project_scope(project_root), create=create)

    def review_service_for_project(self, project_root: Path | str, *, create: bool = False) -> MemoryReviewService:
        return self.stores.review_service_for(self.project_scope(project_root), create=create)

    def retrieve_for_project(
        self,
        project_root: Path | str,
        *,
        facts: dict[str, object],
        now: str,
        max_entries: int,
        max_bytes: int,
        vocabulary_version: str | None = None,
    ) -> DomainMemoryRetrieval:
        """Read only local libraries that persisted settings explicitly allow."""

        project_scope = self.project_scope(project_root)
        global_settings = self.preferences.global_settings()
        project_settings = self.preferences.project_settings(project_scope)
        preference_ref = self._preference_ref(global_settings.revision, project_settings)
        if not project_settings.library_enabled and not (
            global_settings.library_enabled and project_settings.inherit_global
        ):
            return DomainMemoryRetrieval(
                retrieval_ref="retrieval-" + preference_ref[:40],
                scope_ref=project_scope.scope_ref,
                outcome="not_used",
                reason="DOMAIN_MEMORY_DISABLED",
                entries=(),
                omissions=(),
                bounded=True,
                preference_ref=preference_ref,
            )

        effective = DomainMemoryPreferences(cross_project_domain_memory_use=True)
        results: list[DomainMemoryRetrieval] = []
        try:
            if project_settings.library_enabled:
                results.append(
                    self.service_for_project(project_root, create=False).retrieve(
                        requester=project_scope,
                        global_preferences=effective,
                        facts=facts,
                        now=now,
                        max_entries=max_entries,
                        max_bytes=max_bytes,
                        vocabulary_version=vocabulary_version,
                    )
                )
            if global_settings.library_enabled and project_settings.inherit_global:
                results.append(
                    self.service.retrieve(
                        requester=self.scope_resolver.global_scope,
                        global_preferences=effective,
                        facts=facts,
                        now=now,
                        max_entries=max_entries,
                        max_bytes=max_bytes,
                        vocabulary_version=vocabulary_version,
                    )
                )
        except DomainMemoryStoreError as error:
            raise LocalDomainMemoryRuntimeError("local memory store is unavailable") from error
        return self._merge_retrievals(
            project_scope=project_scope,
            preference_ref=preference_ref,
            results=results,
            max_entries=max_entries,
            max_bytes=max_bytes,
        )

    @staticmethod
    def _preference_ref(global_revision: int, project_settings: object) -> str:
        payload = {
            "global_revision": global_revision,
            "project": {
                "scope_ref": getattr(project_settings, "scope_ref", None),
                "revision": getattr(project_settings, "revision", None),
                "library_enabled": getattr(project_settings, "library_enabled", None),
                "inherit_global": getattr(project_settings, "inherit_global", None),
                "candidate_generation_enabled": getattr(project_settings, "candidate_generation_enabled", None),
            },
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _merge_retrievals(
        *,
        project_scope: MemoryScope,
        preference_ref: str,
        results: list[DomainMemoryRetrieval],
        max_entries: int,
        max_bytes: int,
    ) -> DomainMemoryRetrieval:
        entries: list[RetrievedMemoryHint] = []
        omissions: list[RetrievalOmission] = []
        seen: set[tuple[str, int]] = set()
        used_bytes = 0
        for result in results:
            omissions.extend(result.omissions)
            for entry in result.entries:
                identity = (entry.memory_id, entry.revision)
                if identity in seen:
                    omissions.append(RetrievalOmission(entry.memory_id, entry.revision, "duplicate_scope_memory"))
                    continue
                seen.add(identity)
                if len(entries) >= max_entries:
                    omissions.append(RetrievalOmission(entry.memory_id, entry.revision, "entry_budget"))
                    continue
                encoded = json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                if len(encoded) > max_bytes or used_bytes + len(encoded) > max_bytes:
                    omissions.append(RetrievalOmission(entry.memory_id, entry.revision, "byte_budget"))
                    continue
                entries.append(entry)
                used_bytes += len(encoded)
        return DomainMemoryRetrieval(
            retrieval_ref="retrieval-" + preference_ref[:40],
            scope_ref=project_scope.scope_ref,
            outcome="used" if entries else "empty",
            reason="retrieved" if entries else "no_eligible_memory",
            entries=tuple(entries),
            omissions=tuple(omissions),
            bounded=True,
            preference_ref=preference_ref,
        )


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
        stores = MemoryStoreSet(root, global_scope)
        service = stores.service_for(global_scope, create=False)
        candidate_store = service.candidate_store
        review_service = stores.review_service_for(global_scope, create=False)
        preferences = LocalMemoryPreferenceStore(root)
        confirmations = MemoryMutationConfirmationRegistry()
    except (DomainMemoryRootError, OSError, ValueError) as error:
        raise LocalDomainMemoryRuntimeError("local memory runtime is not safe") from error
    return LocalDomainMemoryRuntime(
        base_dir=root,
        scope_resolver=LocalMemoryScopeResolver(global_scope),
        candidate_store=candidate_store,
        service=service,
        review_service=review_service,
        stores=stores,
        preferences=preferences,
        confirmations=confirmations,
    )


__all__ = [
    "LocalDomainMemoryRuntime",
    "LocalDomainMemoryRuntimeError",
    "LocalMemoryScopeResolver",
    "bootstrap_local_domain_memory_runtime",
    "default_local_domain_memory_base_dir",
]
