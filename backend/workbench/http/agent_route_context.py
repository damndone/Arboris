"""agent route context: extracted HTTP responsibility."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any
from ..agent.chains import ChainHeadConflict, ChainHeadUnavailable, ChainStore, ensure_chain_root
from ..agent.context_tools import NodeOperationContextProvider
from ..agent.context_tools import InspectNodeContextRequest
from ..agent.events import AgentEventStream
from ..agent.session import JsonlSessionRepository
from ..api_errors import WorkbenchAPIError
from ..agent.protocol import MAIN_AGENT_PROTOCOL, ensure_current_global_protocol
from ..lineage.node_index import NODE_INDEX_FILENAME
from .agent_route_runtime import (MAX_CONTEXT_CHARS)

def _project_root(raw: str) -> Path:
    root = Path(raw).expanduser().resolve()
    if not root.is_dir():
        raise WorkbenchAPIError(
            status_code=404,
            code="PROJECT_NOT_FOUND",
            message="Workbench project was not found.",
            details={"project_root": str(root)},
        )
    return root


def _stores(root: Path) -> tuple[JsonlSessionRepository, AgentEventStream]:
    # Design §10.1: all Agent-managed metadata (sessions, events, and later
    # chains/forks/operation-records) lives under the project-local
    # `workbench/` namespace, kept out of the runs/graph scanners' inputs.
    storage_root = root / "workbench"
    return JsonlSessionRepository(storage_root), AgentEventStream(storage_root)


def _context_active_head(packet: dict[str, Any]) -> str | None:
    direct = packet.get("active_head_run_id")
    if isinstance(direct, str) and direct:
        return direct
    ownership = packet.get("ownership")
    if isinstance(ownership, dict):
        nested = ownership.get("active_head_run_id")
        if isinstance(nested, str) and nested:
            return nested
    return None


def _canonicalize_chain_context_packet(
    root: Path,
    *,
    chain_id: str,
    packet: dict[str, Any],
    active_head_run_id: str,
) -> dict[str, Any]:
    """Bind a selected-node preview to the durable Chain context.

    The browser packet is a bounded preview used to open the Agent surface. It
    is not an authorization source: the Chain head, node hash, owner
    resolution, and context fingerprint must come from the same backend
    snapshot that the typed inspection tools use. A historical selected node
    remains a valid source hint when it is not the current Chain head.
    """

    target = packet.get("operation_target")
    ownership = packet.get("ownership")
    if target is None and ownership is None:
        inferred = _infer_minimal_chain_target(root, packet, active_head_run_id)
        if inferred is None:
            return packet
        target = {}
        ownership = {}
        owner_run_id, op_node_id = inferred
    elif not isinstance(target, dict) or not isinstance(ownership, dict):
        raise WorkbenchAPIError(
            status_code=422,
            code="AGENT_CONTEXT_INVALID",
            message="A selected Chain node context must include operation target and ownership.",
            details={"chain_id": chain_id},
        )
    else:
        owner_run_id = target.get("owner_run_id") or ownership.get("owner_run_id")
        op_node_id = target.get("op_node_id")
    if not isinstance(owner_run_id, str) or not owner_run_id:
        raise WorkbenchAPIError(
            status_code=422,
            code="AGENT_CONTEXT_INVALID",
            message="The selected Chain context has no source owner run.",
            details={"chain_id": chain_id},
        )
    if not isinstance(op_node_id, str) or not op_node_id:
        raise WorkbenchAPIError(
            status_code=422,
            code="AGENT_CONTEXT_INVALID",
            message="The selected Chain context has no source operation node.",
            details={"chain_id": chain_id, "owner_run_id": owner_run_id},
        )

    try:
        snapshot = NodeOperationContextProvider(root).inspect_node_context(
            InspectNodeContextRequest(
                request_id="agent-session-context",
                owner_run_id=owner_run_id,
                op_node_id=op_node_id,
                active_head_run_id=active_head_run_id,
            )
        )
    except (KeyError, OSError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_CONTEXT_STALE",
            message="The selected Chain node context could not be rebuilt from project facts.",
            details={"chain_id": chain_id, "reason": str(exc)},
        ) from exc

    canonical = dict(packet)
    canonical_target = dict(target)
    canonical_target.update(
        {
            "owner_run_id": snapshot["owner_run_id"],
            "op_node_id": snapshot["op_node_id"],
            "node_hash": snapshot["node_hash"],
        }
    )
    canonical["operation_target"] = canonical_target
    canonical_ownership = dict(ownership)
    canonical_ownership.update(
        {
            "active_head_run_id": snapshot["active_head_run_id"],
            "owner_run_id": snapshot["owner_run_id"],
            "owner_resolution": snapshot["owner_resolution"],
        }
    )
    canonical["ownership"] = canonical_ownership
    selection = packet.get("selection")
    if isinstance(selection, dict):
        canonical_selection = dict(selection)
        canonical_selection["node_hash"] = snapshot["node_hash"]
        canonical["selection"] = canonical_selection
    diagnostics = packet.get("context_diagnostics")
    canonical_diagnostics = dict(diagnostics) if isinstance(diagnostics, dict) else {}
    raw_warnings = canonical_diagnostics.get("warnings")
    warnings = [item for item in raw_warnings if isinstance(item, str)] if isinstance(raw_warnings, list) else []
    client_head = ownership.get("active_head_run_id")
    if client_head != snapshot["active_head_run_id"]:
        warnings.append(
            "The client preview active head was replaced by the durable Chain active head; "
            "the selected source owner was retained."
        )
    canonical_diagnostics["warnings"] = warnings
    canonical["context_diagnostics"] = canonical_diagnostics
    canonical["context_fingerprint"] = snapshot["context_fingerprint"]
    if "covariance_executed" in snapshot:
        summary = canonical.get("node_summary")
        summary = dict(summary) if isinstance(summary, dict) else {}
        params = summary.get("params")
        if isinstance(params, dict):
            params = dict(params)
            # Requested wire defaults are not evidence of executed inference.
            params.pop("covariance", None)
            summary["params"] = params
        summary["covariance_executed"] = snapshot["covariance_executed"]
        canonical["node_summary"] = summary
    return canonical


def _infer_minimal_chain_target(
    root: Path,
    packet: dict[str, Any],
    active_head_run_id: str,
) -> tuple[str, str] | None:
    """Recover a node target from the stable forest-key encoding when needed.

    Older Workbench surfaces can send only ``selection.forest_node_key``. The
    key is a presentation hint until its hash and node ref are matched against
    the server-owned node indexes. An active-head match wins; otherwise a
    single verified owner is required. Ambiguous or unverifiable selections
    remain blocked rather than becoming guessed Chain context.
    """

    selection = packet.get("selection")
    if not isinstance(selection, dict):
        return None
    forest_node_key = selection.get("forest_node_key")
    if not isinstance(forest_node_key, str) or "::" not in forest_node_key:
        return None
    node_hash, op_node_id = forest_node_key.split("::", 1)
    if not node_hash or not op_node_id:
        raise WorkbenchAPIError(
            status_code=422,
            code="AGENT_CONTEXT_INVALID",
            message="The selected Chain forest key is not a complete node identity.",
            details={"forest_node_key": forest_node_key},
        )
    declared_node_hash = selection.get("node_hash")
    if declared_node_hash is not None and declared_node_hash != node_hash:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_CONTEXT_STALE",
            message="The selected Chain node hash disagrees with its forest key.",
            details={"forest_node_key": forest_node_key},
        )

    runs_root = root / "runs"
    candidates: list[str] = []
    try:
        run_roots = sorted(path for path in runs_root.iterdir() if path.is_dir())
    except OSError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_CONTEXT_STALE",
            message="The project run index could not be read for Chain context.",
            details={"reason": str(exc)},
        ) from exc
    for run_root in run_roots:
        index_path = run_root / NODE_INDEX_FILENAME
        if not index_path.is_file():
            continue
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise WorkbenchAPIError(
                status_code=409,
                code="AGENT_CONTEXT_STALE",
                message="A project node index is unreadable; Chain context is not safe to infer.",
                details={"run_id": run_root.name, "reason": str(exc)},
            ) from exc
        entry = index.get(op_node_id) if isinstance(index, dict) else None
        if isinstance(entry, dict) and entry.get("node_hash") == node_hash:
            candidates.append(run_root.name)

    if active_head_run_id in candidates:
        return active_head_run_id, op_node_id
    if len(candidates) == 1:
        return candidates[0], op_node_id
    if not candidates:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_CONTEXT_STALE",
            message="The selected Chain node is not present in a verified project node index.",
            details={"forest_node_key": forest_node_key},
        )
    raise WorkbenchAPIError(
        status_code=409,
        code="AGENT_CONTEXT_AMBIGUOUS",
        message="The selected Chain node has multiple verified owners outside the active head.",
        details={"forest_node_key": forest_node_key, "candidate_run_ids": candidates},
    )


def _ensure_chain_scope(
    root: Path,
    *,
    chain_id: str,
    active_head_run_id: str,
    agent_session_id: str,
) -> dict[str, Any]:
    try:
        return ensure_chain_root(
            root / "workbench",
            runs_root=root / "runs",
            chain_id=chain_id,
            active_head_run_id=active_head_run_id,
            agent_session_id=agent_session_id,
        )
    except ChainHeadConflict as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_CHAIN_SCOPE_CONFLICT",
            message="The Chain session is outside the durable active-head scope.",
            details={"chain_id": chain_id, "reason": str(exc)},
        ) from exc


def _authoritative_active_head(
    root: Path,
    *,
    chain_id: str,
    requested_active_head_run_id: str | None,
) -> str:
    try:
        return ChainStore(root / "workbench", create=False).resolve_active_head(
            chain_id,
            requested_active_head_run_id=requested_active_head_run_id,
        )
    except KeyError as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_CHAIN_NOT_MANAGED",
            message="The Chain has no durable active-head record.",
            details={"chain_id": chain_id},
        ) from exc
    except (ChainHeadConflict, ChainHeadUnavailable) as exc:
        raise WorkbenchAPIError(
            status_code=409,
            code="AGENT_PROPOSAL_STALE",
            message="The durable Chain active head changed before this operation.",
            details={"chain_id": chain_id, "reason": str(exc)},
        ) from exc


def _refresh_main_context(
    repository: JsonlSessionRepository, session_id: str, packet: dict[str, Any]
) -> None:
    """Append the current project overview when it differs from the last one.

    Earlier overviews stay in the session log (the record of what the Agent was
    told when); the newest one is last, and says it supersedes the others.
    """

    serialized, fingerprint = _context_serialized(packet)
    # Compare what the Agent was told, not the packet's declared fingerprint:
    # the panel derives that from family heads only, so a new run inside an
    # existing family left it unchanged while run_count and the active head moved.
    latest = None
    for entry in repository.get_branch(session_id):
        payload = entry.payload
        if entry.entry_type == "custom_message" and payload.get("name") == "workbench_context":
            content = str(payload.get("content") or "")
            latest = content.split("\n", 1)[1] if "\n" in content else content
    if latest == serialized:
        return
    repository.append(
        session_id,
        "custom_message",
        {
            "message_type": "agent_context",
            "audience": "model",
            "name": "workbench_context",
            "content": (
                "Workbench read-only context, refreshed: this supersedes every earlier context "
                "message; runs listed here are the project's current ones. Do not invent facts "
                "or execute actions.\n" + serialized
            ),
            "metadata": {"context_fingerprint": fingerprint, "refreshed": True},
        },
    )


def _context_serialized(packet: dict[str, Any]) -> tuple[str, str]:
    serialized = json.dumps(
        packet,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(serialized) > MAX_CONTEXT_CHARS:
        raise WorkbenchAPIError(
            status_code=422,
            code="AGENT_CONTEXT_TOO_LARGE",
            message="Agent context exceeds the bounded context budget.",
            details={"max_chars": MAX_CONTEXT_CHARS, "actual_chars": len(serialized)},
        )
    fingerprint = str(packet.get("context_fingerprint") or "")
    if not fingerprint:
        fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return serialized, fingerprint


def _ensure_current_global_protocol(
    repository: JsonlSessionRepository,
    session_id: str,
) -> None:
    # Pass the route's current value explicitly for existing injection callers.
    ensure_current_global_protocol(repository, session_id, protocol=MAIN_AGENT_PROTOCOL)


def _ensure_main_session(repository: JsonlSessionRepository, root: Path) -> str:
    """Durable per-project Main session anchor for the HTTP orchestrator.

    The read-only inspection slice never dispatches Main→Chain commands, but
    the orchestrator identity must be a real session so future command entries
    have a home instead of a made-up id.
    """
    main_session_id = "agent_main"
    try:
        repository.get_metadata(main_session_id)
    except (KeyError, ValueError):
        repository.create_session(
            main_session_id, chain_id=f"project:{root}", role="main"
        )
    return main_session_id


def _get_session(
    root: Path,
    session_id: str,
) -> tuple[JsonlSessionRepository, AgentEventStream, dict[str, Any]]:
    # Look the session up without creating storage, so a read of an unknown
    # session leaves the project untouched.
    try:
        metadata = JsonlSessionRepository(root / "workbench", create=False).get_metadata(session_id)
    except (KeyError, ValueError) as exc:
        raise WorkbenchAPIError(
            status_code=404,
            code="AGENT_SESSION_NOT_FOUND",
            message="Agent session was not found in this project.",
            details={"session_id": session_id},
        ) from exc
    repository, events = _stores(root)
    return repository, events, metadata

