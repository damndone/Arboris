"""Deterministic Notebook planning transitions; never calls a model or Core."""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

from ..phases import PhaseRequest, PhaseStep, RecordedProviderError
from ..context_compiler import (
    freshness_dependency_fingerprint,
    generation_context_hash,
    notebook_planning_workbench_context,
)
from ..notebook.evidence import DataEvidencePackV1, InspectionRequest
from ..notebook.vocabulary import (
    ARTIFACT_VOCABULARY_VERSION,
    CAPABILITY_ARTIFACT_VOCABULARY_VERSION,
    DECLARED_ARTIFACT_TYPES,
)
from ..recipe_contracts import recipe_contract_for_model_type
from .types import (
    NotebookPlanningUnavailable,
    NotebookPlanningTimeout,
    NotebookNoEligibleCapability,
    NotebookPlanningContractError,
    PlanningResult,
    PlanningRefusal,
)
from .normalize import (
    _interaction_mode,
    _has_complete_baseline_evidence,
    _inspection_requests,
    _canonicalize_provider_option_batch,
    _parse_submissions,
    _parse_planning_refusal,
    _evidence_citation_policy,
    _append_evidence_pack,
    _execution_pins,
    _typed_operation_contracts,
)
from .corrections import _append_contract_correction
from .provider_contract import _notebook_tools_for
from .validation import _validate_submissions, _published_artifact_types


