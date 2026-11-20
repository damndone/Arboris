"""Bounded server request sources on the existing session WAL, never authority to run."""
from __future__ import annotations

import json
import re
from copy import deepcopy

from jsonschema import Draft202012Validator

from ..contracts.common.errors import OperationValidationError
from ..jsonl_store import _exclusive_jsonl_lock
from .operation_definitions import UnknownOperationError
from .operation_requests import OperationRequest, validate
from .session import SessionTreeEntry, _log_index, _payload_digest
from .tool_receipts import ToolReceiptError, _check_strict, _strict_row, tool_call_sha256
from .tools import ToolVisibleError

ENTRY_TYPE = "operation_request_refs"
SCHEMA = "agent.operation_request_refs.v1"
STAGE = "operation_request_refs"
MAX_REQUESTS = 5
MAX_SOURCE_BYTES = 65_536
REF_PATTERN = r"^opreq:[0-9a-f]{32}:[0-4]$"
_REF = re.compile(REF_PATTERN)
_REINSPECT = " No operation was executed. Call inspect_analysis_completion again for a fresh server-bound request."


class RequestRefError(ToolVisibleError):
    """An unverified, stale or unavailable request cannot be substituted."""


def _fail(reason):
    return RequestRefError("OPERATION_REQUEST_REF_UNAVAILABLE: " + reason + _REINSPECT)


def _encoded(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError) as exc:
        raise _fail("request source is not finite JSON") from exc


def wire_schema(full_schema):
    """Keep the original envelope and add an exclusive opaque reference form."""
    reference = {"type": "object", "required": ["request_ref"],
        "properties": {"request_ref": {"type": "string", "pattern": REF_PATTERN, "maxLength": 64}},
        "additionalProperties": False}
    schema = deepcopy(full_schema)
    if not isinstance(schema.get("oneOf"), list):
        return {"oneOf": [schema, reference]}
    # Keep operation_id discrimination at its original level so required-path,
    # type and JSON-Patch help still selects the actual operation's contract.
    required = schema.pop("required", [])
    for branch in schema["oneOf"]:
        branch["required"] = list(dict.fromkeys([*branch.get("required", []), *required]))
    schema["properties"]["request_ref"] = reference["properties"]["request_ref"]
    schema["oneOf"].append(reference)
    return schema


def validate_request(arguments, operation_registry):
    if (type(arguments) is not dict or arguments.get("operation_id") != "operation.multi_step"
            or not Draft202012Validator(operation_registry.proposal_tool_schema()).is_valid(arguments)):
        raise _fail("the server recommendation is not a complete operation request")
    try:
        request = OperationRequest.from_arguments(arguments)
        validate(request, operation_registry.require(request.operation_id, request.operation_version))
    except (OperationValidationError, UnknownOperationError) as exc:
        raise _fail("the server recommendation does not satisfy its operation contract") from exc


def _entry(repository, session_id, entry_id):
    """Use the strict receipt index and current ancestry, not get_entry's first match."""
    path = repository._session_path(session_id)
    try:
        with repository._lock, _exclusive_jsonl_lock(path):
            index = _log_index(path)
            _check_strict(index)
            positions = index.by_id.get(entry_id, ())
            if len(positions) != 1:
                raise _fail("request source entry is missing or duplicated")
            position = positions[0]
            if not any(branch.identity == index.identity and p == position
                       for branch, p in repository._branch_positions(session_id, None)):
                raise _fail("request source is not on this session's current branch")
            row = _strict_row(index.lines[position])
            entry = SessionTreeEntry.from_dict(row)
            if entry.session_id != session_id or _encoded(row) != _encoded(entry.to_dict()):
                raise _fail("request source entry identity is invalid")
            identity = entry.idempotency
            if (not identity or identity.get("payload_sha256") != _payload_digest(entry.entry_type, entry.payload)):
                raise _fail("request source has no verified append-once payload")
            return entry
    except RequestRefError:
        raise
    except (ValueError, TypeError, KeyError, OSError, UnicodeError, ToolReceiptError) as exc:
        raise _fail("request source session log cannot be verified") from exc


