"""The project's record of every analysis and data change, in the order made.

Researchers fork: they recode, drop, subset, re-specify and test again. Each
choice is legitimate on its own; choosing among them by their p-values is not.
Workbench cannot see intent, but it can make the path visible. Every executed
analysis step and every data change is appended here -- by the user in the UI
or by the Agent, confirmed by a person or run under the read-only policy -- and
the report discloses it (see ``analysis_disclosure``).

The ledger is append-only JSONL under the project's ``workbench/`` namespace.
It is a disclosure record, not a replay log: lineage stays the source of truth
for what produced a result.

``step_category`` classifies every registered workflow step. A step the table
does not name is ``unclassified`` and is disclosed as such; the ledger test
fails until someone classifies it.
"""

from __future__ import annotations

import json
import hashlib
import os
import logging
import threading
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .jsonl_store import _exclusive_jsonl_lock

Category = Literal[
    "data_change", "metadata_change", "deletion", "model", "inferential", "descriptive", "report", "export",
    "unclassified",
]
CATEGORIES: tuple[str, ...] = (
    "data_change", "metadata_change", "deletion", "model", "inferential", "descriptive", "report", "export",
    "unclassified",
)
# Deleting a run changes what the project shows, so it is disclosed with the
# data changes: a deleted run is a path that was taken and then hidden.
CHANGING_CATEGORIES = frozenset({"data_change", "metadata_change", "deletion"})

# Exact ids first, then prefixes; the first match wins.
_EXACT: Mapping[str, str] = {
    "statistical.explore": "descriptive",
    "statistical.derive_boolean": "descriptive",
    "statistical.derived_group_summarize": "descriptive",
    "statistical.derive_numeric": "data_change",
    "nonparametric.robust_summary": "descriptive",
    "missingness.profile": "descriptive",
    "time_series.acf": "descriptive",
    "time_series.pacf": "descriptive",
    "survival.kaplan_meier": "descriptive",
    "meta.effect_size": "descriptive",
    "multivariate.cronbach_alpha": "descriptive",
    "roc.curve": "descriptive",
    "roc.calibration": "descriptive",
    "matching.balance": "descriptive",
    "time_series.arima": "model",
    "time_series.var": "model",
    "time_series.vecm": "model",
    "time_series.irf": "model",
    "synthetic_control.fit": "model",
    "iv.gmm": "model",
    "matching.att": "model",
    "missing_data.rubin_pool": "model",
    "model.joint_f_test": "inferential",
    "model.white_test": "inferential",
    "model.quadratic_stationary_point": "inferential",
    "metadata.edit": "metadata_change",
    "graph.fork": "descriptive",
    "code.execute": "data_change",
    "external.query": "export",
    # UI actions that are not workflow steps
    "run.delete": "deletion",
    "run.submit": "model",
    "run.rerun": "model",
}
_PREFIXES: tuple[tuple[str, str], ...] = (
    ("data.", "data_change"),
    ("resample.", "data_change"),
    ("imputation.", "data_change"),
    ("report.", "report"),
    ("export.", "export"),
    ("model.", "model"),
    ("prediction.", "model"),
    ("glm.", "model"),
    ("multivariate.", "model"),
    ("power_analysis.", "descriptive"),
    ("test.", "inferential"),
    ("nonparametric.", "inferential"),
    ("multiple_comparisons.", "inferential"),
    ("diagnostics.", "inferential"),
    ("categorical.", "inferential"),
    ("spatial.", "inferential"),
    ("time_series.", "inferential"),
    ("survival.", "inferential"),
    ("iv.", "inferential"),
    ("meta.", "inferential"),
    ("resampling.", "inferential"),
    ("repeated_measures_anova.", "inferential"),
    ("synthetic_control.", "inferential"),
    ("postestimation.", "inferential"),
)


def step_category(operation_id: str) -> str:
    if operation_id in _EXACT:
        return _EXACT[operation_id]
    for prefix, category in _PREFIXES:
        if operation_id.startswith(prefix):
            return category
    return "unclassified"


