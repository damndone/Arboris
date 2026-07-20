#!/usr/bin/env python3
"""Formal development-line control CLI.

This is the only supported entry point for *new* FMS lines.  The former
``devline_memory.py`` and its pre-formal records stay read-only during the
migration; this command neither reads nor rewrites them as evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

from workbench.development_control.context_pack import (
    ContextPackError,
    ContextPackRequest,
    create_context_pack,
    record_context_refresh_required,
    record_context_rescope_required,
    refresh_context_pack,
    rescope_context_pack,
    verify_context_pack,
)
from workbench.development_control.events import EventValidationError, append_event, validate_line_id, verify_log
from workbench.development_control.promotion import promote
from workbench.development_control.retrospective import (
    generate_retrospective,
    read_verified_events,
    verify_completed_retrospective,
)


_FORMAL_FILES = frozenset({"RETROSPECTIVE.md", "context-pack.manifest.json", "context-pack.md", "events.jsonl", "events.jsonl.anchor"})
_LEGACY_FILES = frozenset({"CONTEXT_PACK.md", "RETROSPECTIVE.md", "events.jsonl", "line.json"})


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    root = Path(args.root)
    try:
        if args.command == "start":
            request = ContextPackRequest(
                objective=_read_objective(root, args.objective),
                baseline_sha=args.baseline_sha,
                tags=tuple(args.tag),
                affected_paths=tuple(args.affected_path),
                lesson_keys=tuple(args.lesson_key),
                allowed_paths=tuple(args.allowed_path),
                protected_paths=tuple(args.protected_path),
                dependencies=tuple(args.dependency),
                tests=tuple(args.test),
                known_gates=tuple(args.known_gate),
            )
            result = create_context_pack(root, args.line, request)
            _emit({"line_id": result.line_id, "manifest_sha256": result.manifest_sha256})
        elif args.command == "verify":
            if args.all:
                verified, quarantined = _formal_line_ids(root)
                results = [_verify_formal_line(root, line_id) for line_id in verified]
                _emit(
                    {
                        "verified_lines": [result.line_id for result in results],
                        "quarantined_legacy_lines": quarantined,
                    }
                )
            else:
                result = _verify_formal_line(root, args.line)
                _emit({"line_id": result.line_id, "manifest_sha256": result.manifest_sha256})
        elif args.command == "refresh-context":
            required = record_context_refresh_required(root, args.line)
            result = refresh_context_pack(root, args.line)
            _emit(
                {
                    "line_id": result.line_id,
                    "old_manifest_sha256": required.old_manifest_sha256,
                    "manifest_sha256": result.manifest_sha256,
                }
            )
        elif args.command == "rescope-context":
            required = record_context_rescope_required(
                root,
                args.line,
                affected_paths=tuple(args.affected_path),
                allowed_paths=None if args.allow_path is None else tuple(args.allow_path),
            )
            result = rescope_context_pack(
                root,
                args.line,
                affected_paths=tuple(args.affected_path),
                allowed_paths=None if args.allow_path is None else tuple(args.allow_path),
            )
            _emit(
                {
                    "line_id": result.line_id,
                    "old_manifest_sha256": required.old_manifest_sha256,
                    "manifest_sha256": result.manifest_sha256,
                }
            )
        elif args.command == "append":
            event = _read_json_object(root, args.event_file)
            validate_line_id(args.line)
            appended = append_event(root / ".agent" / "devlines", args.line, event)
            output: dict[str, object] = {"event_id": appended["event_id"], "event_sha256": appended["event_sha256"]}
            if appended["type"] == "STATE_CHANGE" and appended.get("state_to") in {"COMPLETED", "CLOSED"}:
                report = generate_retrospective(root / ".agent" / "devlines", args.line)
                verify_completed_retrospective(root / ".agent" / "devlines", args.line)
                output["retrospective"] = report.relative_to(root).as_posix()
            _emit(output)
        elif args.command == "retrospective":
            output = generate_retrospective(root / ".agent" / "devlines", args.line)
            _emit({"line_id": args.line, "retrospective": output.relative_to(root).as_posix()})
        elif args.command == "promote":
            verified, quarantined = _formal_line_ids(root)
            events: list[dict[str, Any]] = []
            for line_id in verified:
                verify_context_pack(root, line_id)
                events.extend(read_verified_events(root / ".agent" / "devlines", line_id))
            result = promote(root / ".agent" / "development-control", events)
            _emit({"verified_lines": verified, "quarantined_legacy_lines": quarantined, "promotion": result})
        elif args.command == "index":
            verified, quarantined = _formal_line_ids(root)
            indexed, in_progress = _rebuild_retrospective_index(root, verified)
            _emit(
                {
                    "indexed_lines": indexed,
                    "in_progress_lines": in_progress,
                    "quarantined_legacy_lines": quarantined,
                }
            )
        else:  # argparse makes this unreachable.
            raise ContextPackError("unsupported command")
    except (ContextPackError, EventValidationError, OSError, ValueError) as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="freeze and create a new formal devline")
    start.add_argument("--line", required=True)
    start.add_argument("--objective", required=True, help="repository-relative UTF-8 objective file")
    start.add_argument("--baseline-sha", required=True)
    for flag, destination in (
        ("--tag", "tag"),
        ("--affected-path", "affected_path"),
        ("--lesson-key", "lesson_key"),
        ("--allowed-path", "allowed_path"),
        ("--protected-path", "protected_path"),
        ("--dependency", "dependency"),
        ("--test", "test"),
        ("--known-gate", "known_gate"),
    ):
        start.add_argument(flag, dest=destination, action="append", default=[])
    verify = commands.add_parser("verify", help="verify formal Context Packs and logs")
    verification_scope = verify.add_mutually_exclusive_group(required=True)
    verification_scope.add_argument("--line")
    verification_scope.add_argument("--all", action="store_true")
    refresh = commands.add_parser("refresh-context", help="audit and explicitly refresh a drifted Context Pack")
    refresh.add_argument("--line", required=True)
    rescope = commands.add_parser("rescope-context", help="audit and explicitly replace a line's scope")
    rescope.add_argument("--line", required=True)
    rescope.add_argument("--affected-path", action="append", default=[], required=True)
    rescope.add_argument("--allow-path", action="append")
    append = commands.add_parser("append", help="append one formal event from a repository-relative JSON object")
    append.add_argument("--line", required=True)
    append.add_argument("--event-file", required=True)
    retrospective = commands.add_parser("retrospective", help="derive a retrospective from a formal event log")
    retrospective.add_argument("--line", required=True)
    promote_parser = commands.add_parser("promote", help="apply 1/2/3 promotion to all formal verified lines")
    promote_parser.add_argument("--all", action="store_true", required=True)
    index = commands.add_parser("index", help="rebuild the completed-line retrospective index from formal evidence")
    index.add_argument("--all", action="store_true", required=True)
    return parser


def _read_objective(root: Path, value: str) -> str:
    return _read_relative_text(root, value, "objective")


def _read_json_object(root: Path, value: str) -> dict[str, Any]:
    raw = _read_relative_text(root, value, "event file")
    try:
        parsed = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (json.JSONDecodeError, ContextPackError) as error:
        raise ContextPackError("event file is not valid JSON") from error
    if not isinstance(parsed, dict):
        raise ContextPackError("event file must contain one JSON object")
    return parsed


def _read_relative_text(root: Path, value: str, label: str) -> str:
    candidate = Path(value)
    if not value or candidate.is_absolute() or ".." in candidate.parts:
        raise ContextPackError(f"{label} must be a repository-relative path")
    base = Path(root)
    try:
        root_info = os.lstat(base)
        if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
            raise ContextPackError("repository root must be a non-symlink directory")
        path = base
        for part in candidate.parts:
            path = path / part
            component = os.lstat(path)
            if stat.S_ISLNK(component.st_mode):
                raise ContextPackError(f"{label} must not traverse a symlink")
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ContextPackError(f"{label} must be a regular non-symlink file")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as error:
        raise ContextPackError(f"{label} is unavailable") from error
    try:
        data = os.read(fd, 64 * 1024 + 1)
        if len(data) > 64 * 1024:
            raise ContextPackError(f"{label} exceeds 64 KiB")
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ContextPackError(f"{label} must be UTF-8") from error
    finally:
        os.close(fd)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContextPackError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _emit(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _formal_line_ids(root: Path) -> tuple[list[str], list[str]]:
    directory = root / ".agent" / "devlines"
    try:
        info = os.lstat(directory)
    except OSError as error:
        raise ContextPackError("formal devlines root is unavailable") from error
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ContextPackError("formal devlines root must be a non-symlink directory")
    verified: list[str] = []
    quarantined: list[str] = []
    for line in sorted(directory.iterdir(), key=lambda item: item.name):
        detail = os.lstat(line)
        if stat.S_ISLNK(detail.st_mode) or not stat.S_ISDIR(detail.st_mode):
            raise ContextPackError("devlines root contains an unsafe non-directory entry")
        names = {entry.name for entry in line.iterdir()}
        if names == _FORMAL_FILES:
            validate_line_id(line.name)
            verified.append(line.name)
        elif _LEGACY_FILES <= names and not (names & {"context-pack.md", "context-pack.manifest.json", "events.jsonl.anchor"}):
            quarantined.append(line.name)
        else:
            raise ContextPackError(f"devline {line.name!r} is neither a formal line nor a quarantined legacy record")
    return verified, quarantined


def _rebuild_retrospective_index(root: Path, line_ids: list[str]) -> tuple[list[str], list[str]]:
    records: list[dict[str, Any]] = []
    indexed: list[str] = []
    in_progress: list[str] = []
    devlines = root / ".agent" / "devlines"
    for line_id in line_ids:
        _verify_formal_line(root, line_id)
        events = read_verified_events(devlines, line_id)
        state_changes = [event for event in events if event["type"] == "STATE_CHANGE" and "state_to" in event]
        final_state = state_changes[-1].get("state_to") if state_changes else None
        if final_state not in {"COMPLETED", "CLOSED"}:
            in_progress.append(line_id)
            continue
        manifest = json.loads((devlines / line_id / "context-pack.manifest.json").read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
        request = manifest["request"]
        lesson_keys = sorted({event["lesson_key"] for event in events if event["type"] in {"FAILURE", "ERROR", "GAP"}})
        summary = f"Completed formal devline {line_id}; final_state={final_state}; failure_lesson_keys=" + (", ".join(lesson_keys) if lesson_keys else "none")
        records.append(
            {
                "schema_version": 1,
                "line_id": line_id,
                "completed_at": state_changes[-1]["timestamp"],
                "tags": request["tags"],
                "affected_paths": request["affected_paths"],
                "lesson_keys": lesson_keys,
                "summary": summary,
                "summary_sha256": hashlib.sha256(summary.encode("utf-8")).hexdigest(),
            }
        )
        indexed.append(line_id)
    content = b"".join(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n" for record in records)
    _atomic_replace_control_file(root / ".agent" / "development-control", "retrospective-index.jsonl", content)
    return indexed, in_progress


def _verify_formal_line(root: Path, line_id: str):
    result = verify_context_pack(root, line_id)
    verify_completed_retrospective(root / ".agent" / "devlines", line_id)
    return result


def _atomic_replace_control_file(directory: Path, name: str, content: bytes) -> None:
    directory_fd = -1
    fd = -1
    temporary = f".{name}.{os.getpid()}.tmp"
    try:
        info = os.lstat(directory)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ContextPackError("development-control directory must be a non-symlink directory")
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        offset = 0
        while offset < len(content):
            written = os.write(fd, content[offset:])
            if written <= 0:
                raise ContextPackError("could not write retrospective index")
            offset += written
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    except OSError as error:
        raise ContextPackError("could not atomically replace retrospective index") from error
    finally:
        if fd >= 0:
            os.close(fd)
        if directory_fd >= 0:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
            os.close(directory_fd)


if __name__ == "__main__":
    raise SystemExit(main())
