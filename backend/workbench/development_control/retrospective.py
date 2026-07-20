"""Deterministic, read-only devline retrospective generation.

``events.jsonl`` remains the sole source of process facts.  This module first
uses the event log verifier and only then renders a Markdown derivative.  The
derivative has no clock, random identifier, or mutable event input, so the
same verified history produces the same bytes.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime
import json
import os
from pathlib import Path
import stat
from typing import Any
import uuid

from .events import (
    EventValidationError,
    ZERO_SHA256,
    canonical_event_bytes,
    validate_event,
    validate_line_id,
    verify_log,
)


_FAILURE_TYPES = frozenset({"FAILURE", "ERROR", "GAP"})
_NON_EXECUTED_GATE_SUBTYPES = frozenset({"skipped"})
_WITHDRAWN_REVIEW_SUBTYPES = frozenset({"withdrawn", "withdrawal"})
_MAX_METADATA_BYTES = 2 * 1024 * 1024


def generate_retrospective(devlines_root: Path, line_id: str) -> Path:
    """Render and atomically replace a line's derived ``RETROSPECTIVE.md``.

    This function never appends, edits, or otherwise opens ``events.jsonl``
    for writing.  It uses a same-directory temporary file so a completed
    replacement is atomic for consumers of the derived report.
    """

    report = render_retrospective(devlines_root, line_id)
    line_fd = _open_line_directory(devlines_root, line_id)
    try:
        _atomic_write(line_fd, "RETROSPECTIVE.md", report.encode("utf-8"))
    finally:
        os.close(line_fd)
    return devlines_root / line_id / "RETROSPECTIVE.md"


def render_retrospective(devlines_root: Path, line_id: str) -> str:
    """Return a byte-stable retrospective for one verified development line."""

    validate_line_id(line_id)
    events = _read_verified_events(devlines_root, line_id)
    goal = _read_goal(devlines_root, line_id)
    metrics = _metrics(events)
    return _render(line_id, goal, events, metrics)


def read_verified_events(devlines_root: Path, line_id: str) -> list[dict[str, Any]]:
    """Return the stable, hash-verified event snapshot used by derivations."""

    validate_line_id(line_id)
    return _read_verified_events(devlines_root, line_id)


def verify_completed_retrospective(devlines_root: Path, line_id: str) -> None:
    """Require a completed line's derived report to match its verified log."""

    events = _read_verified_events(devlines_root, line_id)
    if _final_state(events) not in {"COMPLETED", "CLOSED"}:
        return
    expected = render_retrospective(devlines_root, line_id).encode("utf-8")
    line_fd = _open_line_directory(devlines_root, line_id)
    try:
        actual = _read_child(line_fd, "RETROSPECTIVE.md")
    finally:
        os.close(line_fd)
    if actual != expected:
        raise EventValidationError("completed RETROSPECTIVE.md does not match verified events")


def _read_verified_events(devlines_root: Path, line_id: str) -> list[dict[str, Any]]:
    """Read a stable snapshot only after formal chain/anchor verification.

    ``events.py`` deliberately owns the log validation rules.  We invoke its
    public verifier before and after the no-follow snapshot, then validate the
    snapshot again with its public event contract.  A concurrent controlled
    append causes the second verifier to observe a different count/tail and we
    retry once rather than deriving a report from a mixed history.
    """

    for _attempt in range(2):
        before = verify_log(devlines_root, line_id)
        line_fd = _open_line_directory(devlines_root, line_id)
        try:
            data = _read_child(line_fd, "events.jsonl")
        finally:
            os.close(line_fd)
        events = _parse_verified_snapshot(data)
        after = verify_log(devlines_root, line_id)
        if before == after and before["event_count"] == len(events):
            return events
    raise EventValidationError("events.jsonl changed while retrospective snapshot was read")


