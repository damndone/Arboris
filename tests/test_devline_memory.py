from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.devline_memory import (
    EventValidationError,
    append_event,
    build_context_pack,
    close_devline,
    generate_retrospective,
    init_devline,
    promote_knowledge,
)


def _event(*, timestamp: str, event_type: str = "FAILURE", subtype: str = "capability_escape", cause: str = "raw path bypass") -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": event_type,
        "subtype": subtype,
        "stage": "review",
        "cause_status": "confirmed",
        "cause": cause,
        "evidence": {"test": "evidence-id"},
        "impact": {"gate_minutes": 10, "tokens": 20},
        "preventability": "high",
        "resolution": "sealed capability only",
        "lesson": "do not accept raw paths",
    }


def test_append_is_validated_append_only_and_never_rewrites_history(tmp_path: Path) -> None:
    line_dir = init_devline(tmp_path, "wo-a", goal="safe persistence")
    first = _event(timestamp="2026-07-19T10:00:00Z")
    append_event(line_dir, first)

    with pytest.raises(EventValidationError):
        append_event(line_dir, {key: value for key, value in first.items() if key != "lesson"})

    append_event(line_dir, _event(timestamp="2026-07-19T10:01:00Z", event_type="REVIEW"))
    rows = [json.loads(row) for row in (line_dir / "events.jsonl").read_text().splitlines()]
    assert rows == [first, _event(timestamp="2026-07-19T10:01:00Z", event_type="REVIEW")]


def test_knowledge_promotion_uses_event_occurrences_at_one_two_and_three(tmp_path: Path) -> None:
    root = tmp_path / ".agent"
    for index, line_id in enumerate(("wo-a", "wo-c", "wo-d"), start=1):
        line_dir = init_devline(root, line_id, goal=line_id)
        append_event(
            line_dir,
            _event(timestamp=f"2026-07-19T10:0{index}:00Z", subtype="dependency_gate", cause="missing locked dependency"),
        )
        result = promote_knowledge(root)
        assert result["line_lessons"] == 1
        assert result["candidate_global_rules"] == (1 if index >= 2 else 0)
        assert result["mandatory_global_rules"] == (1 if index >= 3 else 0)


def test_repeated_issue_in_one_line_is_promoted_without_waiting_for_another_line(tmp_path: Path) -> None:
    root = tmp_path / ".agent"
    line_dir = init_devline(root, "wo-a", goal="safe persistence")
    for minute in range(3):
        append_event(
            line_dir,
            _event(timestamp=f"2026-07-19T10:0{minute}:00Z", subtype="capability_escape", cause="raw path bypass"),
        )
    result = promote_knowledge(root)
    assert result["candidate_global_rules"] == 1
    assert result["mandatory_global_rules"] == 1


def test_retrospective_calculates_frequency_repeat_rate_mttr_and_churn(tmp_path: Path) -> None:
    line_dir = init_devline(tmp_path, "wo-a", goal="safe persistence")
    start = datetime(2026, 7, 19, 10, tzinfo=UTC)
    append_event(line_dir, _event(timestamp=start.isoformat().replace("+00:00", "Z"), subtype="persistence_review"))
    append_event(
        line_dir,
        _event(
            timestamp=(start + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
            event_type="STATE_CHANGE",
            subtype="persistence_review",
        ),
    )
    append_event(
        line_dir,
        _event(
            timestamp=(start + timedelta(minutes=35)).isoformat().replace("+00:00", "Z"),
            event_type="REVIEW",
            subtype="persistence_review",
        ),
    )
    retrospective = generate_retrospective(line_dir)
    text = retrospective.read_text()
    assert "Failure frequency" in text
    assert "Repeat rate" in text
    assert "30.0 minutes" in text
    assert "Review churn" in text
    assert "All errors" in text
    assert "All gaps" in text
    assert "All waste" in text
    assert "Added tests" in text
    assert "New rules" in text
    assert "Future guidance" in text
    assert "Token waste: unknown" in text


def test_context_pack_contains_global_rules_and_only_relevant_retrospectives(tmp_path: Path) -> None:
    root = tmp_path / ".agent"
    a = init_devline(root, "wo-a", goal="filesystem persistence")
    c = init_devline(root, "wo-c", goal="read-only ui")
    append_event(a, _event(timestamp="2026-07-19T10:00:00Z", subtype="capability_escape", cause="filesystem persistence raw path"))
    append_event(c, _event(timestamp="2026-07-19T10:01:00Z", subtype="dependency_gate", cause="frontend dependency missing"))
    generate_retrospective(a)
    generate_retrospective(c)
    promote_knowledge(root)

    target = init_devline(root, "wo-new", goal="filesystem persistence hardening")
    context = build_context_pack(root, target, keywords=["filesystem", "persistence"])
    text = context.read_text()
    assert "Global development rules" in text
    assert "wo-a" in text
    assert "wo-c" not in text


def test_close_devline_generates_retrospective_and_promotes_knowledge(tmp_path: Path) -> None:
    root = tmp_path / ".agent"
    line_dir = init_devline(root, "wo-a", goal="safe persistence")
    append_event(line_dir, _event(timestamp="2026-07-19T10:00:00Z"))
    retrospective = close_devline(root, "wo-a")
    assert retrospective == line_dir / "RETROSPECTIVE.md"
    assert retrospective.exists()
    assert (root / "development" / "candidate_global_rules.json").exists()


def test_repository_instructions_require_context_pack_before_new_devline_work() -> None:
    instructions = (Path(__file__).parents[1] / "AGENTS.md").read_text(encoding="utf-8")
    assert ".agent/devlines/<line_id>/CONTEXT_PACK.md" in instructions
    assert ".agent/development/global_rules.md" in instructions
    assert "events.jsonl" in instructions
