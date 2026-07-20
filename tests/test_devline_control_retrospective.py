from __future__ import annotations

import uuid
from pathlib import Path

from workbench.development_control.events import append_event
from workbench.development_control.retrospective import generate_retrospective, render_retrospective


def _event(
    *,
    timestamp: str,
    event_type: str = "FAILURE",
    subtype: str = "failure",
    incident_id: str | None = None,
    lesson_key: str = "filesystem-persistence-capability-bypass",
    resolution: str = "open",
    artifact_digest: str | None = None,
    gate_fingerprint: str | None = None,
    review_round: int | None = None,
    state_from: str | None = None,
    state_to: str | None = None,
    resource_usage: dict[str, int] | None = None,
    tags: list[str] | None = None,
    evidence_sha256: str = "a" * 64,
) -> dict[str, object]:
    event: dict[str, object] = {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "timestamp": timestamp,
        "type": event_type,
        "subtype": subtype,
        "stage": "review",
        "cause_status": "known",
        "cause": "a bounded, evidenced cause",
        "evidence": {
            "kind": "test",
            "ref": "tests/test_devline_control_retrospective.py",
            "sha256": evidence_sha256,
            "observed_at": timestamp,
        },
        "impact": "bounded impact",
        "preventability": "preventable",
        "resolution": resolution,
        "lesson": "keep authority inside the checked capability boundary",
        "incident_id": incident_id or str(uuid.uuid4()),
        "lesson_key": lesson_key,
        "links": [],
    }
    for key, value in {
        "artifact_digest": artifact_digest,
        "gate_fingerprint": gate_fingerprint,
        "review_round": review_round,
        "state_from": state_from,
        "state_to": state_to,
        "resource_usage": resource_usage,
        "tags": tags,
    }.items():
        if value is not None:
            event[key] = value
    return event


