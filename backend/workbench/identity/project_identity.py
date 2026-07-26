"""The single server-owned producer for project identity revisions."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .contracts import PROJECT_IDENTITY_REVISION_CONTRACT, ProjectIdentityRevision
from .local_profile import (
    IdentityClientClaimError,
    IdentityCollisionError,
    IdentityRecordCorruptError,
    IdentityStoreError,
    LocalProfileIdentityStore,
    _IdentityStoreAdmission,
    _append_jsonl,
    _canonical_bytes,
    _create_content_addressed,
    _list_record_names,
    _open_store_admission,
    _parse_json_object,
    _parse_jsonl,
    _process_lock,
    _read_child,
    _read_record_objects,
    _truncate_jsonl,
)
from .root import (
    ProjectRootRelocatedError,
    open_validated_project_root,
)


_HASH = re.compile(r"^[0-9a-f]{64}\Z")


class ProjectIdentityStore:
    """Persist immutable project revisions under one identity authority root."""

    def __init__(
        self,
        authority_root: Path | str,
        *,
        profile_store: LocalProfileIdentityStore | None = None,
    ) -> None:
        self.authority_root = Path(authority_root).expanduser()
        if not self.authority_root.is_absolute():
            raise IdentityStoreError("identity authority root must be absolute")
        if profile_store is not None:
            if not isinstance(profile_store, LocalProfileIdentityStore):
                raise IdentityStoreError("project profile store must be a local identity store")
            try:
                project_path = self.authority_root.resolve(strict=False)
                profile_path = profile_store.authority_root.resolve(strict=False)
            except (OSError, RuntimeError) as exc:
                raise IdentityStoreError("identity authority roots cannot be compared") from exc
            if project_path != profile_path:
                raise IdentityStoreError(
                    "project and profile stores must share one authority root"
                )
        self.profile_store = profile_store or LocalProfileIdentityStore(
            self.authority_root
        )
        self._lock = _process_lock(Path(self.authority_root))

    def _assert_profile_store_authority(
        self, admission: _IdentityStoreAdmission
    ) -> None:
        if self.profile_store._authority_binding() != admission.authority_binding:
            raise IdentityStoreError(
                "project and profile stores must share one authority binding"
            )

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
        self._reject_client_claims(
            project_id=project_id,
            client_project_id=client_project_id,
            profile_id=profile_id,
            client_profile_id=client_profile_id,
        )
        # Root resolution and fstat happen only after the project scope lock is
        # held.  The open FD remains the binding authority for this operation.
        with _open_store_admission(self.authority_root, "projects", self._lock) as admission:
            self._assert_profile_store_authority(admission)
            with open_validated_project_root(project_root) as root_admission:
                authoritative_profile = self.profile_store.get_or_create()
                if profile is not None and profile != authoritative_profile:
                    raise IdentityCollisionError(
                        "project identity was supplied with a non-authoritative profile"
                    )
                records = self._read_records(admission)
                self._validate_profile_scope(records, authoritative_profile.profile_id)
                binding = root_admission.validated.to_binding_dict()
                same_binding = [
                    record
                    for record in records
                    if record.root_binding["binding_key"] == binding["binding_key"]
                ]
                if same_binding:
                    project_ids = {record.project_id for record in same_binding}
                    if len(project_ids) != 1:
                        raise IdentityCollisionError(
                            "one filesystem root has conflicting project identities"
                        )
                    project_id_for_binding = next(iter(project_ids))
                    project_records = [
                        record
                        for record in records
                        if record.project_id == project_id_for_binding
                    ]
                    current = max(project_records, key=lambda record: record.revision)
                    if current.profile_id != authoritative_profile.profile_id:
                        raise IdentityCollisionError(
                            "project identity belongs to another local profile"
                        )
                    if current.root_binding == binding:
                        return current
                    return self._append_revision(admission, current, binding)

                for record in records:
                    if record.root_binding["canonical_path"] == binding["canonical_path"]:
                        raise ProjectRootRelocatedError(
                            "project path is already bound to a different filesystem root"
                        )

                identity = ProjectIdentityRevision(
                    project_id=f"project_{uuid4().hex}",
                    profile_id=authoritative_profile.profile_id,
                    revision=1,
                    root_binding=binding,
                )
                self._persist_in_admission(admission, identity)
                return identity

    ensure = get_or_create

    def get_current(
        self, project_root: Path | str, *, recover: bool = False
    ) -> ProjectIdentityRevision | None:
        with _open_store_admission(self.authority_root, "projects", self._lock) as admission:
            self._assert_profile_store_authority(admission)
            with open_validated_project_root(project_root) as root_admission:
                records = self._read_records(admission, recover=recover)
                if not records:
                    return None
                authoritative_profile = self.profile_store.get_current(recover=recover)
                if authoritative_profile is None:
                    raise IdentityRecordCorruptError(
                        "project records exist without a local profile identity"
                    )
                self._validate_profile_scope(records, authoritative_profile.profile_id)
                binding = root_admission.validated.to_binding_dict()
                matches = [record for record in records if record.root_binding == binding]
                if not matches:
                    return None
                project_ids = {record.project_id for record in matches}
                if len(project_ids) != 1:
                    raise IdentityCollisionError(
                        "one filesystem root has conflicting project identities"
                    )
                return max(matches, key=lambda record: record.revision)

    current = get_current

    def get(
        self, project_id: str, *, recover: bool = False
    ) -> tuple[ProjectIdentityRevision, ...]:
        with _open_store_admission(self.authority_root, "projects", self._lock) as admission:
            self._assert_profile_store_authority(admission)
            records = self._read_records(admission, recover=recover)
            if records:
                authoritative_profile = self.profile_store.get_current(recover=recover)
                if authoritative_profile is None:
                    raise IdentityRecordCorruptError(
                        "project records exist without a local profile identity"
                    )
                self._validate_profile_scope(records, authoritative_profile.profile_id)
            if not isinstance(project_id, str) or not project_id:
                return ()
            return tuple(
                sorted(
                    (record for record in records if record.project_id == project_id),
                    key=lambda record: record.revision,
                )
            )

    revisions = get

    def record_name(self, revision: ProjectIdentityRevision) -> str:
        return f"{revision.content_hash}.json"

    def read_record_bytes(self, revision: ProjectIdentityRevision) -> bytes:
        with _open_store_admission(self.authority_root, "projects", self._lock) as admission:
            self._assert_profile_store_authority(admission)
            records = self._validated_records(admission, recover_invalid_orphans=False)
            if not isinstance(revision, ProjectIdentityRevision) or not any(
                record == revision for record in records
            ):
                raise IdentityCollisionError("project identity record is outside the current scope")
            raw = _read_child(admission.records_fd, self.record_name(revision))
            if raw is None:
                raise IdentityRecordCorruptError("project identity record is missing")
            parsed = self._parse_record(_parse_json_object(raw))
            if parsed != revision or raw != _canonical_bytes(parsed.to_dict()):
                raise IdentityRecordCorruptError("project identity record is not canonical")
            return raw

    def read_records_log_bytes(self) -> bytes:
        with _open_store_admission(self.authority_root, "projects", self._lock) as admission:
            self._assert_profile_store_authority(admission)
            self._validated_records(admission, recover_invalid_orphans=False)
            raw = _read_child(admission.scope_fd, "records.jsonl", missing_is_none=True)
            return raw or b""

    def content_addressed_record_names(self) -> tuple[str, ...]:
        with _open_store_admission(self.authority_root, "projects", self._lock) as admission:
            self._assert_profile_store_authority(admission)
            self._validated_records(admission, recover_invalid_orphans=False)
            return _list_record_names(admission)

    def _append_revision(
        self,
        admission: _IdentityStoreAdmission,
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
        self._persist_in_admission(admission, revision)
        return revision

    def _persist(self, revision: ProjectIdentityRevision) -> None:
        """Persist a testable immutable record through the same FD admission."""

        with _open_store_admission(self.authority_root, "projects", self._lock) as admission:
            self._persist_in_admission(admission, revision)

    def _persist_in_admission(
        self, admission: _IdentityStoreAdmission, revision: ProjectIdentityRevision
    ) -> None:
        _create_content_addressed(admission, self.record_name(revision), revision.to_dict())
        _append_jsonl(
            admission,
            {
                "contract_version": revision.contract_version,
                "record_hash": revision.content_hash,
            },
        )

    def _read_records(
        self,
        admission: _IdentityStoreAdmission,
        *,
        recover: bool = True,
        recover_invalid_orphans: bool = True,
    ) -> list[ProjectIdentityRevision]:
        if not recover:
            recover_invalid_orphans = False
        log_raw = _read_child(admission.scope_fd, "records.jsonl", missing_is_none=True)
        pointers: list[dict[str, str]] = []
        if log_raw is not None:
            parsed, complete_bytes = _parse_jsonl(log_raw)
            if complete_bytes != len(log_raw):
                if not recover:
                    raise IdentityRecordCorruptError(
                        "project identity log is incomplete"
                    )
                _truncate_jsonl(admission, complete_bytes)
            for item in parsed:
                if set(item) != {"contract_version", "record_hash"}:
                    raise IdentityRecordCorruptError("invalid project identity pointer")
                if item["contract_version"] != PROJECT_IDENTITY_REVISION_CONTRACT:
                    raise IdentityRecordCorruptError("unsupported project identity pointer")
                record_hash = item["record_hash"]
                if type(record_hash) is not str or not _HASH.fullmatch(record_hash):
                    raise IdentityRecordCorruptError("invalid project identity record hash")
                pointer = {
                    "contract_version": item["contract_version"],
                    "record_hash": record_hash,
                }
                if pointer not in pointers:
                    pointers.append(pointer)

        referenced = {item["record_hash"] for item in pointers}
        objects = _read_record_objects(
            admission,
            self._parse_record,
            referenced,
            recover_invalid_orphans=recover_invalid_orphans,
        )
        by_hash: dict[str, ProjectIdentityRevision] = {}
        for item in objects:
            name = str(item["name"])
            record_hash = name[:-5]
            record = item["value"]
            assert isinstance(record, ProjectIdentityRevision)
            if record.content_hash != record_hash:
                raise IdentityCollisionError(
                    f"project identity record does not match its content address: {name}"
                )
            by_hash[record_hash] = record

        records: list[ProjectIdentityRevision] = []
        for pointer in pointers:
            try:
                records.append(by_hash[pointer["record_hash"]])
            except KeyError as exc:
                raise IdentityRecordCorruptError(
                    "project identity pointer references a missing record"
                ) from exc
        missing_pointers = sorted(set(by_hash) - referenced)
        all_records = records + [by_hash[record_hash] for record_hash in missing_pointers]
        self._validate_records(all_records)
        if missing_pointers and not recover:
            raise IdentityRecordCorruptError(
                "project identity records are not fully committed"
            )
        for record_hash in missing_pointers:
            _append_jsonl(
                admission,
                {
                    "contract_version": PROJECT_IDENTITY_REVISION_CONTRACT,
                    "record_hash": record_hash,
                },
            )
        return all_records

    def _validated_records(
        self,
        admission: _IdentityStoreAdmission,
        *,
        recover: bool = False,
        recover_invalid_orphans: bool = False,
    ) -> list[ProjectIdentityRevision]:
        records = self._read_records(
            admission,
            recover=recover,
            recover_invalid_orphans=recover_invalid_orphans,
        )
        if records:
            authoritative_profile = self.profile_store.get_current(recover=recover)
            if authoritative_profile is None:
                raise IdentityRecordCorruptError(
                    "project records exist without a local profile identity"
                )
            self._validate_profile_scope(records, authoritative_profile.profile_id)
        return records

    @staticmethod
    def _parse_record(value: dict[str, Any]) -> ProjectIdentityRevision:
        try:
            return ProjectIdentityRevision.from_dict(value)
        except (TypeError, ValueError) as exc:
            raise IdentityRecordCorruptError("project identity record is invalid") from exc

    @staticmethod
    def _validate_records(records: list[ProjectIdentityRevision]) -> None:
        by_project: dict[str, list[ProjectIdentityRevision]] = {}
        binding_projects: dict[str, set[str]] = {}
        for record in records:
            by_project.setdefault(record.project_id, []).append(record)
            binding_key = record.root_binding["binding_key"]
            binding_projects.setdefault(str(binding_key), set()).add(record.project_id)
        if any(len(projects) > 1 for projects in binding_projects.values()):
            raise IdentityCollisionError(
                "one filesystem root has conflicting project identities"
            )
        for project_records in by_project.values():
            ordered = sorted(project_records, key=lambda record: record.revision)
            if [record.revision for record in ordered] != list(
                range(1, len(ordered) + 1)
            ):
                raise IdentityCollisionError("project identity revisions have a gap or fork")
            profiles = {record.profile_id for record in ordered}
            if len(profiles) != 1:
                raise IdentityCollisionError(
                    "project identity revisions conflict on local profile scope"
                )
            for expected, record in enumerate(ordered, start=1):
                expected_previous = None if expected == 1 else expected - 1
                if record.previous_revision != expected_previous:
                    raise IdentityCollisionError("project identity revision chain is broken")

    @staticmethod
    def _validate_profile_scope(
        records: list[ProjectIdentityRevision], profile_id: str
    ) -> None:
        if any(record.profile_id != profile_id for record in records):
            raise IdentityCollisionError(
                "project identity records are outside the authoritative profile scope"
            )

    @staticmethod
    def _reject_client_claims(**claims: object) -> None:
        if any(value is not None for value in claims.values()):
            raise IdentityClientClaimError(
                "project identity and profile identity are issued by the server"
            )


ProjectIdentityRevisionStore = ProjectIdentityStore


__all__ = [
    "ProjectIdentityRevisionStore",
    "ProjectIdentityStore",
]
