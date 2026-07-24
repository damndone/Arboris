"""E2/E3 — make promotion surface severe one-offs and its own ineffective rules.

Both respect the schema's intentional invariant that a *promoted* rule needs at
least two distinct incidents. E2 does not auto-promote a severe one-off (that
would weaken the invariant); it surfaces it for a human decision. E3 flags a
rule that recurred after being enabled — the system noticing its own rule is not
working, which is the difference between recording and evolving.
"""
from pathlib import Path

from workbench.development_control.events import ZERO_SHA256, validate_event
from workbench.development_control.promotion import (
    PromotionPolicy,
    promote,
)

POLICY = PromotionPolicy(
    lesson_key="example-lesson",
    rule_id="example-rule",
    kind="mechanical",
    scope="example",
    enforcement_point="gate",
    false_positive_risk="none",
    verification_method="run marker",
    test_marker="tests/test_example_marker.py",
)


def _event(n: int, *, severity: str | None = None, marker: str | None = None) -> dict:
    ev = {
        "schema_version": 1,
        "event_id": f"00000000-0000-4000-8000-0000000000{n:02d}",
        "incident_id": f"10000000-0000-4000-8000-0000000000{n:02d}",
        "timestamp": f"2026-07-22T00:00:{n:02d}.000Z",
        "type": "FAILURE",
        "subtype": "example",
        "stage": "design",
        "cause_status": "known",
        "cause": "example cause",
        "evidence": {
            "kind": "test",
            "ref": marker or "docs/x.md",
            "sha256": "a" * 64,
            "observed_at": f"2026-07-22T00:00:{n:02d}.000Z",
        },
        "impact": "example impact",
        "preventability": "preventable",
        "resolution": "open",
        "lesson": "example lesson",
        "lesson_key": "example-lesson",
        "links": [],
    }
    if severity is not None:
        ev["severity"] = severity
    # promote() requires fully-canonical validated events (correct hash fields).
    return validate_event(ev, previous_sha256=ZERO_SHA256)


# ----------------------------------------------------------------------
# E2 — severity surfacing (does not weaken the >=2-evidence invariant)
# ----------------------------------------------------------------------


def test_a_high_severity_one_off_is_surfaced_not_promoted(tmp_path: Path) -> None:
    result = promote(tmp_path, [_event(1, severity="high")], policies=[POLICY])

    entry = result["example-lesson"]
    assert entry["distinct_incidents"] == 1
    assert entry["candidate_status"] == "line_experience"  # NOT promoted
    assert entry["severity_review"] is True  # ...but flagged for a human


def test_a_normal_one_off_is_not_surfaced(tmp_path: Path) -> None:
    result = promote(tmp_path, [_event(1)], policies=[POLICY])

    assert result["example-lesson"]["severity_review"] is False


def test_high_severity_does_not_bypass_the_two_evidence_rule(tmp_path: Path) -> None:
    """One severe incident must not mint a candidate; the schema requires two."""
    promote(tmp_path, [_event(1, severity="high")], policies=[POLICY])
    from workbench.development_control.promotion import read_candidate_rules

    assert read_candidate_rules(tmp_path) == []


# ----------------------------------------------------------------------
# E3 — efficacy feedback: a rule that recurs after being enabled
# ----------------------------------------------------------------------


def test_recurrence_after_enable_flags_the_rule_ineffective(tmp_path: Path) -> None:
    # Three incidents, one citing the marker -> rule enabled.
    events = [_event(1), _event(2), _event(3, marker="tests/test_example_marker.py")]
    first = promote(tmp_path, events, policies=[POLICY])
    assert first["example-lesson"]["global_rule_status"] == "enabled"

    # A fourth, distinct incident after the rule exists: the rule did not work.
    events_with_recurrence = events + [_event(4)]
    second = promote(tmp_path, events_with_recurrence, policies=[POLICY])

    assert second["example-lesson"]["rule_effective"] is False
    from workbench.development_control.promotion import read_promotion_ledger

    ledger = read_promotion_ledger(tmp_path)
    assert any(e["decision"] == "rule_ineffective_recurrence" for e in ledger)


def test_an_enabled_rule_with_no_new_recurrence_stays_effective(tmp_path: Path) -> None:
    events = [_event(1), _event(2), _event(3, marker="tests/test_example_marker.py")]
    promote(tmp_path, events, policies=[POLICY])

    again = promote(tmp_path, events, policies=[POLICY])

    assert again["example-lesson"]["rule_effective"] is True
