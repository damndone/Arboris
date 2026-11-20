"""Deterministic context construction for model requests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .compaction import SUMMARY_NAME, UNVERIFIED_SUMMARY_NAME, is_standing, latest_compaction, live_start
from .session import JsonlSessionRepository, SessionTreeEntry


@dataclass(frozen=True)
class CustomAgentMessage:
    """A durable message that can be projected into model context."""

    content: str
    audience: str = "model"
    name: str = "workbench"
    metadata: dict[str, Any] | None = None

    def to_entry_payload(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "audience": self.audience,
            "name": self.name,
            "metadata": dict(self.metadata or {}),
        }


@dataclass(frozen=True)
class ContextSnapshot:
    messages: list[dict[str, Any]]
    fingerprint: str
    source_entry_ids: list[str]


_CONTEXT_PAYLOAD_TYPES = frozenset({"message", "custom_message", "compaction"})


class ContextBuilder:
    """Build model messages from a resolved branch without hidden truncation."""

    def __init__(self, repository: JsonlSessionRepository) -> None:
        self.repository = repository

    def build(
        self,
        session_id: str,
        *,
        leaf_entry_id: str | None = None,
        workbench_context: dict[str, Any] | None = None,
        include_failed_assistant_messages: bool = False,
    ) -> ContextSnapshot:
        messages: list[dict[str, Any]] = []
        source_entry_ids: list[str] = []
        shown_proposals: dict[str, dict[str, Any]] = {}
        branch = self.repository.get_branch(session_id, leaf_entry_id=leaf_entry_id,
                                            payload_entry_types=_CONTEXT_PAYLOAD_TYPES)
        projected = _project(branch)
        # A proposal's audit record is stored before the run_operation result that
        # carries the same proposal, and sent after it; note those results first, or
        # every record goes out in full (about 1.7 KB per proposal, 2026-10-23).
        for entry in projected:
            content = entry.payload.get("content")
            if (entry.entry_type == "message" and entry.payload.get("role") == "tool"
                    and isinstance(content, str) and '"proposal_id"' in content):
                _note_tool_proposal(content, shown_proposals)
        for entry in projected:
            payload = dict(entry.payload)
            if entry.entry_type == "message":
                role = payload.get("role")
                content = payload.get("content")
                if not isinstance(role, str) or not isinstance(content, str):
                    continue
                if (
                    role == "assistant"
                    and payload.get("stop_reason") in {"aborted", "error"}
                    and not include_failed_assistant_messages
                ):
                    continue
                messages.append({
                    key: value
                    for key, value in payload.items()
                    if key not in {"stop_reason", "command_id"}
                })
                source_entry_ids.append(entry.entry_id)
            elif entry.entry_type == "custom_message":
                if payload.get("audience", "model") != "model":
                    continue
                content = payload.get("content")
                if isinstance(content, str):
                    # A server message that asks the model to act now (e.g. the
                    # numeric check's rewrite request) opens a new turn as a user
                    # message: providers with private reasoning refuse a second
                    # answer inside a turn that already used tools.
                    role = "user" if payload.get("model_role") == "user" else "system"
                    content = _proposal_record_content(payload, content, shown_proposals)
                    if isinstance(payload.get("attachment"), dict) and payload["attachment"].get("kind") == "image":
                        messages.append({"role": role, "content": content, "name": payload.get("name"),
                                         "attachment_image": payload["attachment"]})
                        source_entry_ids.append(entry.entry_id)
                        continue
                    messages.append({"role": role, "content": content, "name": payload.get("name", "workbench")})
                    source_entry_ids.append(entry.entry_id)
            elif entry.entry_type == "compaction":
                summary = payload.get("summary")
                if isinstance(summary, str):
                    verified = payload.get("verified", True) is not False
                    messages.append({
                        "role": "system",
                        "content": (
                            "Summary of the earlier part of this conversation (the messages it replaces "
                            "are still on record; inspect results again by id when you need detail):\n"
                            + summary
                            if verified
                            else "Summary of the earlier part of this conversation. Some numbers in it could "
                            "not be matched to the conversation, so do not cite numbers from it: inspect "
                            "them again by id.\n" + summary
                        ),
                        "name": SUMMARY_NAME if verified else UNVERIFIED_SUMMARY_NAME,
                    })
                    source_entry_ids.append(entry.entry_id)

        if workbench_context:
            messages.append(
                {
                    "role": "system",
                    "content": json.dumps(workbench_context, ensure_ascii=False, sort_keys=True),
                    "name": "workbench_context",
                }
            )
        serialized = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return ContextSnapshot(messages=messages, fingerprint=fingerprint, source_entry_ids=source_entry_ids)


def project_published_contracts(snapshot: ContextSnapshot, tools: list[dict[str, Any]]) -> ContextSnapshot:
    """Elide schema fields only when their exact declaration is in this request.

    This is a model view, not an execution reference or a mutation of the WAL.
    Scientific evidence, errors, approval records and other tool results stay full.
    """
    from copy import deepcopy
    from .protocol import _reference_step_spec, step_reference

    calls = set()
    for message in snapshot.messages:
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            if call.get("tool_id", function.get("name")) == "inspect_operation_contract":
                calls.add(call.get("tool_call_id", call.get("id")))
    candidates = [message for message in snapshot.messages
                  if message.get("role") == "tool" and message.get("name") == "inspect_operation_contract"
                  and message.get("tool_call_id") in calls]
    protocols = [message.get("content") for message in snapshot.messages
                 if message.get("role") == "system" and message.get("name") == "workbench_agent_protocol"]
    declarations = [tool.get("input_schema") for tool in tools if tool.get("tool_id") == "run_operation"]
    if not candidates or len(protocols) != 1 or len(declarations) != 1:
        return snapshot
    schema = declarations[0]
    if not isinstance(protocols[0], str) or not isinstance(schema, dict):
        return snapshot
    references = step_reference()
    lines = set(protocols[0].splitlines())
    published = {name: spec for name, spec in references.items()
                 if "      " + name + ": " + json.dumps(spec, ensure_ascii=False, separators=(",", ":")) in lines}
    if not published:
        return snapshot

    def digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":"), allow_nan=False).encode()).hexdigest()

    def project(message):
        try:
            result = json.loads(message["content"])
        except (TypeError, ValueError):
            return message
        if not isinstance(result, dict) or result.get("ok") is not True or result.get("error") is not None:
            return message
        output = result.get("output")
        if not isinstance(output, dict) or output.get("status") == "partial" or output.get("omitted_sections") or output.get("truncated_sections"):
            return message
        contract = output.get("contract")
        if not isinstance(contract, dict) or contract.get("contract_owner") != "operation_registry":
            return message
        operation_id = contract.get("op_type")
        branches = [branch for branch in schema.get("oneOf", [])
                    if branch.get("properties", {}).get("operation_id", {}).get("const") == operation_id]
        if len(branches) != 1:
            return message
        properties = branches[0]["properties"]
        version = properties.get("operation_version", {}).get("const")
        editable = properties.get("changes")
        if version is None or contract.get("schema_id") != f"{operation_id}@{version}" or contract.get("editable_schema") != editable:
            return message
        vocabulary = contract.get("step_vocabulary")
        if not isinstance(vocabulary, dict) or vocabulary.get("unknown_step_operation_ids"):
            return message
        specs = vocabulary.get("step_operations")
        if not isinstance(specs, dict):
            return message
        for name, spec in specs.items():
            if name in references and (name not in published or not isinstance(spec, dict)
                                      or _reference_step_spec(spec) != published[name]):
                return message
        projected = deepcopy(result)
        compact = projected["output"]["contract"]
        compact["editable_schema"] = {"published_in": f"run_operation.{operation_id}.changes",
                                       "schema_sha256": digest(editable)}
        for name, spec in compact["step_vocabulary"]["step_operations"].items():
            if name not in published:
                continue
            equal = [key for key, value in spec.items() if key in published[name] and published[name][key] == value]
            retained = {key: value for key, value in spec.items() if key not in equal}
            retained["same_as_published"] = {"name": "workbench_agent_protocol:" + name,
                                            "schema_sha256": digest(published[name]), "unchanged_fields": equal}
            compact["step_vocabulary"]["step_operations"][name] = retained
        content = json.dumps(projected, ensure_ascii=False, sort_keys=True, allow_nan=False)
        return {**message, "content": content} if len(content.encode()) < len(message["content"].encode()) else message

    candidate_ids = {id(message) for message in candidates}
    messages = [project(message) if id(message) in candidate_ids else message for message in snapshot.messages]
    if messages == snapshot.messages:
        return snapshot
    serialized = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return ContextSnapshot(messages=messages, fingerprint=hashlib.sha256(serialized.encode()).hexdigest(),
                           source_entry_ids=list(snapshot.source_entry_ids))


# Proposal audit messages repeat the proposal the model already received in its
# run_operation tool result (the changes up to four times per confirmation). The
# projection keeps every field whose value is new for that proposal and names
# the rest; the stored audit record stays complete.
_PROPOSAL_RECORD_FIELDS = {"operation_proposal": "proposal", "operation_proposal_revision": "proposal",
                           "operation_confirmation": "confirmation"}
_PROPOSAL_IDENTITY = ("record_type", "proposal_id", "revision", "fingerprint", "status")


def _note_tool_proposal(content: str, shown: dict[str, dict[str, Any]]) -> None:
    try:
        output = json.loads(content).get("output")
    except (ValueError, AttributeError):
        return
    proposal = output.get("proposal") if isinstance(output, dict) else None
    if isinstance(proposal, dict) and isinstance(proposal.get("proposal_id"), str):
        shown[proposal["proposal_id"]] = {**shown.get(proposal["proposal_id"], {}), **proposal}


def _proposal_record_content(payload: dict[str, Any], content: str, shown: dict[str, dict[str, Any]]) -> str:
    record = payload.get(_PROPOSAL_RECORD_FIELDS.get(payload.get("message_type"), ""))
    if not isinstance(record, dict) or not isinstance(record.get("proposal_id"), str):
        return content
    if content != json.dumps(record, ensure_ascii=False, sort_keys=True):
        return content  # already bounded to a summary
    prior = shown.get(record["proposal_id"])
    shown[record["proposal_id"]] = {**(prior or {}), **record}
    if prior is None or prior.get("fingerprint") != record.get("fingerprint"):
        return content
    compact = {key: value for key, value in record.items() if key in _PROPOSAL_IDENTITY or prior.get(key) != value}
    if len(compact) == len(record):
        return content
    compact["repeated_fields"] = sorted(set(record) - set(compact))
    compact["repeated_fields_note"] = "Same values as already shown above for this proposal and fingerprint."
    return json.dumps(compact, ensure_ascii=False, sort_keys=True)


_STANDING_ORDER = {name: index for index,name in enumerate([
    "workbench_global_agent_protocol", "workbench_agent_protocol", "workbench_agent_identity",
    "workbench_instructions", "workbench_context", "workbench_agent_focus", "workbench_project_recall",
])}


def _project(branch: list[SessionTreeEntry]) -> list[SessionTreeEntry]:
    """Latest standing layers lead a stable prefix; dialogue keeps its order."""
    latest = {str(entry.payload.get("name")):entry for entry in branch if is_standing(entry)}
    head = sorted(latest.values(),key=lambda entry:_STANDING_ORDER[str(entry.payload["name"])])
    found = latest_compaction(branch)
    start = live_start(branch) if found is not None else 0
    tail = [entry for entry in branch[start:] if entry.entry_type != "compaction" and not is_standing(entry)]
    return [*head,*([found[1]] if found is not None else []),*tail]
