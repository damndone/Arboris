from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi.responses import StreamingResponse


def test_event_manager_rehydrates_durable_run_history_after_memory_reset(tmp_path: Path) -> None:
    from workbench.events import EventManager

    history_path = tmp_path / "runs" / "run-a" / "workflow_log.jsonl"
    first = EventManager()
    first.register_run("run-a", history_path)
    first.emit("run-a", {"event": "step_start", "step": "load", "message": "Loading"})
    first.emit("run-a", {"event": "step_complete", "step": "load", "message": "Loaded"})
    first.emit_terminal("run-a", "completed", "Workflow completed")

    second = EventManager()
    second.register_run("run-a", history_path)
    _queue, snapshot = second.subscribe("run-a")

    assert [event["event"] for event in snapshot] == [
        "step_start",
        "step_complete",
        "workflow_completed",
    ]


def test_sse_route_registers_completed_run_history_after_memory_reset(tmp_path: Path) -> None:
    from workbench.events import get_event_manager
    from workbench.http.runs_routes import run_events_endpoint
    from workbench.projects import create_project, create_run

    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    run_manifest = {
        "run_id": run.run_id,
        "mode": "auto",
        "status": "completed",
        "lineage": [],
    }
    (run.root / "run_manifest.json").write_text(
        json.dumps(run_manifest), encoding="utf-8"
    )
    history = [
        {"event": "step_start", "step": "load", "message": "Loading", "sequence": 0},
        {"event": "step_complete", "step": "load", "message": "Loaded", "sequence": 1},
        {"event": "workflow_completed", "step": None, "message": "Done", "status": "completed", "sequence": 2},
    ]
    (run.root / "workflow_log.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in history),
        encoding="utf-8",
    )

    events = get_event_manager()
    events._reset_for_testing()
    response = asyncio.run(
        run_events_endpoint(run.run_id, str(project.root))
    )

    assert isinstance(response, StreamingResponse)
    _queue, snapshot = events.subscribe(run.run_id)
    assert [event["event"] for event in snapshot] == [
        "step_start",
        "step_complete",
        "workflow_completed",
    ]
