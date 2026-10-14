"""What a confirmed operation produced, told to the Agent and to its tools.

Confirming a proposal executes it in the Workbench; the Agent only proposes.
Before this, nothing told the Agent what the execution produced, so after a
confirmed rerun it searched the old node, found the old result, and told the
person it could not execute (user review 6). This module names the run the
operation produced and whether that same analysis already existed: the
lineage identifies a node by its inputs, so a rerun identical to an earlier
one joins that node instead of adding a new one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

OUTCOME_NAME = "workbench_operation_result"


def produced_run(record: Mapping[str, Any]) -> str | None:
    outputs = record.get("outputs") or {}
    execution = record.get("execution") or {}
    bindings = execution.get("bindings") or {}
    for value in (outputs.get("target_run_id"), outputs.get("child_run_id"), bindings.get("child_run_id"), execution.get("child_run_id")):
        if isinstance(value, str) and value:
            return value
    return None


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def model_nodes(project_root: Path, run_id: str) -> dict[str, dict[str, Any]]:
    """The run's model nodes: content hash and the covariance it ran with."""

    run = Path(project_root) / "runs" / run_id
    index = _json(run / "node_index.json") or {}
    nodes: dict[str, dict[str, Any]] = {}
    for node_id, entry in index.items() if isinstance(index, dict) else []:
        if not str(node_id).startswith("model:") or not isinstance(entry, dict):
            continue
        result = _json(run / "model_results" / f"{str(node_id).split(':', 1)[1]}.json") or {}
        nodes[str(node_id)] = {
            "node_hash": entry.get("node_hash"),
            "covariance": result.get("covariance"),
            "covariance_estimator": result.get("covariance_estimator"),
        }
    return nodes


def identical_runs(project_root: Path, run_id: str) -> dict[str, list[str]]:
    """Other runs holding a node with the same content hash, per model node."""

    mine = {node: info["node_hash"] for node, info in model_nodes(project_root, run_id).items() if info.get("node_hash")}
    found: dict[str, list[str]] = {node: [] for node in mine}
    runs_root = Path(project_root) / "runs"
    for other in sorted(runs_root.iterdir()) if runs_root.is_dir() else []:
        if other.name == run_id or other.name.startswith("_") or not other.is_dir():
            continue
        index = _json(other / "node_index.json") or {}
        for node, node_hash in mine.items():
            entry = index.get(node) if isinstance(index, dict) else None
            if isinstance(entry, dict) and entry.get("node_hash") == node_hash:
                found[node].append(other.name)
    return {node: runs for node, runs in found.items() if runs}


def outcome(project_root: Path, record: Mapping[str, Any]) -> dict[str, Any]:
    run_id = produced_run(record)
    facts: dict[str, Any] = {
        "operation_record_id": record.get("record_id"),
        "operation_id": record.get("operation_id"),
        "proposal_id": record.get("proposal_id"),
        "status": record.get("status"),
        "produced_run_id": run_id,
    }
    if record.get("error"):
        facts["error"] = record.get("error")
    if run_id:
        facts["model_nodes"] = model_nodes(project_root, run_id)
        facts["identical_runs"] = identical_runs(project_root, run_id)
    return facts


def outcome_text(facts: Mapping[str, Any]) -> str:
    """The message the Agent reads on its next turn."""

    head = (
        f"The person confirmed proposal {facts.get('proposal_id')} ({facts.get('operation_id')}), "
        f"and the Workbench executed it: status {facts.get('status')}."
    )
    lines = [head]
    if facts.get("error"):
        lines.append(f"It failed: {json.dumps(facts['error'], ensure_ascii=False)[:600]}. Nothing it would have produced exists.")
    run_id = facts.get("produced_run_id")
    if run_id:
        lines.append(f"It produced run {run_id}, a new version in the lineage; the run the conversation started from is unchanged.")
        for node, info in (facts.get("model_nodes") or {}).items():
            covariance = info.get("covariance")
            estimator = info.get("covariance_estimator")
            if covariance:
                lines.append(f"- {node} in run {run_id} ran with covariance {covariance}" + (f" ({estimator})." if estimator else "."))
        for node, runs in (facts.get("identical_runs") or {}).items():
            lines.append(
                f"- The same {node} already existed in run(s) {', '.join(runs)} (identical inputs, so identical results); "
                "the lineage shows them as one node. Say so: the result is not new."
            )
        lines.append(
            f"Read the new results with inspect_project_model_coefficients using run_ids [{run_id}] "
            "(add the original run to compare), and report them. Do not say you could not execute it: confirming executed it."
        )
    return "\n".join(lines)
