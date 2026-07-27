"""Unmounted API adapter for explicit domain-memory controls.

Integration must mount this router only after the shared Notebook and Trace seams
are prepared. The adapter has no route that starts analysis or executes code.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..domain_memory.contracts import MemoryCandidate
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
    requester_scope: dict[str, Any]
    preferences: PreferenceBody = Field(default_factory=PreferenceBody)
    override: OverrideBody = Field(default_factory=OverrideBody)
    facts: dict[str, Any] = Field(default_factory=dict)
    now: str = Field(min_length=1, max_length=64)
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


router = APIRouter(prefix="/domain-memory", tags=["domain-memory"])


def _service(request: Request) -> DomainMemoryService:
    service = getattr(request.app.state, "domain_memory_service", None)
    if not isinstance(service, DomainMemoryService):
        raise HTTPException(status_code=503, detail={"code": "DOMAIN_MEMORY_UNAVAILABLE"})
    return service


def _review_service(request: Request) -> MemoryReviewService:
    service = getattr(request.app.state, "domain_memory_review_service", None)
    if not isinstance(service, MemoryReviewService):
        raise HTTPException(status_code=503, detail={"code": "DOMAIN_MEMORY_REVIEW_UNAVAILABLE"})
    return service


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


@router.post("/retrieve")
def retrieve_memory(body: RetrieveBody, request: Request) -> dict[str, Any]:
    service = _service(request)
    try:
        result = service.retrieve(
            requester=MemoryScope.from_dict(body.requester_scope), global_preferences=_preferences(body.preferences),
            override=_override(body.override), facts=body.facts, now=body.now,
            max_entries=body.max_entries, max_bytes=body.max_bytes,
        )
    except (ValueError, TypeError, KeyError) as error:
        raise HTTPException(status_code=400, detail={"code": "DOMAIN_MEMORY_REQUEST_INVALID", "message": str(error)}) from error
    return result.to_context_projection()


@router.post("/candidates")
def create_candidate(body: CandidateBody, request: Request) -> dict[str, Any]:
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
    review = _review_service(request)
    try:
        result = review.restore_memory(memory_id, actor_id=body.actor_id, approved_at=body.approved_at, evidence_ref=body.evidence_ref)
    except (MemoryReviewServiceError, ValueError, TypeError, KeyError) as error:
        raise HTTPException(status_code=409, detail={"code": "DOMAIN_MEMORY_REVIEW_FAILED", "message": str(error)}) from error
    return {"content": result.content.to_dict(), "approval": result.approval.to_dict(), "validity": result.validity.to_dict(), "automatic_execution": False}


__all__ = ["router"]
