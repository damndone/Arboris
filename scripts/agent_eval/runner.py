"""Drive one evaluation task through an explicit Agent transport.

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

import asyncio
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
    #: Candidate turns use the same headless entry as the CLI; HTTP is explicit reproduction.
    transport: str = "headless"


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
          mode: str = "legacy", *, transport: str = "headless") -> dict[str, Any]:
    """One person turn, with transport measurements kept distinct from policy."""
    if transport not in {"http", "headless"}:
        raise ValueError(f"unknown Agent evaluation transport: {transport}")
    started = time.monotonic()
    record: dict[str, Any] = {
        "user": text if text is not None else "<workbench continuation>",
        "transport": transport, "requested_mode": mode,
        "execution_mode_request": mode if mode in {"ask", "auto"} else "server_default",
        "execution_policy": execution_policy,
    }
    if transport == "headless":
        from workbench.cli_agent import continue_headless, run_headless
        from workbench.api_errors import WorkbenchAPIError

        events: list[dict[str, Any]] = []
        try:
            kwargs = {"mode": mode if mode in {"ask", "auto"} else None,
                      "execution_policy": execution_policy, "on_event": events.append}
            if text is None:
                body = asyncio.run(continue_headless(root, session_id, **kwargs))
            else:
                body = asyncio.run(run_headless(root, text, session_id=session_id, **kwargs))
            record["headless_result"] = body
            record["transport_metrics"] = {"kind": "in_process"}
        except Exception as exc:
            error: dict[str, Any] = {"type": type(exc).__name__, "message": str(exc)}
            metrics: dict[str, Any] = {"kind": "in_process", "error_type": type(exc).__name__}
            if isinstance(exc, WorkbenchAPIError):
                error.update(code=exc.code, details=exc.details)
                metrics["api_status_code"] = exc.status_code
            body = {"status": "transport_error", "error": error}
            record["transport_error"] = metrics
            record["transport_metrics"] = metrics
        # Events delivered before an exception are evidence too. No alternate
        # transport or current-provider fallback is attempted after a failure.
        record.update(http_status=None, raw_events=events, raw_events_scope="session_from_seq_0")
    else:
        body: dict[str, Any] = {"execution_policy": execution_policy}
        if mode in {"ask", "auto"}:
            body["execution_mode"] = mode
        if text is None:
            response = client.post(f"/agent/sessions/{session_id}/continue", params={"project_root": str(root)}, json=body)
        else:
            response = client.post(f"/agent/sessions/{session_id}/turns", params={"project_root": str(root)},
                                   json={"question": text, **body})
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {"raw": response.text}
        record.update(http_status=response.status_code,
                      transport_metrics={"kind": "http", "http_status": response.status_code})
    assistant = body.get("assistant")
    reply = (assistant or {}).get("content") if isinstance(assistant, dict) else (assistant or "")
    record.update(status=body.get("status"), reply=reply or "",
                  error=body.get("error") or body.get("detail"),
                  elapsed_s=round(time.monotonic() - started, 1))
    return record


def run_conversation(client, root: Path, run_id: str, prompt: str, policy: Policy,
                     *, focus_node: str = "model:ols_1", progress_path: Path | None = None) -> dict[str, Any]:
    if policy.transport not in {"http", "headless"}:
        raise ValueError(f"unknown Agent evaluation transport: {policy.transport}")
    # As the UI does after an import: a chain session on the run, focused on
    # its model node. The UI also sends a client-built node context packet;
    # the harness sends none, for every version alike.
    created = client.post(
        "/agent/sessions",
        params={"project_root": str(root)},
        json={"role": "chain", "chain_id": f"run:{run_id}", "run_id": run_id, "context_packet": {},
              "focus": {"kind": "node", "id": focus_node, "run_id": run_id,
                        "label": "Imported data" if focus_node.startswith('stage:') else "Imported data and first model"}},
    )
    created.raise_for_status()
    session_id = created.json()["session_id"]
    nudge = NUDGE_ZH if policy.language == "zh" else NUDGE_EN
    confirmed_note = CONFIRMED_ZH if policy.language == "zh" else CONFIRMED_EN
    started = time.monotonic()
    turn = lambda text: _turn(client, root, session_id, text, policy.execution_policy, policy.mode, transport=policy.transport)  # noqa: E731
    turns: list[dict[str, Any]] = []
    confirmations: list[dict[str, Any]] = []
    plan_approvals = 0
    continuations = 0
    nudges = 0
    completed = False
    stop_reason = "nudge_budget"
    try:
        turns.append(turn(prompt))
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
    finally:
        result = {
            "session_id": session_id,
            "transport": policy.transport,
            "requested_mode": policy.mode,
            "execution_mode_request": policy.mode if policy.mode in {"ask", "auto"} else "server_default",
            "execution_policy": policy.execution_policy,
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
        if progress_path is not None:
            progress_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result
