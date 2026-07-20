from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from workbench.development_control.events import ZERO_SHA256, validate_event
from workbench.development_control.promotion import (
    PromotionError,
    PromotionPolicy,
    promote,
    read_candidate_rules,
    read_global_rules,
    read_promotion_ledger,
)


def _event(
    *,
    lesson_key: str,
    event_type: str = "FAILURE",
    incident_id: str | None = None,
    event_id: str | None = None,
    evidence_ref: str = "tests/test_devline_control_promotion.py::test_marker",
    previous_sha256: str = ZERO_SHA256,
) -> dict[str, object]:
    return validate_event(
        {
            "schema_version": 1,
            "event_id": event_id or str(uuid.uuid4()),
            "timestamp": "2026-07-19T20:30:00.000Z",
            "type": event_type,
            "subtype": "promotion_check",
            "stage": "review",
            "cause_status": "known",
            "cause": "a repeatable control failure needs a durable rule",
            "evidence": {
                "kind": "test",
                "ref": evidence_ref,
                "sha256": "a" * 64,
                "observed_at": "2026-07-19T20:30:00.000Z",
            },
            "impact": "prevents a repeated unsafe development decision",
            "preventability": "preventable",
            "resolution": "resolved",
            "lesson": "promote only independently observed incidents",
            "incident_id": incident_id or str(uuid.uuid4()),
            "lesson_key": lesson_key,
            "links": [],
        },
        previous_sha256=previous_sha256,
    )


def _policy(*, lesson_key: str, kind: str = "mechanical") -> PromotionPolicy:
    return PromotionPolicy(
        lesson_key=lesson_key,
        rule_id=f"rule-{lesson_key}",
        kind=kind,
        scope="development_control",
        enforcement_point="pytest gate" if kind == "mechanical" else "integration owner review",
        false_positive_risk="narrowly scoped to the declared lesson key",
        verification_method="run the declared test marker" if kind == "mechanical" else "owner review",
        test_marker="tests/test_devline_control_promotion.py::test_marker" if kind == "mechanical" else None,
        behavior_proposal="Add the reviewed behavior rule to the managed AGENTS block." if kind == "behavior" else None,
    )


def test_same_incident_is_counted_once_and_second_incident_creates_one_candidate(tmp_path: Path) -> None:
    policy = _policy(lesson_key="filesystem-persistence-capability-bypass")
    first_incident = str(uuid.uuid4())
    first = _event(lesson_key=policy.lesson_key, incident_id=first_incident)
    duplicate = _event(lesson_key=policy.lesson_key, incident_id=first_incident)
    second = _event(lesson_key=policy.lesson_key)

    first_result = promote(tmp_path, [first, duplicate], policies=[policy])
    assert first_result[policy.lesson_key]["distinct_incidents"] == 1
    assert read_candidate_rules(tmp_path) == []

    second_result = promote(tmp_path, [first, duplicate, second], policies=[policy])
    assert second_result[policy.lesson_key]["distinct_incidents"] == 2
    candidates = read_candidate_rules(tmp_path)
    assert len(candidates) == 1
    assert candidates[0]["status"] == "candidate"
    assert candidates[0]["trigger_event_ids"] == [first["event_id"], second["event_id"]]
    assert all(len(source["event_sha256"]) == 64 for source in candidates[0]["sources"])
    assert [entry["decision"] for entry in read_promotion_ledger(tmp_path)] == ["candidate_created"]


def test_gate_incidents_follow_the_same_one_two_three_promotion_rule(tmp_path: Path) -> None:
    policy = _policy(lesson_key="native-frontend-environment-blocker", kind="behavior")

    result = promote(
        tmp_path,
        [
            _event(lesson_key=policy.lesson_key, event_type="GATE"),
            _event(lesson_key=policy.lesson_key, event_type="GATE"),
        ],
        policies=[policy],
    )

    assert result[policy.lesson_key]["distinct_incidents"] == 2
    assert read_candidate_rules(tmp_path)[0]["lesson_key"] == policy.lesson_key