def _origin(repository, session_id, entry_id, metadata=None):
    entry = _entry(repository, session_id, entry_id)
    payload = entry.payload
    if (entry.entry_type != "tool_intent" or entry.idempotency.get("stage") != "tool_intent"
            or entry.idempotency.get("key") != payload.get("invocation_id")
            or payload.get("session_id") != session_id
            or type(payload.get("provider_step")) is not int or payload["provider_step"] < 1
            or any(type(payload.get(key)) is not str or not payload[key]
                   for key in ("command_id", "invocation_id", "tool_call_id"))):
        raise _fail("request source was not issued by a durable inspection invocation")
    call = payload.get("tool_call")
    try:
        tool_call_sha256(call)
    except ToolReceiptError as exc:
        raise _fail("inspection call identity is invalid") from exc
    if call["tool_id"] != "inspect_analysis_completion" or call["tool_call_id"] != payload["tool_call_id"]:
        raise _fail("request source was not issued by inspect_analysis_completion")
    if metadata is not None and any(payload.get(key) != metadata.get(key)
            for key in ("command_id", "provider_step", "tool_call_id", "invocation_id")):
        raise _fail("inspection invocation does not match its durable intent")
    return entry


def _items(requests):
    if type(requests) is not list or not 0 < len(requests) <= MAX_REQUESTS:
        raise _fail("request source exceeds its item limit or is empty")
    for item in requests:
        if (type(item) is not dict or set(item) != {"kind", "label", "arguments"}
                or type(item["kind"]) is not str or item["kind"] not in {"sensitivity", "report"}
                or type(item["label"]) is not str or not 0 < len(item["label"]) <= 200
                or type(item["arguments"]) is not dict):
            raise _fail("request source has an invalid item")


def persist(repository, *, session_id, metadata, binding, requests, operation_registry):
    """Save complete requests before ToolRegistry projects the public result."""
    _items(requests)
    if type(binding) is not dict or type(metadata) is not dict:
        raise _fail("request source has no binding or invocation")
    invocation = metadata.get("invocation_id")
    if type(invocation) is not str or not invocation:
        raise _fail("inspection has no durable invocation")
    candidates = repository.get_branch(session_id, payload_entry_types=frozenset({"tool_intent"}))
    matches = [entry for entry in candidates if entry.entry_type == "tool_intent" and entry.idempotency
        and entry.idempotency.get("key") == invocation and entry.idempotency.get("stage") == "tool_intent"]
    if len(matches) != 1:
        raise _fail("inspection has no unique durable intent")
    origin = _origin(repository, session_id, matches[0].entry_id, metadata)
    for item in requests:
        validate_request(item["arguments"], operation_registry)
    payload = {"schema_version": SCHEMA, "origin_entry_id": origin.entry_id,
        "origin_sha256": origin.idempotency["payload_sha256"], "binding": binding, "requests": requests}
    encoded = _encoded(payload)
    if len(encoded) > MAX_SOURCE_BYTES:
        raise _fail("complete request source exceeds its byte limit")
    payload = json.loads(encoded)
    entry = repository.append_once(session_id, ENTRY_TYPE, payload, key=invocation, stage=STAGE)
    return [{"kind": item["kind"], "label": item["label"], "request_ref": f"opreq:{entry.entry_id}:{i}"}
            for i, item in enumerate(requests)]


def read(repository, *, session_id, request_ref):
    """Read only a verified server source on this branch; freshness is checked by its consumer."""
    if type(request_ref) is not str or not _REF.fullmatch(request_ref):
        raise _fail("invalid opaque request reference")
    _, entry_id, slot = request_ref.split(":")
    entry = _entry(repository, session_id, entry_id)
    payload = entry.payload
    if (entry.entry_type != ENTRY_TYPE or entry.idempotency.get("stage") != STAGE
            or set(payload) != {"schema_version", "origin_entry_id", "origin_sha256", "binding", "requests"}
            or payload["schema_version"] != SCHEMA or type(payload["binding"]) is not dict
            or len(_encoded(payload)) > MAX_SOURCE_BYTES):
        raise _fail("entry is not a bounded server request source")
    _items(payload["requests"])
    origin = _origin(repository, session_id, payload["origin_entry_id"])
    if (entry.idempotency["key"] != origin.payload["invocation_id"]
            or payload["origin_sha256"] != origin.idempotency["payload_sha256"]):
        raise _fail("request source does not match its original inspection")
    index = int(slot)
    if index >= len(payload["requests"]):
        raise _fail("request slot is absent")
    return {**payload["requests"][index], "binding": payload["binding"]}