def _parse_verified_snapshot(data: bytes) -> list[dict[str, Any]]:
    if not data:
        return []
    if not data.endswith(b"\n"):
        raise EventValidationError("events.jsonl is truncated: missing trailing newline")
    previous = ZERO_SHA256
    events: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for line_number, raw_line in enumerate(data.splitlines(), start=1):
        try:
            event = json.loads(raw_line.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
        except (UnicodeDecodeError, json.JSONDecodeError, EventValidationError) as error:
            raise EventValidationError(f"events.jsonl line {line_number} is not valid canonical JSON") from error
        if not isinstance(event, dict) or canonical_event_bytes(event) != raw_line:
            raise EventValidationError(f"events.jsonl line {line_number} is not canonical JSON")
        validated = validate_event(event, previous_sha256=previous)
        if validated != event or event["event_id"] in seen_ids:
            raise EventValidationError(f"events.jsonl line {line_number} failed validation")
        seen_ids.add(event["event_id"])
        previous = event["event_sha256"]
        events.append(event)
    return events


def _read_goal(devlines_root: Path, line_id: str) -> str:
    line_fd = _open_line_directory(devlines_root, line_id)
    try:
        try:
            raw = _read_child(line_fd, "context-pack.manifest.json", max_bytes=_MAX_METADATA_BYTES)
        except FileNotFoundError:
            # Legacy files are intentionally read-only during the migration;
            # formal lines use the frozen manifest below.
            try:
                raw = _read_child(line_fd, "line.json", max_bytes=_MAX_METADATA_BYTES)
            except FileNotFoundError:
                return line_id
            source = "legacy"
        else:
            source = "formal"
    finally:
        os.close(line_fd)
    try:
        metadata = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, EventValidationError) as error:
        raise EventValidationError(f"{source} line metadata must be valid JSON") from error
    if source == "formal" and isinstance(metadata, dict):
        request = metadata.get("request")
        goal = request.get("objective", line_id) if isinstance(request, dict) else line_id
    else:
        goal = metadata.get("goal", line_id) if isinstance(metadata, dict) else line_id
    return goal if isinstance(goal, str) and goal.strip() else line_id


def _open_line_directory(devlines_root: Path, line_id: str) -> int:
    validate_line_id(line_id)
    try:
        root_info = os.lstat(devlines_root)
        if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
            raise EventValidationError("devlines root must be a non-symlink directory")
        root_fd = os.open(devlines_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise EventValidationError("devlines root is unavailable") from error
    try:
        return os.open(line_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
    except OSError as error:
        raise EventValidationError("devline directory must exist and must not be a symlink") from error
    finally:
        os.close(root_fd)


def _read_child(line_fd: int, name: str, *, max_bytes: int | None = None) -> bytes:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=line_fd)
    except FileNotFoundError:
        raise
    except OSError as error:
        raise EventValidationError(f"{name} could not be safely opened") from error
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise EventValidationError(f"{name} must be a regular file")
        if max_bytes is not None and info.st_size > max_bytes:
            raise EventValidationError(f"{name} exceeds its maximum size")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 64 * 1024)
            if not chunk:
                data = b"".join(chunks)
                if len(data) != info.st_size:
                    raise EventValidationError(f"{name} changed while it was read")
                return data
            chunks.append(chunk)
    finally:
        os.close(fd)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EventValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    failure_events = [event for event in events if event["type"] in _FAILURE_TYPES]
    problem_events = [event for event in events if event["type"] in _FAILURE_TYPES | {"WASTE"}]
    by_lesson = Counter(event["lesson_key"] for event in failure_events)
    seen_lessons: set[str] = set()
    repeated = 0
    for event in failure_events:
        if event["lesson_key"] in seen_lessons:
            repeated += 1
        seen_lessons.add(event["lesson_key"])

    incident_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        incident_rows[event["incident_id"]].append(event)
    repairs: list[int] = []
    unresolved = 0
    for incident_id in sorted({event["incident_id"] for event in failure_events}):
        rows = incident_rows[incident_id]
        starts = [event for event in rows if event["type"] in _FAILURE_TYPES]
        start = min(starts, key=_timestamp_ms)
        resolved = [event for event in rows if event["resolution"] == "resolved" and _timestamp_ms(event) >= _timestamp_ms(start)]
        if not resolved:
            unresolved += 1
            continue
        repairs.append(_timestamp_ms(min(resolved, key=_timestamp_ms)) - _timestamp_ms(start))

    review_changes = [event for event in events if event["type"] == "REVIEW" and event["subtype"] == "changes_required"]
    review_rounds_by_artifact: dict[str, list[int]] = defaultdict(list)
    for event in review_changes:
        if "artifact_digest" in event and "review_round" in event:
            review_rounds_by_artifact[event["artifact_digest"]].append(event["review_round"])
    review_rounds = [sum(rounds) / len(rounds) for _, rounds in sorted(review_rounds_by_artifact.items())]
    withdrawn = sum(event["type"] == "REVIEW" and event["subtype"] in _WITHDRAWN_REVIEW_SUBTYPES for event in events)

    churn: dict[str, tuple[int, int]] = {}
    for label in ("spec", "plan"):
        candidates = [
            event
            for event in events
            if event["type"] in {"REVIEW", "STATE_CHANGE"}
            and label in event.get("tags", [])
            and "artifact_digest" in event
        ]
        previous: str | None = None
        changes = 0
        for event in candidates:
            digest = event["artifact_digest"]
            if previous is not None and digest != previous:
                changes += 1
            previous = digest
        churn[label] = (changes, len(candidates))

    executed_gates = [
        event for event in events if event["type"] == "GATE" and event["subtype"] not in _NON_EXECUTED_GATE_SUBTYPES
    ]
    seen_gate_runs: set[tuple[str, str, str]] = set()
    wasted_gates = 0
    for event in executed_gates:
        fingerprint = event.get("gate_fingerprint")
        input_digest = event.get("artifact_digest")
        evidence = event["evidence"]["sha256"]
        if not isinstance(fingerprint, str) or not isinstance(input_digest, str):
            continue
        key = (fingerprint, input_digest, evidence)
        if key in seen_gate_runs:
            wasted_gates += 1
        seen_gate_runs.add(key)

    retries = [event for event in events if event["type"] == "STATE_CHANGE" and event["subtype"] == "retry"]
    same_state_retries = sum(event.get("state_from") == event.get("state_to") for event in retries)
    waste_events = [event for event in events if event["type"] == "WASTE"]
    measured_waste = [event for event in waste_events if "resource_usage" in event]
    tokens = sum(sum(event["resource_usage"].values()) for event in measured_waste)

    return {
        "failure_events": failure_events,
        "problem_events": problem_events,
        "lesson_counts": by_lesson,
        "repeated": repeated,
        "repairs": repairs,
        "unresolved": unresolved,
        "review_changes": review_changes,
        "review_rounds": review_rounds,
        "withdrawn": withdrawn,
        "churn": churn,
        "executed_gates": executed_gates,
        "wasted_gates": wasted_gates,
        "retries": retries,
        "same_state_retries": same_state_retries,
        "waste_events": waste_events,
        "measured_waste": measured_waste,
        "tokens": tokens,
    }


