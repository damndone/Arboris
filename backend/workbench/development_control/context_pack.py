"""Frozen, verified Context Packs for starting a development line.

This module deliberately owns no command-line policy.  It exposes a small
interface for the future CLI and makes every filesystem action relative to a
checked repository control root.  A pack is immutable after creation: callers
must explicitly refresh through a later control-plane command when rules
change, rather than letting a normal start/resume path rewrite history.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any
import uuid

from .events import EventValidationError, append_event, validate_line_id, verify_log
from .promotion import PromotionError, read_candidate_rules, read_global_rules


CONTEXT_PACK_SCHEMA_VERSION = 1
MAX_HISTORY_ITEMS = 10
MAX_HISTORY_BYTES = 80 * 1024
MAX_INDEX_BYTES = 1024 * 1024
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9-]{0,127}$")
_RFC3339_MILLIS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_FORMAL_FILES = frozenset(
    {
        "RETROSPECTIVE.md",
        "context-pack.manifest.json",
        "context-pack.md",
        "events.jsonl",
        "events.jsonl.anchor",
    }
)


class ContextPackError(ValueError):
    """A Context Pack cannot safely be created or trusted."""


class ContextPackDriftError(ContextPackError):
    """Enabled/candidate rules changed and require an explicit refresh."""


@dataclass(frozen=True)
class ContextRefreshRequired:
    """Durable before/after rule identity recorded before an explicit refresh."""

    line_id: str
    old_manifest_sha256: str
    old_rules_sha256: str
    new_rules_sha256: str


@dataclass(frozen=True)
class ContextRescopeRequired:
    """Durable before/after manifest identities for an explicit scope correction."""

    line_id: str
    old_manifest_sha256: str
    new_manifest_sha256: str


@dataclass(frozen=True)
class ContextPackRequest:
    """Validated, caller-supplied facts to freeze before a line starts."""

    objective: str
    baseline_sha: str
    tags: tuple[str, ...] = ()
    affected_paths: tuple[str, ...] = ()
    lesson_keys: tuple[str, ...] = ()
    allowed_paths: tuple[str, ...] = ()
    protected_paths: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    known_gates: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContextPackResult:
    line_id: str
    context_pack_path: Path
    manifest_path: Path
    manifest_sha256: str


@dataclass(frozen=True)
class _RescopePlan:
    request: ContextPackRequest
    pack: bytes
    manifest_bytes: bytes
    manifest_sha256: str
    old_allowed_paths: tuple[str, ...]
    new_allowed_paths: tuple[str, ...]


def create_context_pack(repo_root: Path, line_id: str, request: ContextPackRequest) -> ContextPackResult:
    """Create a new line's five formal files and its first durable event.

    Creation never overwrites a line.  All potentially untrusted history and
    rules are validated before the line directory is created.  The final
    ``line_started`` event is appended only after the pack and manifest are
    complete and durable.
    """

    root = _repository_root(repo_root)
    _validate_request(line_id, request)
    control = _control_dir(root, create=True)
    rules = _rule_snapshot(control)
    history = _select_history(_read_history_index(control), request)
    devlines = _devlines_dir(root, create=True)
    line = devlines / line_id
    _reject_existing_or_unsafe(line, "devline directory")

    created = False
    try:
        os.mkdir(line, 0o700)
        created = True
        _require_directory(line, "devline directory")
        pack = _render_context_pack(line_id, request, rules, history)
        pack_sha256 = _sha256(pack)
        manifest = _manifest(line_id, request, pack_sha256, rules, history)
        manifest_bytes = _canonical_json(manifest) + b"\n"
        manifest_sha256 = _sha256(manifest_bytes)
        manifest["manifest_sha256"] = manifest_sha256
        final_manifest = _canonical_json(manifest) + b"\n"

        _write_new_file(line, "context-pack.md", pack)
        _write_new_file(line, "context-pack.manifest.json", final_manifest)
        _write_new_file(line, "RETROSPECTIVE.md", b"# Retrospective\n\nStatus: IN_PROGRESS\n")
        _write_new_file(line, "events.jsonl", b"")
        _write_new_file(
            line,
            "events.jsonl.anchor",
            _canonical_json({"event_count": 0, "tail_event_sha256": "0" * 64}) + b"\n",
        )
        timestamp = _timestamp()
        event = {
            "schema_version": 1,
            "event_id": str(uuid.uuid4()),
            "timestamp": timestamp,
            "type": "STATE_CHANGE",
            "subtype": "line_started",
            "stage": "design",
            "cause_status": "not_applicable",
            "cause": "Context Pack was frozen before development started.",
            "evidence": {
                "kind": "context_pack",
                "ref": f".agent/devlines/{line_id}/context-pack.manifest.json",
                "sha256": manifest_sha256,
                "observed_at": timestamp,
            },
            "impact": "The line has an evidence-bound starting context.",
            "preventability": "unknown",
            "resolution": "not_applicable",
            "lesson": "Freeze the initial context before changing implementation state.",
            "incident_id": str(uuid.uuid4()),
            "lesson_key": "frozen-context-before-start",
            "links": [],
            "state_from": "CREATED",
            "state_to": "STARTED",
        }
        try:
            append_event(devlines, line_id, event)
        except EventValidationError as error:
            raise ContextPackError("could not append the initial line_started event") from error
        # The initial placeholder exists only to establish the formal five-file
        # layout before line_started.  Replace it immediately with the sole
        # event-derived report once the event log is durable.
        from .retrospective import generate_retrospective

        generate_retrospective(devlines, line_id)
        _ensure_formal_files(line)
        return ContextPackResult(line_id, line / "context-pack.md", line / "context-pack.manifest.json", manifest_sha256)
    except Exception:
        if created:
            _remove_new_line(line)
        raise


def verify_context_pack(repo_root: Path, line_id: str) -> ContextPackResult:
    """Verify frozen bytes and current rule identity without changing files.

    On rule drift this deliberately raises ``CONTEXT_REFRESH_REQUIRED``.  A
    caller must invoke an explicit refresh workflow; this read/verify operation
    never updates the pack or appends an event on its own.
    """

    root = _repository_root(repo_root)
    try:
        validate_line_id(line_id)
    except EventValidationError as error:
        raise ContextPackError(str(error)) from error
    line = _devlines_dir(root, create=False) / line_id
    _require_directory(line, "devline directory")
    _ensure_formal_files(line)
    pack = _read_regular_file(line / "context-pack.md", "context-pack.md")
    manifest_bytes = _read_regular_file(line / "context-pack.manifest.json", "context-pack.manifest.json")
    manifest = _parse_manifest(manifest_bytes)
    if manifest.get("line_id") != line_id:
        raise ContextPackError("manifest line_id does not match its directory")
    stored_manifest_hash = manifest.pop("manifest_sha256", None)
    if not isinstance(stored_manifest_hash, str) or not _SHA256.fullmatch(stored_manifest_hash):
        raise ContextPackError("manifest_sha256 is invalid")
    if _sha256(_canonical_json(manifest) + b"\n") != stored_manifest_hash:
        raise ContextPackError("manifest_sha256 does not match frozen manifest bytes")
    if manifest.get("context_pack_sha256") != _sha256(pack):
        raise ContextPackError("context-pack.md does not match its manifest")
    events = _parse_jsonl(_read_regular_file(line / "events.jsonl", "events.jsonl"), "events.jsonl")
    if not events or events[0].get("type") != "STATE_CHANGE" or events[0].get("subtype") != "line_started":
        raise ContextPackError("the first devline event must be line_started")
    evidence = events[0].get("evidence")
    line_started_manifest_sha256 = manifest.get("line_started_manifest_sha256", stored_manifest_hash)
    if not isinstance(evidence, dict) or evidence.get("sha256") != line_started_manifest_sha256:
        raise ContextPackError("line_started does not bind the frozen manifest")
    expected_rules = manifest.get("rules")
    if not isinstance(expected_rules, dict):
        raise ContextPackError("manifest rules snapshot is invalid")
    current_rules = _rule_snapshot(_control_dir(root, create=False))
    if current_rules != expected_rules:
        raise ContextPackDriftError("CONTEXT_REFRESH_REQUIRED: current rules differ from the frozen Context Pack")
    try:
        verify_log(_devlines_dir(root, create=False), line_id)
    except EventValidationError as error:
        raise ContextPackError("initial event log is not trustworthy") from error
    return ContextPackResult(line_id, line / "context-pack.md", line / "context-pack.manifest.json", stored_manifest_hash)


def record_context_refresh_required(repo_root: Path, line_id: str) -> ContextRefreshRequired:
    """Append the required drift audit event, without changing frozen context.

    This is intentionally a separate action from ``refresh_context_pack`` so
    callers cannot accidentally turn an ordinary verification into a mutable
    refresh.  Repeating the same request is idempotent once the exact old/new
    digest pair is already the tail event.
    """

    root, line, manifest, old_manifest_sha256 = _load_frozen_context(repo_root, line_id)
    current_rules = _rule_snapshot(_control_dir(root, create=False))
    old_rules = manifest["rules"]
    old_rules_sha256 = _rules_digest(old_rules)
    new_rules_sha256 = _rules_digest(current_rules)
    if current_rules == old_rules:
        raise ContextPackError("context rules have not drifted; refresh is not required")
    try:
        verify_log(_devlines_dir(root, create=False), line_id)
    except EventValidationError as error:
        raise ContextPackError("event log is not trustworthy before refresh audit") from error
    rows = _parse_jsonl(_read_regular_file(line / "events.jsonl", "events.jsonl"), "events.jsonl")
    if rows and _is_matching_refresh_required(rows[-1], old_manifest_sha256, old_rules_sha256, new_rules_sha256):
        return ContextRefreshRequired(line_id, old_manifest_sha256, old_rules_sha256, new_rules_sha256)
    _append_context_state_event(
        root,
        line_id,
        subtype="context_refresh_required",
        manifest_sha256=old_manifest_sha256,
        cause="Current development-control rules differ from the frozen Context Pack.",
        impact={"old_rules_sha256": old_rules_sha256, "new_rules_sha256": new_rules_sha256},
        lesson="Record rule drift before explicitly refreshing a development context.",
        state_from="CONTEXT_FROZEN",
        state_to="CONTEXT_REFRESH_REQUIRED",
    )
    return ContextRefreshRequired(line_id, old_manifest_sha256, old_rules_sha256, new_rules_sha256)


def refresh_context_pack(repo_root: Path, line_id: str) -> ContextPackResult:
    """Explicitly replace a drifted pack after its audit event is durable."""

    root, line, old_manifest, old_manifest_sha256 = _load_frozen_context(repo_root, line_id)
    try:
        verify_log(_devlines_dir(root, create=False), line_id)
    except EventValidationError as error:
        raise ContextPackError("event log is not trustworthy before explicit refresh") from error
    current_rules = _rule_snapshot(_control_dir(root, create=False))
    old_rules = old_manifest["rules"]
    if current_rules == old_rules:
        raise ContextPackError("context rules have not drifted; refresh is not required")
    old_rules_sha256 = _rules_digest(old_rules)
    new_rules_sha256 = _rules_digest(current_rules)
    rows = _parse_jsonl(_read_regular_file(line / "events.jsonl", "events.jsonl"), "events.jsonl")
    if not rows or not _is_matching_refresh_required(rows[-1], old_manifest_sha256, old_rules_sha256, new_rules_sha256):
        raise ContextPackError("context_refresh_required must be durably recorded before refresh")
    request = _request_from_manifest(old_manifest)
    history = _select_history(_read_history_index(_control_dir(root, create=False)), request)
    pack = _render_context_pack(line_id, request, current_rules, history)
    new_manifest = _manifest(
        line_id,
        request,
        _sha256(pack),
        current_rules,
        history,
        previous_manifest_sha256=old_manifest_sha256,
        refresh_generation=old_manifest["refresh_generation"] + 1,
        line_started_manifest_sha256=old_manifest.get("line_started_manifest_sha256", old_manifest_sha256),
    )
    new_manifest_sha256 = _sha256(_canonical_json(new_manifest) + b"\n")
    new_manifest["manifest_sha256"] = new_manifest_sha256
    _atomic_replace_file(line, "context-pack.md", pack)
    _atomic_replace_file(line, "context-pack.manifest.json", _canonical_json(new_manifest) + b"\n")
    _append_context_state_event(
        root,
        line_id,
        subtype="context_refreshed",
        manifest_sha256=new_manifest_sha256,
        cause="An explicit Context Pack refresh replaced the previously frozen rules snapshot.",
        impact={"old_rules_sha256": old_rules_sha256, "new_rules_sha256": new_rules_sha256},
        lesson="Refresh a Context Pack only after recording the exact rule drift.",
        state_from="CONTEXT_REFRESH_REQUIRED",
        state_to="CONTEXT_REFRESHED",
    )
    return verify_context_pack(root, line_id)


def record_context_rescope_required(
    repo_root: Path,
    line_id: str,
    *,
    affected_paths: tuple[str, ...],
    allowed_paths: tuple[str, ...] | None = None,
) -> ContextRescopeRequired:
    """Audit a requested scope correction without changing the frozen files.

    Unlike a rule refresh, a rescope preserves the current objective, selected
    history, and rules exactly.  The resulting digest pair is recorded before
    either frozen file changes, so an ordinary verify/resume path can never
    silently rewrite a line's scope.
    """

    root = _repository_root(repo_root)
    _validate_rescope_paths(root, affected_paths)
    _validate_rescope_allowed_paths(root, allowed_paths)
    # Do not combine a scope correction with unreviewed policy drift.
    verify_context_pack(root, line_id)
    _, line, old_manifest, old_manifest_sha256 = _load_frozen_context(root, line_id)
    try:
        verify_log(_devlines_dir(root, create=False), line_id)
    except EventValidationError as error:
        raise ContextPackError("event log is not trustworthy before rescope audit") from error
    rows = _parse_jsonl(_read_regular_file(line / "events.jsonl", "events.jsonl"), "events.jsonl")
    pending = _pending_rescope_completion(rows, old_manifest_sha256)
    if pending is not None:
        return ContextRescopeRequired(line_id, pending["old_manifest_sha256"], pending["new_manifest_sha256"])
    plan = _rescope_plan(root, line_id, old_manifest, old_manifest_sha256, affected_paths, allowed_paths)
    if rows and _is_matching_rescope_required(rows[-1], old_manifest_sha256, plan):
        return ContextRescopeRequired(line_id, old_manifest_sha256, plan.manifest_sha256)
    _append_context_state_event(
        root,
        line_id,
        subtype="context_rescope_required",
        manifest_sha256=old_manifest_sha256,
        cause="Affected paths differ from the frozen Context Pack and require an explicit scope correction.",
        impact=_rescope_impact(old_manifest_sha256, plan),
        lesson="Record the exact old and new manifest identities before correcting development scope.",
        state_from="CONTEXT_FROZEN",
        state_to="CONTEXT_RESCOPE_REQUIRED",
        lesson_key="context-pack-rescope",
    )
    return ContextRescopeRequired(line_id, old_manifest_sha256, plan.manifest_sha256)


def rescope_context_pack(
    repo_root: Path,
    line_id: str,
    *,
    affected_paths: tuple[str, ...],
    allowed_paths: tuple[str, ...] | None = None,
) -> ContextPackResult:
    """Create a new frozen manifest generation after a durable rescope audit."""

    root = _repository_root(repo_root)
    _validate_rescope_paths(root, affected_paths)
    _validate_rescope_allowed_paths(root, allowed_paths)
    verify_context_pack(root, line_id)
    _, line, old_manifest, old_manifest_sha256 = _load_frozen_context(root, line_id)
    try:
        verify_log(_devlines_dir(root, create=False), line_id)
    except EventValidationError as error:
        raise ContextPackError("event log is not trustworthy before explicit rescope") from error
    rows = _parse_jsonl(_read_regular_file(line / "events.jsonl", "events.jsonl"), "events.jsonl")
    pending = _pending_rescope_completion(rows, old_manifest_sha256)
    if pending is not None:
        _append_context_state_event(
            root,
            line_id,
            subtype="context_rescoped",
            manifest_sha256=old_manifest_sha256,
            cause="The audited Context Pack rescope was durably published and is now being completed.",
            impact=pending,
            lesson="Complete a previously audited Context Pack rescope without creating another generation.",
            state_from="CONTEXT_RESCOPE_REQUIRED",
            state_to="CONTEXT_RESCOPED",
            lesson_key="context-pack-rescope",
        )
        return verify_context_pack(root, line_id)
    plan = _rescope_plan(root, line_id, old_manifest, old_manifest_sha256, affected_paths, allowed_paths)
    if not rows or not _is_matching_rescope_required(rows[-1], old_manifest_sha256, plan):
        raise ContextPackError("context_rescope_required must be durably recorded before rescope")
    _atomic_replace_file(line, "context-pack.md", plan.pack)
    _atomic_replace_file(line, "context-pack.manifest.json", plan.manifest_bytes)
    _append_context_state_event(
        root,
        line_id,
        subtype="context_rescoped",
        manifest_sha256=plan.manifest_sha256,
        cause="An explicit Context Pack rescope replaced the affected-path snapshot.",
        impact=_rescope_impact(old_manifest_sha256, plan),
        lesson="Correct scope only through an audited, new frozen manifest generation.",
        state_from="CONTEXT_RESCOPE_REQUIRED",
        state_to="CONTEXT_RESCOPED",
        lesson_key="context-pack-rescope",
    )
    return verify_context_pack(root, line_id)


def _validate_request(line_id: str, request: ContextPackRequest) -> None:
    try:
        validate_line_id(line_id)
    except EventValidationError as error:
        raise ContextPackError(str(error)) from error
    if not isinstance(request, ContextPackRequest):
        raise ContextPackError("request must be a ContextPackRequest")
    if not isinstance(request.objective, str) or not request.objective.strip() or "\x00" in request.objective:
        raise ContextPackError("objective is required")
    if len(request.objective.encode("utf-8")) > 16 * 1024:
        raise ContextPackError("objective exceeds 16 KiB")
    if not isinstance(request.baseline_sha, str) or not _SHA1.fullmatch(request.baseline_sha):
        raise ContextPackError("baseline_sha must be an exact lowercase Git SHA")
    _validate_identifiers(request.tags, "tags")
    _validate_identifiers(request.lesson_keys, "lesson_keys")
    for values, label in (
        (request.affected_paths, "affected_paths"),
        (request.allowed_paths, "allowed_paths"),
        (request.protected_paths, "protected_paths"),
        (request.tests, "tests"),
    ):
        _validate_relative_paths(values, label)
    for values, label in ((request.dependencies, "dependencies"), (request.known_gates, "known_gates")):
        _validate_text_values(values, label)


def _validate_identifiers(values: Sequence[str], label: str) -> None:
    if not isinstance(values, tuple) or any(not isinstance(value, str) or not _IDENTIFIER.fullmatch(value) for value in values):
        raise ContextPackError(f"{label} must be a tuple of normalized identifiers")


def _validate_relative_paths(values: Sequence[str], label: str) -> None:
    if not isinstance(values, tuple):
        raise ContextPackError(f"{label} must be a tuple of repository-relative paths")
    for value in values:
        path = Path(value) if isinstance(value, str) else None
        if not isinstance(value, str) or not value or "\x00" in value or path.is_absolute() or ".." in path.parts:
            raise ContextPackError(f"{label} must contain repository-relative paths")


def _validate_rescope_paths(root: Path, affected_paths: tuple[str, ...]) -> None:
    """Reject a rescope request that could traverse a symlinked repository path."""

    _validate_relative_paths(affected_paths, "affected_paths")
    if not affected_paths:
        raise ContextPackError("rescope requires at least one affected_path")
    _reject_symlinked_relative_paths(root, affected_paths, "affected_paths")


def _validate_rescope_allowed_paths(root: Path, allowed_paths: tuple[str, ...] | None) -> None:
    """Validate an opt-in replacement allowlist without default widening."""

    if allowed_paths is None:
        return
    _validate_relative_paths(allowed_paths, "allowed_paths")
    if not allowed_paths:
        raise ContextPackError("rescope requires at least one allow_path when --allow-path is supplied")
    for value in allowed_paths:
        parts = Path(value).parts
        if (
            not parts
            or parts in {("backend",), ("backend", "workbench"), ("tests",), ("frontend",), ("scripts",), (".agent",)}
            or (parts[0] == "backend" and len(parts) < 4)
        ):
            raise ContextPackError("allowed_paths contains a too broad boundary path")
    _reject_symlinked_relative_paths(root, allowed_paths, "allowed_paths")


def _reject_symlinked_relative_paths(root: Path, values: tuple[str, ...], label: str) -> None:
    for value in values:
        current = root
        for part in Path(value).parts:
            current = current / part
            try:
                info = os.lstat(current)
            except FileNotFoundError:
                # A declared future path is allowed, but no existing component
                # may redirect the request outside the checked repository.
                break
            except OSError as error:
                raise ContextPackError(f"{label} could not be checked") from error
            if stat.S_ISLNK(info.st_mode):
                raise ContextPackError(f"{label} must not traverse a symlink")


def _validate_text_values(values: Sequence[str], label: str) -> None:
    if not isinstance(values, tuple) or any(not isinstance(value, str) or not value.strip() or "\x00" in value for value in values):
        raise ContextPackError(f"{label} must be a tuple of non-empty text")


def _repository_root(path: Path) -> Path:
    root = Path(path)
    _require_directory(root, "repository root")
    return root


def _control_dir(root: Path, *, create: bool) -> Path:
    agent = root / ".agent"
    _ensure_directory(agent, "control root", create=create)
    control = agent / "development-control"
    _ensure_directory(control, "development control directory", create=create)
    return control


def _devlines_dir(root: Path, *, create: bool) -> Path:
    agent = root / ".agent"
    _ensure_directory(agent, "control root", create=create)
    devlines = agent / "devlines"
    _ensure_directory(devlines, "devlines root", create=create)
    return devlines


def _ensure_directory(path: Path, label: str, *, create: bool) -> None:
    try:
        _require_directory(path, label)
    except ContextPackError:
        if not create:
            raise
        try:
            os.mkdir(path, 0o700)
        except FileExistsError:
            pass
        except OSError as error:
            raise ContextPackError(f"{label} could not be created") from error
        _require_directory(path, label)


def _require_directory(path: Path, label: str) -> None:
    try:
        info = os.lstat(path)
    except OSError as error:
        raise ContextPackError(f"{label} is unavailable") from error
    if stat.S_ISLNK(info.st_mode):
        raise ContextPackError(f"{label} must not be a symlink")
    if not stat.S_ISDIR(info.st_mode):
        raise ContextPackError(f"{label} must be a directory")


def _reject_existing_or_unsafe(path: Path, label: str) -> None:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    except OSError as error:
        raise ContextPackError(f"{label} could not be checked") from error
    if stat.S_ISLNK(info.st_mode):
        raise ContextPackError(f"{label} must not be a symlink")
    raise ContextPackError(f"{label} already exists; Context Packs are immutable")


def _rule_snapshot(control: Path) -> dict[str, Any]:
    try:
        # Reuse the promotion module's exact schemas and per-record hashes;
        # Context Pack must never freeze a merely JSON-shaped rule as policy.
        global_rules = read_global_rules(control)
        candidates = read_candidate_rules(control)
    except PromotionError as error:
        raise ContextPackError("development-control global rules or candidates are invalid") from error
    snapshot = {
        "global_rules": global_rules,
        "global_rules_sha256": _sha256(_canonical_json(global_rules)),
        "candidate_rules": candidates,
        "candidate_rules_sha256": _sha256(_canonical_json(candidates)),
    }
    snapshot["rules_sha256"] = _rules_digest(snapshot)
    return snapshot


def _rules_digest(rules: Mapping[str, Any]) -> str:
    return _sha256(_canonical_json(rules))


def _read_history_index(control: Path) -> list[dict[str, Any]]:
    path = control / "retrospective-index.jsonl"
    if not _path_exists(path):
        return []
    raw = _read_regular_file(path, "retrospective-index.jsonl")
    if len(raw) > MAX_INDEX_BYTES:
        raise ContextPackError("retrospective index exceeds 1 MiB")
    records = _parse_jsonl(raw, "retrospective index")
    seen: set[str] = set()
    for record in records:
        _validate_history_record(record)
        if record["line_id"] in seen:
            raise ContextPackError("retrospective index contains duplicate line_id")
        seen.add(record["line_id"])
    return records


def _read_optional_json(path: Path, label: str, default: Any) -> Any:
    if not _path_exists(path):
        return default
    raw = _read_regular_file(path, label)
    return _parse_json(raw, label)


def _read_optional_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    if not _path_exists(path):
        return []
    return _parse_jsonl(_read_regular_file(path, label), label)


def _path_exists(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as error:
        raise ContextPackError(f"{path.name} could not be checked") from error
    return True


def _read_regular_file(path: Path, label: str) -> bytes:
    try:
        info = os.lstat(path)
    except OSError as error:
        raise ContextPackError(f"{label} is unavailable") from error
    if stat.S_ISLNK(info.st_mode):
        raise ContextPackError(f"{label} must not be a symlink")
    if not stat.S_ISREG(info.st_mode):
        raise ContextPackError(f"{label} must be a regular file")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise ContextPackError(f"{label} could not be safely opened") from error
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise ContextPackError(f"{label} changed while being opened")
        chunks: list[bytes] = []
        while chunk := os.read(fd, 64 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _parse_json(raw: bytes, label: str) -> Any:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ContextPackError) as error:
        raise ContextPackError(f"{label} is not valid JSON") from error
    return value


def _parse_jsonl(raw: bytes, label: str) -> list[dict[str, Any]]:
    if raw and not raw.endswith(b"\n"):
        raise ContextPackError(f"{label} is truncated")
    records: list[dict[str, Any]] = []
    for number, line in enumerate(raw.splitlines(), start=1):
        if not line:
            raise ContextPackError(f"{label} line {number} is empty")
        value = _parse_json(line, f"{label} line {number}")
        if not isinstance(value, dict):
            raise ContextPackError(f"{label} line {number} must be an object")
        records.append(value)
    return records


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContextPackError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _validate_history_record(record: Mapping[str, Any]) -> None:
    required = {"schema_version", "line_id", "completed_at", "tags", "affected_paths", "lesson_keys", "summary", "summary_sha256"}
    if set(record) != required or record.get("schema_version") != 1:
        raise ContextPackError("retrospective index has an invalid record schema")
    try:
        validate_line_id(record["line_id"])
    except (EventValidationError, TypeError) as error:
        raise ContextPackError("retrospective index has an invalid line_id") from error
    _validate_time(record["completed_at"], "completed_at")
    for field in ("tags", "lesson_keys"):
        values = record[field]
        if not isinstance(values, list) or any(not isinstance(value, str) or not _IDENTIFIER.fullmatch(value) for value in values):
            raise ContextPackError(f"retrospective index {field} is invalid")
    paths = record["affected_paths"]
    if not isinstance(paths, list):
        raise ContextPackError("retrospective index affected_paths is invalid")
    _validate_relative_paths(tuple(paths), "retrospective index affected_paths")
    summary = record["summary"]
    if not isinstance(summary, str) or not summary.strip() or "\x00" in summary:
        raise ContextPackError("retrospective index summary is invalid")
    if len(summary.encode("utf-8")) > MAX_HISTORY_BYTES:
        raise ContextPackError("history summary exceeds the 80 KiB safety limit")
    if not isinstance(record["summary_sha256"], str) or record["summary_sha256"] != _sha256(summary.encode("utf-8")):
        raise ContextPackError("retrospective index summary_sha256 is invalid")


def _validate_time(value: Any, label: str) -> None:
    if not isinstance(value, str) or not _RFC3339_MILLIS.fullmatch(value):
        raise ContextPackError(f"{label} must be UTC RFC3339 with milliseconds")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ContextPackError(f"{label} is not a real timestamp") from error
    if parsed.tzinfo != UTC:
        raise ContextPackError(f"{label} must be UTC")


def _select_history(records: Iterable[dict[str, Any]], request: ContextPackRequest) -> dict[str, Any]:
    tags, paths, lessons = set(request.tags), set(request.affected_paths), set(request.lesson_keys)
    ranked: list[tuple[int, dict[str, Any]]] = []
    all_hashes: list[dict[str, str]] = []
    for record in records:
        score = (
            len(tags & set(record["tags"]))
            + len(lessons & set(record["lesson_keys"]))
            + sum(_path_matches(path, candidate) for path in paths for candidate in record["affected_paths"])
        )
        ranked.append((score, record))
        all_hashes.append({"line_id": record["line_id"], "summary_sha256": record["summary_sha256"]})
    # Completion time must be newest first while line id remains ascending.
    ranked.sort(key=lambda row: row[1]["line_id"])
    ranked.sort(key=lambda row: row[1]["completed_at"], reverse=True)
    ranked.sort(key=lambda row: row[0], reverse=True)
    selected: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    used = 0
    for score, record in ranked:
        if score == 0:
            excluded.append({"line_id": record["line_id"], "reason": "no_relevance"})
            continue
        summary_bytes = len(record["summary"].encode("utf-8"))
        if len(selected) >= MAX_HISTORY_ITEMS:
            excluded.append({"line_id": record["line_id"], "reason": "item_limit"})
        elif used + summary_bytes > MAX_HISTORY_BYTES:
            excluded.append({"line_id": record["line_id"], "reason": "byte_budget"})
        else:
            selected.append(
                {
                    "line_id": record["line_id"],
                    "completed_at": record["completed_at"],
                    "relevance": score,
                    "summary": record["summary"],
                    "summary_sha256": record["summary_sha256"],
                }
            )
            used += summary_bytes
    return {
        "selection_algorithm": "v1: tag+lesson_key+path overlap; relevance desc, completed_at desc, line_id asc",
        "limits": {"max_items": MAX_HISTORY_ITEMS, "max_summary_bytes": MAX_HISTORY_BYTES},
        "all_summary_hashes": sorted(all_hashes, key=lambda item: item["line_id"]),
        "selected": selected,
        "excluded": excluded,
        "selected_summary_bytes": used,
    }


def _path_matches(request_path: str, historical_path: str) -> int:
    return int(request_path == historical_path or request_path.startswith(historical_path + "/") or historical_path.startswith(request_path + "/"))


def _render_context_pack(line_id: str, request: ContextPackRequest, rules: Mapping[str, Any], history: Mapping[str, Any]) -> bytes:
    lines = [
        "# Frozen Context Pack",
        "",
        f"Line: `{line_id}`",
        f"Baseline SHA: `{request.baseline_sha}`",
        "",
        "## Objective",
        request.objective.strip(),
        "",
        "## Boundary",
        _bullet("Affected paths", request.affected_paths),
        _bullet("Allowed paths", request.allowed_paths),
        _bullet("Protected paths", request.protected_paths),
        _bullet("Dependencies", request.dependencies),
        _bullet("Tests", request.tests),
        _bullet("Known gates", request.known_gates),
        "",
        "## Rules",
        "```json",
        _canonical_json(rules).decode("utf-8"),
        "```",
        "",
        "## Selected historical lessons",
    ]
    selected = history["selected"]
    if not selected:
        lines.append("No matching completed retrospective was selected.")
    else:
        for item in selected:
            lines.extend((f"### {item['line_id']} ({item['completed_at']})", "", item["summary"], ""))
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _bullet(label: str, values: Sequence[str]) -> str:
    return f"- {label}: " + (", ".join(f"`{value}`" for value in values) if values else "none")


def _manifest(
    line_id: str,
    request: ContextPackRequest,
    pack_sha256: str,
    rules: Mapping[str, Any],
    history: Mapping[str, Any],
    *,
    previous_manifest_sha256: str | None = None,
    refresh_generation: int = 0,
    line_started_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    result = {
        "schema_version": CONTEXT_PACK_SCHEMA_VERSION,
        "line_id": line_id,
        "baseline_sha": request.baseline_sha,
        "request": _request_data(request),
        "context_pack_sha256": pack_sha256,
        "rules": dict(rules),
        "history": dict(history),
        "previous_manifest_sha256": previous_manifest_sha256,
        "refresh_generation": refresh_generation,
    }
    if line_started_manifest_sha256 is not None:
        result["line_started_manifest_sha256"] = line_started_manifest_sha256
    return result


def _request_data(request: ContextPackRequest) -> dict[str, Any]:
    return {
        "objective": request.objective.strip(),
        "baseline_sha": request.baseline_sha,
        "tags": list(request.tags),
        "affected_paths": list(request.affected_paths),
        "lesson_keys": list(request.lesson_keys),
        "allowed_paths": list(request.allowed_paths),
        "protected_paths": list(request.protected_paths),
        "dependencies": list(request.dependencies),
        "tests": list(request.tests),
        "known_gates": list(request.known_gates),
    }


def _request_from_manifest(manifest: Mapping[str, Any]) -> ContextPackRequest:
    request = manifest.get("request")
    expected = {
        "objective", "baseline_sha", "tags", "affected_paths", "lesson_keys", "allowed_paths",
        "protected_paths", "dependencies", "tests", "known_gates",
    }
    if not isinstance(request, dict) or set(request) != expected:
        raise ContextPackError("context pack manifest request is invalid")
    try:
        result = ContextPackRequest(
            objective=request["objective"],
            baseline_sha=request["baseline_sha"],
            tags=tuple(request["tags"]),
            affected_paths=tuple(request["affected_paths"]),
            lesson_keys=tuple(request["lesson_keys"]),
            allowed_paths=tuple(request["allowed_paths"]),
            protected_paths=tuple(request["protected_paths"]),
            dependencies=tuple(request["dependencies"]),
            tests=tuple(request["tests"]),
            known_gates=tuple(request["known_gates"]),
        )
    except TypeError as error:
        raise ContextPackError("context pack manifest request is invalid") from error
    _validate_request(manifest.get("line_id"), result)
    return result


def _rescope_plan(
    root: Path,
    line_id: str,
    old_manifest: Mapping[str, Any],
    old_manifest_sha256: str,
    affected_paths: tuple[str, ...],
    allowed_paths: tuple[str, ...] | None,
) -> _RescopePlan:
    """Build a replacement pack without reselecting history or rules."""

    _validate_rescope_paths(root, affected_paths)
    _validate_rescope_allowed_paths(root, allowed_paths)
    old_request = _request_from_manifest(old_manifest)
    new_allowed_paths = old_request.allowed_paths if allowed_paths is None else allowed_paths
    if affected_paths == old_request.affected_paths and new_allowed_paths == old_request.allowed_paths:
        raise ContextPackError("affected_paths and allowed_paths already match the frozen Context Pack")
    request = ContextPackRequest(
        objective=old_request.objective,
        baseline_sha=old_request.baseline_sha,
        tags=old_request.tags,
        affected_paths=affected_paths,
        lesson_keys=old_request.lesson_keys,
        allowed_paths=new_allowed_paths,
        protected_paths=old_request.protected_paths,
        dependencies=old_request.dependencies,
        tests=old_request.tests,
        known_gates=old_request.known_gates,
    )
    _validate_request(line_id, request)
    rules = old_manifest.get("rules")
    history = old_manifest.get("history")
    if not isinstance(rules, Mapping) or not isinstance(history, Mapping):
        raise ContextPackError("frozen Context Pack rules or history is invalid")
    pack = _render_context_pack(line_id, request, rules, history)
    manifest = _manifest(
        line_id,
        request,
        _sha256(pack),
        rules,
        history,
        previous_manifest_sha256=old_manifest_sha256,
        # This field is the monotonically increasing Context Pack generation;
        # refresh and rescope are both explicit generation transitions.
        refresh_generation=old_manifest["refresh_generation"] + 1,
        line_started_manifest_sha256=old_manifest.get("line_started_manifest_sha256", old_manifest_sha256),
    )
    manifest_sha256 = _sha256(_canonical_json(manifest) + b"\n")
    manifest["manifest_sha256"] = manifest_sha256
    return _RescopePlan(
        request=request,
        pack=pack,
        manifest_bytes=_canonical_json(manifest) + b"\n",
        manifest_sha256=manifest_sha256,
        old_allowed_paths=old_request.allowed_paths,
        new_allowed_paths=new_allowed_paths,
    )


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ContextPackError("value cannot be encoded as canonical JSON") from error


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_new_file(directory: Path, name: str, content: bytes) -> None:
    if name not in _FORMAL_FILES:
        raise ContextPackError("attempted to create an unexpected formal file")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    directory_fd = -1
    try:
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
    except OSError as error:
        raise ContextPackError(f"{name} could not be safely created") from error
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)
    # The separate directory descriptor is intentionally short-lived; reopening it
    # with O_NOFOLLOW makes this path robust against a replacement directory.
    try:
        offset = 0
        while offset < len(content):
            written = os.write(fd, content[offset:])
            if written <= 0:
                raise ContextPackError(f"{name} could not be fully written")
            offset += written
        os.fsync(fd)
    finally:
        os.close(fd)


def _ensure_formal_files(line: Path) -> None:
    names = {entry.name for entry in line.iterdir()}
    if names != _FORMAL_FILES:
        raise ContextPackError("devline directory does not contain exactly the five formal files")
    for name in _FORMAL_FILES:
        _read_regular_file(line / name, name)


def _parse_manifest(raw: bytes) -> dict[str, Any]:
    value = _parse_json(raw, "context-pack.manifest.json")
    if not isinstance(value, dict) or value.get("schema_version") != CONTEXT_PACK_SCHEMA_VERSION:
        raise ContextPackError("context pack manifest has an invalid schema version")
    required = {
        "schema_version", "line_id", "baseline_sha", "request", "context_pack_sha256", "rules", "history",
        "previous_manifest_sha256", "refresh_generation", "manifest_sha256",
    }
    allowed = required | {"line_started_manifest_sha256"}
    if set(value) != required and set(value) != allowed:
        raise ContextPackError("context pack manifest has an invalid schema")
    if not isinstance(value["baseline_sha"], str) or not _SHA1.fullmatch(value["baseline_sha"]):
        raise ContextPackError("context pack manifest baseline_sha is invalid")
    if not isinstance(value["context_pack_sha256"], str) or not _SHA256.fullmatch(value["context_pack_sha256"]):
        raise ContextPackError("context pack manifest context_pack_sha256 is invalid")
    if value["previous_manifest_sha256"] is not None and (
        not isinstance(value["previous_manifest_sha256"], str) or not _SHA256.fullmatch(value["previous_manifest_sha256"])
    ):
        raise ContextPackError("context pack manifest previous_manifest_sha256 is invalid")
    if "line_started_manifest_sha256" in value and (
        not isinstance(value["line_started_manifest_sha256"], str) or not _SHA256.fullmatch(value["line_started_manifest_sha256"])
    ):
        raise ContextPackError("context pack manifest line_started_manifest_sha256 is invalid")
    if not isinstance(value["refresh_generation"], int) or isinstance(value["refresh_generation"], bool) or value["refresh_generation"] < 0:
        raise ContextPackError("context pack manifest refresh_generation is invalid")
    _request_from_manifest(value)
    return value


def _load_frozen_context(repo_root: Path, line_id: str) -> tuple[Path, Path, dict[str, Any], str]:
    root = _repository_root(repo_root)
    try:
        validate_line_id(line_id)
    except EventValidationError as error:
        raise ContextPackError(str(error)) from error
    line = _devlines_dir(root, create=False) / line_id
    _require_directory(line, "devline directory")
    _ensure_formal_files(line)
    pack = _read_regular_file(line / "context-pack.md", "context-pack.md")
    manifest = _parse_manifest(_read_regular_file(line / "context-pack.manifest.json", "context-pack.manifest.json"))
    if manifest.get("line_id") != line_id:
        raise ContextPackError("manifest line_id does not match its directory")
    manifest_sha256 = manifest.pop("manifest_sha256", None)
    if not isinstance(manifest_sha256, str) or not _SHA256.fullmatch(manifest_sha256):
        raise ContextPackError("manifest_sha256 is invalid")
    if _sha256(_canonical_json(manifest) + b"\n") != manifest_sha256:
        raise ContextPackError("manifest_sha256 does not match frozen manifest bytes")
    if manifest.get("context_pack_sha256") != _sha256(pack):
        raise ContextPackError("context-pack.md does not match its manifest")
    rows = _parse_jsonl(_read_regular_file(line / "events.jsonl", "events.jsonl"), "events.jsonl")
    if not rows or rows[0].get("type") != "STATE_CHANGE" or rows[0].get("subtype") != "line_started":
        raise ContextPackError("the first devline event must be line_started")
    evidence = rows[0].get("evidence")
    line_started_manifest_sha256 = manifest.get("line_started_manifest_sha256", manifest_sha256)
    if not isinstance(evidence, dict) or evidence.get("sha256") != line_started_manifest_sha256:
        raise ContextPackError("line_started does not bind the frozen manifest")
    return root, line, manifest, manifest_sha256


def _is_matching_refresh_required(
    event: Mapping[str, Any], old_manifest_sha256: str, old_rules_sha256: str, new_rules_sha256: str
) -> bool:
    return (
        event.get("type") == "STATE_CHANGE"
        and event.get("subtype") == "context_refresh_required"
        and isinstance(event.get("evidence"), dict)
        and event["evidence"].get("sha256") == old_manifest_sha256
        and event.get("impact") == {"old_rules_sha256": old_rules_sha256, "new_rules_sha256": new_rules_sha256}
    )


def _rescope_impact(old_manifest_sha256: str, plan: _RescopePlan) -> dict[str, Any]:
    return {
        "old_manifest_sha256": old_manifest_sha256,
        "new_manifest_sha256": plan.manifest_sha256,
        "old_allowed_paths": list(plan.old_allowed_paths),
        "new_allowed_paths": list(plan.new_allowed_paths),
    }


def _is_matching_rescope_required(event: Mapping[str, Any], old_manifest_sha256: str, plan: _RescopePlan) -> bool:
    return (
        event.get("type") == "STATE_CHANGE"
        and event.get("subtype") == "context_rescope_required"
        and isinstance(event.get("evidence"), dict)
        and event["evidence"].get("sha256") == old_manifest_sha256
        and event.get("impact") == _rescope_impact(old_manifest_sha256, plan)
    )


def _pending_rescope_completion(
    rows: Sequence[Mapping[str, Any]], current_manifest_sha256: str
) -> dict[str, Any] | None:
    """Recognize the only recoverable interval after atomic replacement.

    A process can stop after publishing the already-audited new files but
    before appending ``context_rescoped``.  The durable required event contains
    both identities, letting the explicit command complete that exact planned
    generation without inventing a new scope change.
    """

    if not rows:
        return None
    event = rows[-1]
    impact = event.get("impact")
    if (
        event.get("type") != "STATE_CHANGE"
        or event.get("subtype") != "context_rescope_required"
        or not isinstance(impact, dict)
    ):
        return None
    old_manifest_sha256 = impact.get("old_manifest_sha256")
    new_manifest_sha256 = impact.get("new_manifest_sha256")
    if (
        isinstance(old_manifest_sha256, str)
        and _SHA256.fullmatch(old_manifest_sha256)
        and isinstance(new_manifest_sha256, str)
        and new_manifest_sha256 == current_manifest_sha256
        and isinstance(impact.get("old_allowed_paths"), list)
        and isinstance(impact.get("new_allowed_paths"), list)
        and all(isinstance(value, str) for value in impact["old_allowed_paths"])
        and all(isinstance(value, str) for value in impact["new_allowed_paths"])
    ):
        return dict(impact)
    return None


def _append_context_state_event(
    root: Path,
    line_id: str,
    *,
    subtype: str,
    manifest_sha256: str,
    cause: str,
    impact: dict[str, Any],
    lesson: str,
    state_from: str,
    state_to: str,
    lesson_key: str = "context-pack-rule-drift",
) -> None:
    timestamp = _timestamp()
    event = {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "timestamp": timestamp,
        "type": "STATE_CHANGE",
        "subtype": subtype,
        "stage": "integration",
        "cause_status": "known",
        "cause": cause,
        "evidence": {
            "kind": "context_pack",
            "ref": f".agent/devlines/{line_id}/context-pack.manifest.json",
            "sha256": manifest_sha256,
            "observed_at": timestamp,
        },
        "impact": impact,
        "preventability": "preventable",
        "resolution": "resolved",
        "lesson": lesson,
        "incident_id": str(uuid.uuid4()),
        "lesson_key": lesson_key,
        "links": [],
        "state_from": state_from,
        "state_to": state_to,
    }
    try:
        append_event(_devlines_dir(root, create=False), line_id, event)
    except EventValidationError as error:
        raise ContextPackError(f"could not append {subtype}") from error


def _atomic_replace_file(directory: Path, name: str, content: bytes) -> None:
    if name not in {"context-pack.md", "context-pack.manifest.json"}:
        raise ContextPackError("attempted to replace an unexpected formal file")
    directory_fd = -1
    fd = -1
    temporary = f".{name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        offset = 0
        while offset < len(content):
            written = os.write(fd, content[offset:])
            if written <= 0:
                raise ContextPackError(f"{name} could not be fully written")
            offset += written
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    except OSError as error:
        raise ContextPackError(f"{name} could not be atomically replaced") from error
    finally:
        if fd >= 0:
            os.close(fd)
        if directory_fd >= 0:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            os.close(directory_fd)


def _timestamp() -> str:
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _remove_new_line(line: Path) -> None:
    """Best-effort rollback of only files this module is permitted to create."""

    try:
        _require_directory(line, "new devline directory")
        for name in _FORMAL_FILES:
            try:
                info = os.lstat(line / name)
            except FileNotFoundError:
                continue
            if stat.S_ISREG(info.st_mode):
                os.unlink(line / name)
        os.rmdir(line)
    except OSError:
        # Preserve evidence rather than risk deleting a changed/concurrent path.
        return
