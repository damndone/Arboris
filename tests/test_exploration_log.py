from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.exploration_log import ExplorationLog, ExplorationLogValidationError


def _event(**overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "event_id": "evt-1",
        "workflow_id": "wf-1",
        "workflow_step_id": "step-1",
        "operation_id": "statistical.explore@v1",
        "spec_fingerprint": "sha256:spec-1",
        "source_artifact_ids": ["raw-1"],
        "dependency_artifact_ids": [],
        "row_counts": {"source": 4110, "filtered": 685},
        "status": "completed",
        "error": None,
    }
    event.update(overrides)
    return event


def test_log_appends_canonical_events_and_reads_them_back(tmp_path: Path) -> None:
    log = ExplorationLog(tmp_path, workflow_id="wf-1")

    first = log.append_event(_event())
    second = log.append_event(_event(event_id="evt-2", status="running"))

    assert first["event_id"] == "evt-1"
    assert second["event_id"] == "evt-2"
    assert log.read_events() == [first, second]
    lines = (tmp_path / "workbench" / "exploration" / "wf-1.jsonl").read_text()
    assert lines.splitlines()[0] == json.dumps(first, ensure_ascii=False, sort_keys=True)


def test_log_rejects_raw_rows_and_full_artifacts(tmp_path: Path) -> None:
    log = ExplorationLog(tmp_path, workflow_id="wf-1")

    with pytest.raises(ExplorationLogValidationError, match="raw_rows"):
        log.append_event(_event(raw_rows=[{"year": 1998}]))

    with pytest.raises(ExplorationLogValidationError, match="full_artifact"):
        log.append_event(_event(full_artifact={"all_rows": "..."}))


def test_log_rejects_event_from_another_workflow(tmp_path: Path) -> None:
    log = ExplorationLog(tmp_path, workflow_id="wf-1")

    with pytest.raises(ExplorationLogValidationError, match="workflow_id"):
        log.append_event(_event(workflow_id="wf-other"))


def test_log_event_fingerprint_is_stable_for_mapping_order(tmp_path: Path) -> None:
    log = ExplorationLog(tmp_path, workflow_id="wf-1")
    left = _event(row_counts={"source": 4110, "filtered": 685})
    right = _event(row_counts={"filtered": 685, "source": 4110})

    assert log.fingerprint_event(left) == log.fingerprint_event(right)
