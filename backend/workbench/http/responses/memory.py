"""Domain memory: settings, libraries, retrieval, candidates and review.

Content revisions, approvals, validity records, candidates and retrieved hints
are derived from the domain-memory contract dataclasses; each record adds its
``contract_version`` (content revisions also have a legacy wire form with a
subset of fields).
"""

from __future__ import annotations

import dataclasses
from typing import Literal, NotRequired

from typing_extensions import TypedDict

from ...domain_memory.contracts import (
    ApplyMode,
    CandidateState,
    DomainMemoryApprovalRecord,
    DomainMemoryContentRevision,
    DomainMemoryValidityRecord,
    MemoryCandidate,
    ValidityState,
)
from ...domain_memory.retrieval import RetrievalOmission, RetrievalOutcome, RetrievedMemoryHint
from .common import view_of, viewed

_LEGACY_OMITTED = tuple(
    field.name
    for field in dataclasses.fields(DomainMemoryContentRevision)
    if field.name not in DomainMemoryContentRevision._legacy_field_names() and field.name != "content_hash"
)

ContentRevisionView = view_of(
    DomainMemoryContentRevision, "ContentRevisionView", omit=("serialized_contract_version",), contract_version=str
)
LegacyContentRevisionView = view_of(
    DomainMemoryContentRevision, "LegacyContentRevisionView", omit=_LEGACY_OMITTED, contract_version=str
)
ApprovalView = view_of(DomainMemoryApprovalRecord, "ApprovalView", contract_version=str)
ValidityView = view_of(DomainMemoryValidityRecord, "ValidityView", contract_version=str)
CandidateView = view_of(MemoryCandidate, "CandidateView", contract_version=str)
RetrievalOmissionView = viewed(RetrievalOmission)
class MemorySource(TypedDict):
    memory_id: str
    revision: int


RetrievedHintView = view_of(
    RetrievedMemoryHint,
    "RetrievedHintView",
    memory_authority=Literal["non_authoritative_hint"],
    memory_source=MemorySource,
)


class GlobalMemorySettings(TypedDict):
    revision: int
    library_enabled: bool


class ProjectMemorySettings(TypedDict):
    revision: int
    library_enabled: bool
    inherit_global: bool
    candidate_generation_enabled: bool


# "global" is a Python keyword, so the settings use the functional form.
MemorySettings = TypedDict(  # type: ignore[misc]
    "MemorySettings",
    {"global": GlobalMemorySettings, "project": ProjectMemorySettings, "memory_authority": Literal["server_owned"]},
)


class ConfirmationReceipt(TypedDict):
    """A short-lived receipt the next write must present; the write is
    rejected without it."""

    receipt: str
    action: str
    scope_ref: str
    target_count: int
    expires_at: str
    expected_revision: NotRequired[int]


class LibraryEntry(TypedDict):
    memory_id: str
    revision: int
    state: ValidityState
    validity_revision: int
    memory_kind: str
    domain_tags: list[str]
    compact_lesson: str
    apply_mode: ApplyMode


class MemoryLibrary(TypedDict):
    library: Literal["global", "project"]
    entries: list[LibraryEntry]
    memory_authority: Literal["server_owned"]


class MemoryArchived(TypedDict):
    archived_count: int
    entries: list[LibraryEntry]


class MemoryRetrieval(TypedDict):
    contract_version: Literal["domain-memory-context-input/v3"]
    retrieval_ref: str
    scope_ref: str
    outcome: RetrievalOutcome
    reason: str
    entries: list[RetrievedHintView]
    omissions: list[RetrievalOmissionView]
    bounded: bool
    preference_ref: str
    memory_authority: Literal["non_authoritative"]


class CandidateCreated(TypedDict):
    candidate: CandidateView
    automatic_execution: Literal[False]


class PendingCandidate(TypedDict):
    candidate_id: str
    revision: int
    status: CandidateState
    memory_kind: str
    compact_lesson: str
    source_summary_refs: list[str]


class PendingCandidates(TypedDict):
    candidates: list[PendingCandidate]
    memory_authority: Literal["server_owned"]


class MemoryReviewed(TypedDict):
    content: ContentRevisionView | LegacyContentRevisionView
    approval: ApprovalView
    validity: ValidityView
    automatic_execution: Literal[False]


class MemoryStateChanged(TypedDict):
    validity: ValidityView
    automatic_execution: Literal[False]


class CandidateRejection(TypedDict):
    candidate_id: str
    revision: int
    status: CandidateState


class CandidateRejected(TypedDict):
    review: CandidateRejection
    automatic_execution: Literal[False]


CandidateReviewed = MemoryReviewed | CandidateRejected
