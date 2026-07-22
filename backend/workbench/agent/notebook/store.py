"""Append-only notebook and option storage (spec §8).

Layout, following the JSONL convention already used by agent sessions and
operation records:

    <project>/notebooks/<notebook_id>/notebook.jsonl
    <project>/notebooks/<notebook_id>/options/<option_id>.jsonl

Nothing is ever rewritten in place. A revision, a lifecycle transition and an
execution are all *records*; the current state is a fold over them. That is what
makes "why did this option change after it went stale" answerable months later,
which a mutable `typed_proposal JSON` column cannot do (spec §3.8).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from ...contracts.agent.notebook_option import NotebookOptionRevision
from ..storage import append_jsonl_atomic, read_jsonl
from .errors import NotebookNotFound, OptionNotFound
from .proposal import TypedProposal

NOTEBOOK_SCHEMA_VERSION = "notebook.v1"
NOTEBOOK_DIRNAME = "notebooks"
NOTEBOOK_FILENAME = "notebook.jsonl"
OPTIONS_DIRNAME = "options"

RECORD_NOTEBOOK = "notebook"
RECORD_NOTEBOOK_STATE = "notebook_state"
RECORD_OPTION = "option"
RECORD_REVISION = "revision"
RECORD_LIFECYCLE = "lifecycle"
RECORD_EXECUTION = "execution"
RECORD_EXECUTION_RESULT = "execution_result"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_component(value: str, *, label: str) -> str:
    if not value or Path(value).name != value or value.startswith("."):
        raise ValueError(f"{label} is not a safe path component: {value!r}")
    return value


@dataclass(frozen=True)
class Notebook:
    """The stable identity. Run pointers are three distinct fields on purpose.

    spec §9.1 criterion 4: `active_head_run_id` (the committed head),
    `focused_run_id` (what the user is looking at) and `last_attempt_run_id`
    (the run that failed) answer different questions. Collapsing them is how a
    failed attempt ends up cited as a result.
    """

    notebook_id: str
    project_id: str
    run_family_id: str
    title: str
    created_by: str
    created_at: str
    active_head_run_id: str | None = None
    focused_run_id: str | None = None
    last_attempt_run_id: str | None = None
    analysis_contract: dict[str, Any] = field(default_factory=dict)
    user_focus: dict[str, Any] = field(default_factory=dict)
    available_capabilities: tuple[str, ...] = ()
    schema_version: str = NOTEBOOK_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": RECORD_NOTEBOOK,
            "schema_version": self.schema_version,
            "notebook_id": self.notebook_id,
            "project_id": self.project_id,
            "run_family_id": self.run_family_id,
            "title": self.title,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "active_head_run_id": self.active_head_run_id,
            "focused_run_id": self.focused_run_id,
            "last_attempt_run_id": self.last_attempt_run_id,
            "analysis_contract": dict(self.analysis_contract),
            "user_focus": dict(self.user_focus),
            "available_capabilities": list(self.available_capabilities),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Notebook":
        return cls(
            notebook_id=str(value["notebook_id"]),
            project_id=str(value["project_id"]),
            run_family_id=str(value["run_family_id"]),
            title=str(value.get("title", "")),
            created_by=str(value.get("created_by", "")),
            created_at=str(value["created_at"]),
            active_head_run_id=value.get("active_head_run_id"),
            focused_run_id=value.get("focused_run_id"),
            last_attempt_run_id=value.get("last_attempt_run_id"),
            analysis_contract=dict(value.get("analysis_contract") or {}),
            user_focus=dict(value.get("user_focus") or {}),
            available_capabilities=tuple(value.get("available_capabilities") or ()),
            schema_version=str(value.get("schema_version", NOTEBOOK_SCHEMA_VERSION)),
        )


@dataclass(frozen=True)
class StoredRevision:
    """A contract revision plus the proposal body it refers to.

    The locked contract stores only `typed_proposal_id` / `typed_proposal_revision`.
    The body has to be kept alongside it, per revision, or §3.8's anti-pattern
    returns by the back door: revision numbers that increment while the content
    they describe has already been overwritten.
    """

    revision: NotebookOptionRevision
    proposal: TypedProposal
    canonical_proposal_hash: str
    validation_issues: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": RECORD_REVISION,
            "option_id": self.revision.option_id,
            "option_revision": self.revision.option_revision,
            "revision": self.revision.to_dict(),
            "typed_proposal": self.proposal.to_dict(),
            "canonical_proposal_hash": self.canonical_proposal_hash,
            "validation_issues": [dict(issue) for issue in self.validation_issues],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "StoredRevision":
        return cls(
            revision=NotebookOptionRevision.from_dict(value["revision"]),
            proposal=TypedProposal.from_dict(value["typed_proposal"]),
            canonical_proposal_hash=str(value["canonical_proposal_hash"]),
            validation_issues=tuple(dict(i) for i in value.get("validation_issues", ())),
        )


@dataclass(frozen=True)
class OptionView:
    """The fold over one option's record log."""

    option_id: str
    notebook_id: str
    batch_id: str
    rank: int
    created_at: str
    stored_revisions: tuple[StoredRevision, ...]
    lifecycle_history: tuple[dict[str, Any], ...]
    executions: tuple[dict[str, Any], ...]
    execution_results: tuple[dict[str, Any], ...]
    freshness_status: str | None = None
    freshness: dict[str, Any] | None = None

    @property
    def revisions(self) -> tuple[NotebookOptionRevision, ...]:
        return tuple(stored.revision for stored in self.stored_revisions)

    @property
    def current_stored_revision(self) -> StoredRevision:
        return self.stored_revisions[-1]

    @property
    def current_revision(self) -> NotebookOptionRevision:
        return self.stored_revisions[-1].revision

    @property
    def lifecycle_status(self) -> str:
        return str(self.lifecycle_history[-1]["to_status"])

    @property
    def last_execution(self) -> dict[str, Any] | None:
        return dict(self.executions[-1]) if self.executions else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "option_id": self.option_id,
            "notebook_id": self.notebook_id,
            "batch_id": self.batch_id,
            "rank": self.rank,
            "created_at": self.created_at,
            "lifecycle_status": self.lifecycle_status,
            "current_option_revision": self.current_revision.option_revision,
            "current_revision": self.current_revision.to_dict(),
            "typed_proposal": self.current_stored_revision.proposal.to_dict(),
            "revisions": [stored.to_dict() for stored in self.stored_revisions],
            "lifecycle_history": [dict(entry) for entry in self.lifecycle_history],
            "executions": [dict(entry) for entry in self.executions],
            "execution_results": [dict(entry) for entry in self.execution_results],
            "freshness": dict(self.freshness) if self.freshness else None,
        }