def _binding(orchestrator, session_id, plan, check):
    from ..canonical import sha256_canonical
    from .task_requirements import signature

    metadata = orchestrator.repository.get_metadata(session_id)
    chain = metadata.get("chain_id")
    if (metadata.get("role") != "chain" or type(chain) is not str or not chain
            or plan is None or not plan.completion or not isinstance(plan.completion.get("source"), dict)
            or not isinstance(check.get("verified_manifest_sha256"), str)):
        raise _fail("recommendation has no complete managed source and plan binding")
    head = orchestrator._resolve_chain_head(chain, None)
    if not isinstance(head, str) or not head:
        raise _fail("recommendation has no current managed head")
    definition = orchestrator.operation_registry.require("operation.multi_step")
    contract = {"proposal": definition.proposal_schema, "editable": definition.editable_schema,
        "vocabulary": definition.vocabulary_builder() if definition.vocabulary_builder else None,
        "wire": orchestrator.operation_registry.proposal_tool_schema()}
    return {"chain_id": chain, "active_head_run_id": head,
        "plan_sha256": sha256_canonical({"question": plan.question, "criteria": list(plan.criteria),
            "completion": plan.completion, "completion_evidence": plan.completion_evidence,
            "task_requirements_sha256": signature(plan.task_requirements)}),
        "contract_sha256": sha256_canonical(contract),
        "verified_manifest_sha256": check["verified_manifest_sha256"]}


def _dataset_target(orchestrator, check, *, target=None, source=None):
    """Bind graph ownership from verified metadata; do not read or serialize observation rows."""
    from pathlib import Path
    from ..graph_model import NodeKind
    from ..graph_store import GraphStore

    root = orchestrator.data_operation_project_root
    run = (source or target or {}).get("run_id")
    if root is None or type(run) is not str:
        raise _fail("recommendation has no project-owned dataset target")
    run_root = (Path(root) / "runs" / run).resolve()
    if run_root.parent != (Path(root) / "runs").resolve():
        raise _fail("recommendation source is outside project runs")
    try:
        graph = GraphStore(Path(root) / "runs").read(run)
        from .context_compiler import registered_artifact_records

        records = registered_artifact_records(run_root)
        if source is not None:
            records = [r for r in records if r.get("artifact_id") == source.get("artifact_id")]
            if len(records) != 1:
                raise _fail("report source artifact is missing or ambiguous")
            candidates = [node for node in graph.nodes.values() if node.kind == NodeKind.DATASET_STAGE
                          and node.payload_ref and node.payload_ref == records[0].get("path")]
            if len(candidates) != 1:
                raise _fail("report dataset target is missing or ambiguous")
            node = candidates[0]
        else:
            node = graph.nodes[target["node_ref"]]
            if node.kind != NodeKind.DATASET_STAGE or not node.payload_ref:
                raise _fail("recommendation target is not a materialized dataset node")
            records = [r for r in records if r.get("path") == node.payload_ref]
            if len(records) != 1:
                raise _fail("recommendation dataset artifact is missing or ambiguous")
    except RequestRefError:
        raise
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise _fail("recommendation dataset ownership cannot be verified") from exc
    record = records[0]
    if not any(item.get("run_id") == run and item.get("artifact_id") == record.get("artifact_id")
               and item.get("sha256") == record.get("sha256")
               for item in check.get("verified_artifacts", [])):
        raise _fail("recommendation dataset is absent from the verified completion evidence")
    return {"run_id": run, "node_ref": node.id, "artifact_id": record["artifact_id"]}


def _preconditions(orchestrator, target, head):
    from .context_tools import InspectNodeContextRequest

    provider = getattr(orchestrator.context_provider, "inspect_node_context", None)
    if not callable(provider):
        raise _fail("recommendation has no node context provider")
    try:
        context = provider(InspectNodeContextRequest(request_id="operation-request-ref",
            owner_run_id=target["run_id"], op_node_id=target["node_ref"], active_head_run_id=head))
        result = {key: context[key] for key in
            ("context_version", "context_fingerprint", "active_head_run_id", "owner_resolution")}
        if any(type(value) is not str or not value for value in result.values()):
            raise ValueError("incomplete node context")
        return result
    except (KeyError, TypeError, ValueError, OSError, ToolVisibleError) as exc:
        raise _fail("recommendation node context cannot be verified") from exc


