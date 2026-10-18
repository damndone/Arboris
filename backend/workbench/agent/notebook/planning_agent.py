"""Typed provider loop for Notebook inspection and option planning."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Mapping, Sequence
from uuid import uuid4

from ...agent.model import ModelAdapter, ModelRequest, ModelStreamEvent
from ..operations import OperationRegistry
from ..context_compiler import (
    NotebookPlanningContextV1,
    freshness_dependency_fingerprint,
    generation_context_hash,
    notebook_planning_workbench_context,
)
from .evidence import DataEvidencePackV1, INSPECTIONS, InspectionRequest
from .recommendation import ForecastRollingOriginProtocol, RecommendationValidator
from .vocabulary import (
    ARTIFACT_VOCABULARY_VERSION,
    CAPABILITY_ARTIFACT_VOCABULARY_VERSION,
    DECLARED_ARTIFACT_TYPES,
)
from ..recipe_contracts import recipe_contract_for_model_type
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


class NotebookPlanningAgent:
    """A two-tool, bounded planning loop over the existing model adapter."""

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
    ) -> None:
        self.adapter = adapter
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

    async def plan_async(
        self,
        *,
        context: NotebookPlanningContextV1,
        initial_evidence: DataEvidencePackV1,
    ) -> PlanningResult | PlanningRefusal:
        if self.adapter is None:
            raise NotebookPlanningUnavailable("no model provider is configured")
        interaction_mode = _interaction_mode(context)
        max_options = 1 if interaction_mode == "action" else 3
        catalog = self.capability_catalog or {name: {} for name in context.available_capabilities}
        catalog = {
            capability_id: dict(declaration)
            for capability_id, declaration in catalog.items()
        }
        for capability_id, declaration in catalog.items():
            contract = recipe_contract_for_model_type(
                declaration.get("model_type", capability_id)
            )
            if contract is not None:
                declaration["recipe_contract"] = contract.to_payload()
        if not catalog:
            raise NotebookNoEligibleCapability("no registered executable Notebook capability is available")
        planning_deadline = (
            None
            if self.planning_timeout_s is None
            else asyncio.get_running_loop().time() + self.planning_timeout_s
        )
        context_payload = notebook_planning_workbench_context(context)
        context_payload["interaction_mode"] = interaction_mode
        context_payload["execution_pins"] = self._execution_pins(context)
        context_payload["available_inspection_ids"] = sorted(self.available_inspections)
        context_payload["typed_operation_contracts"] = self._typed_operation_contracts(context)
        context_payload["artifact_vocabulary"] = {
            "version": ARTIFACT_VOCABULARY_VERSION,
            "declared_artifact_types": dict(DECLARED_ARTIFACT_TYPES),
            "capability_version": CAPABILITY_ARTIFACT_VOCABULARY_VERSION,
            "capability_artifact_types": {
                capability_id: dict(self._published_artifact_types(capability_id))
                for capability_id in sorted(catalog)
                if self._published_artifact_types(capability_id)
            },
            "required_expectations_must_use_declared_ids": True,
        }
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    (
                        "Plan mode: submit one to three genuinely distinct, non-duplicate "
                        "executable paths. Do not force three options: submit one when the "
                        "evidence does not support meaningful alternatives, and say why. "
                        if interaction_mode == "plan"
                        else
                        "Action mode: the user chose direct specification checking. Submit exactly "
                        "one typed, editable Draft path with rank 1. Do not create alternatives, "
                        "call it a recommendation, or execute it. Treat the user's goal as the "
                        "requested specification; list only evidence-backed necessary assumptions "
                        "and limitations. "
                    )
                    + "Use only the three typed Notebook tools. Never invent metrics or executable capability ids. "
                    "When the request cannot be safely or honestly turned into a registered executable plan, "
                    "call decline_notebook_plan with one published reason_code and a concise user-facing message; "
                    "a refusal is terminal and must not be combined with a submission. "
                    "Inspection ids are exactly profile.v1, quality.v1, time_index.v1, sample.v1, "
                    "or forecast_rolling_origin.v1; use dataset:active for a dataset projection and "
                    "run:active for a run projection. Treat completed evidence already supplied in "
                    "the initial Evidence Pack as sufficient for the evidence requirement; request "
                    "an inspection only to fill a concrete evidence gap needed by the option you "
                    "will submit. Do not request profile.v1, quality.v1, time_index.v1, or sample.v1 "
                    "again when that exact completed evidence is already present. "
                    f"You may make at most {self.max_inspection_rounds} inspection turns, each requesting "
                    "one to five distinct ids; after enough evidence is available, submit the option batch. "
                    "Submitted typed options must cite completed evidence refs. Comparative claims are "
                    "bound by the option's structured evidence_refs; do not use unsupported prose. "
                    "Evidence with status partial or failed is non-citable. A partial bounded inspection is "
                    "terminal for that inspection id: describe its omissions as a limitation, but do not "
                    "request it again merely to remove a declared cap. "
                    "Copy execution_pins exactly: for a standalone dataset proposal use model.genesis and set "
                    "target.dataset_source_id exactly to context.projection_source.upload_sha256; for a "
                    "dataset-rooted operation.multi_step use its target_exact and preconditions_exact instead. "
                    "A RecipeContract always remains a dataset-rooted model.genesis proposal when the "
                    "Notebook projection is a dataset, even after that Notebook has an active result head: "
                    "copy the dataset genesis pin and do not turn an ETS or ARMA/GARCH Recipe into a "
                    "model.rerun merely because a prior result is visible. "
                    "For a run proposal copy the active-head and node pins without rewriting them. For model.genesis, "
                    "changes may contain only table_params, model_params, or model_options, each as an object; "
                    "put model-specific fields inside one of those objects, never directly in changes. "
                    "For model.genesis, model_params must include an evidence-backed model_type. "
                    "Use the server-published capability form for that family: x is non-empty only "
                    "when the selected family requires covariates; DID families instead require their "
                    "published entity, time, and cohort or treatment-path columns. Do not add OLS "
                    "covariance fields to a DID family. "
                    "When context.typed_operation_contracts publishes operation.multi_step, use it for a "
                    "typed statistical workflow that needs declared categorical terms, polynomial terms, "
                    "or declared post-estimation steps. Copy its target_exact and preconditions_exact "
                    "verbatim, and use only its published step vocabulary. Every entry in changes.steps "
                    "has exactly this outer envelope: step_id, operation_id, spec, plus optional "
                    "depends_on and expected_artifacts. Omit depends_on when a step has no prerequisite; "
                    "otherwise depends_on must be a JSON array of exact earlier step_id strings, for example "
                    "[\"source_step\"], never a string, object, or branch_id. Put every operation-specific field inside spec; "
                    "never place model, exploration, or adapter fields beside spec. Do not replace a categorical "
                    "term with a numeric code or omit a requested polynomial/post-estimation step. "
                    "Each completed model.genesis branch automatically materializes residuals_vs_<predictor> and "
                    "fitted_vs_<predictor> diagnostic figures for its declared predictor columns. When the user "
                    "requests residuals versus a declared predictor, include that predictor in the branch and describe "
                    "the persisted diagnostic figure; do not claim that a separate scatter step is required. "
                    "capability_id identifies the primary server-published analytical capability, never "
                    "the operation.multi_step envelope. For a workflow with model.genesis it may name one "
                    "declared model_family; for a P7-only workflow it must name one P7 operation_id that "
                    "is actually present in changes.steps. Every model.genesis step must "
                    "use a server-published model_family; panel_ols requires entity_col or time_col, and "
                    "clustered panel_ols requires entity_col. "
                    "For OLS, the server-owned Agent envelope is model_options.covariance and its only "
                    "published values are robust, clustered, and unadjusted. For model.genesis, the "
                    "legacy model_params.covariance field is also accepted for human/Draft compatibility, "
                    "but a typed Agent option should use model_options.covariance so the contract binding "
                    "and rerun path remain inspectable. "
                    "For model.custom, capability_id selects a server-published planner projection; "
                    "changes may contain only operation, input_handle, parameters, and consumer_slots. "
                    "The server injects capability_ref and binding_ref. Never invent entrypoints, source "
                    "paths, dependency refs, trust tiers, admission refs, or executable permissions. "
                    "A custom option is experimental/high-risk by default and still requires the existing "
                    "Proposal/Risk authorization and containment gateway; it is never an automatic fallback. "
                    "For a regression model, y and x must be exact column names present in completed profile/sample evidence. "
                    "For a RecipeContract, do not submit regression y/x fields: use its exact model_options time/value fields. "
                    "Every time-series Recipe must have model_options.time_index_semantics resolved before Draft validation. "
                    "You may omit that field only when the current context includes an eligible approved memory default "
                    "for the same Recipe; the server then applies its exact registered value and provenance. "
                    "Without that exact current default, set model_options.time_index_semantics explicitly. "
                    "Use regular_calendar only when completed evidence establishes constant elapsed intervals; "
                    "otherwise use observation_order and state that index interpretation as an assumption for user confirmation. "
                    "Never submit recipe_contract.server_owned_option_fields; the server binds those fields to the typed dataset target. "
                    "if the target is not supported by evidence, do not submit the option. "
                    "For every non-empty model_options object, use the exact server-published field names "
                    "and nesting shown in capability_catalog's notebook_model_options_contract or "
                    "model_options_vocabulary. Never translate canonical fields into aliases such as ar, ma, "
                    "dist, or mean; the server validates the merged target contract and rejects invented keys. "
                    "If a model type has no published notebook_model_options_contract, omit model_options "
                    "entirely; never borrow options from a related model family. "
                    "Do not claim missingness is random, a model is superior, or a diagnostic is clean unless "
                    "the completed evidence record explicitly supports that claim. If evidence cannot separate "
                    "options, submit the options as tied/insufficient evidence rather than forcing a winner. "
                    "Only declare required artifacts whose ids appear in context.artifact_vocabulary; "
                    "for a capability with a capability_artifact_types entry, declare its listed "
                    "primary result artifact as required; if an artifact is not published there, "
                    "omit it rather than inventing an id."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "context": context_payload,
                        "capability_catalog": catalog,
                        "evidence": initial_evidence.to_dict(),
                        "evidence_citation_policy": self._evidence_citation_policy(
                            initial_evidence
                        ),
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        evidence = initial_evidence
        requests_seen: list[InspectionRequest] = []
        terminal_inspection_ids = {
            record.inspection_id
            for record in evidence.records
            if record.status in {"completed", "partial"}
        }
        inspection_rounds = 0
        contract_corrections = 0
        for round_number in range(
            1, self.max_inspection_rounds + 2 + self.max_contract_corrections
        ):
            remaining_s = (
                None
                if planning_deadline is None
                else planning_deadline - asyncio.get_running_loop().time()
            )
            if remaining_s is not None and remaining_s <= 0:
                raise NotebookPlanningTimeout(
                    f"Notebook planning exceeded the {self.planning_timeout_s:g}s total budget"
                )
            total_budget_limited = (
                remaining_s is not None and remaining_s < self.model_timeout_s
            )
            baseline_complete = _has_complete_baseline_evidence(evidence)
            try:
                events = await self._call_model(
                    messages,
                    timeout_s=(
                        self.model_timeout_s
                        if remaining_s is None
                        else min(self.model_timeout_s, remaining_s)
                    ),
                    total_budget_limited=total_budget_limited,
                    max_options=max_options,
                    submit_only=baseline_complete,
                )
            except NotebookPlanningContractError as error:
                if contract_corrections >= self.max_contract_corrections:
                    raise
                contract_corrections += 1
                self._append_contract_correction(
                    messages,
                    call={},
                    error=error,
                    context=context,
                    evidence=evidence,
                    correction_number=contract_corrections,
                )
                continue
            calls = [event.tool_call for event in events if event.type == "tool_call_delta" and event.tool_call]
            if len(calls) != 1:
                error = NotebookPlanningContractError(
                    "text-only planning completion is not accepted"
                    if not calls
                    else "planning turn must contain exactly one typed tool call"
                )
                if contract_corrections >= self.max_contract_corrections:
                    raise error
                contract_corrections += 1
                self._append_contract_correction(
                    messages,
                    call={},
                    error=error,
                    context=context,
                    evidence=evidence,
                    correction_number=contract_corrections,
                )
                continue
            call = calls[0]
            tool_id = call.get("tool_id")
            arguments = call.get("arguments")
            if tool_id == "request_notebook_inspections":
                try:
                    requests = _inspection_requests(arguments)
                    unavailable = sorted(
                        {
                            request.inspection_id
                            for request in requests
                            if request.inspection_id not in self.available_inspections
                        }
                    )
                    if unavailable:
                        raise NotebookPlanningContractError(
                            "inspection is not available: "
                            + ", ".join(unavailable)
                            + "; available: "
                            + ", ".join(sorted(self.available_inspections))
                        )
                    new_requests: list[InspectionRequest] = []
                    reused_requests: list[InspectionRequest] = []
                    requested_by_id: dict[str, InspectionRequest] = {}
                    for request in requests:
                        current = requested_by_id.get(request.inspection_id)
                        if current is not None:
                            if current != request:
                                raise NotebookPlanningContractError(
                                    "duplicate inspection id has conflicting arguments"
                                )
                            reused_requests.append(request)
                            continue
                        requested_by_id[request.inspection_id] = request
                        prior_request = next(
                            (
                                prior
                                for prior in requests_seen
                                if prior.inspection_id == request.inspection_id
                            ),
                            None,
                        )
                        if prior_request is not None:
                            if prior_request != request:
                                # A completed evidence record is scoped to the
                                # request that produced it.  Reusing it after
                                # a changed target or arguments would quietly
                                # relabel different evidence as equivalent.
                                raise NotebookPlanningContractError(
                                    "duplicate inspection id has conflicting arguments"
                                )
                            # A repeated, byte-for-byte equivalent read is
                            # idempotent. Reuse its immutable evidence packet
                            # below rather than spending another inspection
                            # turn or making the model start over.
                            reused_requests.append(request)
                            continue
                        if request.inspection_id in terminal_inspection_ids:
                            # Default no-argument inspections against the
                            # current pinned run are deterministic.  Initial
                            # evidence is server-created for that exact source,
                            # so this is an identity-preserving replay rather
                            # than a request to widen a bounded read.  Other
                            # target/argument shapes remain fail-closed because
                            # v1 records do not persist a caller envelope.
                            if (
                                request.target_ref == "run:active"
                                and not request.arguments
                                and context.active_head_run_id is not None
                                and evidence.source_id
                                == f"run:{context.active_head_run_id}"
                            ):
                                reused_requests.append(request)
                                continue
                            raise NotebookPlanningContractError("duplicate inspection request")
                        new_requests.append(request)
                except NotebookPlanningContractError as error:
                    if contract_corrections >= self.max_contract_corrections:
                        raise
                    contract_corrections += 1
                    self._append_contract_correction(
                        messages,
                        call=call,
                        error=error,
                        context=context,
                        evidence=evidence,
                        correction_number=contract_corrections,
                    )
                    continue
                if inspection_rounds >= self.max_inspection_rounds:
                    error = NotebookPlanningContractError("inspection round limit exceeded")
                    if contract_corrections >= self.max_contract_corrections:
                        raise error
                    contract_corrections += 1
                    self._append_contract_correction(
                        messages,
                        call=call,
                        error=error,
                        context=context,
                        evidence=evidence,
                        correction_number=contract_corrections,
                    )
                    continue
                if new_requests:
                    if self.inspection_executor is None:
                        raise NotebookPlanningUnavailable("inspection executor is not configured")
                    result = self.inspection_executor(tuple(new_requests), evidence)
                    inspection_pack = await result if hasattr(result, "__await__") else result
                    if not isinstance(inspection_pack, DataEvidencePackV1):
                        raise NotebookPlanningContractError("inspection executor returned no Evidence Pack")
                    inspection_rounds += 1
                    evidence = self._append_evidence_pack(evidence, inspection_pack)
                    resolved_inspection_ids = {
                        record.inspection_id
                        for record in inspection_pack.records
                        if record.status in {"completed", "partial"}
                    }
                    # A failed inspection has not produced reusable evidence.
                    # Leave it retriable so the provider can correct its target
                    # or arguments; only completed/partial reads become
                    # idempotent requests in this planning episode.
                    requests_seen.extend(
                        request
                        for request in new_requests
                        if request.inspection_id in resolved_inspection_ids
                    )
                    terminal_inspection_ids.update(
                        resolved_inspection_ids
                    )
                else:
                    inspection_pack = DataEvidencePackV1(
                        source_id=evidence.source_id,
                        records=(),
                    )
                messages.extend([
                    {"role": "assistant", "tool_calls": [call]},
                    {
                        "role": "tool",
                        "tool_call_id": call.get("tool_call_id", "inspection"),
                        "content": json.dumps(
                            {
                                "evidence": evidence.to_dict(),
                                "evidence_citation_policy": self._evidence_citation_policy(
                                    evidence
                                ),
                                "reused_inspection_ids": sorted(
                                    {request.inspection_id for request in reused_requests}
                                ),
                            },
                            ensure_ascii=False,
                        ),
                    },
                ])
                failed_codes = sorted(
                    {
                        record.failure_code
                        for record in inspection_pack.records
                        if record.status == "failed" and record.failure_code
                    }
                )
                if failed_codes:
                    if contract_corrections >= self.max_contract_corrections:
                        raise NotebookPlanningContractError(
                            "inspection evidence failed: " + ", ".join(failed_codes)
                        )
                    contract_corrections += 1
                    self._append_contract_correction(
                        messages,
                        call=call,
                        error=NotebookPlanningContractError(
                            "inspection evidence failed: " + ", ".join(failed_codes)
                        ),
                        context=context,
                        evidence=evidence,
                        correction_number=contract_corrections,
                    )
                continue
            if tool_id == "decline_notebook_plan":
                try:
                    return _parse_planning_refusal(
                        arguments,
                        requests_seen=tuple(requests_seen),
                        evidence=evidence,
                        rounds=round_number,
                    )
                except NotebookPlanningContractError as error:
                    if contract_corrections >= self.max_contract_corrections:
                        raise
                    contract_corrections += 1
                    self._append_contract_correction(
                        messages,
                        call=call,
                        error=error,
                        context=context,
                        evidence=evidence,
                        correction_number=contract_corrections,
                    )
                    continue
            if tool_id != "submit_notebook_option_batch":
                error = NotebookPlanningContractError(f"unknown Notebook planning tool: {tool_id}")
                if contract_corrections >= self.max_contract_corrections:
                    raise error
                contract_corrections += 1
                self._append_contract_correction(
                    messages,
                    call=call,
                    error=error,
                    context=context,
                    evidence=evidence,
                    correction_number=contract_corrections,
                )
                continue
            try:
                arguments = _canonicalize_provider_option_batch(
                    arguments,
                    evidence=evidence,
                    catalog=catalog,
                )
                submissions = _parse_submissions(arguments, max_options=max_options)
                submissions = self._validate_submissions(
                    context, evidence, submissions, catalog, max_options=max_options
                )
            except NotebookPlanningContractError as error:
                if contract_corrections >= self.max_contract_corrections:
                    raise
                contract_corrections += 1
                self._append_contract_correction(
                    messages,
                    call=call,
                    error=error,
                    context=context,
                    evidence=evidence,
                    correction_number=contract_corrections,
                )
                continue
            from .producer import option_drafts_from_submissions

            # A planning pass is a new recommendation episode, even when the
            # compiler produces the same context id.  Reusing the context-only
            # batch id would make a deliberate replan collide with the old
            # append-only RecommendationDecision record.
            batch_id = f"batch_agent_{context.context_id}_{uuid4().hex}"
            try:
                drafts_without_decision = option_drafts_from_submissions(context, submissions)
                decision = self.recommendation_validator.decide(
                    batch_id=batch_id,
                    candidates=drafts_without_decision,
                    evidence_pack=evidence,
                    generation_context_hash=generation_context_hash(context),
                    freshness_dependency_fingerprint=freshness_dependency_fingerprint(context),
                )
                drafts = option_drafts_from_submissions(context, submissions, decision=decision)
            except (KeyError, TypeError, ValueError) as error:
                # A trusted, server-side decision can reject an otherwise
                # typed provider batch.  Give the provider one bounded
                # correction opportunity instead of leaking this as the
                # route's generic request-validation failure.  The external
                # correction intentionally carries a stable category, not
                # internal exception text or provider-controlled content.
                contract_error = NotebookPlanningContractError(
                    "server recommendation validation failed"
                )
                if contract_corrections >= self.max_contract_corrections:
                    raise contract_error from error
                contract_corrections += 1
                self._append_contract_correction(
                    messages,
                    call=call,
                    error=contract_error,
                    context=context,
                    evidence=evidence,
                    correction_number=contract_corrections,
                )
                continue
            return PlanningResult(tuple(requests_seen), evidence, submissions, drafts, decision, round_number)
        raise NotebookPlanningContractError("planning loop did not submit an option batch")

    _evidence_citation_policy = staticmethod(_evidence_citation_policy)

    _append_evidence_pack = staticmethod(_append_evidence_pack)

    _append_contract_correction = staticmethod(_append_contract_correction)

    _correction_instruction = staticmethod(_correction_instruction)

    async def _call_model(
        self,
        messages: list[dict[str, Any]],
        *,
        timeout_s: float,
        total_budget_limited: bool,
        max_options: int = 3,
        submit_only: bool = False,
    ) -> list[ModelStreamEvent]:
        request = ModelRequest(
            messages=list(messages),
            tools=[
                dict(tool)
                for tool in _notebook_tools_for(
                    max_options,
                    include_inspection=not submit_only,
                )
            ],
            model_config=(
                {
                    **self._planning_request_config(),
                }
            ),
        )
        try:
            events = await asyncio.wait_for(
                self._collect_model_events(request), timeout=timeout_s
            )
        except asyncio.TimeoutError as exc:
            if total_budget_limited:
                raise NotebookPlanningTimeout(
                    f"Notebook planning exceeded the {self.planning_timeout_s:g}s total budget"
                ) from exc
            raise NotebookPlanningTimeout(
                f"Notebook planning provider exceeded {self.model_timeout_s:g}s"
            ) from exc
        if not any(event.type == "done" for event in events):
            raise NotebookPlanningUnavailable("model provider returned no completion")
        return events

    async def _collect_model_events(self, request: ModelRequest) -> list[ModelStreamEvent]:
        events: list[ModelStreamEvent] = []
        try:
            async for event in self.adapter.stream(request):
                if event.type == "retry":
                    continue
                if event.type == "error":
                    if event.error == "provider_tool_arguments_invalid":
                        raise NotebookPlanningContractError(
                            "provider tool-call arguments were not valid JSON"
                        )
                    raise NotebookPlanningUnavailable(event.error or "model provider failed")
                events.append(event)
        except NotebookPlanningUnavailable:
            raise
        except Exception as exc:
            raise NotebookPlanningUnavailable(f"model provider failed: {type(exc).__name__}") from exc
        return events

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
