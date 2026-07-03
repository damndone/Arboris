from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, Field

DRAFT_SCHEMA_VERSION = "pipeline_draft.v1"
EXECUTED_DRAFT_FILENAME = "executed_pipeline_draft.json"

_DRAFT_ID_RE = re.compile(r"^draft_[A-Za-z0-9_-]{6,64}$")


class PipelineDraftError(ValueError):
    code = "PIPELINE_DRAFT_ERROR"


class DraftNotFound(PipelineDraftError):
    code = "DRAFT_NOT_FOUND"


class DraftHashConflict(PipelineDraftError):
    code = "DRAFT_HASH_CONFLICT"


class DraftPathError(PipelineDraftError):
    code = "INVALID_DRAFT_ID"


class DraftLockedForExecution(PipelineDraftError):
    code = "DRAFT_LOCKED_FOR_EXECUTION"


class DraftNodeNotFound(PipelineDraftError):
    code = "DRAFT_NODE_NOT_FOUND"


class DraftNodePatchConflict(PipelineDraftError):
    code = "DRAFT_NODE_PATCH_CONFLICT"


class DraftValidationFailure(PipelineDraftError):
    code = "DRAFT_PARAM_VALIDATION_FAILED"


class InputDatasetNode(BaseModel):
    node_id: str
    node_type: Literal["input.dataset"]
    source_type: Literal["run_input", "upload"]
    run_input_id: str | None = None
    upload_sha: str | None = None
    dataset_snapshot_id: str | None = None
    schema_fingerprint: str
    input_fingerprint: str
    row_count: int | None = None
    column_count: int | None = None
    columns_summary: list[dict[str, Any]] = Field(default_factory=list)
    status: Literal["bound", "missing", "invalid"] = "bound"


class SourceRef(BaseModel):
    source_run_id: str
    source_model_node_id: str
    source_op_node_id: str
    source_node_hash: str
    source_context_fingerprint: str


class ModelDraftNode(BaseModel):
    node_id: str
    node_type: Literal["model"]
    model_family: str
    model_type: str
    schema_id: str
    editable_schema: list[dict[str, Any]]
    editable_schema_hash: str
    source_ref: SourceRef
    source_params: dict[str, Any]
    params: dict[str, Any]


class CreatedFrom(BaseModel):
    source_type: Literal["run"]
    source_run_id: str
    source_model_node_id: str
    source_op_node_id: str
    source_node_hash: str
    source_context_fingerprint: str
    source_input_fingerprint: str


class GenesisCreatedFrom(BaseModel):
    """v1.6.8: parentless draft born from a standalone upload (no source run)."""

    source_type: Literal["genesis"]
    source_input_fingerprint: str


class PipelineDraftV1(BaseModel):
    draft_id: str
    schema_version: Literal["pipeline_draft.v1"]
    created_at: str
    updated_at: str
    status: str = "draft"
    created_from: (
        Annotated[CreatedFrom | GenesisCreatedFrom, Field(discriminator="source_type")] | None
    ) = None
    graph: dict[str, Any]
    default_execution_mode: Literal["rerun_child", "new_run", "genesis"] = "rerun_child"


@dataclass(frozen=True)
class StoredDraft:
    draft: dict[str, Any]
    draft_hash: str


@dataclass(frozen=True)
class DedupeRecord:
    run_id: str
    executed_draft_hash: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_draft_id() -> str:
    return f"draft_{uuid.uuid4().hex}"


def validate_draft_id(draft_id: str) -> None:
    if not _DRAFT_ID_RE.match(draft_id):
        raise DraftPathError(f"Invalid draft_id: {draft_id!r}")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def executable_payload(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": draft.get("schema_version"),
        "created_from": draft.get("created_from"),
        "graph": draft.get("graph"),
        "default_execution_mode": draft.get("default_execution_mode"),
    }


