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
from typing import Any, Literal

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


class PipelineDraftV1(BaseModel):
    draft_id: str
    schema_version: Literal["pipeline_draft.v1"]
    created_at: str
    updated_at: str
    status: str = "draft"
    created_from: CreatedFrom | None = None
    graph: dict[str, Any]
    default_execution_mode: Literal["rerun_child", "new_run"] = "rerun_child"


@dataclass(frozen=True)
class StoredDraft:
    draft: dict[str, Any]
    draft_hash: str


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
    def __init__(self, project_root: Path):
        self.root = project_root
        self.drafts_dir = project_root / "data" / "pipeline_drafts"
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _path(self, draft_id: str) -> Path:
        validate_draft_id(draft_id)
        return self.drafts_dir / f"{draft_id}.json"

    def _lock_for(self, draft_id: str) -> threading.Lock:
        validate_draft_id(draft_id)
        with self._locks_guard:
            return self._locks.setdefault(draft_id, threading.Lock())

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

    def update_params(
        self,
        draft_id: str,
        *,
        model_node_id: str,
        base_draft_hash: str,
        params: dict[str, Any],
    ) -> StoredDraft:
        with self._lock_for(draft_id):
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
            draft["updated_at"] = utc_now()
            PipelineDraftV1(**draft)
            self._write_atomic(self._path(draft_id), draft)
            return StoredDraft(draft=draft, draft_hash=compute_executable_draft_hash(draft))

    def execution_lock(self, draft_id: str) -> threading.Lock:
        return self._lock_for(draft_id)
