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

import json
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterator, Mapping
from uuid import uuid4
from weakref import WeakValueDictionary

from ...canonical import sha256_canonical
from ...contracts.agent.notebook_option import (
    FeasibilityDecision,
    NotebookOptionRevision,
    OptionMaterialization,
    RecommendationDecision,
    RecommendationDecisionV11,
    RECOMMENDATION_DECISION_V11_CONTRACT_VERSION,
)
from ..events import AgentEventStream
from ..storage import append_jsonl_atomic, read_jsonl
from .errors import NotebookNotFound, OptionLegacyUnverified, OptionNotFound
from .proposal import TypedProposal
from .recommendation import ComparisonDecisionRecord, ServerDecisionRegistry

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
RECORD_EVIDENCE_PACK = "evidence_pack"
RECORD_RECOMMENDATION_DECISION = "recommendation_decision"
RECORD_FEASIBILITY_DECISION = "feasibility_decision"
RECORD_COMPARISON_DECISION = "comparison_decision"
RECORD_OPTION_MATERIALIZATION = "option_materialization"

@dataclass
class _ProjectLockHolder:
    lock: Any = field(default_factory=RLock)


_PROJECT_LOCKS: WeakValueDictionary[Path, _ProjectLockHolder] = WeakValueDictionary()
_PROJECT_LOCKS_GUARD = RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_component(value: str, *, label: str) -> str:
    if not value or Path(value).name != value or value.startswith("."):
        raise ValueError(f"{label} is not a safe path component: {value!r}")
    return value


def _project_lock_holder(project_root: Path) -> _ProjectLockHolder:
    """Return the weakly registered lock holder for one resolved project root."""

    with _PROJECT_LOCKS_GUARD:
        resolved_root = project_root.resolve()
        holder = _PROJECT_LOCKS.get(resolved_root)
        if holder is None:
            holder = _ProjectLockHolder()
            _PROJECT_LOCKS[resolved_root] = holder
        return holder


def _require_pathless_string(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
    ):
        raise ValueError(f"{label} must be a nonempty pathless string")
    return value


