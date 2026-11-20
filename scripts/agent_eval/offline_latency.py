"""Offline latency observations from the strict CLI record/replay acceptance fixture.

No provider, socket, product-function replacement or held-out task is used.
Results bound this small replay only; they do not certify model latency or paint.
"""
import asyncio
from datetime import datetime
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
from workbench.jsonl_store import jsonl_lines
import pytest
from typer.testing import CliRunner
from tests.test_agent_product_replay import test_cli_records_and_strictly_replays_actual_analysis_and_reports
from tests.test_agent_core_restart import setup
from tests.test_agent_read_batches import Adapter, registry


def seconds(event):
    return datetime.fromisoformat(event["created_at"]).timestamp()


async def interrupt(root):
    ready = asyncio.Event()
    async def read(args, context):
        ready.set()
        await asyncio.Event().wait()
    core, store, repo = setup(root, Adapter(names=("wait",)), runtime=registry([("wait", read, "none")]))
    task = asyncio.create_task(core.prompt("Read.", budget={"max_steps": 3, "timeout_s": 5}))
    await asyncio.wait_for(ready.wait(), 2)
    started = time.perf_counter()
    await core.abort()
    await task
    elapsed = time.perf_counter() - started
    assert repo.get_metadata("session-a")["status"] == "cancelled" and not store.list_active()
    return elapsed


def main():
    out = ROOT / "local/agent-eval/offline-latency"
    out.mkdir(parents=True, exist_ok=True)
    measurements = []
    for rep in range(5):
        invocations = []
        original = CliRunner.invoke
        def observe(self, *args, **kwargs):
            started = time.perf_counter()
            result = original(self, *args, **kwargs)
            invocations.append({"elapsed_s": time.perf_counter() - started, "exit_code": result.exit_code})
            return result
        with tempfile.TemporaryDirectory(prefix="arboris-offline-latency-") as temp, pytest.MonkeyPatch.context() as guard:
            area = Path(temp).resolve()
            guard.setattr(CliRunner, "invoke", observe)
            test_cli_records_and_strictly_replays_actual_analysis_and_reports(area / "analysis", guard, True)
            event_file = area / "analysis/project/workbench/agent-events/chain-session.jsonl"
            # The fixture owns its project name; locate only its replay tree.
            if not event_file.exists():
                candidates = [p for p in (area / "analysis").rglob("agent-events/chain-session.jsonl")
                              if not any(x in p.parts for x in ("initial-project", "recorded-project"))]
                [event_file] = candidates
            events = [json.loads(line) for line in jsonl_lines(event_file.read_text())]
            start = next(e for e in events if e["event_type"] == "turn_start")
            plan = next(e for e in events if e["event_type"] == "tool_execution_end" and e["payload"]["tool_id"] == "update_plan")
            gaps = []
            for i, event in enumerate(events):
                if event["event_type"] == "message_end":
                    later = next((e for e in events[i+1:] if e["event_type"] in {"message_start", "agent_end"}), None)
                    if later:
                        gaps.append(seconds(later) - seconds(event))
            stop = asyncio.run(interrupt(area / "interrupt"))
            measurements.append({"rep": rep, "record_and_replay": invocations,
                "first_plan_offline_s": seconds(plan) - seconds(start),
                "non_model_intervals_s": gaps, "interrupt_settled_s": stop, "events": events})
    summary = {"kind": "strict_offline_scripted_record_replay", "replicates": 5,
        "first_plan_s_median": statistics.median(m["first_plan_offline_s"] for m in measurements),
        "non_model_step_s_median": statistics.median(x for m in measurements for x in m["non_model_intervals_s"]),
        "interrupt_s_max": max(m["interrupt_settled_s"] for m in measurements),
        "long_native_compute_cancel": "unmeasured; cancelling an awaiting async tool does not certify native solver cancellation",
        "browser_panel_paint": "unmeasured; requires browser acceptance",
        "live_first_plan": "unmeasured; replay excludes provider inference and network latency"}
    (out / "results.json").write_text(json.dumps({"summary": summary, "measurements": measurements}, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
