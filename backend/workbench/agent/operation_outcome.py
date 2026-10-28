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
# Statuses after which an operation changes no more. Confirming returns while
# a rerun still runs; the outcome is told again once it reaches one of these.
TERMINAL = frozenset({"completed", "failed", "cancelled", "rejected", "stale", "aborted"})


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


def outcome_extras(project_root: Path, session_id: str, record: Any) -> dict[str, Any]:
    """What an Ask-mode confirmation tells the Agent beyond the receipt, as Auto mode's
    tool result already does: the results, the plan step it completed, and the delivery
    check. In the free-route DeepSeek rounds the Agent otherwise spent about three
    artifact reads, two plan updates and two completion checks per task asking.
    """

    from . import plans as plan_module
    from .context_tools import NodeOperationContextProvider
    from .delivery import delivery_check, delivery_digest

    extras: dict[str, Any] = {}
    if record.status == "completed":
        try:
            results = NodeOperationContextProvider(project_root).executed_workflow_results(record)
        except Exception:  # the receipt still goes out; the results stay readable by id
            results = []
        if results:
            extras["results"] = results
    operation_ids = ([str(step.get("operation_id", "")) for step in (record.changes or {}).get("steps") or ()
                      if isinstance(step, dict)] if record.operation_id == "operation.multi_step"
                     else [str(record.operation_id)])
    store = plan_module.PlanStore(Path(project_root) / "workbench")
    try:
        before = store.current(session_id)
        if before is not None:
            after = store.update(session_id, lambda current: plan_module.mark_covered(current, operation_ids, record.status))
            changed = [step.step_id for old, step in zip(before.steps, after.steps) if old.status != step.status]
            if changed:
                extras["plan_steps_marked"] = {"steps": changed, "status": "done" if record.status == "completed" else "failed"}
        digest = delivery_digest(delivery_check(project_root, store.current(session_id)))
        if digest:
            extras["delivery"] = digest
    except (plan_module.PlanError, OSError, ValueError, KeyError):
        pass
    return extras


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
    if facts.get("status") not in TERMINAL:
        lines.append(
            (f"It is producing run {run_id}. " if run_id else "")
            + "It has not finished yet: do not report results; you will be told when it finishes."
        )
        return "\n".join(lines)
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
        if not facts.get("results"):
            lines.append(
                f"Read the new results with inspect_project_model_coefficients using run_ids [{run_id}] "
                "(add the original run to compare), and report them. Do not say you could not execute it: confirming executed it."
            )
    if facts.get("results"):
        model_runs = list(dict.fromkeys(
            branch["run_id"] for result in facts["results"] if isinstance(result, Mapping)
            for branch in result.get("model_branches", []) if isinstance(branch, Mapping) and branch.get("run_id")
        ))
        if model_runs:
            lines.append("The workflow produced model branches: read estimates with inspect_project_model_coefficients "
                         "using run_ids " + json.dumps(model_runs[:16], ensure_ascii=False) + "."
                         + (f" ({len(model_runs) - 16} further runs omitted; inspect completed operations.)" if len(model_runs) > 16 else ""))
        lines.append("For inspect_operation_artifact, use the returned read_with scope and exact artifact_id. "
                     "Do not remove run prefixes or replace the operation's owner_run_id with a model branch run. "
                     "Entries for unavailable artifacts are not numerical evidence; use their stated reader where supplied.")
        lines.append("Results (the same public view inspect_operation_artifact serves; answer from these, no need to "
                     "read them again): " + json.dumps(facts["results"], ensure_ascii=False)[:6000])
    if facts.get("plan_steps_marked"):
        marked = facts["plan_steps_marked"]
        lines.append(f"Plan step(s) {', '.join(marked['steps'])} marked {marked['status']} by the Workbench.")
    from .delivery import delivery_lines
    lines.extend(delivery_lines(facts.get("delivery")))
    return "\n".join(lines)


def unfinished_outcomes(branch: Any) -> list[str]:
    """Operation records whose latest outcome message was not terminal."""

    latest: dict[str, str] = {}
    for entry in branch:
        payload = entry.payload
        if entry.entry_type == "custom_message" and payload.get("name") == OUTCOME_NAME:
            metadata = payload.get("metadata") or {}
            record_id = metadata.get("operation_record_id")
            if isinstance(record_id, str):
                latest[record_id] = str(metadata.get("status"))
    return [record_id for record_id, status in latest.items() if status not in TERMINAL]


#: Room for one executed operation's result in the conversation. The full
#: record stays in the session entry (``operation_result``) and the operation
#: store; only the model-visible text is bounded. Unbounded, one Kaplan-Meier
#: workflow (every curve point and censoring flag) put ~450k characters into
#: every later request of a v1.9.1 smoke run.
RESULT_VIEW_CHARS = 12_000
#: Lists longer than this show their first and last items and their length.
LONG_LIST = 12
_LIST_HEAD, _LIST_TAIL = 6, 2


def _shorten_lists(value: Any) -> Any:
    """Every key and scalar kept; only long lists shortened, saying how long they were."""

    if isinstance(value, Mapping):
        return {key: _shorten_lists(item) for key, item in value.items()}
    if isinstance(value, list):
        items = [_shorten_lists(item) for item in value]
        if len(items) <= LONG_LIST:
            return items
        return {"_shortened_list": {"length": len(items), "first": items[:_LIST_HEAD], "last": items[-_LIST_TAIL:]}}
    return value


def result_view(payload: Mapping[str, Any], *, budget: int = RESULT_VIEW_CHARS,
                read_with: Mapping[str, Any] | None = None) -> str:
    """The model-visible text of an executed operation's result.

    Estimates, standard errors, tests and fit statistics are scalars or short
    tables and survive whole, so the numbers the Agent cites stay in the
    evidence the numeric check reads. Long series (curve points, residuals,
    per-row flags) are shortened; if the result is still too large, a prefix
    is kept and the cut sections are named.
    """

    from .tools import _project_value

    view = _shorten_lists(payload)
    text = json.dumps(view, ensure_ascii=False, sort_keys=True)
    if len(text) <= budget and view == payload:
        return text
    where = (" with " + ", ".join(f"{key} {value}" for key, value in read_with.items() if value)
             + " and the artifact_id") if read_with else " (operation_record_id and artifact_id below)"
    note = ("Workbench: this result was shortened for the conversation (long lists show their first and last "
            "items and their length). The full result is on record: read an artifact with "
            f"inspect_operation_artifact{where}.\n")
    if len(text) > budget - len(note):
        text = json.dumps(_project_value(view, budget - len(note)), ensure_ascii=False, sort_keys=True)
    return note + text