def _validate_evidence_pack(value: Mapping[str, Any]) -> dict[str, Any]:
    """Accept serializable evidence references, never an arbitrary file payload."""

    if not isinstance(value, Mapping):
        raise ValueError("evidence pack must be a mapping")
    pack = dict(value)
    evidence_pack_hash = pack.get("evidence_pack_hash")
    if not isinstance(evidence_pack_hash, str) or not evidence_pack_hash:
        raise ValueError("evidence_pack_hash must be a nonempty string")
    _reject_raw_evidence_values(pack)
    try:
        canonical = json.loads(json.dumps(pack, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise ValueError("evidence pack must be JSON serializable") from exc
    if not isinstance(canonical, dict):  # defensive: `pack` is a mapping above.
        raise ValueError("evidence pack must be a mapping")
    return canonical


def _reject_raw_evidence_values(value: object) -> None:
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError("evidence pack cannot contain raw bytes")
    if isinstance(value, Mapping):
        if "raw_path" in value:
            raise ValueError("evidence pack cannot contain a raw path")
        for item in value.values():
            _reject_raw_evidence_values(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _reject_raw_evidence_values(item)


@dataclass(frozen=True)
class WorkflowSource:
    """Server-resolved raw source identity for a dataset-rooted Notebook.

    A dataset projection normally has no active Run head.  When it was started
    from a persisted Run, this small immutable pin preserves the actual raw
    dataset node that the server resolved at creation time.  It is an artifact
    identity, never a filesystem path or a client-supplied execution target.
    """

    run_id: str
    node_ref: str
    artifact_id: str
    source_sha256: str
    source_kind: str = "run_artifact"

    def __post_init__(self) -> None:
        _require_pathless_string(self.run_id, label="workflow_source.run_id")
        _require_pathless_string(self.node_ref, label="workflow_source.node_ref")
        _require_pathless_string(self.artifact_id, label="workflow_source.artifact_id")
        if self.source_kind not in {"run_artifact", "dataset_upload"}:
            raise ValueError(
                "workflow_source.source_kind must be 'run_artifact' or 'dataset_upload'"
            )
        if (
            not isinstance(self.source_sha256, str)
            or len(self.source_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.source_sha256)
        ):
            raise ValueError("workflow_source.source_sha256 must be a lowercase SHA-256 digest")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "WorkflowSource":
        legacy_fields = {
            "run_id",
            "node_ref",
            "artifact_id",
            "source_sha256",
        }
        if not isinstance(value, Mapping):
            raise ValueError("workflow_source has invalid fields")
        fields = frozenset(value)
        if fields not in {
            frozenset(legacy_fields),
            frozenset({*legacy_fields, "source_kind"}),
        }:
            raise ValueError("workflow_source has invalid fields")
        return cls(
            run_id=value["run_id"],
            node_ref=value["node_ref"],
            artifact_id=value["artifact_id"],
            source_sha256=value["source_sha256"],
            source_kind=value.get("source_kind", "run_artifact"),
        )

    def to_dict(self) -> dict[str, str]:
        payload = {
            "run_id": self.run_id,
            "node_ref": self.node_ref,
            "artifact_id": self.artifact_id,
            "source_sha256": self.source_sha256,
        }
        if self.source_kind != "run_artifact":
            payload["source_kind"] = self.source_kind
        return payload


@dataclass(frozen=True)
class ProjectionSource:
    """The immutable, strict source of a default Notebook projection."""

    kind: str
    run_id: str | None = None
    upload_sha256: str | None = None
    filename: str | None = None
    sheet_names: tuple[str, ...] = ()
    workflow_source: WorkflowSource | None = None

    def __post_init__(self) -> None:
        if self.kind == "run":
            _require_pathless_string(self.run_id, label="projection_source.run_id")
            if (
                self.upload_sha256 is not None
                or self.filename is not None
                or self.sheet_names
                or self.workflow_source is not None
            ):
                raise ValueError("run projection_source cannot carry dataset fields")
            return
        if self.kind != "dataset":
            raise ValueError("projection_source.kind must be 'run' or 'dataset'")
        if self.run_id is not None:
            raise ValueError("dataset projection_source cannot carry run_id")
        _require_pathless_string(
            self.upload_sha256, label="projection_source.upload_sha256"
        )
        _require_pathless_string(self.filename, label="projection_source.filename")
        if not isinstance(self.sheet_names, tuple) or any(
            not isinstance(name, str) or not name for name in self.sheet_names
        ):
            raise ValueError(
                "projection_source.sheet_names must be a tuple of nonempty strings"
            )
        if self.workflow_source is not None and not isinstance(
            self.workflow_source, WorkflowSource
        ):
            raise ValueError("dataset workflow_source must be a WorkflowSource when supplied")

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProjectionSource":
        if not isinstance(value, Mapping):
            raise ValueError("projection_source must be a mapping")
        kind = value.get("kind")
        if kind == "run":
            if set(value) != {"kind", "run_id"}:
                raise ValueError("run projection_source must contain only kind and run_id")
            return cls(kind="run", run_id=value["run_id"])
        if kind == "dataset":
            allowed = {
                "kind",
                "upload_sha256",
                "filename",
                "sheet_names",
                "workflow_source",
            }
            required = {"kind", "upload_sha256", "filename"}
            if set(value) - allowed or not required.issubset(value):
                raise ValueError("dataset projection_source has invalid fields")
            raw_sheet_names = value.get("sheet_names", ())
            if not isinstance(raw_sheet_names, (list, tuple)):
                raise ValueError("projection_source.sheet_names must be a list or tuple")
            return cls(
                kind="dataset",
                upload_sha256=value["upload_sha256"],
                filename=value["filename"],
                sheet_names=tuple(raw_sheet_names),
                workflow_source=(
                    WorkflowSource.from_dict(value["workflow_source"])
                    if value.get("workflow_source") is not None
                    else None
                ),
            )
        raise ValueError("projection_source.kind must be 'run' or 'dataset'")

    def to_dict(self) -> dict[str, Any]:
        if self.kind == "run":
            return {"kind": "run", "run_id": self.run_id}
        payload = {
            "kind": "dataset",
            "upload_sha256": self.upload_sha256,
            "filename": self.filename,
            "sheet_names": list(self.sheet_names),
        }
        if self.workflow_source is not None:
            payload["workflow_source"] = self.workflow_source.to_dict()
        return payload


def dataset_workflow_source_pin(source: ProjectionSource) -> dict[str, dict[str, str]] | None:
    """Return the exact execution pin for one server-resolved dataset source.

    The pin is intentionally derived from immutable provenance fields instead
    of accepting a Notebook active head.  A dataset-rooted Notebook may have
    several resulting model branches and therefore no single head to pretend
    is the source of all work.
    """

    workflow_source = source.workflow_source if source.kind == "dataset" else None
    if workflow_source is None:
        return None
    target = {
        "run_id": workflow_source.run_id,
        "node_ref": workflow_source.node_ref,
        "artifact_id": workflow_source.artifact_id,
    }
    identity = {
        "schema_version": "notebook-workflow-source/v1",
        "target": target,
        "source_sha256": workflow_source.source_sha256,
    }
    return {
        "target": target,
        "preconditions": {
            "context_version": "notebook-workflow-source/v1",
            "context_fingerprint": "nbsrc1:" + sha256_canonical(identity),
            # The workflow contract calls this field active_head_run_id.  For
            # a dataset projection it names the immutable *source* Run, not
            # the Notebook's (deliberately absent) result head.
            "active_head_run_id": workflow_source.run_id,
            "owner_resolution": "dataset_projection_source",
        },
    }


def reserve_dataset_upload_workflow_source(source: ProjectionSource) -> ProjectionSource:
    """Bind an upload projection to a future server-owned raw-source identity."""

    if source.kind != "dataset":
        raise ValueError("only a dataset projection may reserve an upload source")
    if source.workflow_source is not None:
        return source
    identity = {
        "schema_version": "notebook-upload-workflow-source/v1",
        "upload_sha256": source.upload_sha256,
        "filename": source.filename,
        "sheet_names": list(source.sheet_names),
    }
    run_id = "notebook_source_" + sha256_canonical(identity)[:24]
    return replace(
        source,
        workflow_source=WorkflowSource(
            run_id=run_id,
            node_ref="stage:raw",
            artifact_id=f"raw_{source.filename}",
            source_sha256=str(source.upload_sha256),
            source_kind="dataset_upload",
        ),
    )


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
    projection_key: str | None = None
    projection_source: ProjectionSource | None = None
    supersedes_notebook_id: str | None = None
    # Internal stable trace identity. It is folded from notebook_state rather
    # than exposed in the public Notebook record so remounts can replay the
    # same decision chain without making Trace a second source of truth.
    trace_id: str | None = None
    schema_version: str = NOTEBOOK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.projection_key is not None and (
            not isinstance(self.projection_key, str) or not self.projection_key
        ):
            raise ValueError("projection_key must be a nonempty string when supplied")
        if self.projection_source is not None and not isinstance(
            self.projection_source, ProjectionSource
        ):
            raise ValueError("projection_source must be a ProjectionSource when supplied")
        if (self.projection_key is None) != (self.projection_source is None):
            raise ValueError(
                "projection_key and projection_source must be supplied together"
            )
        if self.projection_key is not None:
            expected_key = f"default-projection:{self.run_family_id}"
            if self.projection_key != expected_key:
                raise ValueError(
                    f"projection_key must be exactly {expected_key!r} for its run family"
                )
        if self.supersedes_notebook_id is not None and (
            not isinstance(self.supersedes_notebook_id, str)
            or not self.supersedes_notebook_id
        ):
            raise ValueError("supersedes_notebook_id must be a nonempty string when supplied")

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
            "projection_key": self.projection_key,
            "projection_source": (
                self.projection_source.to_dict() if self.projection_source else None
            ),
            "supersedes_notebook_id": self.supersedes_notebook_id,
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
            projection_key=value.get("projection_key"),
            projection_source=(
                ProjectionSource.from_dict(value["projection_source"])
                if value.get("projection_source") is not None
                else None
            ),
            supersedes_notebook_id=value.get("supersedes_notebook_id"),
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
        self._lock_holder = _project_lock_holder(self.project_root)
        self._lock = self._lock_holder.lock

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

    @contextmanager
    def project_lock(self) -> Iterator[None]:
        """Hold this project's shared, in-process reentrant store lock."""

        with self._lock:
            yield

    def create_notebook(self, notebook: Notebook) -> Notebook:
        with self._lock:
            path = self._notebook_path(notebook.notebook_id)
            if path.exists() and read_jsonl(path):
                raise ValueError(f"notebook already exists: {notebook.notebook_id}")
            (path.parent / OPTIONS_DIRNAME).mkdir(parents=True, exist_ok=True)
            append_jsonl_atomic(path, notebook.to_dict())
            return notebook

    def ensure_default_projection(self, notebook: Notebook) -> Notebook:
        """Read/create a key-bound projection while holding the store lock."""

        if notebook.projection_key is None or notebook.projection_source is None:
            raise ValueError("default projections require projection_key and projection_source")
        with self._lock:
            for existing in self.list_notebooks():
                if existing.projection_key != notebook.projection_key:
                    continue
                if existing.projection_source != notebook.projection_source:
                    raise ValueError(
                        f"projection key {notebook.projection_key!r} is already bound "
                        "to a different source"
                    )
                if existing.run_family_id != notebook.run_family_id:
                    raise ValueError(
                        f"projection key {notebook.projection_key!r} is already bound "
                        "to a different run family"
                    )
                return existing
            return self.create_notebook(notebook)

    def ensure_dataset_default_projection(
        self,
        source: ProjectionSource,
        create_notebook: Callable[[], Notebook],
    ) -> Notebook:
        """Find an existing Dataset default before creating its pre-run family."""

        if source.kind != "dataset":
            raise ValueError("dataset default projection requires a dataset source")
        with self._lock:
            for existing in self.list_notebooks():
                if (
                    existing.projection_key is not None
                    and existing.projection_source == source
                ):
                    return existing
            return self.ensure_default_projection(create_notebook())

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
                    trace_id=record.get("trace_id", notebook.trace_id),
                )
            return notebook

    def ensure_trace_id(self, notebook_id: str) -> str:
        """Return one append-only trace identity for the Notebook.

        The check and state append share the project lock, so concurrent route
        calls cannot fork a Notebook into multiple planning traces.
        """

        with self._lock:
            notebook = self.get_notebook(notebook_id)
            if notebook.trace_id:
                return notebook.trace_id
            trace_id = self._legacy_trace_id(notebook)
            if trace_id is None:
                trace_id = f"trace_{uuid4().hex}"
            append_jsonl_atomic(
                self._notebook_path(notebook_id),
                {
                    "record_type": RECORD_NOTEBOOK_STATE,
                    "recorded_at": _now(),
                    "trace_id": trace_id,
                    "reason": "trace_started",
                },
            )
            return trace_id

    def _legacy_trace_id(self, notebook: Notebook) -> str | None:
        """Find the richest pre-persistence trace for one Notebook.

        v1.8.1 initially created a new trace per HTTP request. On first read
        after this repair, adopt the existing trace with the most matching
        events so a user's prior planning evidence is not discarded. Future
        requests use the persisted state above and never rescan this directory.
        """

        events = AgentEventStream(self.project_root, create=False)
        candidates: list[tuple[int, int, str]] = []
        if not events.events_dir.is_dir():
            return None
        for path in events.events_dir.glob("trace_*.jsonl"):
            trace_id = path.stem
            matching = [
                event
                for event in events.replay(trace_id)
                if event.payload.get("scope", {}).get("notebook_id") == notebook.notebook_id
                and event.payload.get("scope", {}).get("run_family_id")
                == notebook.run_family_id
            ]
            if matching:
                candidates.append((len(matching), matching[-1].seq, trace_id))
        if not candidates:
            return None
        return max(candidates)[2]

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

    # -- immutable notebook projection records -----------------------

    def _notebook_records(self, notebook_id: str) -> list[dict[str, Any]]:
        records = read_jsonl(self._notebook_path(notebook_id))
        if not records:
            raise NotebookNotFound(
                f"unknown notebook: {notebook_id}", notebook_id=notebook_id
            )
        return records

    def _evidence_packs(self, notebook_id: str) -> dict[str, dict[str, Any]]:
        packs: dict[str, dict[str, Any]] = {}
        for record in self._notebook_records(notebook_id):
            if record.get("record_type") != RECORD_EVIDENCE_PACK:
                continue
            value = record.get("evidence_pack")
            if not isinstance(value, Mapping):
                raise ValueError("evidence pack record is malformed")
            pack = _validate_evidence_pack(value)
            evidence_pack_hash = str(pack["evidence_pack_hash"])
            existing = packs.get(evidence_pack_hash)
            if existing is not None and existing != pack:
                raise ValueError(
                    f"conflicting evidence pack for hash {evidence_pack_hash}"
                )
            packs[evidence_pack_hash] = pack
        return packs

    def append_evidence_pack(self, notebook_id: str, pack: Mapping[str, Any]) -> None:
        """Append one content-addressed evidence pack, or accept its exact replay."""

        canonical = _validate_evidence_pack(pack)
        evidence_pack_hash = str(canonical["evidence_pack_hash"])
        with self._lock:
            existing = self._evidence_packs(notebook_id).get(evidence_pack_hash)
            if existing is not None:
                if existing != canonical:
                    raise ValueError(
                        f"conflicting evidence pack for hash {evidence_pack_hash}"
                    )
                return
            append_jsonl_atomic(
                self._notebook_path(notebook_id),
                {
                    "record_type": RECORD_EVIDENCE_PACK,
                    "recorded_at": _now(),
                    "evidence_pack": canonical,
                },
            )

    def read_evidence_pack(
        self, notebook_id: str, evidence_pack_hash: str
    ) -> dict[str, Any] | None:
        with self._lock:
            pack = self._evidence_packs(notebook_id).get(evidence_pack_hash)
            return dict(pack) if pack is not None else None

    def list_evidence_pack_hashes(self, notebook_id: str) -> list[str]:
        """Return persisted pack identities in deterministic order."""

        with self._lock:
            return sorted(self._evidence_packs(notebook_id))

    def _decisions(
        self, notebook_id: str
    ) -> dict[str, RecommendationDecision | RecommendationDecisionV11]:
        decisions: dict[str, RecommendationDecision | RecommendationDecisionV11] = {}
        for record in self._notebook_records(notebook_id):
            if record.get("record_type") != RECORD_RECOMMENDATION_DECISION:
                continue
            value = record.get("decision")
            if not isinstance(value, Mapping):
                raise ValueError("recommendation decision record is malformed")
            decision = (
                RecommendationDecisionV11.from_dict(value)
                if value.get("contract_version")
                == RECOMMENDATION_DECISION_V11_CONTRACT_VERSION
                else RecommendationDecision.from_dict(value)
            )
            existing = decisions.get(decision.batch_id)
            if existing is not None and existing != decision:
                raise ValueError(
                    f"conflicting recommendation decision for batch {decision.batch_id}"
                )
            decisions[decision.batch_id] = decision
        return decisions

    def append_decision(
        self,
        notebook_id: str,
        decision: RecommendationDecision | RecommendationDecisionV11,
    ) -> None:
        if not isinstance(decision, (RecommendationDecision, RecommendationDecisionV11)):
            raise ValueError("decision must be a RecommendationDecision")
        with self._lock:
            if isinstance(decision, RecommendationDecisionV11):
                try:
                    self._server_decision_registry(notebook_id).validate_recommendation(
                        decision
                    )
                except (ValueError, KeyError, TypeError) as error:
                    raise ValueError(
                        "recommendation decision is not backed by a persisted server decision"
                    ) from error
            existing = self._decisions(notebook_id).get(decision.batch_id)
            if existing is not None:
                if existing != decision:
                    raise ValueError(
                        f"conflicting recommendation decision for batch {decision.batch_id}"
                    )
                return
            append_jsonl_atomic(
                self._notebook_path(notebook_id),
                {
                    "record_type": RECORD_RECOMMENDATION_DECISION,
                    "recorded_at": _now(),
                    "decision": decision.to_dict(),
                },
            )

    def read_decision(
        self, notebook_id: str, batch_id: str
    ) -> RecommendationDecision | RecommendationDecisionV11 | None:
        with self._lock:
            return self._decisions(notebook_id).get(batch_id)

    def _server_decision_registry(self, notebook_id: str) -> ServerDecisionRegistry:
        registry = ServerDecisionRegistry()
        for record in self._notebook_records(notebook_id):
            record_type = record.get("record_type")
            if record_type not in {
                RECORD_FEASIBILITY_DECISION,
                RECORD_COMPARISON_DECISION,
            }:
                continue
            value = record.get("decision")
            if not isinstance(value, Mapping):
                raise ValueError("server decision record is malformed")
            if record_type == RECORD_FEASIBILITY_DECISION:
                registry.register_feasibility(FeasibilityDecision.from_dict(value))
            else:
                registry.register_comparison(ComparisonDecisionRecord.from_dict(value))
        return registry

    def append_server_decision(
        self,
        notebook_id: str,
        decision: FeasibilityDecision | ComparisonDecisionRecord,
    ) -> None:
        """Persist one server-owned source decision exactly once.

        This method never accepts an Agent recommendation or a free-form
        payload. The decision contract is parsed again when the registry is
        reconstructed after a process restart.
        """

        if not isinstance(decision, (FeasibilityDecision, ComparisonDecisionRecord)):
            raise ValueError("server decision must be a supported contract")
        record_type = (
            RECORD_FEASIBILITY_DECISION
            if isinstance(decision, FeasibilityDecision)
            else RECORD_COMPARISON_DECISION
        )
        decision_ref = (
            decision.feasibility_decision_id
            if isinstance(decision, FeasibilityDecision)
            else decision.comparison_decision_id
        )
        with self._lock:
            registry = self._server_decision_registry(notebook_id)
            existing = registry.get(decision_ref)
            if existing is not None:
                if existing != decision:
                    raise ValueError(
                        f"conflicting server decision for reference {decision_ref}"
                    )
                return
            if isinstance(decision, FeasibilityDecision):
                registry.register_feasibility(decision)
            else:
                registry.register_comparison(decision)
            append_jsonl_atomic(
                self._notebook_path(notebook_id),
                {
                    "record_type": record_type,
                    "recorded_at": _now(),
                    "decision": decision.to_dict(),
                },
            )

    def read_server_decision_registry(self, notebook_id: str) -> ServerDecisionRegistry:
        """Rebuild the trusted source registry from append-only Notebook records."""

        with self._lock:
            return self._server_decision_registry(notebook_id)

    def _materializations(
        self, notebook_id: str
    ) -> dict[tuple[str, int], OptionMaterialization]:
        materializations: dict[tuple[str, int], OptionMaterialization] = {}
        for record in self._notebook_records(notebook_id):
            if record.get("record_type") != RECORD_OPTION_MATERIALIZATION:
                continue
            value = record.get("materialization")
            if not isinstance(value, Mapping):
                raise ValueError("option materialization record is malformed")
            materialization = OptionMaterialization.from_dict(value)
            self._validate_persisted_materialization(notebook_id, materialization)
            key = (materialization.option_id, materialization.option_revision)
            existing = materializations.get(key)
            if existing is not None and existing != materialization:
                raise ValueError(
                    "conflicting option materialization for "
                    f"{materialization.option_id}@{materialization.option_revision}"
                )
            materializations[key] = materialization
        return materializations

    def _materialization_revision(
        self, notebook_id: str, materialization: OptionMaterialization
    ) -> tuple[Notebook, OptionView, NotebookOptionRevision]:
        """Resolve immutable materialization pins against persisted Notebook state."""

        notebook = self.get_notebook(notebook_id)
        if materialization.run_family_id != notebook.run_family_id:
            raise ValueError("materialization run_family_id does not match Notebook")

        view = self.read_option(notebook_id, materialization.option_id)
        revision = next(
            (
                candidate
                for candidate in view.revisions
                if candidate.option_revision == materialization.option_revision
            ),
            None,
        )
        if revision is None:
            raise ValueError("materialization option_revision does not exist")
        if not revision.materializable:
            raise OptionLegacyUnverified(
                f"option {materialization.option_id} revision "
                f"{materialization.option_revision} is legacy and cannot be materialized",
                option_id=materialization.option_id,
                option_revision=materialization.option_revision,
                contract_version=revision.contract_version,
            )

        pins = {
            "proposal_id": revision.typed_proposal_id,
            "proposal_revision": revision.typed_proposal_revision,
            "freshness_dependency_fingerprint": revision.freshness_dependency_fingerprint,
            "generation_context_id": revision.generation_context_id,
        }
        for field, expected in pins.items():
            if getattr(materialization, field) != expected:
                raise ValueError(f"materialization {field} does not match option revision")
        return notebook, view, revision

    def _validate_persisted_materialization(
        self, notebook_id: str, materialization: OptionMaterialization
    ) -> None:
        """Fail closed on malformed, conflicting, or foreign persisted records."""

        self._materialization_revision(notebook_id, materialization)

    def _validate_new_materialization(
        self, notebook_id: str, materialization: OptionMaterialization
    ) -> None:
        _, view, revision = self._materialization_revision(notebook_id, materialization)
        if view.current_revision.option_revision != revision.option_revision:
            raise ValueError("materialization option_revision is not current")
        if view.lifecycle_status != "selected":
            raise ValueError("materialization requires a selected option")

    def append_materialization(
        self, notebook_id: str, materialization: OptionMaterialization
    ) -> None:
        if not isinstance(materialization, OptionMaterialization):
            raise ValueError("materialization must be an OptionMaterialization")
        key = (materialization.option_id, materialization.option_revision)
        with self._lock:
            existing = self._materializations(notebook_id).get(key)
            if existing is not None:
                if existing != materialization:
                    raise ValueError(
                        "conflicting option materialization for "
                        f"{materialization.option_id}@{materialization.option_revision}"
                    )
                return
            self._validate_new_materialization(notebook_id, materialization)
            append_jsonl_atomic(
                self._notebook_path(notebook_id),
                {
                    "record_type": RECORD_OPTION_MATERIALIZATION,
                    "recorded_at": _now(),
                    "materialization": materialization.to_dict(),
                },
            )

    def read_materialization(
        self, notebook_id: str, option_id: str, option_revision: int
    ) -> OptionMaterialization | None:
        with self._lock:
            return self._materializations(notebook_id).get((option_id, option_revision))

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
    "ProjectionSource",
    "RECORD_EXECUTION",
    "RECORD_EXECUTION_RESULT",
    "RECORD_LIFECYCLE",
    "RECORD_OPTION",
    "RECORD_REVISION",
    "StoredRevision",
    "WorkflowSource",
    "dataset_workflow_source_pin",
    "reserve_dataset_upload_workflow_source",
]