def offer_completion_requests(orchestrator, *, session_id, result, metadata):
    """Only the two server recommendation producers may create complete request sources."""
    options = result.get("sensitivity_options") or []
    report = result.get("compose_report")
    if not options and not report:
        return result
    plan = orchestrator._bound_plan(session_id)
    unavailable, requests = [], []
    try:
        binding = _binding(orchestrator, session_id, plan, result)
    except RequestRefError as exc:
        return {**result, "operation_request_refs_unavailable": [str(exc)]}
    recommendations = [("sensitivity", str(option.get("label") or "Declared sensitivity")[:200], option.get("workflow"))
                       for option in options if isinstance(option, dict)]
    if report:
        recommendations.append(("report", "Compose a report covering the verified selected results", report))
    for kind, label, recommendation in recommendations:
        try:
            if not isinstance(recommendation, dict):
                raise _fail("server recommendation is incomplete")
            if kind == "sensitivity":
                target = _dataset_target(orchestrator, result, target=recommendation.get("target"))
                steps = recommendation["steps"]
                evidence = [f"{target['run_id']}/{target['artifact_id']}"]
            else:
                target = _dataset_target(orchestrator, result, source=plan.completion["source"])
                if recommendation.get("operation_id") != "report.compose":
                    raise _fail("server report recommendation is not report.compose")
                steps = [{"step_id": "report", **recommendation}]
                evidence = [f"{item['run_id']}/{item['artifact_id']}"
                            for item in recommendation.get("spec", {}).get("result_refs", [])]
                if not evidence:
                    raise _fail("server report recommendation has no result sources")
            arguments = {"operation_id": "operation.multi_step", "operation_version": "v1", "target": target,
                "preconditions": _preconditions(orchestrator, target, binding["active_head_run_id"]),
                "changes": {"steps": steps}, "evidence_refs": evidence, "expected_effect": [label],
                "risks": ["The operation does not certify scientific validity; retain the declared source and limitations."]}
            validate_request(arguments, orchestrator.operation_registry)
            requests.append({"kind": kind, "label": label, "arguments": arguments})
        except (KeyError, TypeError) as exc:
            unavailable.append(str(_fail(f"{kind} recommendation is incomplete")))
        except RequestRefError as exc:
            unavailable.append(str(exc))
    offered = []
    if requests:
        try:
            offered = persist(orchestrator.repository, session_id=session_id, metadata=metadata,
                binding=binding, requests=requests, operation_registry=orchestrator.operation_registry)
            offered = [{**item, "source": requests[i]["arguments"]["target"]} for i, item in enumerate(offered)]
        except RequestRefError as exc:
            unavailable.append(str(exc))
    # Short references precede large catalogs so the ordinary 12k projection
    # preserves their complete spelling and readable operation/source summary.
    return {**({"operation_requests": offered} if offered else {}), **result,
        **({"operation_request_refs_unavailable": unavailable[:MAX_REQUESTS]} if unavailable else {})}


def resolve_completion_request(orchestrator, *, session_id, request_ref):
    from .operations import normalize_operation_target

    saved = read(orchestrator.repository, session_id=session_id, request_ref=request_ref)
    try:
        current = orchestrator._completion_check(session_id, suggest=True)
        binding = _binding(orchestrator, session_id, orchestrator._bound_plan(session_id), current)
        if binding != saved["binding"]:
            raise _fail("source, head, plan or operation contract changed")
        arguments = saved["arguments"]
        if _preconditions(orchestrator, arguments["target"], binding["active_head_run_id"]) != arguments["preconditions"]:
            raise _fail("the request's node context changed")
        validate_request(arguments, orchestrator.operation_registry)
        return normalize_operation_target(orchestrator.operation_registry, arguments)
    except RequestRefError:
        raise
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise _fail("the current recommendation binding cannot be verified") from exc