def test_third_distinct_incident_enables_mechanical_rule_only_with_test_marker_and_is_idempotent(tmp_path: Path) -> None:
    policy = _policy(lesson_key="containment-c1-c2-boundary")
    events = [_event(lesson_key=policy.lesson_key) for _ in range(3)]

    first = promote(tmp_path, events, policies=[policy])
    assert first[policy.lesson_key]["global_rule_status"] == "enabled"
    rules = read_global_rules(tmp_path)
    assert len(rules["rules"]) == 1
    assert rules["rules"][0]["status"] == "enabled"
    assert rules["rules"][0]["test_marker"] == policy.test_marker
    assert [entry["decision"] for entry in read_promotion_ledger(tmp_path)] == [
        "candidate_created",
        "mechanical_rule_enabled",
    ]

    before = {
        path.name: path.read_bytes()
        for path in tmp_path.iterdir()
        if path.is_file()
    }
    second = promote(tmp_path, events, policies=[policy])
    after = {
        path.name: path.read_bytes()
        for path in tmp_path.iterdir()
        if path.is_file()
    }
    assert second == first
    assert after == before


def test_mechanical_rule_remains_disabled_without_a_matching_test_marker(tmp_path: Path) -> None:
    policy = _policy(lesson_key="native-frontend-environment-blocker")
    events = [
        _event(lesson_key=policy.lesson_key, evidence_ref="tests/another_test.py::test_other")
        for _ in range(3)
    ]

    result = promote(tmp_path, events, policies=[policy])

    assert result[policy.lesson_key]["global_rule_status"] == "blocked_missing_test_marker"
    assert read_global_rules(tmp_path)["rules"] == []
    assert read_promotion_ledger(tmp_path)[-1]["decision"] == "mechanical_rule_blocked_missing_test_marker"


def test_third_behavior_rule_creates_a_review_proposal_without_enabling_a_global_rule(tmp_path: Path) -> None:
    policy = _policy(lesson_key="native-frontend-environment-blocker", kind="behavior")
    events = [_event(lesson_key=policy.lesson_key) for _ in range(3)]

    result = promote(tmp_path, events, policies=[policy])

    assert result[policy.lesson_key]["global_rule_status"] == "proposal_pending_review"
    assert read_global_rules(tmp_path)["rules"] == []
    proposal = read_promotion_ledger(tmp_path)[-1]
    assert proposal["decision"] == "behavior_rule_proposed"
    assert proposal["proposal_target"] == "AGENTS.md managed block"
    assert not (tmp_path / "AGENTS.md").exists()


def test_rejects_tampered_candidate_ledger_and_global_rule_hashes(tmp_path: Path) -> None:
    policy = _policy(lesson_key="filesystem-persistence-capability-bypass")
    promote(tmp_path, [_event(lesson_key=policy.lesson_key) for _ in range(3)], policies=[policy])

    candidate_path = tmp_path / "candidate-rules.jsonl"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate["scope"] = "rewritten"
    candidate_path.write_text(json.dumps(candidate, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    with pytest.raises(PromotionError, match="candidate_sha256"):
        read_candidate_rules(tmp_path)

    ledger_path = tmp_path / "promotion-ledger.jsonl"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[0])
    ledger["candidate_id"] = "rewritten"
    ledger_path.write_text(json.dumps(ledger, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    with pytest.raises(PromotionError, match="ledger_sha256"):
        read_promotion_ledger(tmp_path)

    global_path = tmp_path / "global-rules.json"
    global_rules = json.loads(global_path.read_text(encoding="utf-8"))
    global_rules["rules"][0]["scope"] = "rewritten"
    global_path.write_text(json.dumps(global_rules, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(PromotionError, match="rule_sha256"):
        read_global_rules(tmp_path)
