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
    ProjectMemoryTraceError,
    ProjectMemoryTraceEvent,
    TRACE_CONTRACT_VERSION,
    build_project_memory_trace,
)

__all__ = [
    "FACT_KINDS",
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
    "TRACE_CONTRACT_VERSION",
    "build_project_memory_trace",
    "project_index_to_context",
]