@dataclass(frozen=True)
class LedgerStep:
    operation_id: str
    category: str
    detail: str = ""
    # How many tests the step ran: one, or one per group for a by-group step.
    tests: int = 1

    @classmethod
    def of(cls, operation_id: str, detail: str = "", tests: int = 1) -> "LedgerStep":
        return cls(operation_id=operation_id, category=step_category(operation_id), detail=detail,
                   tests=max(int(tests), 1))


@dataclass(frozen=True)
class LedgerEntry:
    """One executed action: a UI call or one Agent operation (with its steps)."""

    actor: Literal["user", "agent"]
    # Who allowed it to run: the user's own action or confirmation, or the
    # read-only analysis policy (Agent analyses that change no data).
    # v1.9.1: or the person's standing permission -- the approved plan, a
    # conversation grant or a project rule (agent/permissions.py).
    authorized_by: Literal["user", "read_only_policy", "approved_plan", "session_grant", "project_rule"]
    source: str  # the route or operation that ran it
    status: Literal["completed", "failed"]
    steps: tuple[LedgerStep, ...]
    run_id: str | None = None
    node_id: str | None = None
    produced_run_id: str | None = None
    summary: str = ""
    session_id: str | None = None
    record_id: str | None = None
    # The data this entry is about, resolved when it is written: a run that
    # is later deleted can no longer be traced back to its data.
    source_upload_sha256: str | None = None
    research_specification: dict[str, Any] | None = None
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="milliseconds"))

    @property
    def categories(self) -> set[str]:
        return {step.category for step in self.steps}

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.research_specification is None:
            value.pop("research_specification")
        else:
            value["specification_status"] = self.research_specification["specification_status"]
            value["specification_reason"] = self.research_specification["reason"]
            value["question_id"] = self.research_specification["question_id"]
        value["steps"] = [asdict(step) for step in self.steps]
        value["inferential_steps"] = sum(step.tests for step in self.steps if step.category == "inferential")
        value["changes_data"] = bool(self.categories & CHANGING_CATEGORIES)
        return value


_LOCK = threading.Lock()
_LOG = logging.getLogger(__name__)


def ledger_path(project_root: Path | str) -> Path:
    return Path(project_root) / "workbench" / "analysis_ledger.jsonl"


