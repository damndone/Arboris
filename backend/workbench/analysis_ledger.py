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
import threading
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

Category = Literal["data_change", "metadata_change", "model", "inferential", "descriptive", "report", "export", "unclassified"]
CATEGORIES: tuple[str, ...] = (
    "data_change", "metadata_change", "model", "inferential", "descriptive", "report", "export", "unclassified",
)

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
}
_PREFIXES: tuple[tuple[str, str], ...] = (
    ("data.", "data_change"),
    ("resample.", "data_change"),
    ("imputation.", "data_change"),
    ("report.", "report"),
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

    @classmethod
    def of(cls, operation_id: str, detail: str = "") -> "LedgerStep":
        return cls(operation_id=operation_id, category=step_category(operation_id), detail=detail)


@dataclass(frozen=True)
class LedgerEntry:
    """One executed action: a UI call or one Agent operation (with its steps)."""

    actor: Literal["user", "agent"]
    # Who allowed it to run: the user's own action or confirmation, or the
    # read-only analysis policy (Agent analyses that change no data).
    authorized_by: Literal["user", "read_only_policy"]
    source: str  # the route or operation that ran it
    status: Literal["completed", "failed"]
    steps: tuple[LedgerStep, ...]
    run_id: str | None = None
    node_id: str | None = None
    produced_run_id: str | None = None
    summary: str = ""
    session_id: str | None = None
    record_id: str | None = None
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="milliseconds"))

    @property
    def categories(self) -> set[str]:
        return {step.category for step in self.steps}

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["steps"] = [asdict(step) for step in self.steps]
        value["inferential_steps"] = sum(1 for step in self.steps if step.category == "inferential")
        value["changes_data"] = bool(self.categories & {"data_change", "metadata_change"})
        return value


_LOCK = threading.Lock()


def ledger_path(project_root: Path | str) -> Path:
    return Path(project_root) / "workbench" / "analysis_ledger.jsonl"


def record(project_root: Path | str, entry: LedgerEntry) -> dict[str, Any]:
    """Append one entry. A ledger write never blocks the action it records;
    a failure to write is itself surfaced by the caller's tests, not hidden."""

    payload = entry.to_dict()
    path = ledger_path(project_root)
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    return payload


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
