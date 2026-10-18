"""Typed feedback for the bounded planning correction loop."""

from __future__ import annotations

import json
from typing import Any, Mapping
from ..context_compiler import NotebookPlanningContextV1
from ..notebook.evidence import DataEvidencePackV1
from ..recipe_contracts import recipe_contract_for_model_type

from .types import NotebookPlanningContractError
from .provider_contract import NOTEBOOK_TOOLS
from .normalize import _execution_pins


def _append_contract_correction(
    messages: list[dict[str, Any]],
    *,
    call: Mapping[str, Any],
    error: NotebookPlanningContractError,
    context: NotebookPlanningContextV1,
    evidence: DataEvidencePackV1,
    correction_number: int,
) -> None:
    """Give the provider typed feedback without repairing its payload.

    The rejected call is never executed and never becomes evidence.  When
    it names a declared Notebook tool, echoing the assistant/tool pair
    keeps the next provider request valid on OpenAI-compatible APIs.  An
    undeclared tool name is not echoed because some providers reject a
    transcript containing a function that was not offered.
    """

    tool_id = call.get("tool_id")
    if tool_id in {tool["tool_id"] for tool in NOTEBOOK_TOOLS}:
        messages.append({"role": "assistant", "tool_calls": [dict(call)]})
        messages.append(
            {
                "role": "tool",
                "tool_call_id": str(call.get("tool_call_id") or f"contract-{correction_number}"),
                "content": json.dumps(
                    {
                        "status": "rejected",
                        "error_code": NotebookPlanningContractError.code,
                        "message": str(error),
                        "retryable": True,
                        "do_not_use_as_evidence": True,
                    },
                    ensure_ascii=False,
                ),
            }
        )

    messages.append(
        {
            "role": "user",
            "content": _correction_instruction(
                error=error,
                context=context,
                evidence=evidence,
                correction_number=correction_number,
            ),
        }
    )


