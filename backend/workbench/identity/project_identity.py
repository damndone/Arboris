"""The single server-owned producer for project identity revisions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .contracts import ProjectIdentityRevision
from .local_profile import (
    IdentityClientClaimError,
    IdentityCollisionError,
    IdentityRecordCorruptError,
    LocalProfileIdentityStore,
    _append_jsonl,
    _create_content_addressed,
    _file_lock,
    _process_lock,
)
from .root import ProjectRootRelocatedError, validate_project_root


class ProjectIdentityStore:
    """Persist immutable project revisions under one identity authority root."""

    def __init__(
        self,
        authority_root: Path | str,
        *,
        profile_store: LocalProfileIdentityStore | None = None,
    ) -> None:
        self.authority_root = Path(authority_root).expanduser().resolve()
        self.root = self.authority_root / "identity" / "projects"
        self.records_dir = self.root / "records"
        self.records_log_path = self.root / "records.jsonl"
        self.lock_path = self.root / ".lock"
        self.profile_store = profile_store or LocalProfileIdentityStore(
            self.authority_root
        )
        self._lock = _process_lock(self.authority_root)

    def get_or_create(
        self,
        project_root: Path | str,
        *,
        project_id: str | None = None,
        client_project_id: str | None = None,
        profile_id: str | None = None,
        client_profile_id: str | None = None,
        profile: object | None = None,
    ) -> ProjectIdentityRevision:
        if any(
            value is not None
            for value in (
                project_id,
                client_project_id,
                profile_id,
                client_profile_id,
            )
        ):
            raise IdentityClientClaimError(
                "project identity and profile identity are issued by the server"
            )
        validated_root = validate_project_root(project_root)
        with self._lock:
            with _file_lock(self.lock_path):
                authoritative_profile = self.profile_store.get_or_create()
                if profile is not None:
                    if profile != authoritative_profile:
                        raise IdentityCollisionError(
                            "project identity was supplied with a non-authoritative profile"
                        )
                records = self._read_records()
                same_binding = [
                    record
                    for record in records
                    if record.root_binding["binding_key"] == validated_root.binding_key
                ]
                if same_binding:
                    project_ids = {record.project_id for record in same_binding}
                    profile_ids = {record.profile_id for record in same_binding}
                    if len(project_ids) != 1 or len(profile_ids) != 1:
                        raise IdentityCollisionError(
                            "one filesystem root has conflicting project identity records"
                        )
                    current = max(
                        same_binding,
                        key=lambda record: (record.project_id, record.revision),
                    )
                    if current.profile_id != authoritative_profile.profile_id:
                        raise IdentityCollisionError(
                            "one filesystem root is bound to another local profile"
                        )
                    if current.root_binding["canonical_path"] == validated_root.canonical_path:
                        return current
                    return self._append_revision(
                        current,
                        validated_root.to_binding_dict(),
                    )

                for record in records:
                    if record.root_binding["canonical_path"] == validated_root.canonical_path:
                        raise ProjectRootRelocatedError(
                            "project path is already bound to a different filesystem root"
                        )

                identity = ProjectIdentityRevision(
                    project_id=f"project_{uuid4().hex}",
                    profile_id=authoritative_profile.profile_id,
                    revision=1,
                    root_binding=validated_root.to_binding_dict(),
                )
                self._persist(identity)
                return identity

    ensure = get_or_create

    def get_current(self, project_root: Path | str) -> ProjectIdentityRevision | None:
        validated_root = validate_project_root(project_root)
        with self._lock:
            with _file_lock(self.lock_path):
                records = [
                    record
                    for record in self._read_records()
                    if record.root_binding["binding_key"] == validated_root.binding_key
                ]
                if not records:
                    return None
                return max(records, key=lambda record: record.revision)

    current = get_current

    def get(self, project_id: str) -> tuple[ProjectIdentityRevision, ...]:
        if not isinstance(project_id, str) or not project_id:
            return ()
        with self._lock:
            with _file_lock(self.lock_path):
                return tuple(
                    sorted(
                        (
                            record
                            for record in self._read_records()
                            if record.project_id == project_id
                        ),
                        key=lambda record: record.revision,
                    )
                )

    revisions = get

    def record_path(self, revision: ProjectIdentityRevision) -> Path:
        return self.records_dir / f"{revision.content_hash}.json"

    def _append_revision(
        self,
        current: ProjectIdentityRevision,
        root_binding: Mapping[str, Any],
    ) -> ProjectIdentityRevision:
        revision = ProjectIdentityRevision(
            project_id=current.project_id,
            profile_id=current.profile_id,
            revision=current.revision + 1,
            previous_revision=current.revision,
            root_binding=root_binding,
        )
        self._persist(revision)
        return revision

    def _persist(self, revision: ProjectIdentityRevision) -> None:
        _create_content_addressed(
            self.record_path(revision), revision.to_dict()
        )
        _append_jsonl(
            self.records_log_path,
            {
                "contract_version": revision.contract_version,
                "record_hash": revision.content_hash,
            },
        )

    def _read_records(self) -> list[ProjectIdentityRevision]:
        if not self.records_log_path.exists():
            return []
        try:
            lines = self.records_log_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise IdentityRecordCorruptError(
                f"cannot read project identity log: {self.records_log_path}"
            ) from exc
        records: list[ProjectIdentityRevision] = []
        seen: set[str] = set()
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                pointer = json.loads(line)
            except json.JSONDecodeError as exc:
                raise IdentityRecordCorruptError(
                    f"invalid project identity log line {line_number}"
                ) from exc
            if (
                not isinstance(pointer, dict)
                or set(pointer) != {"contract_version", "record_hash"}
                or type(pointer["record_hash"]) is not str
            ):
                raise IdentityRecordCorruptError(
                    f"invalid project identity pointer at line {line_number}"
                )
            record_hash = pointer["record_hash"]
            if record_hash in seen:
                continue
            seen.add(record_hash)
            record_path = self.records_dir / f"{record_hash}.json"
            try:
                payload = json.loads(record_path.read_text(encoding="utf-8"))
                record = ProjectIdentityRevision.from_dict(payload)
            except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
                raise IdentityRecordCorruptError(
                    f"invalid project identity record: {record_path}"
                ) from exc
            if record.content_hash != record_hash:
                raise IdentityCollisionError(
                    f"project identity record does not match its content address: {record_hash}"
                )
            records.append(record)
        return records


ProjectIdentityRevisionStore = ProjectIdentityStore


__all__ = [
    "ProjectIdentityRevisionStore",
    "ProjectIdentityStore",
]