def _line(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / ".agent" / "devlines"
    (root / "wo-a").mkdir(parents=True)
    (root / "wo-a" / "line.json").write_text('{"goal":"safe persistence"}\n', encoding="utf-8")
    return root, "wo-a"


def test_report_is_byte_stable_and_covers_required_sections_and_metric_semantics(tmp_path: Path) -> None:
    root, line_id = _line(tmp_path)
    incident = str(uuid.uuid4())
    append_event(root, line_id, _event(timestamp="2026-07-19T10:00:00.000Z", incident_id=incident))
    append_event(
        root,
        line_id,
        _event(
            timestamp="2026-07-19T10:03:00.000Z",
            event_type="ERROR",
            subtype="retry_error",
            incident_id=incident,
            resolution="resolved",
        ),
    )
    append_event(root, line_id, _event(timestamp="2026-07-19T10:04:00.000Z", event_type="GAP"))
    append_event(
        root,
        line_id,
        _event(
            timestamp="2026-07-19T10:05:00.000Z",
            event_type="WASTE",
            resource_usage={"input_tokens": 7, "tool_tokens": 3},
        ),
    )
    append_event(
        root,
        line_id,
        _event(
            timestamp="2026-07-19T10:06:00.000Z",
            event_type="REVIEW",
            subtype="changes_required",
            artifact_digest="b" * 64,
            review_round=2,
        ),
    )
    append_event(
        root,
        line_id,
        _event(
            timestamp="2026-07-19T10:07:00.000Z",
            event_type="REVIEW",
            subtype="withdrawn",
            artifact_digest="b" * 64,
            review_round=3,
        ),
    )
    append_event(
        root,
        line_id,
        _event(
            timestamp="2026-07-19T10:08:00.000Z",
            event_type="STATE_CHANGE",
            subtype="spec_revised",
            artifact_digest="c" * 64,
            tags=["spec"],
            state_from="review",
            state_to="review",
        ),
    )
    append_event(
        root,
        line_id,
        _event(
            timestamp="2026-07-19T10:09:00.000Z",
            event_type="STATE_CHANGE",
            subtype="plan_revised",
            artifact_digest="d" * 64,
            tags=["plan"],
            state_from="review",
            state_to="review",
        ),
    )
    append_event(
        root,
        line_id,
        _event(
            timestamp="2026-07-19T10:10:00.000Z",
            event_type="GATE",
            subtype="executed",
            artifact_digest="e" * 64,
            gate_fingerprint="focused-tests",
            evidence_sha256="f" * 64,
        ),
    )
    append_event(
        root,
        line_id,
        _event(
            timestamp="2026-07-19T10:11:00.000Z",
            event_type="GATE",
            subtype="executed",
            artifact_digest="e" * 64,
            gate_fingerprint="focused-tests",
            evidence_sha256="f" * 64,
        ),
    )
    append_event(
        root,
        line_id,
        _event(
            timestamp="2026-07-19T10:12:00.000Z",
            event_type="STATE_CHANGE",
            subtype="retry",
            state_from="review",
            state_to="review",
        ),
    )

    report = generate_retrospective(root, line_id).read_bytes()
    assert report == generate_retrospective(root, line_id).read_bytes()
    text = report.decode("utf-8")
    for section in (
        "## Goal",
        "## Final status",
        "## Metrics",
        "## All failures",
        "## All errors",
        "## All gaps",
        "## All waste",
        "## Root causes and solutions",
        "## Added tests",
        "## New rules",
        "## Future guidance",
        "## Event index",
    ):
        assert section in text
    assert "Failure frequency: 3/11 (27.3%; 27.3 per 100 events)" in text
    assert "Repeat rate: 2/3 (66.7%)" in text
    assert "Recurrence rate: 1/1 (100.0%)" in text
    assert "MTTR: median=180000 ms (sample=1; unresolved=1)" in text
    assert "Review churn: changes_required=1; average_review_round=2.0 (sample=1); withdrawn=1" in text
    assert "Spec churn: 0 (sample=1)" in text
    assert "Plan churn: 0 (sample=1)" in text
    assert "Gate waste rate: 1/2 (50.0%)" in text
    assert "Same-state retry rate: 1/1 (100.0%)" in text
    assert "Token waste: 10 (coverage=1/1)" in text


def test_zero_samples_are_never_invented_and_external_first_gate_is_not_waste(tmp_path: Path) -> None:
    root, line_id = _line(tmp_path)
    event = _event(
        timestamp="2026-07-19T10:00:00.000Z",
        event_type="GATE",
        subtype="blocked",
        gate_fingerprint="frontend-environment",
        artifact_digest="e" * 64,
    )
    event["cause_status"] = "external"
    append_event(root, line_id, event)

    text = generate_retrospective(root, line_id).read_text(encoding="utf-8")
    assert "Failure frequency: N/A (sample=0)" in text
    assert "Repeat rate: N/A (sample=0)" in text
    assert "Recurrence rate: N/A (sample=0)" in text
    assert "MTTR: N/A (sample=0; unresolved=0)" in text
    assert "Gate waste rate: 0/1 (0.0%)" in text
    assert "Same-state retry rate: N/A (sample=0)" in text
    assert "Token waste: N/A (sample=0)" in text
    assert "Spec churn: N/A (sample=0)" in text
    assert "Plan churn: N/A (sample=0)" in text


def test_rendering_and_atomic_derived_write_do_not_change_event_history(tmp_path: Path) -> None:
    root, line_id = _line(tmp_path)
    append_event(root, line_id, _event(timestamp="2026-07-19T10:00:00.000Z"))
    events_path = root / line_id / "events.jsonl"
    before = events_path.read_bytes()

    output = generate_retrospective(root, line_id)

    assert output == root / line_id / "RETROSPECTIVE.md"
    assert events_path.read_bytes() == before
    assert render_retrospective(root, line_id).encode("utf-8") == output.read_bytes()


def test_churn_requires_a_digest_change_and_preserves_unknown_cause_status(tmp_path: Path) -> None:
    root, line_id = _line(tmp_path)
    incident = str(uuid.uuid4())
    unknown = _event(
        timestamp="2026-07-19T10:00:00.000Z",
        incident_id=incident,
        event_type="GAP",
        lesson_key="containment-c1-c2-boundary",
    )
    unknown["cause_status"] = "unknown"
    append_event(root, line_id, unknown)
    for timestamp, digest in (
        ("2026-07-19T10:01:00.000Z", "a" * 64),
        ("2026-07-19T10:02:00.000Z", "a" * 64),
        ("2026-07-19T10:03:00.000Z", "b" * 64),
    ):
        append_event(
            root,
            line_id,
            _event(
                timestamp=timestamp,
                event_type="REVIEW",
                subtype="changes_required",
                artifact_digest=digest,
                tags=["spec", "plan"],
            ),
        )

    text = render_retrospective(root, line_id)
    assert "Spec churn: 1 (sample=3)" in text
    assert "Plan churn: 1 (sample=3)" in text
    assert "cause_status: `unknown`" in text