def compute_executable_draft_hash(draft: dict[str, Any]) -> str:
    payload = canonical_json(executable_payload(draft)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def schema_hash(editable_schema: list[dict[str, Any]]) -> str:
    payload = canonical_json(editable_schema).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class PipelineDraftStore:
    _shared_locks: ClassVar[dict[tuple[str, str], threading.Lock]] = {}
    _shared_locks_guard: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, project_root: Path):
        self.root = project_root
        self.drafts_dir = project_root / "data" / "pipeline_drafts"
        self._lock_root = str(project_root.resolve())

    def _path(self, draft_id: str) -> Path:
        validate_draft_id(draft_id)
        return self.drafts_dir / f"{draft_id}.json"

    def _lock_for(self, draft_id: str) -> threading.Lock:
        validate_draft_id(draft_id)
        key = (self._lock_root, draft_id)
        with self._shared_locks_guard:
            return self._shared_locks.setdefault(key, threading.Lock())

    def _write_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, sort_keys=True, indent=2, ensure_ascii=False)
                fh.write("\n")
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def create(self, draft: dict[str, Any]) -> StoredDraft:
        PipelineDraftV1(**draft)
        path = self._path(str(draft["draft_id"]))
        if path.exists():
            raise DraftHashConflict("draft already exists")
        self._write_atomic(path, draft)
        return StoredDraft(draft=draft, draft_hash=compute_executable_draft_hash(draft))

    def get(self, draft_id: str) -> StoredDraft:
        path = self._path(draft_id)
        if not path.is_file():
            raise DraftNotFound(draft_id)
        draft = json.loads(path.read_text(encoding="utf-8"))
        PipelineDraftV1(**draft)
        return StoredDraft(draft=draft, draft_hash=compute_executable_draft_hash(draft))

    def list(self) -> list[dict[str, Any]]:
        """Summaries of every draft json in the store dir (for reload hydrate).

        Skips unreadable / schema-invalid files rather than raising, so one
        corrupt draft never breaks the whole forest.
        """
        if not self.drafts_dir.is_dir():
            return []
        summaries: list[dict[str, Any]] = []
        for path in sorted(self.drafts_dir.glob("*.json")):
            if path.name.endswith(".execution.json"):
                continue
            try:
                draft = json.loads(path.read_text(encoding="utf-8"))
                PipelineDraftV1(**draft)
            except Exception:
                continue
            created_from = draft.get("created_from") or {}
            model_node = next(
                (n for n in draft["graph"]["nodes"] if n.get("node_type") == "model"),
                None,
            )
            summaries.append(
                {
                    "draft_id": draft["draft_id"],
                    "status": draft.get("status", "draft"),
                    "model_type": (model_node or {}).get("model_type"),
                    "source_run_id": created_from.get("source_run_id"),
                    "source_model_node_id": created_from.get("source_model_node_id"),
                    "source_op_node_id": created_from.get("source_op_node_id"),
                    "source_node_hash": created_from.get("source_node_hash"),
                    "draft_hash": compute_executable_draft_hash(draft),
                    "updated_at": draft.get("updated_at"),
                }
            )
        return summaries

    def delete(self, draft_id: str) -> None:
        """Delete a draft json plus its execution/dedupe sidecar files.

        Idempotent: deleting a non-existent draft is a no-op (safe under
        concurrent discard). draft_id is validated to stay inside the store dir.
        """
        validate_draft_id(draft_id)
        lock = self._lock_for(draft_id)
        with lock:
            path = self._path(draft_id)
            if path.exists():
                path.unlink()
            for sidecar in self.drafts_dir.glob(f"{draft_id}.*.execution.json"):
                try:
                    sidecar.unlink()
                except OSError:
                    pass

    def update_params(
        self,
        draft_id: str,
        *,
        model_node_id: str,
        base_draft_hash: str,
        params: dict[str, Any],
    ) -> StoredDraft:
        lock = self._lock_for(draft_id)
        if not lock.acquire(blocking=False):
            raise DraftLockedForExecution("draft is locked for execution")
        try:
            stored = self.get(draft_id)
            if stored.draft_hash != base_draft_hash:
                raise DraftHashConflict("base_draft_hash does not match current draft")
            draft = stored.draft
            model_node = next(
                (
                    node
                    for node in draft["graph"]["nodes"]
                    if node.get("node_type") == "model" and node.get("node_id") == model_node_id
                ),
                None,
            )
            if model_node is None:
                raise ValueError("MISSING_MODEL_NODE")
            model_node["params"] = params
            param_checks = _validate_params(model_node)
            if param_checks:
                codes = ", ".join(item["code"] for item in param_checks)
                raise DraftValidationFailure(codes)
            draft["updated_at"] = utc_now()
            PipelineDraftV1(**draft)
            self._write_atomic(self._path(draft_id), draft)
            return StoredDraft(draft=draft, draft_hash=compute_executable_draft_hash(draft))
        finally:
            lock.release()

    # node_types the genesis wizard may edit; the bound source is immutable
    # (changing the file = discard the draft and restart genesis).
    _PATCHABLE: ClassVar[frozenset[str]] = frozenset({"table", "model"})

    def update_node_params(
        self,
        draft_id: str,
        node_id: str,
        params: dict[str, Any],
        *,
        columns: list[str] | None = None,
    ) -> StoredDraft:
        """v1.6.8 genesis wizard step: merge params into one chain node.

        Genesis-only by design — from-node drafts keep using update_params
        (hash-guarded model-node edits).
        """
        lock = self._lock_for(draft_id)
        if not lock.acquire(blocking=False):
            raise DraftLockedForExecution("draft is locked for execution")
        try:
            stored = self.get(draft_id)
            draft = stored.draft
            if (draft.get("created_from") or {}).get("source_type") != "genesis":
                raise DraftNodePatchConflict("NODE_PATCH_GENESIS_ONLY")
            node = next(
                (n for n in draft["graph"]["nodes"] if n.get("node_id") == node_id),
                None,
            )
            if node is None:
                raise DraftNodeNotFound(f"node {node_id}")
            if node.get("node_type") not in self._PATCHABLE:
                raise DraftNodePatchConflict("NODE_NOT_PATCHABLE")
            node["params"] = {**node.get("params", {}), **params}
            if columns is not None and node["node_type"] == "table":
                node["columns"] = columns
            node["status"] = "configured"
            draft["updated_at"] = utc_now()
            draft["status"] = "draft"  # any edit returns to draft state; must re-validate
            PipelineDraftV1(**draft)
            self._write_atomic(self._path(draft_id), draft)
            return StoredDraft(draft=draft, draft_hash=compute_executable_draft_hash(draft))
        finally:
            lock.release()

    def execution_lock(self, draft_id: str) -> threading.Lock:
        return self._lock_for(draft_id)

    def dedupe_path(self, draft_id: str, key: str) -> Path:
        validate_draft_id(draft_id)
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.drafts_dir / f"{draft_id}.{digest}.execution.json"

    def get_dedupe(self, draft_id: str, key: str) -> DedupeRecord | None:
        path = self.dedupe_path(draft_id, key)
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return DedupeRecord(
            run_id=payload["run_id"],
            executed_draft_hash=payload["executed_draft_hash"],
        )

    def record_dedupe(
        self,
        draft_id: str,
        key: str,
        *,
        run_id: str,
        executed_draft_hash: str,
    ) -> None:
        self._write_atomic(
            self.dedupe_path(draft_id, key),
            {"run_id": run_id, "executed_draft_hash": executed_draft_hash},
        )


