"""Drive one evaluation task through the real Agent HTTP path.

The simulated user is deterministic and never uses a model:

* it sends the task's opening request;
* whenever proposals are pending, it confirms every one of them and waits for
  the operations to finish (each confirmation is one user action);
* otherwise, if the Agent has not said the analysis is complete, it sends a
  fixed nudge (one user action), up to ``max_nudges``;
* it stops when the Agent writes the completion marker, when the nudge budget
  is spent, or at the task's wall-clock limit.

So "user actions" measures how much a person must do to get a complete
analysis, which is what v1.9.1 sets out to reduce.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

COMPLETION_MARKERS = ("分析完成", "ANALYSIS COMPLETE")
NUDGE_ZH = "请继续，把这项分析做完。全部完成后，请回复「分析完成」并给出最终总结。"
NUDGE_EN = 'Please continue and finish the analysis. When everything is done, reply "ANALYSIS COMPLETE" with a final summary.'
CONFIRMED_ZH = "我已经确认了上面的提案。"
CONFIRMED_EN = "I have confirmed the proposals above."
TERMINAL_OPERATION = {"completed", "failed", "stale", "cancelled", "blocked", "interrupted", "partial"}


@dataclass
class Policy:
    max_nudges: int = 8
    max_wall_s: float = 1800.0
    language: str = "zh"
    #: The UI's default in v1.9.0 ("Review before running"): read-only
    #: workflows also wait for a confirmation.
    execution_policy: str = "proposal_only"
    #: v1.9.1: "legacy" (v1.9.0 flow: confirm, then the person says continue),
    #: "ask" (confirm, then the Workbench resumes the Agent) or "auto"
    #: (approve the plan once, then the Workbench resumes the Agent).
    mode: str = "legacy"


def _session_entries(root: Path, session_id: str) -> list[dict[str, Any]]:
    path = root / "workbench" / "agent-sessions" / f"{session_id}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _pending_proposals(client, root: Path, session_id: str) -> list[dict[str, Any]]:
    response = client.get(f"/agent/sessions/{session_id}/proposals", params={"project_root": str(root)})
    if response.status_code != 200:
        return []
    return [item for item in response.json().get("proposals", []) if item.get("status") == "pending"]


def _active_head(client, root: Path, session_id: str, fallback: str) -> str:
    response = client.get(f"/agent/sessions/{session_id}", params={"project_root": str(root)})
    if response.status_code == 200:
        body = response.json()
        for key in ("active_head_run_id", "run_id"):
            value = body.get(key) or (body.get("session") or {}).get(key)
            if isinstance(value, str) and value:
                return value
    return fallback


def _confirm(client, root: Path, session_id: str, run_id: str, proposal: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    response = client.post(
        f"/agent/sessions/{session_id}/proposals/{proposal['proposal_id']}/confirm",
        params={"project_root": str(root)},
        json={"revision": proposal["revision"], "fingerprint": proposal["fingerprint"], "active_head_run_id": run_id},
    )
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if response.status_code != 200:
        return {"proposal_id": proposal["proposal_id"], "status": f"http_{response.status_code}", "error": body}
    operation = body.get("operation") or {}
    record_id = operation.get("record_id")
    deadline = time.monotonic() + 600
    while operation.get("status") not in TERMINAL_OPERATION and record_id and time.monotonic() < deadline:
        time.sleep(1)
        reconciled = client.post(f"/agent/sessions/{session_id}/operations/{record_id}/reconcile",
                                 params={"project_root": str(root)})
        if reconciled.status_code == 200:
            operation = reconciled.json().get("operation") or operation
            continue
        polled = client.get(f"/agent/sessions/{session_id}/operations/{record_id}", params={"project_root": str(root)})
        if polled.status_code == 200:
            operation = polled.json().get("operation") or operation
    return {
        "proposal_id": proposal["proposal_id"],
        "operation_id": proposal.get("operation_id"),
        "status": operation.get("status") or "unknown",
        "error": operation.get("error") or operation.get("failure"),
        "result_run_ids": operation.get("result_run_ids") or operation.get("run_ids"),
        "elapsed_s": round(time.monotonic() - started, 1),
    }


def _approve_plan_if_waiting(client, root: Path, session_id: str) -> bool:
    response = client.get(f"/agent/sessions/{session_id}/plan", params={"project_root": str(root)})
    plan = (response.json() or {}).get("plan") if response.status_code == 200 else None
    if not plan or plan.get("status") not in {"draft", "needs_approval"}:
        return False
    approved = client.post(f"/agent/sessions/{session_id}/plan/approve", params={"project_root": str(root)},
                           json={"version": plan["version"]})
    return approved.status_code == 200


def _turn(client, root: Path, session_id: str, text: str | None, execution_policy: str,
          mode: str = "legacy") -> dict[str, Any]:
    """One person turn (text), or a Workbench continuation (text None, v1.9.1)."""
    started = time.monotonic()
    body: dict[str, Any] = {"execution_policy": execution_policy}
    if mode in {"ask", "auto"}:
        body["execution_mode"] = mode
    if text is None:
        response = client.post(f"/agent/sessions/{session_id}/continue", params={"project_root": str(root)}, json=body)
    else:
        response = client.post(f"/agent/sessions/{session_id}/turns", params={"project_root": str(root)},
                               json={"question": text, **body})
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {"raw": response.text}
    assistant = body.get("assistant")
    reply = (assistant or {}).get("content") if isinstance(assistant, dict) else (assistant or "")
    return {"user": text if text is not None else "<workbench continuation>", "http_status": response.status_code,
            "status": body.get("status"),
            "reply": reply or "", "error": body.get("error") or body.get("detail"),
            "elapsed_s": round(time.monotonic() - started, 1)}


def run_conversation(client, root: Path, run_id: str, prompt: str, policy: Policy,
                     *, focus_node: str = "model:ols_1") -> dict[str, Any]:
    # As the UI does after an import: a chain session on the run, focused on
    # its model node. The UI also sends a client-built node context packet;
    # the harness sends none, for every version alike.
    created = client.post(
        "/agent/sessions",
        params={"project_root": str(root)},
        json={"role": "chain", "chain_id": f"run:{run_id}", "run_id": run_id, "context_packet": {},
              "focus": {"kind": "node", "id": focus_node, "run_id": run_id, "label": "Imported data and first model"}},
    )
    created.raise_for_status()
    session_id = created.json()["session_id"]
    nudge = NUDGE_ZH if policy.language == "zh" else NUDGE_EN
    confirmed_note = CONFIRMED_ZH if policy.language == "zh" else CONFIRMED_EN
    started = time.monotonic()
    turn = lambda text: _turn(client, root, session_id, text, policy.execution_policy, policy.mode)  # noqa: E731
    turns: list[dict[str, Any]] = [turn(prompt)]
    confirmations: list[dict[str, Any]] = []
    plan_approvals = 0
    continuations = 0
    nudges = 0
    completed = False
    stop_reason = "nudge_budget"
    while time.monotonic() - started < policy.max_wall_s:
        if any(marker in turns[-1]["reply"] for marker in COMPLETION_MARKERS):
            completed, stop_reason = True, "completion_marker"
            break
        if policy.mode == "auto" and _approve_plan_if_waiting(client, root, session_id):
            plan_approvals += 1
            continuations += 1
            turns.append(turn(None))
            continue
        pending = _pending_proposals(client, root, session_id)
        if pending:
            head = _active_head(client, root, session_id, run_id)
            for proposal in pending:
                confirmations.append(_confirm(client, root, session_id, head, proposal))
            if policy.mode in {"ask", "auto"}:
                # v1.9.1: the Workbench resumes the Agent; the person says nothing.
                continuations += 1
                if continuations > 4 * policy.max_nudges:
                    break
                turns.append(turn(None))
                continue
            # After confirming, v1.9.0 needs the person to speak again; the
            # nudge that follows is counted separately.
            if nudges >= policy.max_nudges:
                break
            nudges += 1
            turns.append(turn(f"{confirmed_note}{nudge}"))
            continue
        if nudges >= policy.max_nudges:
            break
        nudges += 1
        turns.append(turn(nudge))
    else:
        stop_reason = "wall_clock"
    return {
        "session_id": session_id,
        "turns": turns,
        "confirmations": confirmations,
        "plan_approvals": plan_approvals,
        "continuations": continuations,
        "nudges": nudges,
        "user_actions": len(confirmations) + nudges + plan_approvals,
        "completed_marker": completed,
        "stop_reason": stop_reason,
        "wall_s": round(time.monotonic() - started, 1),
        "entries": _session_entries(root, session_id),
    }