def _render(line_id: str, goal: str, events: list[dict[str, Any]], metrics: Mapping[str, Any]) -> str:
    final_state = _final_state(events)
    lines = [f"# Retrospective — {line_id}", "", "## Goal", "", _markdown_text(goal), "", "## Final status", "", _markdown_text(final_state), "", "## Metrics", ""]
    lines.extend(_metric_lines(events, metrics))
    for event_type, heading in (("FAILURE", "All failures"), ("ERROR", "All errors"), ("GAP", "All gaps"), ("WASTE", "All waste")):
        lines.extend(["", f"## {heading}", ""])
        matching = [event for event in events if event["type"] == event_type]
        if matching:
            lines.extend(_event_summary(index, event) for index, event in _indexed(events, matching))
        else:
            lines.append("- None recorded.")
    lines.extend(["", "## Root causes and solutions", ""])
    lines.extend(_root_cause_lines(metrics["problem_events"]) or ["- None recorded."])
    lines.extend(["", "## Added tests", ""])
    test_refs = sorted({event["evidence"]["ref"] for event in events if event["evidence"]["kind"] == "test"})
    lines.extend([f"- `{_markdown_text(ref)}`" for ref in test_refs] or ["- No test evidence recorded."])
    lines.extend(["", "## New rules", ""])
    lines.extend(_rule_lines(Counter(event["lesson_key"] for event in metrics["problem_events"])) or ["- No rule candidate recorded."])
    lines.extend(["", "## Future guidance", ""])
    guidance = sorted({event["lesson"] for event in events if event["type"] in _FAILURE_TYPES | {"WASTE", "REVIEW"}})
    lines.extend([f"- {_markdown_text(lesson)}" for lesson in guidance] or ["- No guidance recorded."])
    lines.extend(["", "## Event index", ""])
    if events:
        lines.extend(_event_index_line(index, event) for index, event in enumerate(events, start=1))
    else:
        lines.append("- No events recorded.")
    return "\n".join(lines) + "\n"


