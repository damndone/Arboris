"""Gate 4 — Notebook objects, typed analysis options and their lifecycle.

Public surface for Lane A (Work Order A, v1.8.1). Consumes the locked contracts
in `workbench.contracts.agent.notebook_option`, the Gate 2 context compiler and
the Gate 3 trace writer; owns none of them.
"""

from __future__ import annotations

from .artifact_contract import (
    CONTRACT_PROFILE,
    build_artifact_contract,
    validate_produced_artifacts,
)
from .errors import (
    ArtifactContractEmpty,
    ArtifactNotDeclarable,
    ArtifactSchemaContractUnsupported,
    NotebookNotFound,
    NotebookOptionError,
    NotebookRunFamilyImmutable,
    OptionBatchInvalid,
    OptionLifecycleTransitionInvalid,
    OptionNotFound,
    OptionRevisionStale,
    OptionValidationFailed,
)
from .freshness import (
    assert_executable,
    evaluate_option_freshness,
    freshness_details,
)
from .proposal import OptionDraft, TypedProposal
from .producer import (
    MAX_PLANNED_OPTIONS,
    NOTEBOOK_OPTION_BATCH_STATUS,
    generate_option_batch,
    plan_option_drafts,
)
from .service import ExecutionOutcome, MAX_OPTIONS_PER_BATCH, NotebookService
from .store import Notebook, NotebookStore, OptionView, StoredRevision
from .vocabulary import DECLARED_ARTIFACT_TYPES

__all__ = [
    "ArtifactContractEmpty",
    "ArtifactNotDeclarable",
    "ArtifactSchemaContractUnsupported",
    "CONTRACT_PROFILE",
    "DECLARED_ARTIFACT_TYPES",
    "ExecutionOutcome",
    "MAX_OPTIONS_PER_BATCH",
    "MAX_PLANNED_OPTIONS",
    "NOTEBOOK_OPTION_BATCH_STATUS",
    "Notebook",
    "NotebookNotFound",
    "NotebookOptionError",
    "NotebookRunFamilyImmutable",
    "NotebookService",
    "NotebookStore",
    "OptionBatchInvalid",
    "OptionDraft",
    "OptionLifecycleTransitionInvalid",
    "OptionNotFound",
    "OptionRevisionStale",
    "OptionValidationFailed",
    "OptionView",
    "StoredRevision",
    "TypedProposal",
    "assert_executable",
    "build_artifact_contract",
    "evaluate_option_freshness",
    "freshness_details",
    "generate_option_batch",
    "plan_option_drafts",
    "validate_produced_artifacts",
]
