"""Dependency *data* integrity, not authority issuance.

Callers must obtain the sealed manifest from their admitted C0 envelope. A
caller-supplied replacement manifest is not authenticated by these primitives.
Checks describe the admitted read boundary, not future filesystem immutability.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
import stat
from types import MappingProxyType

from .persistence import EvidencePersistenceError


MAX_ARTIFACT_INDEX_BYTES = 8 * 1024 * 1024
_READ_CHUNK_BYTES = 1024 * 1024


def _fail(message: str, code: str = "EVIDENCE_DEPENDENCY_INVALID"):
    # Keep the owner/results import cycle out of module initialization.
    from ..services.results_service import EvidenceProjectionError

    raise EvidenceProjectionError(code, message)


def _text(value):
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        _fail("Dependency identity must be an exact nonempty string")
    return value


def _parts(value):
    if not isinstance(value, (list, tuple)) or not value:
        _fail("Dependency path must contain safe relative components")
    for part in value:
        _text(part)
        if part in {".", ".."} or "/" in part or "\\" in part:
            _fail("Dependency path is unsafe")
    return tuple(value)


def _digest(value):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        _fail("Dependency digest must be lowercase SHA-256")
    return value


def _plain(value):
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            _fail("Dependency object keys must be strings")
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if value is None or type(value) in (str, bool, int, float):
        return value
    _fail("Dependency data must be JSON values")


def _canonical(value):
    try:
        return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        _fail(f"Invalid dependency JSON: {type(exc).__name__}")


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class ResultDependencyManifestV1:
    schema_version: int
    project_ref: str
    run_id: str
    records: tuple[Mapping, ...]

    def __post_init__(self):
        object.__setattr__(self, "records", _freeze(self.records))

    def to_dict(self) -> dict:
        return {"schema_version": self.schema_version, "project_ref": self.project_ref,
                "run_id": self.run_id, "records": _plain(self.records)}


def _store(store, project_ref, run_id):
    from ..services.report_evidence_owner_factory import HostBoundProjectFileStoreV1

    if type(store) is not HostBoundProjectFileStoreV1:
        _fail("Exact host project file store required", "EVIDENCE_DEPENDENCY_STORE_REQUIRED")
    _text(project_ref)
    _parts([run_id])
    try:
        store._admission._require_open()
    except (AttributeError, EvidencePersistenceError, OSError) as exc:
        _fail(f"Host admission unavailable: {type(exc).__name__}", "EVIDENCE_DEPENDENCY_STORE_REQUIRED")


def _metadata(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)


def _read(store, parts, *, buffer_index=False):
    """Stream a source digest, or buffer a size-limited index, via admitted FDs.

    The existing store's _read_bytes has no before/after metadata comparison.
    Rewalk via admission after reading to detect replaced parent/leaf entries.
    O_NONBLOCK avoids hanging on a substituted FIFO before regular-file checks.
    Read only the initial size; growing files fail the final metadata check
    instead of extending the read budget. Source bytes are never accumulated.
    """
    checked = _parts(parts)
    admission = store._admission
    parent = fd = check_parent = -1
    try:
        parent = admission._directory(checked[:-1], create=False)
        fd = os.open(checked[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                     dir_fd=parent)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            _fail("Dependency is not a regular file", "EVIDENCE_DEPENDENCY_UNAVAILABLE")
        if buffer_index and before.st_size > MAX_ARTIFACT_INDEX_BYTES:
            _fail("Artifact index exceeds the 8 MiB byte limit")
        buffer = bytearray(before.st_size) if buffer_index else None
        digest = hashlib.sha256() if not buffer_index else None
        consumed = 0
        while consumed < before.st_size:
            chunk = os.read(fd, min(_READ_CHUNK_BYTES, before.st_size - consumed))
            if not chunk:
                break
            if buffer is not None:
                buffer[consumed:consumed + len(chunk)] = chunk
            else:
                digest.update(chunk)
            consumed += len(chunk)
            del chunk
        after = os.fstat(fd)
        check_parent = admission._directory(checked[:-1], create=False)
        entry = os.stat(checked[-1], dir_fd=check_parent, follow_symlinks=False)
        if (_metadata(before) != _metadata(after) or _metadata(after) != _metadata(entry)
                or consumed != before.st_size):
            _fail("Dependency changed during read", "EVIDENCE_DEPENDENCY_UNSTABLE")
        return buffer if buffer_index else digest.hexdigest()
    except (OSError, EvidencePersistenceError) as exc:
        _fail(f"Dependency cannot be read safely: {type(exc).__name__}", "EVIDENCE_DEPENDENCY_UNAVAILABLE")
    finally:
        if fd >= 0:
            os.close(fd)
        if check_parent >= 0:
            admission._close_directory(check_parent)
        if parent >= 0:
            admission._close_directory(parent)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("Duplicate dependency JSON key")
        result[key] = value
    return result


def _row(row, project_ref, run_id):
    if not isinstance(row, Mapping):
        _fail("Artifact index record must be an object")
    _canonical(row)
    _text(row.get("artifact_id"))
    path = _text(row.get("path"))
    parts = _parts(path.split("/"))
    _text(row.get("artifact_type"))
    _text(row.get("step"))
    _digest(row.get("sha256"))
    for key, expected in (("project_ref", project_ref), ("run_id", run_id), ("evidence_run_id", run_id)):
        if key in row and row[key] != expected:
            _fail("Foreign artifact index binding")
    return ("runs", run_id, *parts)


def _acyclic(row, path):
    if (row["step"] in {"report", "export"}
            or row["artifact_type"] in {"report", "report_evidence", "export", "table_export"}
            or row["artifact_id"].split(":", 1)[0] in {"report", "report_evidence", "export"}
            or path[-1] in {"artifacts_index.json", "report_evidence.json"}):
        _fail("Report/export/index cannot be a result dependency")


def _index(store, project_ref, run_id):
    raw = _read(store, ("runs", run_id, "artifacts_index.json"), buffer_index=True)
    try:
        index = json.loads(raw, object_pairs_hook=_pairs)
    except (ValueError, UnicodeError, RecursionError) as exc:
        _fail(f"Invalid artifact index JSON: {type(exc).__name__}")
    _canonical(index)
    if (type(index) is not dict or type(index.get("schema_version")) is not int
            or index["schema_version"] != 1 or type(index.get("artifacts")) is not list):
        _fail("Unsupported artifact index schema")
    for key, expected in (("project_ref", project_ref), ("run_id", run_id)):
        if key in index and index[key] != expected:
            _fail("Foreign artifact index identity")
    rows, paths = {}, set()
    for row in index["artifacts"]:
        path = _row(row, project_ref, run_id)
        identity = row["artifact_id"]
        if identity in rows or path in paths:
            _fail("Duplicate artifact index identity or path")
        rows[identity] = row
        paths.add(path)
    return rows


def _ids(values):
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        _fail("Dependency selection must be a sequence of unique IDs")
    result = tuple(_text(value) for value in values)
    if len(set(result)) != len(result):
        _fail("Duplicate dependency selection")
    return result


def _check_records(store, records, project_ref, run_id):
    current = _index(store, project_ref, run_id)
    for record in records:
        identity = record["artifact_id"]
        if identity not in current or _canonical(current[identity]) != _canonical(record["index_record"]):
            _fail("Bound artifact index record changed or disappeared", "EVIDENCE_DEPENDENCY_MISMATCH")
        if _read(store, record["path"]) != record["sha256"]:
            _fail("Bound source bytes changed", "EVIDENCE_DEPENDENCY_MISMATCH")
    after = _index(store, project_ref, run_id)
    for record in records:
        if _canonical(after.get(record["artifact_id"])) != _canonical(record["index_record"]):
            _fail("Bound index changed during dependency reads", "EVIDENCE_DEPENDENCY_UNSTABLE")


def capture_result_dependencies(store, *, project_ref, run_id, artifact_ids):
    """Snapshot requested final sources; reject explicit cyclic dependencies."""
    _store(store, project_ref, run_id)
    ids = _ids(artifact_ids)
    rows = _index(store, project_ref, run_id)
    records = []
    for identity in ids:
        if identity not in rows:
            _fail("Requested artifact is missing", "EVIDENCE_DEPENDENCY_UNAVAILABLE")
        row = rows[identity]
        path = _row(row, project_ref, run_id)
        _acyclic(row, path)
        digest = _read(store, path)
        if digest != row["sha256"]:
            _fail("Source does not match index", "EVIDENCE_DEPENDENCY_MISMATCH")
        records.append(dict(artifact_id=identity, path=path, sha256=digest, index_record=row))
    _check_records(store, records, project_ref, run_id)
    return ResultDependencyManifestV1(1, project_ref, run_id, tuple(records))


def verify_result_dependencies(store, manifest, *, project_ref, run_id, dependency_ids=None):
    """Return None on integrity success; otherwise raise EvidenceProjectionError.

    None selects every manifest record. An explicit selection checks only that
    closure's sources/relevant index records; the entire manifest is validated.
    This deliberately does not authenticate the manifest's origin or mint C0.
    """
    _store(store, project_ref, run_id)
    checked = validate_result_dependency_manifest(manifest, project_ref=project_ref, run_id=run_id)
    records = {record["artifact_id"]: record for record in checked.records}
    selected = tuple(records) if dependency_ids is None else _ids(dependency_ids)
    if any(identity not in records for identity in selected):
        _fail("Selected dependency is absent from sealed manifest")
    _check_records(store, [records[identity] for identity in selected], project_ref, run_id)


def validate_result_dependency_manifest(manifest, *, project_ref, run_id):
    """Validate only the closed value schema; no file access or authority."""
    _text(project_ref)
    _parts([run_id])
    if type(manifest) is ResultDependencyManifestV1:
        manifest = manifest.to_dict()
    _canonical(manifest)
    if (not isinstance(manifest, Mapping)
            or set(manifest) != {"schema_version", "project_ref", "run_id", "records"}
            or type(manifest["schema_version"]) is not int):
        _fail("Invalid dependency manifest schema")
    if manifest["schema_version"] != 1:
        _fail("Unsupported dependency manifest version", "UNSUPPORTED_VERSION")
    if (manifest["project_ref"] != project_ref or manifest["run_id"] != run_id
            or not isinstance(manifest["records"], (list, tuple))):
        _fail("Invalid dependency manifest schema or binding")
    records, paths = {}, set()
    for record in manifest["records"]:
        if not isinstance(record, Mapping) or set(record) != {"artifact_id", "path", "sha256", "index_record"}:
            _fail("Invalid dependency record schema")
        identity = _text(record["artifact_id"])
        path = _parts(record["path"])
        row = record["index_record"]
        if (_row(row, project_ref, run_id) != path or row["artifact_id"] != identity
                or _digest(record["sha256"]) != row["sha256"] or identity in records or path in paths):
            _fail("Invalid dependency record binding or duplicate")
        _acyclic(row, path)
        records[identity] = record
        paths.add(path)
    return ResultDependencyManifestV1(1, project_ref, run_id, tuple(records.values()))
