"""Append-only failure memory and development-efficiency control plane.

This tool deliberately uses only local JSONL and Markdown.  It never estimates
missing measurements and it never rewrites an event history.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


EVENT_TYPES = {"FAILURE", "ERROR", "GAP", "WASTE", "REVIEW", "GATE", "STATE_CHANGE"}
REQUIRED_FIELDS = (
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
)
LINE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class EventValidationError(ValueError):
    """Raised before an invalid event can enter an append-only history."""


def _agent_root(root: Path) -> Path:
    return root if root.name == ".agent" else root / ".agent"


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise EventValidationError("timestamp must be an RFC3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EventValidationError("timestamp must be RFC3339") from exc
    if parsed.tzinfo is None:
        raise EventValidationError("timestamp must include an offset")
    return parsed.astimezone(UTC)


def _fingerprint(event: Mapping[str, object]) -> str:
    cause = " ".join(str(event["cause"]).casefold().split())
    return "|".join((str(event["type"]), str(event["subtype"]).casefold(), cause))


def _read_events(line_dir: Path) -> list[dict[str, object]]:
    event_file = line_dir / "events.jsonl"
    if not event_file.exists():
        return []
    rows: list[dict[str, object]] = []
    for number, raw in enumerate(event_file.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EventValidationError(f"invalid JSONL at {event_file}:{number}") from exc
        if not isinstance(row, dict):
            raise EventValidationError(f"event at {event_file}:{number} is not an object")
        validate_event(row)
        rows.append(row)
    return rows


def validate_event(event: Mapping[str, object]) -> None:
    missing = [field for field in REQUIRED_FIELDS if field not in event]
    if missing:
        raise EventValidationError(f"event missing required fields: {', '.join(missing)}")
    _parse_timestamp(event["timestamp"])
    if event["type"] not in EVENT_TYPES:
        raise EventValidationError(f"unsupported event type: {event['type']!r}")
    for field in ("subtype", "stage", "cause_status", "cause", "preventability", "resolution", "lesson"):
        if not isinstance(event[field], str) or not event[field].strip():
            raise EventValidationError(f"{field} must be a non-empty string")
    if not isinstance(event["evidence"], (str, list, dict)):
        raise EventValidationError("evidence must be a string, list, or object")
    if not isinstance(event["impact"], (str, list, dict)):
        raise EventValidationError("impact must be a string, list, or object")
    try:
        json.dumps(event, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise EventValidationError("event must be JSON serializable without non-finite values") from exc


def init_devline(root: Path, line_id: str, *, goal: str) -> Path:
    if not LINE_ID.fullmatch(line_id):
        raise EventValidationError("line_id must be lowercase letters, digits, _ or -")
    if not goal.strip():
        raise EventValidationError("goal must not be empty")
    line_dir = _agent_root(root) / "devlines" / line_id
    line_dir.mkdir(parents=True, exist_ok=True)
    event_file = line_dir / "events.jsonl"
    event_file.touch(exist_ok=True)
    metadata = line_dir / "line.json"
    if not metadata.exists():
        metadata.write_text(json.dumps({"line_id": line_id, "goal": goal}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return line_dir


def append_event(line_dir: Path, event: Mapping[str, object]) -> None:
    validate_event(event)
    event_file = line_dir / "events.jsonl"
    if not event_file.exists():
        raise EventValidationError("initialize the devline before appending events")
    payload = json.dumps(dict(event), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    with event_file.open("a", encoding="utf-8") as handle:
        handle.write(payload + "\n")
        handle.flush()


def _all_lines(root: Path) -> list[Path]:
    directory = _agent_root(root) / "devlines"
    return sorted((path for path in directory.iterdir() if path.is_dir()), key=lambda path: path.name) if directory.exists() else []


def promote_knowledge(root: Path) -> dict[str, int]:
    agent_root = _agent_root(root)
    occurrences: Counter[str] = Counter()
    lines_by_fingerprint: dict[str, set[str]] = defaultdict(set)
    examples: dict[str, dict[str, object]] = {}
    for line_dir in _all_lines(agent_root):
        for event in _read_events(line_dir):
            if event["type"] not in {"FAILURE", "ERROR", "GAP", "WASTE", "GATE", "REVIEW"}:
                continue
            key = _fingerprint(event)
            occurrences[key] += 1
            lines_by_fingerprint[key].add(line_dir.name)
            examples.setdefault(key, event)

    promotion_dir = agent_root / "development"
    promotion_dir.mkdir(parents=True, exist_ok=True)
    candidates = []
    mandatory = []
    for key in sorted(occurrences):
        count = occurrences[key]
        rule = {
            "fingerprint": key,
            "occurrences": count,
            "lines": sorted(lines_by_fingerprint[key]),
            "lesson": examples[key]["lesson"],
            "resolution": examples[key]["resolution"],
        }
        if count >= 2:
            candidates.append(rule)
        if count >= 3:
            mandatory.append(rule)
    (promotion_dir / "candidate_global_rules.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Global Development Rules", "", "Generated from repeated devline events. Mandatory rules have appeared at least three times.", ""]
    for rule in mandatory:
        lines.append(f"- `{rule['fingerprint']}` — {rule['lesson']} (resolution: {rule['resolution']})")
    if not mandatory:
        lines.append("- No mandatory promoted rules yet.")
    (promotion_dir / "global_rules.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"line_lessons": len(occurrences), "candidate_global_rules": len(candidates), "mandatory_global_rules": len(mandatory)}


def _minutes_between(start: dict[str, object], end: dict[str, object]) -> float:
    return (_parse_timestamp(end["timestamp"]) - _parse_timestamp(start["timestamp"])).total_seconds() / 60


def generate_retrospective(line_dir: Path) -> Path:
    events = _read_events(line_dir)
    metadata_file = line_dir / "line.json"
    metadata = json.loads(metadata_file.read_text(encoding="utf-8")) if metadata_file.exists() else {"goal": line_dir.name}
    failures = [event for event in events if event["type"] in {"FAILURE", "ERROR", "GAP", "WASTE"}]
    fingerprints = Counter(_fingerprint(event) for event in failures)
    resolutions = [event for event in events if event["type"] == "STATE_CHANGE"]
    repair_minutes = []
    for failure in failures:
        match = next((event for event in resolutions if event["subtype"] == failure["subtype"] and _parse_timestamp(event["timestamp"]) >= _parse_timestamp(failure["timestamp"])), None)
        if match is not None:
            repair_minutes.append(_minutes_between(failure, match))
    repeat_count = sum(count - 1 for count in fingerprints.values() if count > 1)
    repeat_rate = repeat_count / len(failures) if failures else 0.0
    review_churn = sum(event["type"] == "REVIEW" for event in events)
    spec_churn = sum(event["type"] == "REVIEW" and "spec" in str(event["stage"]).casefold() for event in events)
    plan_churn = sum(event["type"] == "REVIEW" and "plan" in str(event["stage"]).casefold() for event in events)
    gate_events = [event for event in events if event["type"] == "GATE"]
    wasted_gates = sum("waste" in str(event["impact"]).casefold() or "blocked" in str(event["resolution"]).casefold() for event in gate_events)
    token_measurements = [
        impact.get("tokens")
        for event in events
        if isinstance((impact := event.get("impact")), dict)
        and impact.get("tokens_measured") is True
        and isinstance(impact.get("tokens"), (int, float))
    ]
    token_waste: int | float | str = sum(token_measurements) if token_measurements else "unknown"

    report = [
        f"# Retrospective — {line_dir.name}", "", f"## Goal\n\n{metadata.get('goal', line_dir.name)}", "",
        "## Final status\n\nGenerated from the append-only event history; release acceptance is determined separately by the release ledger.", "",
        "## Metrics", "",
        f"- Failure frequency: {len(failures)}", f"- Repeat rate: {repeat_rate:.1%}",
        f"- Recurrence rate: {(sum(count > 1 for count in fingerprints.values()) / len(fingerprints)) if fingerprints else 0.0:.1%}",
        f"- MTTR: {(sum(repair_minutes) / len(repair_minutes)) if repair_minutes else 'unknown'}{' minutes' if repair_minutes else ''}",
        f"- Review churn: {review_churn}", f"- Spec churn: {spec_churn}", f"- Plan churn: {plan_churn}",
        f"- Gate waste rate: {(wasted_gates / len(gate_events)) if gate_events else 0.0:.1%}",
        f"- Same-state retry rate: {repeat_rate:.1%}", f"- Token waste: {token_waste}", "",
        "## All failures", "",
    ]
    categories = (("FAILURE", "failures"), ("ERROR", "errors"), ("GAP", "gaps"), ("WASTE", "waste"))
    for index, (event_type, label) in enumerate(categories):
        if index:
            report.extend(["", f"## All {label}", ""])
        category_events = [event for event in events if event["type"] == event_type]
        if category_events:
            for event in category_events:
                report.append(f"- {event['timestamp']} [{event['subtype']}] cause: {event['cause']}; resolution: {event['resolution']}; lesson: {event['lesson']}")
        else:
            report.append("- None recorded.")
    report.extend(["", "## Root causes and solutions", ""])
    for key, count in sorted(fingerprints.items()):
        sample = next(event for event in failures if _fingerprint(event) == key)
        report.append(f"- {key}: {count} occurrence(s); root cause: {sample['cause']}; solution: {sample['resolution']}")
    if not fingerprints:
        report.append("- No promoted lesson yet.")
    evidence_tests = sorted({str(event["evidence"].get("test")) for event in events if isinstance(event["evidence"], dict) and event["evidence"].get("test")})
    report.extend(["", "## Added tests", ""])
    report.extend([f"- {test}" for test in evidence_tests] or ["- No test evidence recorded."])
    report.extend(["", "## New rules", ""])
    report.extend([f"- {event['lesson']}" for event in events if event["type"] in {"FAILURE", "ERROR", "GAP", "WASTE", "REVIEW"}] or ["- No rule candidate recorded."])
    report.extend(["", "## Future guidance", ""])
    report.extend([f"- {event['lesson']}" for event in events if event["type"] in {"FAILURE", "ERROR", "GAP", "WASTE", "REVIEW"}] or ["- No future guidance recorded."])
    target = line_dir / "RETROSPECTIVE.md"
    target.write_text("\n".join(report) + "\n", encoding="utf-8")
    return target


def build_context_pack(root: Path, target_line: Path, *, keywords: Sequence[str]) -> Path:
    agent_root = _agent_root(root)
    lowered = {keyword.casefold() for keyword in keywords if keyword.strip()}
    rules = agent_root / "development" / "global_rules.md"
    parts = [f"# Context Pack — {target_line.name}", "", "## Global development rules", "", rules.read_text(encoding="utf-8") if rules.exists() else "- No promoted rule yet.", "", "## Relevant historical retrospectives", ""]
    matched = 0
    for line_dir in _all_lines(agent_root):
        if line_dir == target_line:
            continue
        retrospective = line_dir / "RETROSPECTIVE.md"
        if not retrospective.exists():
            continue
        text = retrospective.read_text(encoding="utf-8")
        if lowered and not any(keyword in text.casefold() for keyword in lowered):
            continue
        parts.append(f"- [{line_dir.name}]({retrospective.relative_to(agent_root.parent).as_posix()}): relevant to {', '.join(sorted(lowered)) or 'all history'}")
        matched += 1
    if not matched:
        parts.append("- No matching retrospective found.")
    target = target_line / "CONTEXT_PACK.md"
    target.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return target


def close_devline(root: Path, line_id: str) -> Path:
    """Perform the mandatory line-close memory actions in one deterministic step."""
    agent_root = _agent_root(root)
    retrospective = generate_retrospective(agent_root / "devlines" / line_id)
    promote_knowledge(agent_root)
    return retrospective


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init")
    init.add_argument("line_id")
    init.add_argument("--goal", required=True)
    append = subparsers.add_parser("append")
    append.add_argument("line_id")
    append.add_argument("--event-json", required=True)
    retrospective = subparsers.add_parser("retrospective")
    retrospective.add_argument("line_id")
    close = subparsers.add_parser("close")
    close.add_argument("line_id")
    subparsers.add_parser("promote")
    context = subparsers.add_parser("context")
    context.add_argument("line_id")
    context.add_argument("--keywords", default="")
    args = parser.parse_args()
    root = _agent_root(args.root)
    if args.command == "init":
        print(init_devline(root, args.line_id, goal=args.goal))
    elif args.command == "append":
        line = root / "devlines" / args.line_id
        append_event(line, json.loads(args.event_json))
    elif args.command == "retrospective":
        print(generate_retrospective(root / "devlines" / args.line_id))
    elif args.command == "close":
        print(close_devline(root, args.line_id))
    elif args.command == "promote":
        print(json.dumps(promote_knowledge(root), ensure_ascii=False))
    else:
        print(build_context_pack(root, root / "devlines" / args.line_id, keywords=[value for value in args.keywords.split(",") if value]))


if __name__ == "__main__":
    _main()
