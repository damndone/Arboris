"""Extension effects after ordinary operation approval; outputs never grant authority."""
from __future__ import annotations

import hashlib
import json
import os
from uuid import uuid4
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator

from ..egress import egress_project, guard_outgoing_messages, load_policy
from .extensions import ExtensionStore, ExtensionError, _area

MAX_ARGUMENT_BYTES = 16_000
MAX_RESPONSE_BYTES = 32_000


def fetch_json(tool, arguments):
    """One fixed HTTPS GET. No ambient proxies, redirects, credentials or commands."""
    try:
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=2.0) as client:
            with client.stream("GET", tool["endpoint"], params={"arguments": json.dumps(arguments, ensure_ascii=False)}) as response:
                if response.status_code != 200 or "application/json" not in response.headers.get("content-type", ""):
                    raise ExtensionError("EXTENSION_RESPONSE: expected successful JSON without redirects")
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise ExtensionError("EXTENSION_LIMIT: response too large")
                return json.loads(raw)
    except (httpx.HTTPError, ValueError) as exc:
        if isinstance(exc, ExtensionError):
            raise
        raise ExtensionError("EXTENSION_TRANSPORT: external query failed") from exc


def query_external(root, spec):
    store = ExtensionStore(root)
    tool = store.require_tool(spec["extension_id"], spec["catalog_sha256"])
    arguments = spec["arguments"]
    if len(json.dumps(arguments, ensure_ascii=False, allow_nan=False).encode()) > MAX_ARGUMENT_BYTES:
        raise ExtensionError("EXTENSION_LIMIT: arguments too large")
    if not Draft202012Validator(tool["input_schema"]).is_valid(arguments):
        raise ExtensionError("EXTENSION_ARGUMENTS: arguments do not match the admitted schema")
    provider = "external:" + tool["id"]
    # Endpoint locality never silently opts an extension into sharing.
    if "extension" not in load_policy(Path(root)).providers.get(provider, frozenset()):
        raise ExtensionError("EXTENSION_EGRESS: approve this endpoint's sharing class before sending")
    outgoing = [{"role": "assistant", "tool_calls": [{"id": "external", "type": "function", "function": {"name": "inspect_extensions", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "external", "content": json.dumps(arguments, ensure_ascii=False)}]
    with egress_project(root):
        guarded = guard_outgoing_messages(outgoing, base_url=tool["endpoint"], provider_id=provider)
    if json.loads(guarded[-1]["content"]) != arguments:
        raise ExtensionError("EXTENSION_EGRESS: sharing policy withheld or redacted the request; revise it")
    data = fetch_json(tool, arguments)
    if len(json.dumps(data, ensure_ascii=False, allow_nan=False).encode()) > MAX_RESPONSE_BYTES or not Draft202012Validator(tool["output_schema"]).is_valid(data):
        raise ExtensionError("EXTENSION_RESPONSE: result violates the admitted bounded schema")
    return {"protocol_version": "external-tool/v1", "content_role": "untrusted_data",
            "observations": {"extension_id": tool["id"], "version": tool["version"], "origin": tool["origin"],
                             "catalog_sha256": spec["catalog_sha256"], "data": data}}


def dispatch_hooks(root, event, facts, *, key):
    value = ExtensionStore(root).view()
    matched = []
    for hook in value["manifest"]["hooks"]:
        if hook["id"] in value["disabled"] or hook["event"] != event:
            continue
        if hook["operation_ids"] and not set(hook["operation_ids"]).intersection(facts.get("operation_ids", [])):
            continue
        receipt = {"event": event, "key": key, "hook_id": hook["id"], "version": hook["version"],
                   "catalog_sha256": value["sha256"], "action": hook["action"], "facts": facts}
        encoded = json.dumps(receipt, ensure_ascii=False, allow_nan=False).encode()
        if len(encoded) > 8192:
            raise ExtensionError("EXTENSION_LIMIT: hook event exceeds its bound")
        name = "extension-event-" + hashlib.sha256((key + event + hook["id"] + value["sha256"]).encode()).hexdigest() + ".json"
        with _area(root, create=True) as fd:
            # Publish a complete receipt atomically. A crash during writing
            # must not leave an O_EXCL destination that looks delivered.
            temp = f".extension-event-{uuid4().hex}.tmp"
            out = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            try:
                with os.fdopen(out, "wb") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(temp, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
                except FileExistsError:
                    pass  # Complete receipt already delivered; denial still applies.
                os.fsync(fd)
            finally:
                os.unlink(temp, dir_fd=fd)
        matched.append(receipt)
        if hook["action"] == "deny":
            # Never promote project-authored reasons to server instructions.
            raise ExtensionError("EXTENSION_HOOK_DENIED: " + hook["id"])
    return matched


def external_workflow_step(root, draft, step):
    from ..artifacts import read_json, write_json
    from .workflow import WorkflowStepResult
    from .workflow_runtime_parts.artifacts import _ensure_runtime_artifact
    run_root = Path(root) / "runs" / draft.target["run_id"]
    identity = hashlib.sha256((draft.workflow_id + step.step_id + step.fingerprint).encode()).hexdigest()[:32]
    path = run_root / "derived" / f"external-{identity}.json"
    # A durable GET result is reused on resume, never fetched merely to inspect it.
    # A disabled or changed extension also refuses recovery of its output.
    ExtensionStore(root).require_tool(step.spec["extension_id"], step.spec["catalog_sha256"])
    if path.exists():
        result = read_json(path)
    else:
        result = query_external(root, step.spec)
        write_json(path, result)
    artifact_id = f"external_{identity}"
    _ensure_runtime_artifact(run_root, artifact_id=artifact_id, path=path, artifact_type="external_tool_result",
                             step="external.query", inputs=[])
    return WorkflowStepResult(artifact_ids=[artifact_id], result_fingerprint=step.fingerprint, payload=result)