def _metric_lines(events: list[dict[str, Any]], metrics: Mapping[str, Any]) -> list[str]:
    failure_count = len(metrics["failure_events"])
    total_count = len(events)
    if failure_count:
        frequency_line = f"Failure frequency: {failure_count}/{total_count} ({failure_count / total_count:.1%}; {failure_count * 100 / total_count:.1f} per 100 events)"
    else:
        frequency_line = "Failure frequency: N/A (sample=0)"
    distinct_lessons = len(metrics["lesson_counts"])
    recurrent = sum(count >= 2 for count in metrics["lesson_counts"].values())
    repairs = sorted(metrics["repairs"])
    median = _median_ms(repairs)
    average_round = (sum(metrics["review_rounds"]) / len(metrics["review_rounds"]) if metrics["review_rounds"] else None)
    spec_changes, spec_sample = metrics["churn"]["spec"]
    plan_changes, plan_sample = metrics["churn"]["plan"]
    return [
        f"- {frequency_line}",
        f"- Repeat rate: {_ratio(metrics['repeated'], failure_count)}",
        f"- Recurrence rate: {_ratio(recurrent, distinct_lessons)}",
        f"- MTTR: {'N/A (sample=0' if median is None else f'median={median} ms (sample={len(repairs)}'}; unresolved={metrics['unresolved']})",
        f"- Review churn: changes_required={len(metrics['review_changes'])}; average_review_round={'N/A (sample=0)' if average_round is None else f'{average_round:.1f} (sample={len(metrics["review_rounds"])})'}; withdrawn={metrics['withdrawn']}",
        f"- Spec churn: {'N/A (sample=0)' if not spec_sample else f'{spec_changes} (sample={spec_sample})'}",
        f"- Plan churn: {'N/A (sample=0)' if not plan_sample else f'{plan_changes} (sample={plan_sample})'}",
        f"- Gate waste rate: {_ratio(metrics['wasted_gates'], len(metrics['executed_gates']))}",
        f"- Same-state retry rate: {_ratio(metrics['same_state_retries'], len(metrics['retries']))}",
        f"- Token waste: {'N/A (sample=0)' if not metrics['waste_events'] else ('N/A (sample=0; coverage=0/' + str(len(metrics['waste_events'])) + ')' if not metrics['measured_waste'] else str(metrics['tokens']) + ' (coverage=' + str(len(metrics['measured_waste'])) + '/' + str(len(metrics['waste_events'])) + ')')}",
    ]


def _ratio(numerator: int, denominator: int) -> str:
    return "N/A (sample=0)" if not denominator else f"{numerator}/{denominator} ({numerator / denominator:.1%})"


def _median_ms(values: list[int]) -> int | None:
    if not values:
        return None
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) // 2


def _timestamp_ms(event: Mapping[str, Any]) -> int:
    return int(datetime.fromisoformat(str(event["timestamp"]).replace("Z", "+00:00")).timestamp() * 1000)


def _final_state(events: Iterable[Mapping[str, Any]]) -> str:
    state_changes = [event for event in events if event["type"] == "STATE_CHANGE" and "state_to" in event]
    return str(state_changes[-1]["state_to"]) if state_changes else "IN_PROGRESS (no state transition recorded)"


def _indexed(events: list[dict[str, Any]], matching: list[dict[str, Any]]) -> Iterable[tuple[int, dict[str, Any]]]:
    positions = {event["event_id"]: index for index, event in enumerate(events, start=1)}
    return ((positions[event["event_id"]], event) for event in matching)


def _event_summary(index: int, event: Mapping[str, Any]) -> str:
    return f"- #{index} {_markdown_text(str(event['timestamp']))} `{event['subtype']}`; cause_status: `{event['cause_status']}`; cause: {_markdown_text(str(event['cause']))}; resolution: `{event['resolution']}`; lesson: {_markdown_text(str(event['lesson']))}"


def _root_cause_lines(events: list[dict[str, Any]]) -> list[str]:
    counts = Counter(event["lesson_key"] for event in events)
    lines: list[str] = []
    for lesson_key in sorted(counts):
        sample = next(event for event in events if event["lesson_key"] == lesson_key)
        lines.append(f"- `{lesson_key}`: occurrences={counts[lesson_key]}; cause_status: `{sample['cause_status']}`; root cause: {_markdown_text(str(sample['cause']))}; solution: `{sample['resolution']}`")
    return lines


def _rule_lines(counts: Counter[str]) -> list[str]:
    return [f"- `{key}`: line experience occurrence(s)={counts[key]}" for key in sorted(counts)]


def _event_index_line(index: int, event: Mapping[str, Any]) -> str:
    return f"- #{index}: `{event['event_id']}` | {event['timestamp']} | {event['type']}/{event['subtype']} | incident=`{event['incident_id']}` | lesson_key=`{event['lesson_key']}` | event_sha256=`{event['event_sha256']}`"


def _markdown_text(value: str) -> str:
    return " ".join(value.replace("\r", "\n").splitlines()).replace("`", "\\`")


def _atomic_write(line_fd: int, name: str, contents: bytes) -> None:
    temporary = f".{name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    fd = -1
    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=line_fd,
        )
        _write_all(fd, contents)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(temporary, name, src_dir_fd=line_fd, dst_dir_fd=line_fd)
        os.fsync(line_fd)
    except OSError as error:
        raise EventValidationError("could not atomically write retrospective") from error
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary, dir_fd=line_fd)
        except FileNotFoundError:
            pass


def _write_all(fd: int, contents: bytes) -> None:
    offset = 0
    while offset < len(contents):
        written = os.write(fd, contents[offset:])
        if written <= 0:
            raise EventValidationError("could not write retrospective")
        offset += written