def record(project_root: Path | str, entry: LedgerEntry) -> dict[str, Any]:
    """Append one entry. A ledger write never blocks the action it records;
    a failure to write is itself surfaced by the caller's tests, not hidden."""

    payload = entry.to_dict()
    if not payload.get("source_upload_sha256"):
        payload["source_upload_sha256"] = upload_sha(project_root, entry.run_id or entry.produced_run_id)
    path = ledger_path(project_root)
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    with _LOCK, _exclusive_jsonl_lock(path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    return payload


def record_plan_event_once(project_root: Path | str, *, session_id: str, event_type: str,
                           plan_snapshot: Mapping[str, Any], actor: str | None = None) -> dict[str, Any]:
    """Fix an exact research intent before plan authority becomes active.

    This event records a request, not proof that results were unseen or that
    the matching plan commit succeeded. Pre-specified/exploratory status needs
    separate exposure evidence; no analysis count or result is fabricated.
    """
    if event_type not in {"criteria_fixed", "question_change"}:
        raise ValueError("unknown plan event type")
    actor = actor or ("user" if event_type == "criteria_fixed" else "agent")
    if actor not in {"user", "agent"} or event_type == "criteria_fixed" and actor != "user":
        raise ValueError("invalid plan event actor")
    snapshot = json.loads(json.dumps(dict(plan_snapshot), ensure_ascii=False, allow_nan=False))
    identity = ["agent.plan-event.v1", session_id, snapshot["plan_id"], snapshot["version"], event_type]
    event_id = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()
    payload = {
        "record_type": "research_intent", "event_type": event_type, "event_id": event_id,
        "actor": actor, "authorized_by": "user",
        "source": f"agent.plan.{event_type}", "status": "completed", "steps": [],
        "inferential_steps": 0, "changes_data": False, "session_id": session_id,
        "plan_id": snapshot["plan_id"], "plan_version": snapshot["version"], "plan_snapshot": snapshot,
        "activation": "requires_matching_approved_plan", "summary": "Research intent recorded; no analysis executed.",
    }
    path = ledger_path(project_root)
    with _LOCK, _exclusive_jsonl_lock(path):
        raw = path.read_text(encoding="utf-8") if path.exists() else ""
        if raw and not raw.endswith("\n"):
            raise ValueError("incomplete analysis ledger needs reconciliation")
        entries = [json.loads(line) for line in raw.splitlines() if line.strip()]
        matches = [entry for entry in entries if entry.get("event_id") == event_id]
        if matches:
            recorded = {k: v for k, v in matches[0].items() if k != "at"}
            expected = payload
            if event_type == "question_change":
                # This event prepares a generated revision timestamp. The
                # first snapshot owns it; return that exact snapshot to commit.
                # Every other field must still match the same requested change.
                def without_generated_time(value):
                    return {**value, "plan_snapshot": {
                        key: item for key, item in value.get("plan_snapshot", {}).items() if key != "updated_at"}}
                recorded, expected = without_generated_time(recorded), without_generated_time(expected)
            if len(matches) != 1 or recorded != expected:
                raise ValueError("plan event conflicts with the recorded research intent")
            return matches[0]
        payload["at"] = datetime.now(UTC).isoformat(timespec="milliseconds")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    return payload


def upload_sha(project_root: Path | str, run_id: str | None) -> str | None:
    """The sha256 of the upload a run was estimated on, or None."""

    if not run_id:
        return None
    from .lineage.run_inputs import read_run_inputs

    try:
        inputs = read_run_inputs(Path(project_root) / "runs" / run_id)
    except (OSError, ValueError):
        return None
    upload = inputs.get("upload") if isinstance(inputs, Mapping) else None
    sha = upload.get("sha256") if isinstance(upload, Mapping) else None
    return str(sha) if sha else None


def read(project_root: Path | str) -> list[dict[str, Any]]:
    path = ledger_path(project_root)
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def inferential_count(entries: Iterable[Mapping[str, Any]], *, session_id: str | None = None) -> int:
    return sum(
        int(entry.get("inferential_steps") or 0)
        for entry in entries
        if entry.get("status") == "completed" and (session_id is None or entry.get("session_id") == session_id)
    )


def record_agent_action(
    project_root: Path | str,
    *,
    source: str,
    steps: Iterable[str | LedgerStep],
    session_id: str | None = None,
    run_id: str | None = None,
    node_id: str | None = None,
    summary: str = "",
) -> None:
    """Record something the Agent did at once, without a proposal (an export).

    Like a UI action it has already happened, so a failed write is logged,
    not raised.
    """

    entry = LedgerEntry(
        actor="agent",
        authorized_by="read_only_policy",
        source=source,
        status="completed",
        steps=tuple(step if isinstance(step, LedgerStep) else LedgerStep.of(step) for step in steps),
        run_id=run_id,
        node_id=node_id,
        summary=summary,
        session_id=session_id,
        source_upload_sha256=upload_sha(project_root, run_id) if run_id else None,
    )
    try:
        record(project_root, entry)
    except Exception:  # noqa: BLE001 -- the export already happened
        logging.getLogger(__name__).exception("analysis ledger: could not record Agent action %s", source)


def record_ui_action(
    project_root: Path | str,
    *,
    source: str,
    steps: Iterable[str | LedgerStep],
    run_id: str | None = None,
    node_id: str | None = None,
    produced_run_id: str | None = None,
    summary: str = "",
    source_upload_sha256: str | None = None,
) -> None:
    """Record an action the user took in the UI, after it succeeded.

    The action has already happened, so a failed ledger write must not turn
    it into an error response; it is logged loudly instead.
    """

    entry = LedgerEntry(
        actor="user",
        authorized_by="user",
        source=source,
        status="completed",
        steps=tuple(step if isinstance(step, LedgerStep) else LedgerStep.of(step) for step in steps),
        run_id=run_id,
        node_id=node_id,
        produced_run_id=produced_run_id,
        summary=summary,
        source_upload_sha256=source_upload_sha256,
    )
    try:
        record(project_root, entry)
    except OSError:
        _LOG.exception("analysis ledger write failed for %s", source)
