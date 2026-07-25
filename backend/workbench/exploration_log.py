"""Append-only, bounded logs for multi-step statistical exploration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

class ExplorationLogValidationError(ValueError):
    """Raised when a workflow log event is not bounded or well-formed."""


_REQUIRED_FIELDS = frozenset(
    {
        "event_id",
        "workflow_id",
        "workflow_step_id",
        "operation_id",
        "spec_fingerprint",
        "source_artifact_ids",
        "dependency_artifact_ids",
        "row_counts",
        "status",
        "error",
    }
)
_OPTIONAL_FIELDS = frozenset(
    {"occurred_at", "phase", "artifact_ids", "dependency_fingerprints"}
)
_FORBIDDEN_FIELDS = frozenset({"raw_rows", "full_artifact", "full_artifacts", "dataset"})
_STATUSES = frozenset({"planned", "running", "completed", "failed", "blocked"})


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ExplorationLogValidationError(
        f"event contains unsupported value type: {type(value).__name__}"
    )


class ExplorationLog:
    """Persist compact workflow events under a project-local workbench path."""

    def __init__(self, project_root: Path | str, *, workflow_id: str) -> None:
        if not isinstance(workflow_id, str) or not workflow_id.strip():
            raise ExplorationLogValidationError("workflow_id must be non-empty")
        self.project_root = Path(project_root).expanduser().resolve()
        self.workflow_id = workflow_id
        self.path = self.project_root / "workbench" / "exploration" / f"{workflow_id}.jsonl"

    def append_event(self, event: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(event, Mapping):
            raise ExplorationLogValidationError("event must be an object")
        forbidden = _FORBIDDEN_FIELDS.intersection(event)
        if forbidden:
            raise ExplorationLogValidationError(
                "event contains forbidden field(s): " + ", ".join(sorted(forbidden))
            )
        missing = _REQUIRED_FIELDS.difference(event)
        if missing:
            raise ExplorationLogValidationError(
                "event missing field(s): " + ", ".join(sorted(missing))
            )
        unknown = set(event).difference(_REQUIRED_FIELDS | _OPTIONAL_FIELDS)
        if unknown:
            raise ExplorationLogValidationError(
                "event contains unknown field(s): " + ", ".join(sorted(unknown))
            )
        normalized = _canonical(dict(event))
        if normalized["workflow_id"] != self.workflow_id:
            raise ExplorationLogValidationError(
                "event workflow_id does not match the log workflow_id"
            )
        if not isinstance(normalized["event_id"], str) or not normalized["event_id"]:
            raise ExplorationLogValidationError("event_id must be non-empty")
        if normalized["status"] not in _STATUSES:
            raise ExplorationLogValidationError(
                f"event status is unsupported: {normalized['status']}"
            )
        for field in ("source_artifact_ids", "dependency_artifact_ids"):
            if not isinstance(normalized[field], list) or not all(
                isinstance(item, str) and item for item in normalized[field]
            ):
                raise ExplorationLogValidationError(f"{field} must be a list of artifact ids")
        if "dependency_fingerprints" in normalized and (
            not isinstance(normalized["dependency_fingerprints"], list)
            or not all(
                isinstance(item, str) and item
                for item in normalized["dependency_fingerprints"]
            )
        ):
            raise ExplorationLogValidationError(
                "dependency_fingerprints must be a list of non-empty strings"
            )
        if not isinstance(normalized["row_counts"], Mapping):
            raise ExplorationLogValidationError("row_counts must be an object")
        if normalized["error"] is not None and not isinstance(normalized["error"], str):
            raise ExplorationLogValidationError("error must be a string or null")
        # Import lazily: importing ``workbench.agent`` initializes the
        # orchestrator, which imports the workflow module that owns this log.
        # Keeping the storage dependency lazy makes this module independently
        # readable for report/export tooling and unit tests.
        from .agent.storage import append_jsonl_atomic

        append_jsonl_atomic(self.path, normalized)
        return normalized

    def read_events(self) -> list[dict[str, Any]]:
        from .agent.storage import read_jsonl

        return read_jsonl(self.path)

    @staticmethod
    def fingerprint_event(event: Mapping[str, Any]) -> str:
        canonical = json.dumps(
            _canonical(dict(event)), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