class NotebookStore:
    """Append-only reader/writer. Knows nothing about validation or agents."""

    def __init__(self, project_root: Path | str, *, create: bool = True) -> None:
        self.project_root = Path(project_root)
        self.directory = self.project_root / NOTEBOOK_DIRNAME
        if create:
            self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    # -- paths ---------------------------------------------------------

    def notebook_dir(self, notebook_id: str) -> Path:
        return self.directory / _safe_component(notebook_id, label="notebook_id")

    def _notebook_path(self, notebook_id: str) -> Path:
        return self.notebook_dir(notebook_id) / NOTEBOOK_FILENAME

    def _option_path(self, notebook_id: str, option_id: str) -> Path:
        return (
            self.notebook_dir(notebook_id)
            / OPTIONS_DIRNAME
            / f"{_safe_component(option_id, label='option_id')}.jsonl"
        )

    # -- notebooks -----------------------------------------------------

    def create_notebook(self, notebook: Notebook) -> Notebook:
        with self._lock:
            path = self._notebook_path(notebook.notebook_id)
            if path.exists() and read_jsonl(path):
                raise ValueError(f"notebook already exists: {notebook.notebook_id}")
            (path.parent / OPTIONS_DIRNAME).mkdir(parents=True, exist_ok=True)
            append_jsonl_atomic(path, notebook.to_dict())
            return notebook

    def get_notebook(self, notebook_id: str) -> Notebook:
        with self._lock:
            records = read_jsonl(self._notebook_path(notebook_id))
            if not records:
                raise NotebookNotFound(
                    f"unknown notebook: {notebook_id}", notebook_id=notebook_id
                )
            notebook = Notebook.from_dict(records[0])
            for record in records[1:]:
                if record.get("record_type") != RECORD_NOTEBOOK_STATE:
                    continue
                notebook = replace(
                    notebook,
                    active_head_run_id=record.get(
                        "active_head_run_id", notebook.active_head_run_id
                    ),
                    focused_run_id=record.get("focused_run_id", notebook.focused_run_id),
                    last_attempt_run_id=record.get(
                        "last_attempt_run_id", notebook.last_attempt_run_id
                    ),
                    user_focus=dict(record["user_focus"])
                    if "user_focus" in record
                    else notebook.user_focus,
                )
            return notebook

    def list_notebooks(self) -> list[Notebook]:
        with self._lock:
            if not self.directory.is_dir():
                return []
            notebooks: list[Notebook] = []
            for entry in sorted(self.directory.iterdir()):
                if (entry / NOTEBOOK_FILENAME).is_file():
                    notebooks.append(self.get_notebook(entry.name))
            return notebooks

    def append_notebook_state(self, notebook_id: str, payload: Mapping[str, Any]) -> None:
        with self._lock:
            record = {
                "record_type": RECORD_NOTEBOOK_STATE,
                "recorded_at": _now(),
                **dict(payload),
            }
            append_jsonl_atomic(self._notebook_path(notebook_id), record)

    # -- options -------------------------------------------------------

    def append_option_record(
        self, notebook_id: str, option_id: str, record: Mapping[str, Any]
    ) -> None:
        with self._lock:
            path = self._option_path(notebook_id, option_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            append_jsonl_atomic(path, {"recorded_at": _now(), **dict(record)})

    def option_ids(self, notebook_id: str) -> list[str]:
        directory = self.notebook_dir(notebook_id) / OPTIONS_DIRNAME
        if not directory.is_dir():
            return []
        return sorted(path.stem for path in directory.glob("*.jsonl"))

    def read_option(self, notebook_id: str, option_id: str) -> OptionView:
        with self._lock:
            records = read_jsonl(self._option_path(notebook_id, option_id))
        if not records:
            raise OptionNotFound(f"unknown option: {option_id}", option_id=option_id)

        header: dict[str, Any] | None = None
        stored: list[StoredRevision] = []
        lifecycle: list[dict[str, Any]] = []
        executions: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        for record in records:
            kind = record.get("record_type")
            if kind == RECORD_OPTION:
                header = record
            elif kind == RECORD_REVISION:
                stored.append(StoredRevision.from_dict(record))
            elif kind == RECORD_LIFECYCLE:
                lifecycle.append(record)
            elif kind == RECORD_EXECUTION:
                executions.append(record)
            elif kind == RECORD_EXECUTION_RESULT:
                results.append(record)
        if header is None or not stored or not lifecycle:
            raise OptionNotFound(
                f"option log for {option_id} is incomplete", option_id=option_id
            )
        return OptionView(
            option_id=option_id,
            notebook_id=notebook_id,
            batch_id=str(header["batch_id"]),
            rank=int(header["rank"]),
            created_at=str(header["created_at"]),
            stored_revisions=tuple(stored),
            lifecycle_history=tuple(lifecycle),
            executions=tuple(executions),
            execution_results=tuple(results),
        )


__all__ = [
    "NOTEBOOK_DIRNAME",
    "Notebook",
    "NotebookStore",
    "OptionView",
    "RECORD_EXECUTION",
    "RECORD_EXECUTION_RESULT",
    "RECORD_LIFECYCLE",
    "RECORD_OPTION",
    "RECORD_REVISION",
    "StoredRevision",
]
