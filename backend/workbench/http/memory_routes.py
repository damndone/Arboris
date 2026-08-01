"""Local control-plane API for explicit domain-memory settings and review.

The router has no route that starts analysis or executes code.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..domain_memory.confirmation import MemoryMutationConfirmationError, MemoryMutationIntent
from ..domain_memory.contracts import MemoryCandidate
from ..domain_memory.local_runtime import (
    LocalDomainMemoryRuntime,
    LocalDomainMemoryRuntimeError,
)
from ..domain_memory.local_preferences import LocalMemoryPreferenceError
from ..domain_memory.preferences import DomainMemoryPreferences, DomainMemoryRequestOverride
from ..domain_memory.scope import MemoryScope
from ..domain_memory.service import DomainMemoryService, DomainMemoryServiceError
from ..domain_memory.review_service import MemoryReviewService, MemoryReviewServiceError


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreferenceBody(_StrictModel):
    cross_project_domain_memory_use: bool = False
    cross_project_domain_memory_iteration: bool = False


class OverrideBody(_StrictModel):
    cross_project_domain_memory_use: bool | None = None
    cross_project_domain_memory_iteration: bool | None = None


class RetrieveBody(_StrictModel):
    facts: dict[str, Any] = Field(default_factory=dict)
    max_entries: int = Field(default=8, ge=0, le=32)
    max_bytes: int = Field(default=8192, ge=256, le=32768)


class CandidateBody(_StrictModel):
    candidate: dict[str, Any]
    preferences: PreferenceBody = Field(default_factory=PreferenceBody)
    override: OverrideBody = Field(default_factory=OverrideBody)


class ApproveBody(_StrictModel):
    expected_revision: int = Field(ge=1)
    approver_id: str = Field(min_length=1, max_length=128)
    approved_at: str = Field(min_length=1, max_length=64)
    review_after: str = Field(min_length=1, max_length=64)
    preferences: PreferenceBody = Field(default_factory=PreferenceBody)
    override: OverrideBody = Field(default_factory=OverrideBody)


class CandidateReviewBody(_StrictModel):
    decision: Literal["approved", "rejected"]
    expected_revision: int = Field(ge=1)
    actor_id: str = Field(min_length=1, max_length=128)
    approved_at: str | None = Field(default=None, min_length=1, max_length=64)
    review_after: str | None = Field(default=None, min_length=1, max_length=64)
    resolve_conflicts: bool = False


class MemoryStateBody(_StrictModel):
    expected_approval_ref: str = Field(min_length=1, max_length=256)
    expected_validity_revision: int = Field(ge=1)
    state: Literal["stale", "archived"]
    actor_id: str = Field(min_length=1, max_length=128)
    effective_at: str = Field(min_length=1, max_length=64)


class MemoryRestoreBody(_StrictModel):
    actor_id: str = Field(min_length=1, max_length=128)
    approved_at: str = Field(min_length=1, max_length=64)
    evidence_ref: str = Field(min_length=1, max_length=256)


class SettingsConfirmationBody(_StrictModel):
    action: Literal[
        "enable_global_library",
        "disable_global_library",
        "enable_project_library",
        "disable_project_library",
        "enable_global_inheritance",
        "disable_global_inheritance",
        "enable_candidate_generation",
        "disable_candidate_generation",
    ]
    expected_revision: int = Field(ge=0)
    target_refs: list[str] = Field(default_factory=list, max_length=1024)


class GlobalSettingsBody(_StrictModel):
    library_enabled: bool
    expected_revision: int = Field(ge=0)
    confirmation_receipt: str = Field(min_length=1, max_length=256)


class ProjectSettingsBody(_StrictModel):
    setting: Literal["library_enabled", "inherit_global", "candidate_generation_enabled"]
    enabled: bool
    expected_revision: int = Field(ge=0)
    confirmation_receipt: str = Field(min_length=1, max_length=256)


class ArchiveConfirmationBody(_StrictModel):
    memory_ids: list[str] = Field(min_length=1, max_length=1024)


class ArchiveBody(ArchiveConfirmationBody):
    confirmation_receipt: str = Field(min_length=1, max_length=256)


router = APIRouter(prefix="/domain-memory", tags=["domain-memory"])


def _service(request: Request) -> DomainMemoryService:
    service = getattr(request.app.state, "domain_memory_service", None)
    if not isinstance(service, DomainMemoryService):
        raise HTTPException(status_code=503, detail={"code": "DOMAIN_MEMORY_UNAVAILABLE"})
    return service


def _runtime(request: Request) -> LocalDomainMemoryRuntime:
    runtime = getattr(request.app.state, "domain_memory_runtime", None)
    if not isinstance(runtime, LocalDomainMemoryRuntime):
        raise HTTPException(status_code=503, detail={"code": "DOMAIN_MEMORY_IDENTITY_UNAVAILABLE"})
    return runtime


def _project_scope(runtime: LocalDomainMemoryRuntime, project_root: str) -> MemoryScope:
    try:
        return runtime.project_scope(project_root)
    except ValueError as error:
        raise HTTPException(status_code=400, detail={"code": "DOMAIN_MEMORY_PROJECT_INVALID", "message": str(error)}) from error


def _settings_payload(runtime: LocalDomainMemoryRuntime, project_root: str) -> dict[str, Any]:
    project_scope = _project_scope(runtime, project_root)
    global_settings = runtime.preferences.global_settings()
    project_settings = runtime.preferences.project_settings(project_scope)
    return {
        "global": {"revision": global_settings.revision, "library_enabled": global_settings.library_enabled},
        "project": {
            "revision": project_settings.revision,
            "library_enabled": project_settings.library_enabled,
            "inherit_global": project_settings.inherit_global,
            "candidate_generation_enabled": project_settings.candidate_generation_enabled,
        },
        "memory_authority": "server_owned",
    }


def _setting_action(setting: str, enabled: bool) -> str:
    actions = {
        "library_enabled": ("enable_project_library", "disable_project_library"),
        "inherit_global": ("enable_global_inheritance", "disable_global_inheritance"),
        "candidate_generation_enabled": ("enable_candidate_generation", "disable_candidate_generation"),
    }
    return actions[setting][0 if enabled else 1]


def _library_scope(runtime: LocalDomainMemoryRuntime, library: str, project_root: str) -> MemoryScope:
    if library == "global":
        return runtime.scope_resolver.global_scope
    if library == "project":
        return _project_scope(runtime, project_root)
    raise HTTPException(status_code=404, detail={"code": "DOMAIN_MEMORY_LIBRARY_UNKNOWN"})


def _library_entries(runtime: LocalDomainMemoryRuntime, scope: MemoryScope) -> list[dict[str, Any]]:
    try:
        service = runtime.stores.service_for(scope, create=False)
    except ValueError:
        # A project with no explicit opt-in has no project store yet. It is an
        # empty library, not an invitation to silently create storage on read.
        if not scope.exact_match(runtime.scope_resolver.global_scope):
            return []
        raise
    entries: list[dict[str, Any]] = []
    for content in service.store.list_content():
        approval = service.store.current_approval(content.memory_id)
        validity = service.store.latest_validity(content.memory_id)
        if approval is None or validity is None or approval.content_revision != content.revision:
            continue
        entries.append({
            "memory_id": content.memory_id,
            "revision": content.revision,
            "state": validity.state,
            "validity_revision": validity.validity_revision,
            # This is a bounded management projection, not retrieval evidence:
            # it lets a local user identify what they are about to archive
            # without disclosing provenance, predicates, or matching telemetry.
            "memory_kind": content.memory_kind,
            "domain_tags": list(content.domain_tags),
            "compact_lesson": content.compact_lesson,
            "apply_mode": content.apply_mode,
        })
    return sorted(entries, key=lambda item: (item["memory_id"], item["revision"]))


def _archive_target_refs(runtime: LocalDomainMemoryRuntime, scope: MemoryScope, memory_ids: list[str]) -> tuple[str, ...]:
    if len(set(memory_ids)) != len(memory_ids) or any(not item or len(item) > 256 for item in memory_ids):
        raise ValueError("memory ids must be unique bounded values")
    entries = {item["memory_id"]: item for item in _library_entries(runtime, scope) if item["state"] == "active"}
    if set(memory_ids) != set(entries).intersection(memory_ids):
        raise ValueError("one or more requested memories are not active")
    return tuple(sorted(
        f"{memory_id}@{entries[memory_id]['revision']}@{entries[memory_id]['validity_revision']}"
        for memory_id in memory_ids
    ))


def _review_service(request: Request) -> MemoryReviewService:
    service = getattr(request.app.state, "domain_memory_review_service", None)
    if not isinstance(service, MemoryReviewService):
        raise HTTPException(status_code=503, detail={"code": "DOMAIN_MEMORY_REVIEW_UNAVAILABLE"})
    return service


def _require_mutations_enabled(request: Request) -> None:
    """Keep the newly bootstrapped local library read-only until Settings opts in."""

    runtime = getattr(request.app.state, "domain_memory_runtime", None)
    if isinstance(runtime, LocalDomainMemoryRuntime) and getattr(
        request.app.state, "domain_memory_mutations_enabled", False
    ) is not True:
        raise HTTPException(status_code=503, detail={"code": "DOMAIN_MEMORY_MUTATIONS_DISABLED"})


def _preferences(body: PreferenceBody) -> DomainMemoryPreferences:
    return DomainMemoryPreferences(
        cross_project_domain_memory_use=body.cross_project_domain_memory_use,
        cross_project_domain_memory_iteration=body.cross_project_domain_memory_iteration,
    )


def _override(body: OverrideBody) -> DomainMemoryRequestOverride:
    return DomainMemoryRequestOverride(
        cross_project_domain_memory_use=body.cross_project_domain_memory_use,
        cross_project_domain_memory_iteration=body.cross_project_domain_memory_iteration,
    )


@router.get("/settings")
def get_settings(project_root: str, request: Request) -> dict[str, Any]:
    try:
        return _settings_payload(_runtime(request), project_root)
    except LocalMemoryPreferenceError as error:
        raise HTTPException(status_code=503, detail={"code": "DOMAIN_MEMORY_SETTINGS_UNAVAILABLE", "message": str(error)}) from error


@router.post("/settings/confirmations")
def issue_settings_confirmation(
    body: SettingsConfirmationBody, project_root: str, request: Request
) -> dict[str, Any]:
    runtime = _runtime(request)
    try:
        if body.target_refs:
            raise ValueError("settings confirmations do not accept targets")
        scope = runtime.scope_resolver.global_scope if body.action.endswith("global_library") else _project_scope(runtime, project_root)
        confirmation = runtime.confirmations.issue(
            MemoryMutationIntent(body.action, scope.scope_ref, body.expected_revision, ())
        )
    except (MemoryMutationConfirmationError, ValueError) as error:
        raise HTTPException(status_code=400, detail={"code": "DOMAIN_MEMORY_CONFIRMATION_INVALID", "message": str(error)}) from error
    return {
        "receipt": confirmation.receipt,
        "action": confirmation.action,
        "scope_ref": confirmation.scope_ref,
        "expected_revision": confirmation.expected_revision,
        "target_count": confirmation.target_count,
        "expires_at": confirmation.expires_at.isoformat().replace("+00:00", "Z"),
    }


@router.put("/settings/global")
def update_global_settings(body: GlobalSettingsBody, project_root: str, request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    action = "enable_global_library" if body.library_enabled else "disable_global_library"
    intent = MemoryMutationIntent(action, runtime.scope_resolver.global_scope.scope_ref, body.expected_revision, ())
    try:
        runtime.confirmations.consume(body.confirmation_receipt, intent)
        runtime.preferences.update_global(
            expected_revision=body.expected_revision, library_enabled=body.library_enabled
        )
        return _settings_payload(runtime, project_root)
    except MemoryMutationConfirmationError as error:
        raise HTTPException(status_code=409, detail={"code": "DOMAIN_MEMORY_CONFIRMATION_INVALID", "message": str(error)}) from error
    except LocalMemoryPreferenceError as error:
        raise HTTPException(status_code=409, detail={"code": "DOMAIN_MEMORY_SETTINGS_STALE", "message": str(error)}) from error


@router.put("/settings/project")
def update_project_settings(body: ProjectSettingsBody, project_root: str, request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    scope = _project_scope(runtime, project_root)
    action = _setting_action(body.setting, body.enabled)
    intent = MemoryMutationIntent(action, scope.scope_ref, body.expected_revision, ())
    try:
        runtime.confirmations.consume(body.confirmation_receipt, intent)
        current = runtime.preferences.project_settings(scope)
        values = {
            "library_enabled": current.library_enabled,
            "inherit_global": current.inherit_global,
            "candidate_generation_enabled": current.candidate_generation_enabled,
        }
        values[body.setting] = body.enabled
        if values["inherit_global"] and not runtime.preferences.global_settings().library_enabled:
            raise LocalMemoryPreferenceError("global library must be enabled before inheritance")
        if values["candidate_generation_enabled"] and not values["library_enabled"]:
            raise LocalMemoryPreferenceError("project library must be enabled before candidate generation")
        if body.setting == "library_enabled" and body.enabled:
            runtime.service_for_project(project_root, create=True)
        runtime.preferences.update_project(scope, expected_revision=body.expected_revision, **values)
        return _settings_payload(runtime, project_root)
    except MemoryMutationConfirmationError as error:
        raise HTTPException(status_code=409, detail={"code": "DOMAIN_MEMORY_CONFIRMATION_INVALID", "message": str(error)}) from error
    except LocalMemoryPreferenceError as error:
        raise HTTPException(status_code=409, detail={"code": "DOMAIN_MEMORY_SETTINGS_STALE", "message": str(error)}) from error


@router.get("/libraries/{library}")
def list_library(library: Literal["global", "project"], project_root: str, request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    scope = _library_scope(runtime, library, project_root)
    try:
        return {"library": library, "entries": _library_entries(runtime, scope), "memory_authority": "server_owned"}
    except ValueError as error:
        raise HTTPException(status_code=503, detail={"code": "DOMAIN_MEMORY_LIBRARY_UNAVAILABLE", "message": str(error)}) from error


@router.post("/libraries/{library}/archive/confirmations")
def issue_archive_confirmation(
    library: Literal["global", "project"],
    body: ArchiveConfirmationBody,
    project_root: str,
    request: Request,
) -> dict[str, Any]:
    runtime = _runtime(request)
    scope = _library_scope(runtime, library, project_root)
    try:
        target_refs = _archive_target_refs(runtime, scope, body.memory_ids)
        confirmation = runtime.confirmations.issue(
            MemoryMutationIntent("archive_memories", scope.scope_ref, 0, target_refs)
        )
    except (MemoryMutationConfirmationError, ValueError) as error:
        raise HTTPException(status_code=409, detail={"code": "DOMAIN_MEMORY_ARCHIVE_INVALID", "message": str(error)}) from error
    return {
        "receipt": confirmation.receipt,
        "action": confirmation.action,
        "scope_ref": confirmation.scope_ref,
        "target_count": confirmation.target_count,
        "expires_at": confirmation.expires_at.isoformat().replace("+00:00", "Z"),
    }


@router.post("/libraries/{library}/archive")
def archive_library_memories(
    library: Literal["global", "project"],
    body: ArchiveBody,
    project_root: str,
    request: Request,
) -> dict[str, Any]:
    runtime = _runtime(request)
    scope = _library_scope(runtime, library, project_root)
    try:
        target_refs = _archive_target_refs(runtime, scope, body.memory_ids)
        runtime.confirmations.consume(
            body.confirmation_receipt,
            MemoryMutationIntent("archive_memories", scope.scope_ref, 0, target_refs),
        )
        review = runtime.stores.review_service_for(scope, create=False)
        effective_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        for memory_id in body.memory_ids:
            approval = review.memory_service.store.current_approval(memory_id)
            validity = review.memory_service.store.current_validity(memory_id)
            if approval is None or validity is None:
                raise ValueError("requested memory is no longer active")
            review.change_memory_state(
                memory_id,
                expected_approval_ref=approval.approval_ref,
                expected_validity_revision=validity.validity_revision,
                state="archived",
                actor_id="local-user",
                effective_at=effective_at,
            )
    except MemoryMutationConfirmationError as error:
        raise HTTPException(status_code=409, detail={"code": "DOMAIN_MEMORY_CONFIRMATION_INVALID", "message": str(error)}) from error
    except (ValueError, MemoryReviewServiceError) as error:
        raise HTTPException(status_code=409, detail={"code": "DOMAIN_MEMORY_ARCHIVE_INVALID", "message": str(error)}) from error
    return {"archived_count": len(body.memory_ids), "entries": _library_entries(runtime, scope)}


@router.post("/retrieve")
def retrieve_memory(body: RetrieveBody, project_root: str, request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    try:
        result = runtime.retrieve_for_project(
            project_root,
            facts=body.facts,
            now=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            max_entries=body.max_entries,
            max_bytes=body.max_bytes,
        )
    except LocalDomainMemoryRuntimeError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "DOMAIN_MEMORY_UNAVAILABLE", "message": str(error)},
        ) from error
    except (ValueError, TypeError, KeyError) as error:
        raise HTTPException(status_code=400, detail={"code": "DOMAIN_MEMORY_REQUEST_INVALID", "message": str(error)}) from error
    return result.to_context_projection()


@router.post("/candidates")
def create_candidate(body: CandidateBody, request: Request) -> dict[str, Any]:
    _require_mutations_enabled(request)
    service = _service(request)
    try:
        candidate = service.create_candidate(
            MemoryCandidate.from_dict(body.candidate), global_preferences=_preferences(body.preferences), override=_override(body.override)
        )
    except (ValueError, TypeError, KeyError) as error:
        raise HTTPException(status_code=400, detail={"code": "DOMAIN_MEMORY_CANDIDATE_INVALID", "message": str(error)}) from error
    return {"candidate": candidate.to_dict(), "automatic_execution": False}


@router.post("/candidates/{candidate_id}/approve")
def approve_candidate(candidate_id: str, body: ApproveBody, request: Request) -> dict[str, Any]:
    _require_mutations_enabled(request)
    service = _service(request)
    try:
        result = service.approve_candidate(
            candidate_id, expected_revision=body.expected_revision, approver_id=body.approver_id,
            approved_at=body.approved_at, review_after=body.review_after,
            global_preferences=_preferences(body.preferences), override=_override(body.override),
        )
    except (DomainMemoryServiceError, ValueError, TypeError, KeyError) as error:
        raise HTTPException(status_code=409, detail={"code": "DOMAIN_MEMORY_APPROVAL_FAILED", "message": str(error)}) from error
    return {
        "content": result.content.to_dict(), "approval": result.approval.to_dict(), "validity": result.validity.to_dict(),
        "automatic_execution": False,
    }


@router.post("/review/candidates/{candidate_id}")
def review_candidate(candidate_id: str, body: CandidateReviewBody, request: Request) -> dict[str, Any]:
    _require_mutations_enabled(request)
    review = _review_service(request)
    try:
        if body.decision == "rejected":
            result = review.reject_candidate(candidate_id, expected_revision=body.expected_revision, actor_id=body.actor_id)
            return {"review": {"candidate_id": result.candidate_id, "revision": result.revision, "status": result.status}, "automatic_execution": False}
        if body.approved_at is None or body.review_after is None:
            raise MemoryReviewServiceError("approved_at and review_after are required for approval")
        result = review.approve_candidate(
            candidate_id, expected_revision=body.expected_revision, actor_id=body.actor_id,
            approved_at=body.approved_at, review_after=body.review_after, resolve_conflicts=body.resolve_conflicts,
        )
    except (MemoryReviewServiceError, ValueError, TypeError, KeyError) as error:
        raise HTTPException(status_code=409, detail={"code": "DOMAIN_MEMORY_REVIEW_FAILED", "message": str(error)}) from error
    return {"content": result.content.to_dict(), "approval": result.approval.to_dict(), "validity": result.validity.to_dict(), "automatic_execution": False}


@router.post("/review/memories/{memory_id}/state")
def change_memory_state(memory_id: str, body: MemoryStateBody, request: Request) -> dict[str, Any]:
    _require_mutations_enabled(request)
    review = _review_service(request)
    try:
        result = review.change_memory_state(
            memory_id, expected_approval_ref=body.expected_approval_ref, expected_validity_revision=body.expected_validity_revision,
            state=body.state, actor_id=body.actor_id, effective_at=body.effective_at,
        )
    except (MemoryReviewServiceError, ValueError, TypeError, KeyError) as error:
        raise HTTPException(status_code=409, detail={"code": "DOMAIN_MEMORY_REVIEW_FAILED", "message": str(error)}) from error
    return {"validity": result.to_dict(), "automatic_execution": False}


@router.post("/review/memories/{memory_id}/restore")
def restore_memory(memory_id: str, body: MemoryRestoreBody, request: Request) -> dict[str, Any]:
    _require_mutations_enabled(request)
    review = _review_service(request)
    try:
        result = review.restore_memory(memory_id, actor_id=body.actor_id, approved_at=body.approved_at, evidence_ref=body.evidence_ref)
    except (MemoryReviewServiceError, ValueError, TypeError, KeyError) as error:
        raise HTTPException(status_code=409, detail={"code": "DOMAIN_MEMORY_REVIEW_FAILED", "message": str(error)}) from error
    return {"content": result.content.to_dict(), "approval": result.approval.to_dict(), "validity": result.validity.to_dict(), "automatic_execution": False}


__all__ = ["router"]
