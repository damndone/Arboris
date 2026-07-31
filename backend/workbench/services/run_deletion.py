"""Safe, explicit deletion of one completed leaf run.

This service owns the destructive boundary.  It never accepts a path from a
caller: a run id resolves through the project's ``runs/`` directory, and the
same immutable preview is recomputed immediately before deletion.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from ..artifacts import read_json
from ..lineage.family import scan_family
from ..repository.run_repository import _resolve_run_root


class RunDeletionConfirmationError(ValueError):
    """A destructive deletion request lacks a current, explicit confirmation."""


@dataclass(frozen=True)
class RunDeletionPreview:
    run_id: str
    deletable: bool
    blocking_descendant_run_ids: tuple[str, ...]
    blocking_status: str | None
    artifact_counts: dict[str, int]
    report_count: int
    agent_session_ids: tuple[str, ...]
    agent_event_session_ids: tuple[str, ...]
    proposal_ids: tuple[str, ...]
    operation_record_ids: tuple[str, ...]
    retained_shared_record_ids: tuple[str, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "deletable": self.deletable,
            "blocking_descendant_run_ids": list(self.blocking_descendant_run_ids),
            "blocking_status": self.blocking_status,
            "artifact_counts": dict(self.artifact_counts),
            "report_count": self.report_count,
            "agent_session_ids": list(self.agent_session_ids),
            "agent_event_session_ids": list(self.agent_event_session_ids),
            "proposal_ids": list(self.proposal_ids),
            "operation_record_ids": list(self.operation_record_ids),
            "retained_shared_record_ids": list(self.retained_shared_record_ids),
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class RunDeletionReceipt:
    run_id: str
    deleted_agent_session_ids: tuple[str, ...]
    deleted_agent_event_session_ids: tuple[str, ...]
    deleted_proposal_ids: tuple[str, ...]
    deleted_operation_record_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "deleted_agent_session_ids": list(self.deleted_agent_session_ids),
            "deleted_agent_event_session_ids": list(self.deleted_agent_event_session_ids),
            "deleted_proposal_ids": list(self.deleted_proposal_ids),
            "deleted_operation_record_ids": list(self.deleted_operation_record_ids),
        }


class RunDeletionService:
    """Preview and delete one terminal leaf run plus exclusively scoped history."""

    def __init__(self, project_root: Path | str) -> None:
        self.project_root = Path(project_root).resolve()
        self.runs_root = self.project_root / "runs"

    def preview(self, run_id: str) -> RunDeletionPreview:
        run_root = _resolve_run_root(str(self.project_root), run_id)
        manifest = read_json(run_root / "run_manifest.json")
        status = str(manifest.get("status") or "")
        family = scan_family(self.runs_root, run_id)
        descendants = tuple(family.descendants)
        blocking_status = status if status in {"running", "cancelling"} else None
        sessions = self._run_scoped_sessions(run_id)
        event_sessions = tuple(
            session_id
            for session_id in sessions
            if (self._agent_events_dir / f"{session_id}.jsonl").is_file()
        )
        artifact_counts = self._artifact_counts(run_root)
        report_count = self._report_count(run_root)
        proposal_ids, operation_record_ids, retained_shared_record_ids = (
            self._run_scoped_control_records(run_id)
        )
        deletable = not descendants and blocking_status is None
        fingerprint = self._fingerprint(
            run_id=run_id,
            run_root=run_root,
            descendants=descendants,
            blocking_status=blocking_status,
            artifact_counts=artifact_counts,
            report_count=report_count,
            session_ids=sessions,
            event_session_ids=event_sessions,
            proposal_ids=proposal_ids,
            operation_record_ids=operation_record_ids,
            retained_shared_record_ids=retained_shared_record_ids,
        )
        return RunDeletionPreview(
            run_id=run_id,
            deletable=deletable,
            blocking_descendant_run_ids=descendants,
            blocking_status=blocking_status,
            artifact_counts=artifact_counts,
            report_count=report_count,
            agent_session_ids=sessions,
            agent_event_session_ids=event_sessions,
            proposal_ids=proposal_ids,
            operation_record_ids=operation_record_ids,
            retained_shared_record_ids=retained_shared_record_ids,
            fingerprint=fingerprint,
        )

    def delete(
        self,
        run_id: str,
        *,
        expected_fingerprint: str,
        confirmation_run_id: str,
    ) -> RunDeletionReceipt:
        if confirmation_run_id != run_id:
            raise RunDeletionConfirmationError("confirmation run id does not match")
        preview = self.preview(run_id)
        if preview.fingerprint != expected_fingerprint:
            raise RunDeletionConfirmationError("deletion preview changed; review it again")
        if not preview.deletable:
            if preview.blocking_descendant_run_ids:
                raise RunDeletionConfirmationError("run has descendants and cannot be deleted")
            raise RunDeletionConfirmationError("run is active and cannot be deleted")

        run_root = _resolve_run_root(str(self.project_root), run_id)
        self._remove_run_tree(run_root)
        for session_id in preview.agent_session_ids:
            self._unlink_if_file(self._agent_sessions_dir / f"{session_id}.jsonl")
            self._unlink_if_file(self._agent_sessions_dir / f"{session_id}.meta.json")
        for session_id in preview.agent_event_session_ids:
            self._unlink_if_file(self._agent_events_dir / f"{session_id}.jsonl")
        for proposal_id in preview.proposal_ids:
            self._unlink_if_file(self._proposals_dir / f"{proposal_id}.jsonl")
        for record_id in preview.operation_record_ids:
            self._unlink_if_file(self._operation_records_dir / f"{record_id}.jsonl")
        return RunDeletionReceipt(
            run_id=run_id,
            deleted_agent_session_ids=preview.agent_session_ids,
            deleted_agent_event_session_ids=preview.agent_event_session_ids,
            deleted_proposal_ids=preview.proposal_ids,
            deleted_operation_record_ids=preview.operation_record_ids,
        )

    @property
    def _workbench_root(self) -> Path:
        return self.project_root / "workbench"

    @property
    def _agent_sessions_dir(self) -> Path:
        return self._workbench_root / "agent-sessions"

    @property
    def _agent_events_dir(self) -> Path:
        return self._workbench_root / "agent-events"

    @property
    def _proposals_dir(self) -> Path:
        return self._workbench_root / "proposals"

    @property
    def _operation_records_dir(self) -> Path:
        return self._workbench_root / "operation-records"

    def _run_scoped_sessions(self, run_id: str) -> tuple[str, ...]:
        direct: set[str] = set()
        parents: dict[str, str] = {}
        if not self._agent_sessions_dir.is_dir():
            return ()
        for metadata_path in sorted(self._agent_sessions_dir.glob("*.meta.json")):
            session_id = metadata_path.name.removesuffix(".meta.json")
            if not self._safe_identifier(session_id):
                continue
            metadata = self._read_json_or_none(metadata_path)
            parent = metadata.get("inherited_parent_ref") if isinstance(metadata, dict) else None
            if isinstance(parent, dict) and isinstance(parent.get("session_id"), str):
                parent_id = parent["session_id"]
                if self._safe_identifier(parent_id):
                    parents[session_id] = parent_id
            entries = self._read_json_lines(self._agent_sessions_dir / f"{session_id}.jsonl")
            if any(self._entry_targets_run(entry, run_id) for entry in entries):
                direct.add(session_id)

        scoped = set(direct)
        changed = True
        while changed:
            changed = False
            for session_id, parent_id in parents.items():
                if parent_id in scoped and session_id not in scoped:
                    scoped.add(session_id)
                    changed = True
        return tuple(sorted(scoped))

    def _run_scoped_control_records(
        self, run_id: str
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        proposal_ids, retained_proposals = self._exclusive_record_ids(
            self._proposals_dir, run_id
        )
        operation_record_ids, retained_operations = self._exclusive_record_ids(
            self._operation_records_dir, run_id
        )
        retained = tuple(
            sorted(
                [*(f"proposal:{item}" for item in retained_proposals),
                 *(f"operation_record:{item}" for item in retained_operations)]
            )
        )
        return proposal_ids, operation_record_ids, retained

    def _exclusive_record_ids(
        self, directory: Path, run_id: str
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        exclusive: list[str] = []
        retained_shared: list[str] = []
        if not directory.is_dir():
            return (), ()
        for path in sorted(directory.glob("*.jsonl")):
            record_id = path.stem
            if not self._safe_identifier(record_id):
                continue
            entries = self._read_json_lines_strict(path)
            if entries is None or not entries:
                continue
            targets_run = [self._record_entry_targets_run(entry, run_id) for entry in entries]
            if all(targets_run):
                exclusive.append(record_id)
            elif any(targets_run):
                retained_shared.append(record_id)
        return tuple(exclusive), tuple(retained_shared)

    @staticmethod
    def _entry_targets_run(entry: dict[str, Any], run_id: str) -> bool:
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            return False
        metadata = payload.get("metadata")
        return isinstance(metadata, dict) and metadata.get("run_id") == run_id

    @staticmethod
    def _record_entry_targets_run(entry: dict[str, Any], run_id: str) -> bool:
        target = entry.get("target")
        return isinstance(target, dict) and target.get("run_id") == run_id

    @staticmethod
    def _artifact_counts(run_root: Path) -> dict[str, int]:
        index = RunDeletionService._read_json_or_none(run_root / "artifacts_index.json")
        artifacts = index.get("artifacts", []) if isinstance(index, dict) else []
        counts = Counter(
            str(item.get("artifact_type") or "unknown")
            for item in artifacts
            if isinstance(item, dict)
        )
        return dict(sorted(counts.items()))

    @staticmethod
    def _report_count(run_root: Path) -> int:
        reports = run_root / "reports"
        if not reports.is_dir():
            return 0
        return sum(1 for path in reports.rglob("*") if path.is_file())

    def _fingerprint(
        self,
        *,
        run_id: str,
        run_root: Path,
        descendants: tuple[str, ...],
        blocking_status: str | None,
        artifact_counts: dict[str, int],
        report_count: int,
        session_ids: tuple[str, ...],
        event_session_ids: tuple[str, ...],
        proposal_ids: tuple[str, ...],
        operation_record_ids: tuple[str, ...],
        retained_shared_record_ids: tuple[str, ...],
    ) -> str:
        payload = {
            "run_id": run_id,
            "descendants": list(descendants),
            "blocking_status": blocking_status,
            "artifact_counts": artifact_counts,
            "report_count": report_count,
            "session_ids": list(session_ids),
            "event_session_ids": list(event_session_ids),
            "proposal_ids": list(proposal_ids),
            "operation_record_ids": list(operation_record_ids),
            "retained_shared_record_ids": list(retained_shared_record_ids),
            "run_files": self._file_snapshot(run_root),
            "agent_files": self._file_snapshot(
                *[
                    path
                    for session_id in session_ids
                    for path in (
                        self._agent_sessions_dir / f"{session_id}.jsonl",
                        self._agent_sessions_dir / f"{session_id}.meta.json",
                    )
                ],
                *[
                    self._agent_events_dir / f"{session_id}.jsonl"
                    for session_id in event_session_ids
                ],
                *[
                    self._proposals_dir / f"{proposal_id}.jsonl"
                    for proposal_id in proposal_ids
                ],
                *[
                    self._operation_records_dir / f"{record_id}.jsonl"
                    for record_id in operation_record_ids
                ],
            ),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _file_snapshot(self, *paths: Path) -> list[tuple[str, int, int]]:
        snapshot: list[tuple[str, int, int]] = []
        for path in paths:
            if path.is_dir():
                candidates = sorted(item for item in path.rglob("*") if item.is_file())
            else:
                candidates = [path] if path.is_file() else []
            for item in candidates:
                stat = item.stat()
                try:
                    relative = item.resolve().relative_to(self.project_root).as_posix()
                except ValueError:
                    continue
                snapshot.append((relative, stat.st_size, stat.st_mtime_ns))
        return sorted(snapshot)

    def _remove_run_tree(self, run_root: Path) -> None:
        expected_parent = self.runs_root.resolve()
        resolved = run_root.resolve()
        if resolved.parent != expected_parent or not resolved.is_dir() or run_root.is_symlink():
            raise RunDeletionConfirmationError("run deletion target is invalid")
        shutil.rmtree(resolved)

    @staticmethod
    def _unlink_if_file(path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink()

    @staticmethod
    def _read_json_or_none(path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _read_json_lines(path: Path) -> list[dict[str, Any]]:
        try:
            rows = path.read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, OSError):
            return []
        values: list[dict[str, Any]] = []
        for row in rows:
            try:
                value = json.loads(row)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                values.append(value)
        return values

    @staticmethod
    def _read_json_lines_strict(path: Path) -> list[dict[str, Any]] | None:
        try:
            rows = path.read_text(encoding="utf-8").splitlines()
        except (FileNotFoundError, OSError):
            return None
        values: list[dict[str, Any]] = []
        for row in rows:
            try:
                value = json.loads(row)
            except json.JSONDecodeError:
                return None
            if not isinstance(value, dict):
                return None
            values.append(value)
        return values

    @staticmethod
    def _safe_identifier(value: str) -> bool:
        return bool(value) and Path(value).name == value
