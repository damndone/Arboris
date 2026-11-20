"""Typed planning API backed by the shared AgentCore phase driver."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Mapping, Sequence

from ...agent.model import ModelAdapter
from ..operations import OperationRegistry
from ..context_compiler import NotebookPlanningContextV1
from ..notebook.evidence import DataEvidencePackV1, INSPECTIONS, InspectionRequest
from ..notebook.recommendation import ForecastRollingOriginProtocol, RecommendationValidator
from .types import (
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
from .normalize import (
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
from .provider_contract import (
    NOTEBOOK_TOOLS,
    _notebook_tools_for,
    _provider_workflow_steps_schema,
    _INSPECTION_REQUEST_SCHEMA,
    _TYPED_PROPOSAL_SCHEMA,
    _EXPECTED_ARTIFACT_SCHEMA,
    _EVIDENCE_REF_SCHEMA,
    _OPTION_SUBMISSION_SCHEMA,
)
from .validation import (
    _published_artifact_types,
    _validate_submissions,
    _workflow_primary_artifacts,
    _assert_user_visible_domain_language,
)
from .corrections import _append_contract_correction, _correction_instruction


class NotebookPlanningAgent:
    """Compatibility facade for deterministic planning phases on AgentCore."""

    def __init__(
        self,
        *,
        adapter: ModelAdapter,
        capability_catalog: Mapping[str, Any] | None = None,
        capability_artifact_types: Mapping[str, Mapping[str, str]] | None = None,
        inspection_executor: InspectionExecutor | None = None,
        recommendation_validator: RecommendationValidator | None = None,
        operation_registry: OperationRegistry | None = None,
        proposal_validator: ProposalValidator | None = None,
        available_inspections: Sequence[str] | None = None,
        max_inspection_rounds: int = 5,
        max_contract_corrections: int = 4,
        model_timeout_s: float = 120.0,
        planning_timeout_s: float | None = None,
        phase_runner: Callable | None = None,
    ) -> None:
        self.adapter = adapter
        self.phase_runner = phase_runner
        self.capability_catalog = dict(capability_catalog or {})
        self._capability_artifact_types = {
            str(capability_id): dict(artifact_types)
            for capability_id, artifact_types in (capability_artifact_types or {}).items()
            if isinstance(capability_id, str) and isinstance(artifact_types, Mapping)
        }
        self.inspection_executor = inspection_executor
        self.recommendation_validator = recommendation_validator or RecommendationValidator(
            protocols={"forecast.v1": ForecastRollingOriginProtocol()}
        )
        self.operation_registry = operation_registry or OperationRegistry()
        self.proposal_validator = proposal_validator
        self.available_inspections = frozenset(
            available_inspections if available_inspections is not None else INSPECTIONS
        )
        if max_inspection_rounds < 1 or max_inspection_rounds > 5:
            raise ValueError("max_inspection_rounds must be between 1 and 5")
        if max_contract_corrections < 0 or max_contract_corrections > 4:
            raise ValueError("max_contract_corrections must be between 0 and 4")
        self.max_inspection_rounds = max_inspection_rounds
        self.max_contract_corrections = max_contract_corrections
        if model_timeout_s <= 0:
            raise ValueError("model_timeout_s must be positive")
        self.model_timeout_s = float(model_timeout_s)
        if planning_timeout_s is not None and planning_timeout_s <= 0:
            raise ValueError("planning_timeout_s must be positive")
        self.planning_timeout_s = (
            None if planning_timeout_s is None else float(planning_timeout_s)
        )

    def _published_artifact_types(self, capability_id: str) -> Mapping[str, str]:
        return _published_artifact_types(capability_id, self._capability_artifact_types)

    def _supports_named_tool_choice(self) -> bool:
        capability = getattr(self.adapter, "supports_named_tool_choice", None)
        if callable(capability):
            return bool(capability())
        if isinstance(capability, bool):
            return capability
        # Test doubles and provider adapters that have not declared a
        # limitation retain the generic OpenAI-compatible behavior.
        return True

    def _planning_request_config(self) -> dict[str, Any]:
        config = getattr(self.adapter, "planning_request_config", None)
        if callable(config):
            value = config()
            if isinstance(value, Mapping):
                return dict(value)
        return {}

    def _workflow_primary_artifacts(
        self,
        steps: Any,
        catalog: Mapping[str, Any],
    ) -> tuple[dict[str, str], dict[str, int], frozenset[str]]:
        return _workflow_primary_artifacts(steps, catalog, self._capability_artifact_types)

    def plan(
        self,
        *,
        context: NotebookPlanningContextV1,
        initial_evidence: DataEvidencePackV1,
    ) -> PlanningResult | PlanningRefusal:
        return asyncio.run(self.plan_async(context=context, initial_evidence=initial_evidence))

    def create_phase(self, *, context, initial_evidence, episode_id=None):
        from .notebook_phase import NotebookPlanningPhase
        return NotebookPlanningPhase(
            context=context, initial_evidence=initial_evidence,
            capability_catalog=self.capability_catalog, artifact_types_by_capability=self._capability_artifact_types,
            inspection_executor=self.inspection_executor, recommendation_validator=self.recommendation_validator,
            operation_registry=self.operation_registry, proposal_validator=self.proposal_validator,
            available_inspections=self.available_inspections, max_inspection_rounds=self.max_inspection_rounds,
            max_contract_corrections=self.max_contract_corrections, model_timeout_s=self.model_timeout_s,
            planning_timeout_s=self.planning_timeout_s, request_config=self._planning_request_config(),
            episode_id=episode_id,
        )

    async def plan_async(
        self,
        *,
        context: NotebookPlanningContextV1,
        initial_evidence: DataEvidencePackV1,
    ) -> PlanningResult | PlanningRefusal:
        if self.adapter is None:
            raise NotebookPlanningUnavailable("no model provider is configured")
        phase = self.create_phase(context=context, initial_evidence=initial_evidence)
        if self.phase_runner is not None:
            return await self.phase_runner(phase)
        # Legacy programmatic calls had no durable session. Retain that scope
        # with a short-lived Core, rather than guessing a root from context.
        from tempfile import TemporaryDirectory
        from ..core import AgentCore
        from ..events import AgentEventStream
        from ..session import JsonlSessionRepository
        with TemporaryDirectory(prefix="workbench-notebook-phase-") as temporary:
            repository = JsonlSessionRepository(temporary)
            repository.create_session("planning", chain_id=phase.episode_id, role="planning")
            core = AgentCore(repository, AgentEventStream(temporary), self.adapter, session_id="planning")
            return await core.run_phase(phase)

    _evidence_citation_policy = staticmethod(_evidence_citation_policy)

    _append_evidence_pack = staticmethod(_append_evidence_pack)

    _append_contract_correction = staticmethod(_append_contract_correction)

    _correction_instruction = staticmethod(_correction_instruction)



    _execution_pins = staticmethod(_execution_pins)

    _typed_operation_contracts = staticmethod(_typed_operation_contracts)

    def _validate_submissions(
        self,
        context: NotebookPlanningContextV1,
        evidence: DataEvidencePackV1,
        submissions: tuple[AgentOptionSubmission, ...],
        catalog: Mapping[str, Any],
        *,
        max_options: int = 3,
    ) -> tuple[AgentOptionSubmission, ...]:
        return _validate_submissions(
            context, evidence, submissions, catalog,
            operation_registry=self.operation_registry,
            proposal_validator=self.proposal_validator,
            artifact_types_by_capability=self._capability_artifact_types,
            max_options=max_options,
        )

    _assert_user_visible_domain_language = staticmethod(_assert_user_visible_domain_language)

    _canonicalize_server_owned_pins = staticmethod(_canonicalize_server_owned_pins)

    _canonicalize_provider_capability_id = staticmethod(_canonicalize_provider_capability_id)

    _strip_unsupported_model_options = staticmethod(_strip_unsupported_model_options)


__all__ = [
    "AgentOptionSubmission",
    "NOTEBOOK_TOOLS",
    "NotebookPlanningAgent",
    "NotebookPlanningContractError",
    "NotebookNoEligibleCapability",
    "NotebookPlanningUnavailable",
    "PlanningRefusal",
    "PlanningResult",
]