def check(
    code: str,
    message: str,
    *,
    node_id: str | None = None,
    level: str = "error",
    blocking: bool = True,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "code": code,
        "level": level,
        "message": message,
        "blocking": blocking,
    }
    if node_id is not None:
        out["node_id"] = node_id
    return out


def _nodes_by_type(draft: dict[str, Any], node_type: str) -> list[dict[str, Any]]:
    return [
        node
        for node in draft.get("graph", {}).get("nodes", [])
        if node.get("node_type") == node_type
    ]


_GENESIS_CHAIN = ["input.upload", "table", "model"]


def _validate_genesis_shape(draft: dict[str, Any]) -> list[dict[str, Any]]:
    """v1.6.8 genesis drafts are a fixed parentless chain source -> table -> model.

    Structural only: column/param checks belong to validate-for-execution /
    execute (spec F3/F4), not to the graph shape.
    """
    checks: list[dict[str, Any]] = []
    nodes = draft.get("graph", {}).get("nodes", [])
    types = [node.get("node_type") for node in nodes]
    if types != _GENESIS_CHAIN:
        checks.append(
            check(
                "GENESIS_CHAIN_SHAPE",
                f"Genesis chain must be {_GENESIS_CHAIN}, got {types}.",
            )
        )
        return checks
    node_ids = [node.get("node_id") for node in nodes]
    if len(set(node_ids)) != len(node_ids):
        checks.append(
            check(
                "GENESIS_CHAIN_SHAPE",
                f"Genesis chain node_ids must be distinct, got {node_ids}.",
            )
        )
        return checks
    edges = draft.get("graph", {}).get("edges", [])
    want = [
        {"from": nodes[0].get("node_id"), "to": nodes[1].get("node_id")},
        {"from": nodes[1].get("node_id"), "to": nodes[2].get("node_id")},
    ]
    if edges != want:
        checks.append(
            check(
                "GENESIS_CHAIN_EDGES",
                "Genesis edges must chain source -> table -> model.",
            )
        )
    return checks


