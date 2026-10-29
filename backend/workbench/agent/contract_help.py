"""What to write instead: help appended to a refusal of the Agent's own input.

Contract errors name what was wrong. The Agent also needs what is right, or it
guesses again: in the v1.9.1 smoke it wrote ``event_col`` for the Cox model's
``event_column`` and learned only that ``event_col`` was refused. The help is
read from the declarations the check used, so it cannot drift from them.
"""

from __future__ import annotations

import difflib
import json
import re

_UNKNOWN_OPTIONS = re.compile(r"model\.genesis (\S+) model_options does not accept field\(s\): (.+)$")
_MISSING_OPTIONS = re.compile(r"model\.genesis (\S+) model_options requires: ")


def _family_fields(family: str) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    from ..contracts.model.family import MODEL_FAMILY_CONTRACTS

    contract = MODEL_FAMILY_CONTRACTS.get(family)
    if contract is None:
        return None
    return tuple(contract.model_options_fields), tuple(contract.model_options_required_fields)


def workflow_step_hint(operation_id: object) -> dict | None:
    from .workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

    if not isinstance(operation_id, str) or operation_id not in WORKFLOW_STEP_SPEC_CONTRACTS:
        return None
    return {"tool_id": "inspect_operation_contract", "arguments_patch": {
        "operation_id": "operation.multi_step", "step_operation_ids": [operation_id]}}


def retry_hint_for(message: str) -> dict | None:
    for pattern in (r"^operation is not registered: (\S+)@", r"^(\S+)@\S+ is a workflow step"):
        match = re.match(pattern, message)
        if match:
            return workflow_step_hint(match.group(1))
    return None


def _ols_cluster_help() -> str:
    from ..contracts.model.ols import OLS_COVARIANCE_VALUES
    from .operation_schemas import _model_rerun_proposal_schema, model_rerun_change_fields

    if "clustered" not in OLS_COVARIANCE_VALUES:
        return ""
    fields = {"covariance", "entity_col"}
    if fields <= set(model_rerun_change_fields()):
        return " If clustered OLS standard errors are required, inspect model.rerun on the fitted OLS model for its covariance/entity_col patch."
    branches = _model_rerun_proposal_schema()["properties"]["changes"]["oneOf"]
    if any(fields <= set(branch.get("properties", {}))
           and "preconditions.analysis_loop" in branch.get("description", "") for branch in branches):
        return (
            " If clustered OLS standard errors are required, inspect model.rerun on the fitted OLS model. "
            "Its covariance/entity_col compatibility patch requires an existing server-bound Analysis Loop "
            "(preconditions.analysis_loop); do not invent that binding or submit it as an ordinary rerun patch."
        )
    return ""


def help_for(message: str) -> str:
    """A sentence to append to ``message``, or ''."""

    first_line = message.splitlines()[0][:1000] if message else ""
    hint = retry_hint_for(first_line)
    if hint is not None:
        steps = json.dumps(hint["arguments_patch"]["step_operation_ids"])
        return (" Read inspect_operation_contract with operation_id=operation.multi_step and "
                f"step_operation_ids={steps}; retain required source identity, then declare the step in changes.steps.")
    match = re.match(r"^model\.genesis (\S+) ", first_line)
    if match is None:
        return ""
    from ..contracts.model.family import MODEL_FAMILY_CONTRACTS

    family = match.group(1)
    contract = MODEL_FAMILY_CONTRACTS.get(family)
    if contract is None:
        return ""
    options = _help_for_options(first_line)
    parts = [f"{family} step.spec context fields: {', '.join(contract.context_spec_fields) or 'no fields'}."]
    if contract.required_spec_fields:
        parts.append(f"Context required ({contract.required_spec_field_mode}): {', '.join(contract.required_spec_fields)}.")
    parts.append("branches[].categorical is " + ("allowed" if contract.allows_categorical_terms else "not allowed") + ".")
    if not options:
        options = (f" {family} model_options accepts: {', '.join(contract.model_options_fields) or 'no fields'}"
                   + (f" (required: {', '.join(contract.model_options_required_fields)})" if contract.model_options_required_fields else "") + ".")
    cluster = _ols_cluster_help() if family == "ols" and (
        "does not accept panel entity_col or time_col" in first_line
        or ("model_options does not accept" in first_line and "cluster" in first_line)
    ) else ""
    return (options + " " + " ".join(parts) + cluster
            + ' Read inspect_operation_contract with operation_id=operation.multi_step and step_operation_ids=["model.genesis"] for nested spec schemas; retain required source identity.')


def _help_for_options(first_line: str) -> str:
    unknown = _UNKNOWN_OPTIONS.search(first_line)
    family = unknown.group(1) if unknown else (m.group(1) if (m := _MISSING_OPTIONS.search(first_line)) else None)
    fields = _family_fields(family) if family else None
    if not fields:
        return ""
    accepted, required = fields
    parts = [f"{family} model_options accepts: {', '.join(accepted) or 'no fields'}"
             + (f" (required: {', '.join(required)})" if required else "") + "."]
    if unknown:
        guesses = []
        for name in (item.strip() for item in unknown.group(2).split(",")):
            match = difflib.get_close_matches(name, accepted, n=1, cutoff=0.5)
            if match:
                guesses.append(f"{name} -> {match[0]}")
        if guesses:
            parts.append("Did you mean " + "; ".join(guesses) + "?")
    return " " + " ".join(parts)