class NotebookPlanningPhase:
    replay_safe = False
    def __init__(self, *, context, initial_evidence, capability_catalog,
                 artifact_types_by_capability, inspection_executor, recommendation_validator,
                 operation_registry, proposal_validator, available_inspections,
                 max_inspection_rounds, max_contract_corrections, model_timeout_s,
                 planning_timeout_s, request_config, episode_id=None):
        self.context = context
        self.capability_catalog = dict(capability_catalog)
        self.artifact_types_by_capability = artifact_types_by_capability
        self.inspection_executor = inspection_executor
        self.recommendation_validator = recommendation_validator
        self.operation_registry = operation_registry
        self.proposal_validator = proposal_validator
        self.available_inspections = available_inspections
        self.max_inspection_rounds = max_inspection_rounds
        self.max_contract_corrections = max_contract_corrections
        self.model_timeout_s = model_timeout_s
        self.planning_timeout_s = planning_timeout_s
        self.request_config = dict(request_config)
        if episode_id is not None and (type(episode_id) is not str or not episode_id):
            raise NotebookPlanningContractError("planning episode_id must be a non-empty string")
        self.episode_id = uuid4().hex if episode_id is None else episode_id
        self.deadline = None if planning_timeout_s is None else time.monotonic() + planning_timeout_s
        self.total_budget_limited = False
        self.round_number = 0
        self.inspection_rounds = 0
        self.contract_corrections = 0
        self.evidence = initial_evidence
        self.requests_seen = []
        self.terminal_inspection_ids = {r.inspection_id for r in initial_evidence.records if r.status in {"completed", "partial"}}
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
        self.catalog = catalog
        self.max_options = max_options
        self.initial_messages = messages

    _evidence_citation_policy = staticmethod(_evidence_citation_policy)
    _append_evidence_pack = staticmethod(_append_evidence_pack)
    _append_contract_correction = staticmethod(_append_contract_correction)
    _execution_pins = staticmethod(_execution_pins)
    _typed_operation_contracts = staticmethod(_typed_operation_contracts)

    def _published_artifact_types(self, capability_id):
        return _published_artifact_types(capability_id, self.artifact_types_by_capability)

    def _validate_submissions(self, context, evidence, submissions, catalog, *, max_options):
        return _validate_submissions(context, evidence, submissions, catalog,
            operation_registry=self.operation_registry, proposal_validator=self.proposal_validator,
            artifact_types_by_capability=self.artifact_types_by_capability, max_options=max_options)

    def request(self, transcript):
        if self.round_number >= self.max_inspection_rounds + 1 + self.max_contract_corrections:
            raise NotebookPlanningContractError("planning loop did not submit an option batch")
        remaining = None if self.deadline is None else self.deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            self.total_budget_limited = True
            raise self.failure("timeout")
        self.total_budget_limited = remaining is not None and remaining < self.model_timeout_s
        self.round_number += 1
        return PhaseRequest(
            messages=list(transcript) if transcript else list(self.initial_messages),
            tools=[dict(tool) for tool in _notebook_tools_for(self.max_options,
                include_inspection=not _has_complete_baseline_evidence(self.evidence))],
            model_config=dict(self.request_config),
            provider_timeout_s=self.model_timeout_s if remaining is None else min(self.model_timeout_s, remaining),
        )

    def failure(self, reason, error=None):
        if reason == "timeout":
            if self.total_budget_limited:
                return NotebookPlanningTimeout(f"Notebook planning exceeded the {self.planning_timeout_s:g}s total budget")
            return NotebookPlanningTimeout(f"Notebook planning provider exceeded {self.model_timeout_s:g}s")
        if reason == "budget":
            return NotebookPlanningContractError("planning loop did not submit an option batch")
        if isinstance(error, NotebookPlanningUnavailable):
            return error
        error_type = error.original_type if isinstance(error, RecordedProviderError) else type(error).__name__
        return NotebookPlanningUnavailable(f"model provider failed: {error_type}")

    def checkpoint(self):
        return {"schema_version": 1, "episode_id": self.episode_id, "context_id": self.context.context_id,
            "context_fingerprint": freshness_dependency_fingerprint(self.context),
            "batch_id": f"batch_agent_{self.context.context_id}_{self.episode_id}",
            "catalog": self.catalog, "request_config": dict(self.request_config),
            "model_timeout_s": self.model_timeout_s, "planning_timeout_s": self.planning_timeout_s,
            "max_inspection_rounds":self.max_inspection_rounds,
            "max_contract_corrections":self.max_contract_corrections,
            "available_inspections":sorted(self.available_inspections),
            "checkpointed_at":time.time(),
            "remaining_wall_s": None if self.deadline is None else max(0.0, self.deadline - time.monotonic()),
            "rounds": self.round_number, "inspection_rounds": self.inspection_rounds,
            "contract_corrections": self.contract_corrections, "evidence": self.evidence.to_dict(),
            "requests_seen": [{"inspection_id": r.inspection_id, "target_ref": r.target_ref,
                "arguments": dict(r.arguments)} for r in self.requests_seen],
            "terminal_inspection_ids": sorted(self.terminal_inspection_ids)}

    def restore_checkpoint(self, checkpoint):
        """Restore counters and original evidence; never repeat baseline inspections."""
        from ..notebook.evidence import EvidenceRecord

        current = self.checkpoint()
        for key in ("catalog", "request_config", "model_timeout_s", "planning_timeout_s",
                    "max_inspection_rounds", "max_contract_corrections", "available_inspections"):
            if current[key] != checkpoint[key]:
                raise NotebookPlanningContractError("planning runtime contract changed: " + key)
        self.round_number = checkpoint["rounds"]
        self.inspection_rounds = checkpoint["inspection_rounds"]
        self.contract_corrections = checkpoint["contract_corrections"]
        pack = checkpoint["evidence"]
        self.evidence = DataEvidencePackV1(source_id=pack["source_id"],
            records=tuple(EvidenceRecord(**record) for record in pack["records"]),
            pack_omissions=tuple(pack["pack_omissions"]))
        self.requests_seen = [InspectionRequest(**request) for request in checkpoint["requests_seen"]]
        self.terminal_inspection_ids = set(checkpoint["terminal_inspection_ids"])
        remaining = checkpoint["remaining_wall_s"]
        if remaining is not None:
            self.deadline = time.monotonic() + max(0, remaining - (time.time() - checkpoint["checkpointed_at"]))

    def _finish(self, state, messages, result):
        return PhaseStep(state, tuple(messages), result, {
            "episode_id": self.episode_id, "status": state,
            "option_ids": [item.option_id for item in result.submissions],
            **({"reason_code": result.reason_code, "message": result.message[:320]}
               if isinstance(result, PlanningRefusal) else {}),
        })

    async def consume(self, events, *, error=None):
        messages = []
        if error is not None:
            raise self.failure("timeout" if isinstance(error, TimeoutError) else "provider", error) from error
        contract_error = None
        filtered = []
        for event in events:
            if event.type == "retry":
                continue
            if event.type == "error":
                if event.error == "provider_tool_arguments_invalid":
                    contract_error = NotebookPlanningContractError("provider tool-call arguments were not valid JSON")
                    break
                raise NotebookPlanningUnavailable(event.error or "model provider failed")
            filtered.append(event)
        if contract_error is not None:
            if self.contract_corrections >= self.max_contract_corrections:
                raise contract_error
            self.contract_corrections += 1
            self._append_contract_correction(messages, call={}, error=contract_error,
                context=self.context, evidence=self.evidence, correction_number=self.contract_corrections)
            return PhaseStep("continue", tuple(messages))
        if not any(event.type == "done" for event in filtered):
            raise NotebookPlanningUnavailable("model provider returned no completion")
        events = filtered
        calls = [event.tool_call for event in events if event.type == "tool_call_delta" and event.tool_call]
        if len(calls) != 1:
            error = NotebookPlanningContractError(
                "text-only planning completion is not accepted"
                if not calls
                else "planning turn must contain exactly one typed tool call"
            )
            if self.contract_corrections >= self.max_contract_corrections:
                raise error
            self.contract_corrections += 1
            self._append_contract_correction(
                messages,
                call={},
                error=error,
                context=self.context,
                evidence=self.evidence,
                correction_number=self.contract_corrections,
            )
            return PhaseStep("continue", tuple(messages))
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
                            for prior in self.requests_seen
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
                    if request.inspection_id in self.terminal_inspection_ids:
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
                            and self.context.active_head_run_id is not None
                            and self.evidence.source_id
                            == f"run:{self.context.active_head_run_id}"
                        ):
                            reused_requests.append(request)
                            continue
                        raise NotebookPlanningContractError("duplicate inspection request")
                    new_requests.append(request)
            except NotebookPlanningContractError as error:
                if self.contract_corrections >= self.max_contract_corrections:
                    raise
                self.contract_corrections += 1
                self._append_contract_correction(
                    messages,
                    call=call,
                    error=error,
                    context=self.context,
                    evidence=self.evidence,
                    correction_number=self.contract_corrections,
                )
                return PhaseStep("continue", tuple(messages))
            if self.inspection_rounds >= self.max_inspection_rounds:
                error = NotebookPlanningContractError("inspection round limit exceeded")
                if self.contract_corrections >= self.max_contract_corrections:
                    raise error
                self.contract_corrections += 1
                self._append_contract_correction(
                    messages,
                    call=call,
                    error=error,
                    context=self.context,
                    evidence=self.evidence,
                    correction_number=self.contract_corrections,
                )
                return PhaseStep("continue", tuple(messages))
            if new_requests:
                if self.inspection_executor is None:
                    raise NotebookPlanningUnavailable("inspection executor is not configured")
                result = self.inspection_executor(tuple(new_requests), self.evidence)
                inspection_pack = await result if hasattr(result, "__await__") else result
                if not isinstance(inspection_pack, DataEvidencePackV1):
                    raise NotebookPlanningContractError("inspection executor returned no Evidence Pack")
                self.inspection_rounds += 1
                self.evidence = self._append_evidence_pack(self.evidence, inspection_pack)
                resolved_inspection_ids = {
                    record.inspection_id
                    for record in inspection_pack.records
                    if record.status in {"completed", "partial"}
                }
                # A failed inspection has not produced reusable evidence.
                # Leave it retriable so the provider can correct its target
                # or arguments; only completed/partial reads become
                # idempotent requests in this planning episode.
                self.requests_seen.extend(
                    request
                    for request in new_requests
                    if request.inspection_id in resolved_inspection_ids
                )
                self.terminal_inspection_ids.update(
                    resolved_inspection_ids
                )
            else:
                inspection_pack = DataEvidencePackV1(
                    source_id=self.evidence.source_id,
                    records=(),
                )
            messages.extend([
                {"role": "assistant", "tool_calls": [call]},
                {
                    "role": "tool",
                    "tool_call_id": call.get("tool_call_id", "inspection"),
                    "content": json.dumps(
                        {
                            "evidence": self.evidence.to_dict(),
                            "evidence_citation_policy": self._evidence_citation_policy(
                                self.evidence
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
                if self.contract_corrections >= self.max_contract_corrections:
                    raise NotebookPlanningContractError(
                        "inspection evidence failed: " + ", ".join(failed_codes)
                    )
                self.contract_corrections += 1
                self._append_contract_correction(
                    messages,
                    call=call,
                    error=NotebookPlanningContractError(
                        "inspection evidence failed: " + ", ".join(failed_codes)
                    ),
                    context=self.context,
                    evidence=self.evidence,
                    correction_number=self.contract_corrections,
                )
            return PhaseStep("continue", tuple(messages))
        if tool_id == "decline_notebook_plan":
            try:
                return self._finish("refused", messages, _parse_planning_refusal(
                    arguments,
                    requests_seen=tuple(self.requests_seen),
                    evidence=self.evidence,
                    rounds=self.round_number,
                ))
            except NotebookPlanningContractError as error:
                if self.contract_corrections >= self.max_contract_corrections:
                    raise
                self.contract_corrections += 1
                self._append_contract_correction(
                    messages,
                    call=call,
                    error=error,
                    context=self.context,
                    evidence=self.evidence,
                    correction_number=self.contract_corrections,
                )
                return PhaseStep("continue", tuple(messages))
        if tool_id != "submit_notebook_option_batch":
            error = NotebookPlanningContractError(f"unknown Notebook planning tool: {tool_id}")
            if self.contract_corrections >= self.max_contract_corrections:
                raise error
            self.contract_corrections += 1
            self._append_contract_correction(
                messages,
                call=call,
                error=error,
                context=self.context,
                evidence=self.evidence,
                correction_number=self.contract_corrections,
            )
            return PhaseStep("continue", tuple(messages))
        try:
            arguments = _canonicalize_provider_option_batch(
                arguments,
                evidence=self.evidence,
                catalog=self.catalog,
            )
            submissions = _parse_submissions(arguments, max_options=self.max_options)
            submissions = self._validate_submissions(
                self.context, self.evidence, submissions, self.catalog, max_options=self.max_options
            )
        except NotebookPlanningContractError as error:
            if self.contract_corrections >= self.max_contract_corrections:
                raise
            self.contract_corrections += 1
            self._append_contract_correction(
                messages,
                call=call,
                error=error,
                context=self.context,
                evidence=self.evidence,
                correction_number=self.contract_corrections,
            )
            return PhaseStep("continue", tuple(messages))
        from ..notebook.producer import option_drafts_from_submissions

        # A planning pass is a new recommendation episode, even when the
        # compiler produces the same context id.  Reusing the context-only
        # batch id would make a deliberate replan collide with the old
        # append-only RecommendationDecision record.
        batch_id = f"batch_agent_{self.context.context_id}_{self.episode_id}"
        try:
            drafts_without_decision = option_drafts_from_submissions(self.context, submissions)
            decision = self.recommendation_validator.decide(
                batch_id=batch_id,
                candidates=drafts_without_decision,
                evidence_pack=self.evidence,
                generation_context_hash=generation_context_hash(self.context),
                freshness_dependency_fingerprint=freshness_dependency_fingerprint(self.context),
            )
            drafts = option_drafts_from_submissions(self.context, submissions, decision=decision)
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
            if self.contract_corrections >= self.max_contract_corrections:
                raise contract_error from error
            self.contract_corrections += 1
            self._append_contract_correction(
                messages,
                call=call,
                error=contract_error,
                context=self.context,
                evidence=self.evidence,
                correction_number=self.contract_corrections,
            )
            return PhaseStep("continue", tuple(messages))
        return self._finish("completed", messages, PlanningResult(tuple(self.requests_seen), self.evidence, submissions, drafts, decision, self.round_number))
