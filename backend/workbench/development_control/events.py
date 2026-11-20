"""Version 1 devline event validation, append, and integrity verification.

The local filesystem cannot make a same-UID writer tamper-proof.  This module
therefore makes append-only claims only for the controlled writer: events are
locked, appended, fsynced, hash chained, and checked against a separately
fsynced tail anchor.  A missing or mismatched anchor fails closed.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
import fcntl
import gzip
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
from typing import Any
import uuid
import zlib


MAX_EVENT_BYTES = 16 * 1024
ARCHIVE_NAME = "events.jsonl.gz"
_MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
_EVENTS_NAME = "events.jsonl"
_ANCHOR_NAME = "events.jsonl.anchor"
ZERO_SHA256 = "0" * 64
EVENT_TYPES = frozenset({"FAILURE", "ERROR", "GAP", "WASTE", "REVIEW", "GATE", "STATE_CHANGE"})
CAUSE_STATUSES = frozenset({"known", "suspected", "unknown", "external", "not_applicable"})
PREVENTABILITY = frozenset({"preventable", "partially_preventable", "not_preventable", "unknown"})
RESOLUTIONS = frozenset({"open", "mitigated", "resolved", "accepted", "not_applicable"})
STAGES = frozenset({"design", "implementation", "review", "gate", "integration", "release"})
REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "timestamp",
        "type",
        "subtype",
        "stage",
        "cause_status",
        "cause",
        "evidence",
        "impact",
        "preventability",
        "resolution",
        "lesson",
        "incident_id",
        "lesson_key",
        "links",
        "prev_event_sha256",
        "event_sha256",
    }
)
OPTIONAL_FIELDS = frozenset(
    {
        "state_from",
        "state_to",
        "gate_fingerprint",
        "review_round",
        "artifact_digest",
        "duration_ms",
        "resource_usage",
        "tags",
        "severity",
    }
)
# Optional; absent means "normal". A "high" severity does not shortcut the
# two-incident evidence rule for promotion -- it only makes a single occurrence
# visible for a human decision (E2). Kept small on purpose.
SEVERITIES = frozenset({"low", "normal", "high"})
_LINE_ID = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_LESSON_KEY = re.compile(r"^[a-z][a-z0-9-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RFC3339_MILLIS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_ABSOLUTE_PATH = re.compile(r"(?:^|[\s\"'])/(?:Users|home|private|var|tmp)/", re.IGNORECASE)
_SECRET = re.compile(
    r"(?:api[_-]?key|authorization|bearer|cookie|password|secret|token)\s*(?:=|:|\s)\s*[^\s,;]+",
    re.IGNORECASE,
)
_RESOURCE_USAGE_KEYS = frozenset({"input_tokens", "output_tokens", "tool_tokens"})


class EventValidationError(ValueError):
    """Raised before an invalid event or an untrustworthy log is used."""


def redact_sensitive_text(value: str) -> str:
    """Return a diagnostic-safe rendering without accepting raw sensitive input."""

    value = _SECRET.sub("[REDACTED_SECRET]", value)
    return _ABSOLUTE_PATH.sub("[REDACTED_ABSOLUTE_PATH]/", value)


def canonical_event_bytes(event: Mapping[str, Any]) -> bytes:
    """Encode an event with a deterministic UTF-8 JSON representation."""

    return json.dumps(
        dict(event), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def validate_line_id(line_id: str) -> None:
    if not isinstance(line_id, str) or not _LINE_ID.fullmatch(line_id):
        raise EventValidationError("line_id must match ^[a-z][a-z0-9-]{1,62}$")


def validate_event(event: Mapping[str, Any], *, previous_sha256: str) -> dict[str, Any]:
    """Validate an event and produce its canonical hash-chain fields.

    Callers provide a source event without the two chain fields.  Log readers
    provide the complete stored event; a supplied `event_sha256` must match.
    """

    if not isinstance(event, Mapping):
        raise EventValidationError("event must be a JSON object")
    if not isinstance(previous_sha256, str) or not _SHA256.fullmatch(previous_sha256):
        raise EventValidationError("previous_sha256 must be a sha256 digest")
    normalized = dict(event)
    supplied_hash = normalized.pop("event_sha256", None)
    supplied_previous = normalized.pop("prev_event_sha256", None)
    allowed_source = REQUIRED_FIELDS - {"event_sha256", "prev_event_sha256"} | OPTIONAL_FIELDS
    unknown = set(normalized) - allowed_source
    if unknown:
        raise EventValidationError(f"unknown event fields: {', '.join(sorted(unknown))}")
    missing = (REQUIRED_FIELDS - {"event_sha256", "prev_event_sha256"}) - set(normalized)
    if missing:
        raise EventValidationError(f"missing required event fields: {', '.join(sorted(missing))}")
    if any(value is None for value in normalized.values()):
        raise EventValidationError("event fields must not be null")

    _validate_contract(normalized)
    _reject_sensitive_values(normalized)
    normalized["prev_event_sha256"] = previous_sha256
    digest_input = canonical_event_bytes(normalized)
    calculated_hash = hashlib.sha256(digest_input).hexdigest()
    normalized["event_sha256"] = calculated_hash
    encoded = canonical_event_bytes(normalized)
    if len(encoded) > MAX_EVENT_BYTES:
        raise EventValidationError("event exceeds 16 KiB")
    if supplied_previous is not None and supplied_previous != previous_sha256:
        raise EventValidationError("prev_event_sha256 does not match the preceding event")
    if supplied_hash is not None and supplied_hash != calculated_hash:
        raise EventValidationError("event_sha256 does not match canonical event bytes")
    return normalized


def append_event(devlines_root: Path, line_id: str, event: Mapping[str, Any]) -> dict[str, Any]:
    """Append one validated event under a checked devlines root and fsync it."""

    with _locked_log(devlines_root, line_id, write=True, create=True) as (line_fd, event_fd):
        live = _read_live(line_fd, event_fd)
        _, archived = _read_archive(line_fd)
        history = _combine_history(archived, live)
        existing = _parse_event_lines(history)
        _verify_events(existing)
        _verify_anchor(line_fd, existing, allow_uninitialized=not history)
        source_event_id = event.get("event_id") if isinstance(event, Mapping) else None
        if any(row["event_id"] == source_event_id for row in existing):
            raise EventValidationError("duplicate event_id")
        appended = validate_event(event, previous_sha256=_tail_sha256(existing))
        if live and history == archived:
            _clear_live_suffix(line_fd, event_fd)
        _write_all(event_fd, canonical_event_bytes(appended) + b"\n")
        os.fsync(event_fd)
        all_events = _parse_event_lines(archived + _read_live(line_fd, event_fd))
        _verify_events(all_events)
        _write_anchor(devlines_root, line_fd, len(all_events), appended["event_sha256"])
        _verify_anchor(line_fd, all_events)
        return appended


def verify_log(devlines_root: Path, line_id: str) -> dict[str, Any]:
    """Fail closed unless the chain and its separately durable tail anchor agree."""

    events = read_verified_events(devlines_root, line_id)
    return {"event_count": len(events), "tail_event_sha256": _tail_sha256(events)}


def read_verified_events(devlines_root: Path, line_id: str) -> list[dict[str, Any]]:
    """Read the complete anchored history, including any archived prefix."""

    with _locked_log(devlines_root, line_id) as (line_fd, event_fd):
        _, archived = _read_archive(line_fd)
        return _verified_history(line_fd, _combine_history(archived, _read_live(line_fd, event_fd)))


def archive_event_log(devlines_root: Path, line_id: str) -> dict[str, Any]:
    """Losslessly compact a verified history and keep its live append file."""

    with _locked_log(devlines_root, line_id, write=True) as (line_fd, event_fd):
        live = _read_live(line_fd, event_fd)
        compressed, archived = _read_archive(line_fd)
        history = _combine_history(archived, live)
        events = _verified_history(line_fd, history)
        if not history or len(history) > _MAX_ARCHIVE_BYTES:
            raise EventValidationError("event history must contain between 1 byte and 16 MiB to archive")
        if history != archived:
            compressed = gzip.compress(history, mtime=0)
            if _decompress_archive(compressed) != history:
                raise EventValidationError("event archive failed byte-for-byte verification")
            _publish_log_file(devlines_root, line_fd, ARCHIVE_NAME, compressed)
            on_disk, restored = _read_archive(line_fd)
            if on_disk != compressed or restored != history:
                raise EventValidationError("stored event archive failed byte-for-byte verification")
        if live:
            _clear_live_suffix(line_fd, event_fd)
        return {
            "event_count": len(events),
            "tail_event_sha256": _tail_sha256(events),
            "raw_bytes": len(history),
            "raw_sha256": hashlib.sha256(history).hexdigest(),
            "archive_bytes": len(compressed),
            "archive_sha256": hashlib.sha256(compressed).hexdigest(),
        }


def _validate_contract(event: dict[str, Any]) -> None:
    if event["schema_version"] != 1 or isinstance(event["schema_version"], bool):
        raise EventValidationError("schema_version must be 1")
    _validate_uuid(event["event_id"], "event_id")
    _validate_timestamp(event["timestamp"], "timestamp")
    if event["type"] not in EVENT_TYPES:
        raise EventValidationError("unknown event type")
    _validate_identifier(event["subtype"], "subtype")
    if event["stage"] not in STAGES:
        raise EventValidationError("unknown stage")
    if event["cause_status"] not in CAUSE_STATUSES:
        raise EventValidationError("unknown cause_status")
    _validate_nonempty_string(event["cause"], "cause")
    _validate_evidence(event["evidence"])
    _validate_impact(event["impact"])
    if event["preventability"] not in PREVENTABILITY:
        raise EventValidationError("unknown preventability")
    if event["resolution"] not in RESOLUTIONS:
        raise EventValidationError("unknown resolution")
    _validate_nonempty_string(event["lesson"], "lesson")
    _validate_uuid(event["incident_id"], "incident_id")
    if not isinstance(event["lesson_key"], str) or not _LESSON_KEY.fullmatch(event["lesson_key"]):
        raise EventValidationError("lesson_key must be a normalized identifier")
    if not isinstance(event["links"], list) or not all(isinstance(link, str) and link for link in event["links"]):
        raise EventValidationError("links must be an array of non-empty references")
    _validate_optional_fields(event)


def _validate_uuid(value: Any, name: str) -> None:
    if not isinstance(value, str):
        raise EventValidationError(f"{name} must be a UUID")
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError) as error:
        raise EventValidationError(f"{name} must be a UUID") from error
    if str(parsed) != value.lower() or parsed.int == 0:
        raise EventValidationError(f"{name} must be a canonical non-zero UUID")


def _validate_timestamp(value: Any, name: str) -> None:
    if not isinstance(value, str) or not _RFC3339_MILLIS.fullmatch(value):
        raise EventValidationError(f"{name} must be UTC RFC3339 with millisecond precision")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EventValidationError(f"{name} must be a real timestamp") from error
    if parsed.tzinfo != UTC:
        raise EventValidationError(f"{name} must be UTC")


def _validate_identifier(value: Any, name: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise EventValidationError(f"{name} must be a controlled short identifier")


def _validate_nonempty_string(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise EventValidationError(f"{name} must be a non-empty text summary")


def _validate_evidence(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"kind", "ref", "sha256", "observed_at"}:
        raise EventValidationError("evidence must contain exactly kind, ref, sha256, observed_at")
    _validate_identifier(value["kind"], "evidence.kind")
    _validate_nonempty_string(value["ref"], "evidence.ref")
    if not isinstance(value["sha256"], str) or not _SHA256.fullmatch(value["sha256"]):
        raise EventValidationError("evidence.sha256 must be a sha256 digest")
    _validate_timestamp(value["observed_at"], "evidence.observed_at")


def _validate_impact(value: Any) -> None:
    if isinstance(value, str):
        _validate_nonempty_string(value, "impact")
        return
    if isinstance(value, dict) and value and all(isinstance(key, str) and key for key in value):
        return
    raise EventValidationError("impact must be a non-empty summary or object")


def _validate_optional_fields(event: dict[str, Any]) -> None:
    if "review_round" in event and (not isinstance(event["review_round"], int) or isinstance(event["review_round"], bool) or event["review_round"] < 1):
        raise EventValidationError("review_round must be a positive integer")
    if "duration_ms" in event and (not isinstance(event["duration_ms"], int) or isinstance(event["duration_ms"], bool) or event["duration_ms"] < 0):
        raise EventValidationError("duration_ms must be a non-negative integer")
    if "artifact_digest" in event and (not isinstance(event["artifact_digest"], str) or not _SHA256.fullmatch(event["artifact_digest"])):
        raise EventValidationError("artifact_digest must be a sha256 digest")
    if "tags" in event and (not isinstance(event["tags"], list) or not all(isinstance(tag, str) and _LESSON_KEY.fullmatch(tag) for tag in event["tags"])):
        raise EventValidationError("tags must be normalized identifiers")
    if "resource_usage" in event:
        usage = event["resource_usage"]
        if not isinstance(usage, dict) or not usage or set(usage) - _RESOURCE_USAGE_KEYS:
            raise EventValidationError("resource_usage contains unsupported metrics")
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in usage.values()):
            raise EventValidationError("resource_usage values must be non-negative integers")
    for field in ("state_from", "state_to", "gate_fingerprint"):
        if field in event:
            _validate_nonempty_string(event[field], field)
    if "severity" in event and event["severity"] not in SEVERITIES:
        raise EventValidationError("severity must be one of low, normal, high")


def _reject_sensitive_values(value: Any) -> None:
    if isinstance(value, str):
        if _SECRET.search(value):
            raise EventValidationError("event contains a secret-like value; redact it before recording")
        if _ABSOLUTE_PATH.search(value):
            raise EventValidationError("event contains an absolute host path; use a repository-relative reference")
    elif isinstance(value, dict):
        for item in value.values():
            _reject_sensitive_values(item)
    elif isinstance(value, list):
        for item in value:
            _reject_sensitive_values(item)


def _open_directory(path: Path, label: str) -> int:
    try:
        info = os.lstat(path)
    except OSError as error:
        raise EventValidationError(f"{label} is unavailable") from error
    if stat.S_ISLNK(info.st_mode):
        raise EventValidationError(f"{label} must not be a symlink")
    if not stat.S_ISDIR(info.st_mode):
        raise EventValidationError(f"{label} must be a directory")
    try:
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise EventValidationError(f"{label} could not be safely opened") from error


def _open_child_directory(parent_fd: int, name: str, label: str) -> int:
    try:
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except OSError as error:
        raise EventValidationError(f"{label} must exist and must not be a symlink") from error


@contextmanager
def _locked_log(
    devlines_root: Path, line_id: str, *, write: bool = False, create: bool = False
) -> Iterator[tuple[int, int]]:
    validate_line_id(line_id)
    root_fd = _open_directory(devlines_root, "devlines root")
    try:
        line_fd = _open_child_directory(root_fd, line_id, "devline directory")
        try:
            event_fd = _open_live(line_fd, write=write, create=create)
            try:
                if not stat.S_ISREG(os.fstat(event_fd).st_mode):
                    raise EventValidationError("events.jsonl must be a regular file")
                fcntl.flock(event_fd, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
                yield line_fd, event_fd
            finally:
                os.close(event_fd)
        finally:
            os.close(line_fd)
    finally:
        os.close(root_fd)


def _open_live(line_fd: int, *, write: bool, create: bool) -> int:
    flags = (os.O_RDWR | os.O_APPEND if write else os.O_RDONLY) | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        try:
            return os.open(_EVENTS_NAME, flags, dir_fd=line_fd)
        except FileNotFoundError:
            if not create:
                raise
        try:
            return os.open(_EVENTS_NAME, flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=line_fd)
        except FileExistsError:
            return os.open(_EVENTS_NAME, flags, dir_fd=line_fd)
    except OSError as error:
        raise EventValidationError("events.jsonl could not be safely opened") from error


def _read_live(line_fd: int, event_fd: int) -> bytes:
    info = os.fstat(event_fd)
    path_info = os.stat(_EVENTS_NAME, dir_fd=line_fd, follow_symlinks=False)
    if (info.st_dev, info.st_ino) != (path_info.st_dev, path_info.st_ino):
        raise EventValidationError("events.jsonl identity changed while locked")
    os.lseek(event_fd, 0, os.SEEK_SET)
    content = _read_all(event_fd)
    if len(content) != info.st_size:
        raise EventValidationError("events.jsonl changed while locked")
    return content


def _read_archive(line_fd: int) -> tuple[bytes, bytes]:
    try:
        fd = os.open(ARCHIVE_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=line_fd)
    except FileNotFoundError:
        return b"", b""
    except OSError as error:
        raise EventValidationError("event archive could not be safely opened") from error
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_ARCHIVE_BYTES:
            raise EventValidationError("event archive must be a regular file no larger than 16 MiB")
        compressed = _read_all(fd)
    finally:
        os.close(fd)
    return compressed, _decompress_archive(compressed)


def _decompress_archive(compressed: bytes) -> bytes:
    if len(compressed) > _MAX_ARCHIVE_BYTES:
        raise EventValidationError("event archive exceeds 16 MiB")
    try:
        with gzip.GzipFile(fileobj=BytesIO(compressed)) as stream:
            raw = stream.read(_MAX_ARCHIVE_BYTES + 1)
    except (OSError, EOFError, zlib.error) as error:
        raise EventValidationError("event archive is not valid gzip") from error
    if not raw or len(raw) > _MAX_ARCHIVE_BYTES or not raw.endswith(b"\n"):
        raise EventValidationError("event archive has an invalid uncompressed size or missing trailing newline")
    return raw


def _combine_history(archived: bytes, live: bytes) -> bytes:
    # Publication can finish before the old live suffix is truncated. Its
    # exact bytes are already part of the archive in that recoverable state.
    return archived if archived.endswith(live) else archived + live


def _verified_history(line_fd: int, content: bytes) -> list[dict[str, Any]]:
    events = _parse_event_lines(content)
    _verify_events(events)
    _verify_anchor(line_fd, events)
    return events


def _clear_live_suffix(line_fd: int, event_fd: int) -> None:
    os.fsync(line_fd)
    os.ftruncate(event_fd, 0)
    os.fsync(event_fd)


def _tail_sha256(events: list[dict[str, Any]]) -> str:
    return events[-1]["event_sha256"] if events else ZERO_SHA256


def _read_all(fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 64 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _parse_event_lines(content: bytes) -> list[dict[str, Any]]:
    if not content:
        return []
    if not content.endswith(b"\n"):
        raise EventValidationError("events.jsonl is truncated: missing trailing newline")
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(content[:-1].split(b"\n"), start=1):
        if not line or len(line) > MAX_EVENT_BYTES:
            raise EventValidationError(f"events.jsonl line {index} is invalid or exceeds 16 KiB")
        try:
            decoded = line.decode("utf-8")
            parsed = json.loads(decoded, object_pairs_hook=_reject_duplicate_keys)
        except (UnicodeDecodeError, json.JSONDecodeError, EventValidationError) as error:
            raise EventValidationError(f"events.jsonl line {index} is not valid canonical JSON") from error
        if not isinstance(parsed, dict):
            raise EventValidationError(f"events.jsonl line {index} must be an object")
        if canonical_event_bytes(parsed) != line:
            raise EventValidationError(f"events.jsonl line {index} is not canonical JSON")
        rows.append(parsed)
    return rows


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EventValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _verify_events(events: list[dict[str, Any]]) -> None:
    seen_ids: set[str] = set()
    previous_sha256 = ZERO_SHA256
    for index, event in enumerate(events, start=1):
        validated = validate_event(event, previous_sha256=previous_sha256)
        event_id = validated["event_id"]
        if event_id in seen_ids:
            raise EventValidationError(f"duplicate event_id at line {index}")
        if validated != event:
            raise EventValidationError(f"events.jsonl line {index} changed during validation")
        seen_ids.add(event_id)
        previous_sha256 = validated["event_sha256"]


def _write_all(fd: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        written = os.write(fd, content[offset:])
        if written <= 0:
            raise EventValidationError("could not append a complete event")
        offset += written


def _write_anchor(devlines_root: Path, line_fd: int, count: int, tail_sha256: str) -> None:
    anchor = canonical_event_bytes({"event_count": count, "tail_event_sha256": tail_sha256}) + b"\n"
    _publish_log_file(devlines_root, line_fd, _ANCHOR_NAME, anchor)


def _publish_log_file(devlines_root: Path, line_fd: int, name: str, content: bytes) -> None:
    # Stage outside the formal line directory so a verifier sees only
    # published files, even if the writer stops before the atomic rename.
    staging_fd = _open_directory(devlines_root.parent, "event staging directory")
    temporary = f".devline-{name}-{uuid.uuid4().hex}.tmp"
    fd = -1
    try:
        fd = os.open(temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=staging_fd)
        _write_all(fd, content)
        os.fsync(fd)
        os.lseek(fd, 0, os.SEEK_SET)
        if _read_all(fd) != content:
            raise EventValidationError(f"staged {name} failed byte-for-byte verification")
        os.close(fd)
        fd = -1
        os.replace(temporary, name, src_dir_fd=staging_fd, dst_dir_fd=line_fd)
        os.fsync(line_fd)
        os.fsync(staging_fd)
    except OSError as error:
        raise EventValidationError(f"could not durably publish {name}") from error
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary, dir_fd=staging_fd)
        except FileNotFoundError:
            pass
        finally:
            os.close(staging_fd)


def _verify_anchor(line_fd: int, events: list[dict[str, Any]], *, allow_uninitialized: bool = False) -> None:
    try:
        fd = os.open(_ANCHOR_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=line_fd)
    except FileNotFoundError as error:
        if allow_uninitialized:
            try:
                os.stat("context-pack.manifest.json", dir_fd=line_fd, follow_symlinks=False)
            except FileNotFoundError:
                return
        raise EventValidationError("events tail anchor is missing") from error
    except OSError as error:
        raise EventValidationError("events tail anchor could not be safely opened") from error
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise EventValidationError("events tail anchor must be a regular file")
        try:
            anchor = json.loads(_read_all(fd).decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
        except (UnicodeDecodeError, json.JSONDecodeError, EventValidationError) as error:
            raise EventValidationError("events tail anchor is invalid") from error
    finally:
        os.close(fd)
    expected = {
        "event_count": len(events),
        "tail_event_sha256": _tail_sha256(events),
    }
    if anchor != expected:
        raise EventValidationError("events tail anchor detects truncation, reordering, or replacement")
