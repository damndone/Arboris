"""Legacy typed planning API backed by the shared AgentCore phase driver."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Mapping, Sequence

from ...agent.model import ModelAdapter
from ..operations import OperationRegistry
from ..context_compiler import NotebookPlanningContextV1
from .evidence import DataEvidencePackV1, INSPECTIONS, InspectionRequest
from .recommendation import ForecastRollingOriginProtocol, RecommendationValidator
from ..planning.types import (
    NotebookPlanningUnavailable,
    NotebookPlanningTimeout,
    NotebookNoEligibleCapability,
    NotebookPlanningContractError,
    AgentOptionSubmission,
    PlanningResult,
    PlanningRefusal,
    InspectionExecutor,
    ProposalValidator,
)
from ..planning.normalize import (
    _BASELINE_INSPECTION_IDS,
    _interaction_mode,
    _has_complete_baseline_evidence,
    _strict_mapping,
    _strict_string,
    _strict_int,
    _strict_string_list,
    _strict_typed_proposal,
    _inspection_requests,
    _submission,
    _canonicalize_provider_option_batch,
    _parse_submissions,
    _parse_planning_refusal,
    _evidence_citation_policy,
    _append_evidence_pack,
    _execution_pins,
    _typed_operation_contracts,
    _canonicalize_server_owned_pins,
    _canonicalize_provider_capability_id,
    _strip_unsupported_model_options,
)
from ..planning.provider_contract import (
    NOTEBOOK_TOOLS,
    _notebook_tools_for,
    _provider_workflow_steps_schema,
    _INSPECTION_REQUEST_SCHEMA,
    _TYPED_PROPOSAL_SCHEMA,
    _EXPECTED_ARTIFACT_SCHEMA,
    _EVIDENCE_REF_SCHEMA,
    _OPTION_SUBMISSION_SCHEMA,
)
from ..planning.validation import (
    _published_artifact_types,
    _validate_submissions,
    _workflow_primary_artifacts,
    _assert_user_visible_domain_language,
)
from ..planning.corrections import _append_contract_correction, _correction_instruction


from ..planning.agent import NotebookPlanningAgent
