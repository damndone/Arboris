"""Core checkpoints and original receipts; never resubmit an unknown effect.

The session log owns content; TurnStore holds compact references and usage.
Local execution ownership is held for the entire command, including tools.
Recovery is explicit per project: this module does not discover project roots
or initiate provider calls from an application import.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import asdict
from uuid import uuid4

from . import tool_receipts
from .session import EntryRef, SessionAppendPendingError, _payload_digest
from .turn_store import TERMINAL, TurnStoreError


class TurnRecoveryRequired(TurnStoreError):
    """Recovery lacks evidence; operator reconciliation is required."""


_STATE_FIELDS = (
    "_numeric_repairs_left", "_steps_used", "_overflow_retried",
    "_last_tool_call_fingerprint", "_consecutive_identical_tool_calls",
    "_answered_tool_calls", "_tools_used", "_last_tool_failure", "_ready_proposal",
)


def invocation_id(session_id, command_id, step, call_id):
    return "invocation_" + hashlib.sha256(json.dumps([
        "workbench.agent.invocation.v1", session_id, command_id, step, call_id,
    ], separators=(",", ":")).encode()).hexdigest()


def _runtime_contract(core):
    return json.loads(json.dumps({"model": core.model_name, "model_config": core.model_config_identity,
        "tools": core.tools, "compaction": core.compaction_policy.to_dict() if core.compaction_policy else None},
        ensure_ascii=False, allow_nan=False))


class TurnJournal:
    def __init__(self, store, repository, *, session_id, execution_mode="ask"):
        self.store, self.repository = store, repository
        self.session_id, self.execution_mode = session_id, execution_mode
        self.record = None
        self.owner = "runtime_" + uuid4().hex
        self.started_at = None

    def ownership(self):
        return self.store.execution_guard(self.session_id)

    def _edit(self, method, **values):
        # External queue/cancel writes are legitimate; always reload their CAS.
        self.record = self.store.get(self.record.turn_id)
        self.record = method(self.record.turn_id, expected_version=self.record.version,
                             owner=self.owner, fence=self.record.lease_epoch, **values)
        return self.record

    def start(self, core, text, *, continuation):
        if core._budget.max_steps is None or core._budget.timeout_s is None:
            raise TurnStoreError("durable commands require finite step and wall budgets")
        command = core._active_command_id
        self.started_at = time.time()
        turn_id = "turn_" + hashlib.sha256(json.dumps([self.session_id, command]).encode()).hexdigest()[:32]
        initial = self._payload(core, "initial", command_id=command, turn_id=turn_id,
                                text=text, continuation=continuation)
        entry = self.repository.append_once(self.session_id, "turn_input", {
            "command_id": command, "text": text, "continuation": continuation, "initial_checkpoint": initial,
        }, key=command, stage="turn_input")
        self.record = self.store.create(self.session_id, entry.entry_id, command_id=command, turn_id=turn_id,
            execution_mode=self.execution_mode,
            budget={"max_steps": core._budget.max_steps, "timeout_s": core._budget.timeout_s})
        self.record = self.store.claim(self.record.turn_id, expected_version=self.record.version,
            owner=self.owner, lease_seconds=core._budget.timeout_s + 60)
        self.save(core, "initial", text=text, continuation=continuation)
        self._edit(self.store.transition, status="running")

    def _payload(self, core, stage, *, command_id, turn_id, **details):
        payload = {"schema_version": "agent.core_checkpoint.v1", "command_id": command_id,
                   "turn_id": turn_id, "stage": stage, "started_at": self.started_at,
                   "budget": asdict(core._budget), "user_text": getattr(core, "_user_text", None),
                   "runtime_contract": _runtime_contract(core),
                   "phase_active": core._core_phase is not None,
                   "state": {name: getattr(core, name) for name in _STATE_FIELDS}, **details}
        # Match the existing message JSON boundary (e.g. domain StrEnum values)
        # before the private WAL's strict JSON-only validation.
        return json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))

    def save(self, core, stage, **details):
        states = [e for e in self.repository.get_branch(self.session_id)
                  if e.entry_type == "turn_state" and e.payload.get("command_id") == self.record.command_id]
        payload = self._payload(core, stage, command_id=self.record.command_id, turn_id=self.record.turn_id, **details)
        entry = self.repository.append_once(self.session_id, "turn_state", payload,
                                            key=self.record.command_id, stage=f"checkpoint:{len(states)}")
        self._edit(self.store.checkpoint, steps_used=core._steps_used,
                   wall_s_used=max(self.record.wall_s_used, time.time() - self.started_at),
                   checkpoint={"state_entry_id": entry.entry_id})
        return entry

    def append_user(self, core, text):
        current = self.store.get(self.record.turn_id)
        override = getattr(core, "_resume_input", None)
        queued = next((q for q in current.queue if (q["message_id"] == override["queue_id"] if override else not q["consumed"])
                       and self.repository.get_entry(EntryRef(self.session_id, q["entry_id"])).payload["text"] == text), None)
        stage = override["user_stage"] if override else "user:" + queued["message_id"] if queued else "initial_user"
        self.save(core, "input", text=text, user_stage=stage, queue_id=queued["message_id"] if queued else None,
                  queue_kind=queued["kind"] if queued else None)
        entry = self.repository.append_once(self.session_id, "message", {
            "role": "user", "content": text, "command_id": current.command_id,
        }, key=current.command_id, stage=stage)
        if queued and not queued["consumed"]:
            self._edit(self.store.consume_queue, message_id=queued["message_id"])
        core._resume_input = None
        return entry

    def enqueue(self, kind, text):
        message_id = "queue_" + uuid4().hex
        entry = self.repository.append_once(self.session_id, "turn_queue", {"text": text, "kind": kind},
                                            key=message_id, stage="queue_input")
        current = self.store.get(self.record.turn_id)
        self.record = self.store.enqueue(current.turn_id, kind, entry.entry_id,
                                        expected_version=current.version, message_id=message_id)

    def cancel(self):
        current = self.store.get(self.record.turn_id)
        self.record = self.store.request_cancel(current.turn_id, expected_version=current.version)

    def assistant(self, core, payload, *, request_id, context_fingerprint):
        self.save(core, "assistant", assistant=payload, request_id=request_id,
                  context_fingerprint=context_fingerprint)
        return self.assistant_message(payload, core._steps_used)

    def assistant_message(self, payload, step):
        return self.repository.append_once(self.session_id, "message", payload,
            key=self.record.command_id, stage=f"assistant:{step}")

    def identity(self, core, call):
        call_id = str(call.get("tool_call_id", ""))
        return dict(session_id=self.session_id, command_id=self.record.command_id,
                    provider_step=core._steps_used, tool_call_id=call_id,
                    invocation_id=invocation_id(self.session_id, self.record.command_id, core._steps_used, call_id),
                    tool_call=call)

    def original_receipt(self, core, call):
        identity = self.identity(core, call)
        entry = tool_receipts.read(self.repository, **identity)
        current = self.store.get(self.record.turn_id)
        if entry is None and identity["invocation_id"] in current.tool_calls:
            raise TurnRecoveryRequired("tool has no durable original receipt; do not reexecute")
        return entry.payload["tool_result"] if entry is not None else None

    def before_tool(self, core, call):
        identity = self.identity(core, call)
        entry = self.repository.append_once(self.session_id, "tool_intent", identity,
            key=identity["invocation_id"], stage="tool_intent")
        self._edit(self.store.record_tool_call, tool_call_id=identity["invocation_id"],
                   operation_key=identity["invocation_id"], checkpoint={"intent_entry_id": entry.entry_id})

    def result_message(self, core, call, payload):
        identity = self.identity(core, call)
        payload = json.loads(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False))
        receipt = tool_receipts.persist(self.repository, **identity, payload=payload)
        message = tool_receipts.repair_message(self.repository, **identity)
        current = self.store.get(self.record.turn_id)
        pending = current.tool_calls.get(identity["invocation_id"])
        if pending and pending["status"] == "pending":
            self._edit(self.store.resolve_tool_call, tool_call_id=identity["invocation_id"],
                       operation_key=identity["invocation_id"], evidence={"receipt_entry_id": receipt.entry_id})
        return message

    def finish(self, core):
        self.save(core, "terminal", final_status=core._final_status,
                  response=getattr(core, "_durable_response", ""))
        self._edit(self.store.transition, status="failed" if core._final_status == "blocked"
                   else core._final_status or "completed")

    def interrupted(self, core):
        # Do not replace the pre-assistant checkpoint with half-applied state.
        current = self.store.get(self.record.turn_id)
        if current.status == "running":
            self._edit(self.store.transition, status="interrupted")
        core._final_status = "interrupted"

    def recover(self, core, turn_id, guard):
        self.record = self.store.get(turn_id)
        if self.record.session_id != self.session_id or self.record.status in TERMINAL:
            raise TurnRecoveryRequired("turn is terminal or belongs to another session")
        try:
            self.repository.recover_append_once(self.session_id)
        except SessionAppendPendingError:
            # A compact append intent without a logged message can only be
            # completed from the exact prior input checkpoint. Other unknown
            # content still fails the repository's stage/digest checks.
            branch = self.repository.get_branch(self.session_id)
            inputs = [entry for entry in branch if entry.entry_type == "turn_state"
                      and entry.payload.get("command_id") == self.record.command_id]
            if not inputs or inputs[-1].payload.get("stage") != "input":
                raise
            if (inputs[-1].idempotency is None
                    or inputs[-1].idempotency["payload_sha256"] != _payload_digest("turn_state", inputs[-1].payload)):
                raise TurnRecoveryRequired("input checkpoint digest is invalid")
            pending_input = inputs[-1].payload
            self.repository.append_once(self.session_id, "message", {"role": "user", "content": pending_input["text"],
                "command_id": pending_input["command_id"]}, key=pending_input["command_id"], stage=pending_input["user_stage"])
        if self.record.status == "running":
            self.record = self.store.interrupt_orphaned(turn_id, expected_version=self.record.version, guard=guard)
        elif self.record.lease_owner is not None:
            self.record = self.store.release_orphaned_claim(turn_id, expected_version=self.record.version, guard=guard)
        states = [e for e in self.repository.get_branch(self.session_id)
                  if e.entry_type == "turn_state" and e.payload.get("command_id") == self.record.command_id]
        if not states:
            entry = self.repository.get_entry(EntryRef(self.session_id, self.record.input_entry_id))
            if (entry not in self.repository.get_branch(self.session_id) or entry.entry_type != "turn_input"
                    or entry.idempotency != {"key": self.record.command_id, "stage": "turn_input",
                                             "payload_sha256": _payload_digest(entry.entry_type, entry.payload)}
                    or self.record.steps_used or self.record.tool_calls):
                raise TurnRecoveryRequired("turn has no durable Core checkpoint")
            state = entry.payload["initial_checkpoint"]
            state_entry_id = entry.entry_id
        else:
            state = states[-1].payload
            state_entry_id = states[-1].entry_id
        for index, entry in enumerate(states):
            if (entry.session_id != self.session_id or entry.payload.get("turn_id") != turn_id
                    or entry.idempotency != {"key": self.record.command_id, "stage": f"checkpoint:{index}",
                                             "payload_sha256": _payload_digest(entry.entry_type, entry.payload)}):
                raise TurnRecoveryRequired("Core checkpoint identity or content digest is invalid")
        if state.get("schema_version") != "agent.core_checkpoint.v1" or state.get("phase_active"):
            raise TurnRecoveryRequired("phase checkpoint requires a registered phase restorer")
        if (state.get("stage") not in {"initial", "input", "provider", "assistant", "repair", "ready", "terminal"}
                or state.get("command_id") != self.record.command_id or state.get("turn_id") != turn_id
                or set(state.get("state", {})) != set(_STATE_FIELDS)
                or state["runtime_contract"] != _runtime_contract(core)
                or {key: state["budget"][key] for key in ("max_steps", "timeout_s")} != self.record.budget
                or state["state"]["_steps_used"] < self.record.steps_used):
            raise TurnRecoveryRequired("Core checkpoint runtime contract or cumulative budget changed")
        self.started_at = state["started_at"]
        receipts = []
        for call_key, call in self.record.tool_calls.items():
            if call["status"] != "pending":
                continue
            intent = self.repository.get_entry(EntryRef(self.session_id, call["checkpoint"]["intent_entry_id"]))
            identity = intent.payload
            if intent not in self.repository.get_branch(self.session_id) or identity["invocation_id"] != call_key:
                raise TurnRecoveryRequired("tool intent is not on the active branch")
            receipt = tool_receipts.read(self.repository, **identity)
            if receipt is None:
                raise TurnRecoveryRequired("tool has no durable original receipt; do not reexecute")
            receipts.append((call_key, identity, receipt))
        self.record = self.store.claim(turn_id, expected_version=self.record.version,
            owner=self.owner, lease_seconds=self.record.budget["timeout_s"] + 60)
        for call_key, identity, receipt in receipts:
            tool_receipts.repair_message(self.repository, **identity)
            self._edit(self.store.resolve_tool_call, tool_call_id=call_key, operation_key=call_key,
                       evidence={"receipt_entry_id": receipt.entry_id})
        if self.record.requires_reconcile:
            self._edit(self.store.mark_reconciled, evidence={"state_entry_id": state_entry_id})
        core._active_command_id = self.record.command_id
        for name in _STATE_FIELDS:
            setattr(core, name, state["state"][name])
        core._user_text = state["user_text"]
        core._budget = type(core._budget).from_value(state["budget"])
        elapsed = max(self.record.wall_s_used, time.time() - self.started_at)
        core._turn_started_at = asyncio.get_running_loop().time() - elapsed
        for kind, queue in (("steer", core._steer_queue), ("follow_up", core._follow_up_queue)):
            queue.clear()
            queue.extend(self.repository.get_entry(EntryRef(self.session_id, q["entry_id"])).payload["text"]
                         for q in self.record.queue if not q["consumed"] and q["kind"] == kind)
        exhausted = elapsed >= core._budget.timeout_s or (core._steps_used >= core._budget.max_steps
                                                         and state["stage"] not in {"assistant", "terminal"})
        settle_only = state["stage"] == "assistant" and core._steps_used >= core._budget.max_steps
        if settle_only:
            # Settle an already returned final answer / original receipts
            # without re-entering execution or granting another provider step.
            for call in state["assistant"].get("tool_calls", []):
                if tool_receipts.read(self.repository, **self.identity(core, call)) is None:
                    exhausted = True
        # A terminal checkpoint needs no provider step, including a command
        # which spent its final allowed step producing that answer.
        if state["stage"] == "terminal":
            exhausted = False
        if not exhausted and not self.record.cancel_requested and state["stage"] != "terminal" and not settle_only:
            self._edit(self.store.transition, status="running")
        return state, exhausted, self.record.cancel_requested
