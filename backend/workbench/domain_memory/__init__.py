"""Versioned, opt-in domain-memory foundations for Workbench."""

from .context_projection import ProjectContextProjection, ProjectionOmission, project_index_to_context
from .project_index_builder import ProjectContextIndexBuilder, ProjectIndexBuildError
from .project_index_contract import (
    FACT_KINDS,
    PROJECT_CONTEXT_INDEX_CONTRACT_VERSION,
    SOURCE_KINDS,
    ProjectContextFact,
    ProjectContextIndex,
    ProjectIndexError,
    SourceManifestEntry,
)
from .project_index_store import ProjectContextIndexStore, ProjectIndexStoreConflict, ProjectIndexStoreError
from .trace_contracts import (
    DomainMemoryTraceError,
    ProjectMemoryTraceError,
    ProjectMemoryTraceEvent,
    TRACE_CONTRACT_VERSION,
    build_domain_memory_trace,
    build_project_memory_trace,
)
from .candidate_store import MemoryCandidateStore, MemoryCandidateStoreConflict, MemoryCandidateStoreError
from .contracts import (
    ApplicabilityPredicate,
    DomainMemoryApprovalRecord,
    DomainMemoryContentRevision,
    DomainMemoryContractError,
    DomainMemoryValidityRecord,
    MemoryCandidate,
    SourceSummaryRef,
)
from .preferences import DomainMemoryPreferences, DomainMemoryRequestOverride, EffectiveDomainMemoryPreferences, resolve_preferences
from .retrieval import DomainMemoryRetrieval, DomainMemoryRetrievalError, RetrievedMemoryHint, RetrievalOmission, retrieve_domain_memory
from .scope import DomainMemoryScopeError, MemoryScope
from .service import CandidateApprovalResult, DomainMemoryService, DomainMemoryServiceError
from .source_access import SourceAccessBinding, SourceAccessValidityRecord
from .store import DomainMemoryStore, DomainMemoryStoreConflict, DomainMemoryStoreError

__all__ = [
    "FACT_KINDS",
    "ApplicabilityPredicate",
    "CandidateApprovalResult",
    "DomainMemoryApprovalRecord",
    "DomainMemoryContentRevision",
    "DomainMemoryContractError",
    "DomainMemoryRetrieval",
    "DomainMemoryRetrievalError",
    "DomainMemoryScopeError",
    "DomainMemoryService",
    "DomainMemoryServiceError",
    "DomainMemoryStore",
    "DomainMemoryStoreConflict",
    "DomainMemoryStoreError",
    "DomainMemoryTraceError",
    "DomainMemoryValidityRecord",
    "DomainMemoryPreferences",
    "DomainMemoryRequestOverride",
    "EffectiveDomainMemoryPreferences",
    "MemoryCandidate",
    "MemoryCandidateStore",
    "MemoryCandidateStoreConflict",
    "MemoryCandidateStoreError",
    "MemoryScope",
    "PROJECT_CONTEXT_INDEX_CONTRACT_VERSION",
    "ProjectContextFact",
    "ProjectContextIndex",
    "ProjectContextIndexBuilder",
    "ProjectContextIndexStore",
    "ProjectContextProjection",
    "ProjectIndexBuildError",
    "ProjectIndexError",
    "ProjectIndexStoreConflict",
    "ProjectIndexStoreError",
    "ProjectMemoryTraceError",
    "ProjectMemoryTraceEvent",
    "ProjectionOmission",
    "SOURCE_KINDS",
    "SourceManifestEntry",
    "SourceAccessBinding",
    "SourceAccessValidityRecord",
    "SourceSummaryRef",
    "RetrievedMemoryHint",
    "RetrievalOmission",
    "TRACE_CONTRACT_VERSION",
    "build_domain_memory_trace",
    "build_project_memory_trace",
    "project_index_to_context",
    "resolve_preferences",
    "retrieve_domain_memory",
]