def _validate_graph_shape(draft: dict[str, Any]) -> list[dict[str, Any]]:
    if (draft.get("created_from") or {}).get("source_type") == "genesis":
        return _validate_genesis_shape(draft)
    checks: list[dict[str, Any]] = []
    inputs = _nodes_by_type(draft, "input.dataset")
    models = _nodes_by_type(draft, "model")
    edges = draft.get("graph", {}).get("edges", [])

    if len(inputs) != 1:
        checks.append(check("MISSING_INPUT_NODE", "Draft must contain exactly one input.dataset node."))
    if len(models) != 1:
        checks.append(check("MISSING_MODEL_NODE", "Draft must contain exactly one model node."))

    if (
        len(edges) != 1
        or len(inputs) != 1
        or len(models) != 1
        or edges[0].get("from") != inputs[0].get("node_id")
        or edges[0].get("to") != models[0].get("node_id")
    ):
        checks.append(check("INVALID_DRAFT_GRAPH_SHAPE", "v1.6.4 supports only InputNode -> ModelNode."))

    for node in draft.get("graph", {}).get("nodes", []):
        if node.get("node_type") not in {"input.dataset", "model"}:
            checks.append(
                check(
                    "UNKNOWN_DRAFT_NODE_TYPE",
                    f"Unsupported draft node_type {node.get('node_type')!r}.",
                    node_id=node.get("node_id"),
                )
            )
    return checks


def _editable_controls(model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["key"]): item
        for item in model.get("editable_schema", [])
        if item.get("key")
    }