def _correction_instruction(
    *,
    error: NotebookPlanningContractError,
    context: NotebookPlanningContextV1,
    evidence: DataEvidencePackV1,
    correction_number: int,
) -> str:
    message = str(error)
    evidence_ids = [record.evidence_id for record in evidence.records if record.status == "completed"]
    failed_targets = {
        record.failure_code
        for record in evidence.records
        if record.status == "failed" and record.failure_code
    }
    if message == "provider tool-call arguments were not valid JSON":
        remediation = (
            "The previous typed tool-call arguments were not valid JSON and were "
            "not executed. Submit exactly one Notebook tool call again with one "
            "complete JSON object matching the published schema; do not continue "
            "the truncated fragment or treat it as evidence."
        )
    elif "TARGET_REF_INVALID" in failed_targets:
        expected_target = (
            "run:active"
            if context.projection_source
            and context.projection_source.get("kind") == "run"
            else "dataset:active"
        )
        remediation = (
            "The inspection target did not match the server-bound Notebook projection. "
            f"Request the same inspection ids again with target_ref exactly {expected_target!r}; "
            "do not switch between run:active and dataset:active. Do not submit options until "
            "the resulting evidence records have status completed."
        )
    elif message.startswith("unknown inspection id:"):
        remediation = (
            "Call request_notebook_inspections again with one of these exact ids: "
            "profile.v1, quality.v1, time_index.v1, sample.v1, "
            "forecast_rolling_origin.v1. Never use an internal name such as "
            "inspect_head."
        )
    elif message.startswith("inspection is not available:"):
        available = message.split("; available:", 1)[-1].strip()
        remediation = (
            "Do not request an unregistered inspection. Use only the server-published "
            f"inspection ids: {available}. If the available evidence cannot separate "
            "options, submit them as tied or insufficient evidence."
        )
    elif message == "duplicate inspection request":
        remediation = (
            "Do not request an inspection id already present with status completed "
            "or partial. A partial result is the terminal bounded result; preserve "
            "its omissions as a limitation and proceed using only completed refs "
            "from evidence_citation_policy for citations."
        )
    elif message == "duplicate inspection id has conflicting arguments":
        remediation = (
            "This planning pass already completed that inspection id with a different "
            "target_ref or arguments. Do not relabel its evidence: use the evidence "
            "already returned, or continue with a different registered inspection id."
        )
    elif message == "text-only planning completion is not accepted":
        remediation = (
            "Do not answer in prose. You must call exactly one declared Notebook "
            "tool: request_notebook_inspections when more evidence is required, "
            "submit_notebook_option_batch when the bounded evidence is enough, or "
            "decline_notebook_plan when the request cannot be safely or honestly "
            "become an executable plan."
        )
    elif message == "option tool arguments must contain only options":
        remediation = (
            "Call submit_notebook_option_batch with exactly one top-level field "
            "named options whose value is the option array. Do not include "
            "reasoning, explanation, evidence, metadata, or any other sibling "
            "field; put option-specific rationale inside each option.rationale."
        )
    elif message == "option submission fields are incomplete or unknown":
        remediation = (
            "Each item in options must contain exactly these fields: rank, rationale, "
            "proposal, evidence_refs, comparative_claims, capability_id, and option_id; "
            "assumptions and expected_artifacts are optional. Do not add reasoning, "
            "explanation, evidence, metadata, or other provider fields to an option."
        )
    elif message == "user-visible option text contains internal protocol vocabulary":
        remediation = (
            "Resubmit the same typed proposal, evidence refs, and option identity, but "
            "rewrite rationale, assumptions, and comparative_claims in domain language "
            "for a non-developer. Do not mention operation or capability ids, typed "
            "adapters/workflows/proposals, server-owned pins, or JSON field names."
        )
    elif message == "option evidence ref is missing, changed, or incomplete":
        completed = [
            {
                "evidence_id": record.evidence_id,
                "result_hash": record.result_hash,
                "source_refs": list(record.source_refs),
            }
            for record in evidence.records
            if record.status == "completed"
        ]
        partial = [
            {
                "evidence_id": record.evidence_id,
                "status": record.status,
                "omissions": [dict(item) for item in record.omissions],
            }
            for record in evidence.records
            if record.status == "partial"
        ]
        remediation = (
            "Resubmit the option batch using only an exact evidence_id, "
            "result_hash, and source_refs tuple from completed_evidence_refs "
            f"{json.dumps(completed, sort_keys=True)}. Partial evidence "
            f"{json.dumps(partial, sort_keys=True)} must not be cited as completed; "
            "its omissions may be described only as a limitation. Do not request "
            "the same bounded inspection again merely to remove a declared cap."
        )
    elif "RECIPE_INPUT_PREFLIGHT_FAILED" in message:
        remediation = (
            "The selected Recipe is not executable on the verified source. "
            "Do not resubmit that same Recipe as feasible and do not lower or "
            "guess its data requirement. Choose another server-published method "
            "whose input contract the completed evidence supports, or submit a "
            "domain-language option that explicitly says the current data are "
            "insufficient for a reliable analysis. Preserve the exact evidence "
            "refs and source-bound proposal shape."
        )
    elif message.startswith("RECIPE_MODEL_OPTIONS_REQUIRED:"):
        recipe_id = message.partition(":")[2].partition(" requires")[0].strip()
        recipe_contract = recipe_contract_for_model_type(recipe_id)
        if recipe_contract is None:
            remediation = (
                "Resubmit the Recipe proposal with the exact server-required "
                "model_params.model_options object. Do not replace it with y/x "
                "or an unregistered alias."
            )
        else:
            recipe_payload = recipe_contract.to_payload()
            required_inputs = recipe_payload["required_inputs"]
            remediation = (
                "Resubmit model.genesis with model_params.model_type exactly "
                f"{recipe_id!r} and model_params.model_options containing these "
                f"exact required fields: {json.dumps(required_inputs)}. The field "
                "values must be exact completed-evidence column names; do not use "
                "regression y/x fields. Use only the remaining option fields and "
                "values published in this Recipe vocabulary: "
                f"{json.dumps(recipe_payload['parameter_vocabulary'], sort_keys=True)}."
            )
    elif message == "dataset-source proposal is not pinned to the source upload":
        source_id = (context.projection_source or {}).get("upload_sha256")
        remediation = (
            "Resubmit the dataset proposal without changing the server-owned pin: "
            "operation_id must be model.genesis and target.dataset_source_id must "
            f"equal exactly {source_id!r}. Do not derive or shorten this value."
        )
    elif message.startswith("operation.multi_step capability_id must name"):
        eligible = sorted(str(item) for item in context.available_capabilities)
        remediation = (
            "Resubmit the same source-pinned operation.multi_step proposal, but set "
            "capability_id to one primary capability actually declared by its steps: "
            "a model_family from model.genesis or a P7 operation_id from a P7-only "
            "workflow. Do not use operation.multi_step itself. "
            f"Eligible published capabilities include {eligible}."
        )
    elif message.startswith("operation.multi_step has no contractible"):
        remediation = (
            "The current Notebook is upload-only and has no server-pinned workflow "
            "source for operation.multi_step. Do not submit operation.multi_step. "
            "Submit exactly one ordinary model.genesis option using a registered "
            "model whose typed input contract the completed evidence supports, "
            "or state that the data are insufficient; never invent a workflow "
            "source or a P7 result artifact."
        )
    elif "model.genesis preconditions missing" in message:
        pins = _execution_pins(context)["genesis_preconditions"]
        remediation = (
            "Resubmit model.genesis with the complete server-owned preconditions "
            f"copied exactly: {json.dumps(pins, sort_keys=True)}."
        )
    elif "model.genesis changes contain unknown field(s)" in message:
        remediation = (
            "Resubmit model.genesis with changes containing only these exact "
            "object fields: table_params, model_params, or model_options. Put "
            "model_type, y, x, covariance, and other model settings inside "
            "model_params or model_options; never put capability_id, params, "
            "capability, parameters, or raw model fields directly under changes."
        )
    elif "workflow step contains unknown field(s)" in message:
        remediation = (
            "Resubmit the workflow with each changes.steps entry using only "
            "step_id, operation_id, spec, and optionally depends_on or "
            "expected_artifacts at its outer level. Move every operation-specific "
            "field, including model, exploration, or adapter parameters, inside "
            "spec; then use only the exact field names published for that step's "
            "operation_id in typed_operation_contracts.operation.multi_step.step_vocabulary."
        )
    elif "depends_on must be step ids" in message:
        remediation = (
            "Resubmit every workflow step: omit depends_on when it has no prerequisite, "
            "or as a JSON array of exact earlier step ids, for example \"depends_on\": "
            "[\"source_step\"]. Never use a string, object, branch_id, or artifact id."
        )
    elif (
        message.startswith("model.genesis model_params must")
        or message.startswith("model.genesis requires completed column evidence")
        or message.startswith("model.genesis y is not present")
        or message.startswith("model.genesis x is not present")
    ):
        columns = sorted(
            {
                str(column.get("name"))
                for record in evidence.records
                if isinstance(record.observations, Mapping)
                for column in (record.observations.get("columns") or [])
                if isinstance(column, Mapping) and column.get("name")
            }
        )
        remediation = (
            "Resubmit model.genesis with model_params containing model_type, an exact target y, "
            "and a non-empty x list for non-time-series models. Every name must be present in "
            f"completed evidence columns {columns or ['not available']}; do not infer a target "
            "from convention."
        )
    elif "model.rerun changes contain unknown field(s)" in message:
        remediation = (
            "Resubmit model.rerun with changes containing only model_options as "
            "an object; do not put capability, params, or raw model fields "
            "directly under changes."
        )
    elif "model.custom" in message:
        remediation = (
            "Resubmit model.custom with only operation, input_handle, parameters, and consumer_slots "
            "under changes. Keep capability_ref and binding_ref out of the Agent payload; the server "
            "resolves them from capability_id. Use only the exact input handle and consumer slots "
            "published by the server, and do not request execution outside the Proposal/Risk gateway."
        )
    elif (
        "model_options target contract rejected" in message
        and "MODEL_OPTIONS_UNSUPPORTED" in message
    ):
        remediation = (
            "This exact model type publishes no model_options contract. Resubmit "
            "the same proposal but omit model_options entirely. Do not borrow "
            "covariance or any other option from a related model family."
        )
    elif "OLS_MODEL_OPTIONS_UNKNOWN_FIELD" in message:
        remediation = (
            "For a standalone OLS model.genesis proposal, OLS model_options may contain "
            "only the server-published covariance field. Remove branches and every "
            "other nested key; put the exact y and x columns in model_params. If the "
            "user needs multiple OLS branches, submit operation.multi_step with its "
            "published step vocabulary instead of placing branches inside model_options."
        )
    elif "model_options target contract rejected" in message:
        remediation = (
            "Resubmit the same typed proposal only after correcting model_options against the "
            "server-published target contract. Preserve the exact nested field names and value types "
            "shown in capability_catalog.notebook_model_options_contract or model_options_vocabulary; "
            "send a patch, not a new alias vocabulary. Do not guess a model setting."
        )
    elif "does not accept OLS covariance settings" in message:
        remediation = (
            "The selected model family does not accept OLS covariance settings. "
            "omit model_params.covariance and changes.model_options entirely; "
            "submit only the model_type, evidence-backed y/x, and family-required "
            "fields published for the selected capability. Do not borrow covariance "
            "or model_options from OLS or another related family."
        )
    elif message.startswith("typed proposal fields are incomplete or unknown:"):
        remediation = (
            "Resubmit the proposal with exactly these fields and no others: "
            "proposal_id, proposal_revision, operation_id, operation_version, "
            "target, preconditions, changes. proposal_revision must be an "
            "integer >= 1; do not omit it or add model fields at proposal level."
        )
    elif message == "option batch contains duplicate executable proposals":
        remediation = (
            "Do not submit duplicate executable proposals under different option "
            "ids. Each option must have a distinct canonical typed proposal; if "
            "there is no genuinely distinct supported path, submit fewer options."
        )
    elif message == "option ranks must be unique":
        remediation = "Use each rank only once, from 1 through the number of submitted options."
    elif message == "option batch must contain at most 3 options":
        remediation = (
            "Resubmit at most three options in one submit_notebook_option_batch call. "
            "Keep only genuinely distinct supported paths; do not split one analysis "
            "across multiple calls or silently invent a fourth option."
        )
    elif "expected artifact failed published artifact vocabulary validation" in message:
        remediation = (
            "Keep every required expected_artifact aligned with the selected capability: "
            "logit uses logit_1, probit uses probit_1, and OLS uses ols_1. Do not mix a "
            "result id from another model family. Use the exact artifact_type published "
            "for that capability, and do not invent a new artifact id."
        )
    elif "published artifact vocabulary validation" in message:
        remediation = (
            "Remove the unsupported required artifact and resubmit. A required "
            "artifact_id must appear exactly in context.artifact_vocabulary with "
            "its declared artifact_type; do not invent artifact ids or types. If "
            "no published artifact is certain, do not submit this capability; "
            "the server will not accept an unauditable option."
        )
    elif message.startswith("capability required artifact(s) missing:"):
        remediation = (
            "Resubmit the option with every server-published primary result "
            "artifact named in the error as a required expected_artifact, using "
            "the exact artifact_type from context.artifact_vocabulary."
        )
    elif "operation is not registered:" in message:
        if context.projection_source and context.projection_source.get("kind") == "dataset":
            remediation = (
                "For this dataset projection, operation_id must be exactly "
                "model.genesis and operation_version exactly v1. Never append "
                "another operation id, adapter name, or @version suffix. Use "
                "the exact dataset_source_id and genesis execution pins already "
                "provided in context."
            )
        else:
            remediation = (
                "operation_id must be exactly model.genesis or model.rerun and "
                "operation_version exactly v1. Never append another operation "
                "id, adapter name, or @version suffix."
            )
    elif "does not copy the server execution pins" in message:
        pins = _execution_pins(context)
        remediation = (
            "Resubmit the proposal with the matching server-owned preconditions "
            f"copied exactly from execution_pins: {json.dumps(pins, sort_keys=True)}."
        )
    elif message == "run-source proposal is not a rerun-child of the active head":
        # The server refused a target outside the active head's lineage.
        # Naming only the violation leaves an otherwise workable request
        # stranded, so hand back the eligible targets -- or, when the head
        # admits none, send the provider to genesis instead of asking it to
        # satisfy a rerun that cannot exist.
        pins = _execution_pins(context)
        rerun_pins = pins.get("rerun_preconditions_by_target", [])
        if rerun_pins:
            remediation = (
                "A run-source proposal must target a model node on the active head. "
                "Resubmit with operation_id model.rerun (or model.custom) and one "
                "exact target and precondition pair copied from the server-owned "
                "execution_pins.rerun_preconditions_by_target; do not rewrite "
                f"run_id, node_ref, node_hash, forest_node_key, or context_fingerprint: "
                f"{json.dumps(rerun_pins, sort_keys=True)}."
            )
        else:
            remediation = (
                "The active head exposes no eligible model node, so no rerun target "
                "exists. Do not retry a run-source proposal. Submit a dataset-source "
                "model.genesis proposal instead, copying the server-owned genesis "
                f"execution pins exactly: {json.dumps(pins.get('genesis'), sort_keys=True)}."
            )
    elif message == "run-source proposal target is not a server-pinned model node":
        pins = _execution_pins(context).get(
            "rerun_preconditions_by_target", []
        )
        remediation = (
            "Choose one exact target and precondition pair from the server-owned "
            "execution_pins.rerun_preconditions_by_target list; do not rewrite "
            f"node_ref, node_hash, forest_node_key, or context_fingerprint: {json.dumps(pins, sort_keys=True)}."
        )
    else:
        remediation = (
            "Resubmit exactly one typed Notebook tool call after correcting the "
            "reported contract error. Do not invent evidence, capabilities, or "
            "execution pins."
        )
    return (
        "Workbench rejected the previous Notebook tool call; it was not executed "
        "and is not evidence. This is bounded contract correction attempt "
        f"#{correction_number}. {message}. {remediation}"
    )