def _option_values(options: Any) -> set[Any]:
    if not isinstance(options, list):
        return set()
    return {
        option.get("value") if isinstance(option, dict) else option
        for option in options
    }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_control_value(
    key: str,
    value: Any,
    control: dict[str, Any],
    *,
    node_id: str | None,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    kind = control.get("kind")
    options = _option_values(control.get("options"))

    if kind in {"columns", "multiselect"}:
        if not isinstance(value, list):
            return [
                check(
                    "INVALID_PARAM_TYPE",
                    f"Param {key!r} must be a list.",
                    node_id=node_id,
                )
            ]
        if options:
            invalid = [item for item in value if item not in options]
            if invalid:
                checks.append(
                    check(
                        "INVALID_PARAM_OPTION",
                        f"Param {key!r} contains values outside editable_schema options.",
                        node_id=node_id,
                    )
                )
        return checks

    if kind == "toggle":
        if not isinstance(value, bool):
            checks.append(
                check(
                    "INVALID_PARAM_TYPE",
                    f"Param {key!r} must be a boolean.",
                    node_id=node_id,
                )
            )
        return checks

    if kind == "slider":
        if not _is_number(value):
            return [
                check(
                    "INVALID_PARAM_TYPE",
                    f"Param {key!r} must be a number.",
                    node_id=node_id,
                )
            ]
        minimum = control.get("min")
        maximum = control.get("max")
        if _is_number(minimum) and value < minimum:
            checks.append(check("PARAM_BELOW_MIN", f"Param {key!r} is below min.", node_id=node_id))
        if _is_number(maximum) and value > maximum:
            checks.append(check("PARAM_ABOVE_MAX", f"Param {key!r} is above max.", node_id=node_id))

    if kind in {"select", "radio"} and isinstance(value, (dict, list)):
        checks.append(
            check(
                "INVALID_PARAM_TYPE",
                f"Param {key!r} must be a scalar option value.",
                node_id=node_id,
            )
        )

    if options and value not in options:
        checks.append(
            check(
                "INVALID_PARAM_OPTION",
                f"Param {key!r} is outside editable_schema options.",
                node_id=node_id,
            )
        )
    return checks


def _validate_params(model: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    controls = _editable_controls(model)
    allowed = set(controls)
    expected_schema_hash = schema_hash(model.get("editable_schema", []))
    if model.get("editable_schema_hash") != expected_schema_hash:
        checks.append(
            check(
                "EDITABLE_SCHEMA_HASH_MISMATCH",
                "editable_schema_hash must match editable_schema.",
                node_id=model.get("node_id"),
            )
        )
    for key in model.get("params", {}):
        if key not in allowed:
            checks.append(
                check(
                    "NON_EDITABLE_PARAM",
                    f"Param {key!r} is not declared in editable_schema.",
                    node_id=model.get("node_id"),
                )
            )
            continue
        checks.extend(
            _validate_control_value(
                key,
                model.get("params", {}).get(key),
                controls[key],
                node_id=model.get("node_id"),
            )
        )
    for key in allowed:
        if key not in model.get("params", {}):
            checks.append(
                check(
                    "MISSING_EDITABLE_PARAM",
                    f"Param {key!r} is required by editable_schema.",
                    node_id=model.get("node_id"),
                )
            )
    return checks


def _validate_created_from_source_ref(draft: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    created_from = draft.get("created_from")
    models = _nodes_by_type(draft, "model")
    if not created_from or len(models) != 1:
        return checks

    model = models[0]
    source_ref = model.get("source_ref") or {}
    fields = [
        "source_run_id",
        "source_model_node_id",
        "source_op_node_id",
        "source_node_hash",
        "source_context_fingerprint",
    ]
    if any(source_ref.get(field) != created_from.get(field) for field in fields):
        checks.append(
            check(
                "MODEL_SOURCE_REF_MISMATCH",
                "Model source_ref must match PipelineDraft.created_from.",
                node_id=model.get("node_id"),
            )
        )
    return checks


def _resolved_execution(
    draft: dict[str, Any],
    execution_mode: str,
    *,
    compare_source_available: bool,
) -> dict[str, Any]:
    created_from = draft.get("created_from") or {}
    out: dict[str, Any] = {
        "execution_mode": execution_mode,
        "compare_source_available": compare_source_available,
    }
    if created_from:
        out.update(
            {
                "rerun_from_run_id": created_from.get("source_run_id"),
                "rerun_from_model_node_id": created_from.get("source_model_node_id"),
                "rerun_from_op_node_id": created_from.get("source_op_node_id"),
            }
        )
    return out


def validate_draft_for_execution(
    draft: dict[str, Any],
    *,
    execution_mode: Literal["rerun_child", "new_run"] | None = None,
) -> dict[str, Any]:
    mode = execution_mode or draft.get("default_execution_mode", "rerun_child")
    checks: list[dict[str, Any]] = []

    try:
        PipelineDraftV1(**draft)
    except Exception as exc:
        checks.append(check("INVALID_PIPELINE_DRAFT", str(exc)))

    if mode == "new_run":
        checks.append(
            check(
                "NEW_RUN_EXECUTION_NOT_ENABLED",
                "new_run execution is reserved but disabled in v1.6.4.",
            )
        )
    elif mode != "rerun_child":
        checks.append(check("INVALID_EXECUTION_MODE", f"Unsupported execution_mode {mode!r}."))

    checks.extend(_validate_graph_shape(draft))
    checks.extend(_validate_created_from_source_ref(draft))

    models = _nodes_by_type(draft, "model")
    if len(models) == 1:
        checks.extend(_validate_params(models[0]))

    created_from = draft.get("created_from")
    if mode == "rerun_child" and not created_from:
        checks.append(
            check(
                "CREATED_FROM_REQUIRED_FOR_RERUN_CHILD",
                "rerun_child execution requires PipelineDraft.created_from.",
            )
        )

    inputs = _nodes_by_type(draft, "input.dataset")
    compare_source_available = bool(mode == "rerun_child" and created_from and len(inputs) == 1)
    if mode == "rerun_child" and created_from and len(inputs) == 1:
        input_node = inputs[0]
        if input_node.get("source_type") != "run_input":
            checks.append(
                check(
                    "INPUT_BINDING_NOT_SUPPORTED",
                    "v1.6.4 rerun_child execution supports only run_input bindings.",
                    node_id=input_node.get("node_id"),
                )
            )
        if input_node.get("input_fingerprint") != created_from.get("source_input_fingerprint"):
            checks.append(
                check(
                    "SOURCE_INPUT_FINGERPRINT_MISMATCH",
                    "InputNode fingerprint must match PipelineDraft.created_from.",
                    node_id=input_node.get("node_id"),
                )
            )

    blocking = [item for item in checks if item.get("blocking", True)]
    executable = not blocking and mode == "rerun_child"
    status = "valid" if executable else ("blocked" if any(c["code"] == "NEW_RUN_EXECUTION_NOT_ENABLED" for c in blocking) else "invalid")

    result: dict[str, Any] = {
        "ok": executable,
        "status": status,
        "executable": executable,
        "checks": checks,
        "resolved_execution": _resolved_execution(
            draft,
            str(mode),
            compare_source_available=compare_source_available,
        ),
        "validated_at": utc_now(),
    }
    if executable:
        result["validated_execution_mode"] = mode
        result["validated_draft_hash"] = compute_executable_draft_hash(draft)
    return result
