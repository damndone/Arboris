"""Kill a real product analysis at provider step three, then resume it."""
from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
from unittest.mock import patch

from tests.test_agent_routes import _config
from tests.test_read_only_analysis import FINGERPRINT, _Fixture, _explore, _t_test
from workbench.agent.model import ModelStreamEvent
from workbench.agent.runtime_adapter import headless_runtime_scope
from workbench.agent.session import JsonlSessionRepository
from workbench.agent.turn_store import TurnStore
from workbench.cli_agent import resume_headless, run_headless


class ProductAnalysis:
    def __init__(self):
        self.calls = 0

    async def stream(self, request):
        self.calls += 1
        if self.calls < 3:
            call = {"tool_call_id": f"arithmetic-{self.calls}", "tool_id": "calculate",
                    "arguments": {"calculations": [{"expression": "2 + 3" if self.calls == 1 else "5 - 2",
                                                     "label": "arithmetic"}]}}
        else:
            call = {"tool_call_id": "analysis", "tool_id": "run_operation", "arguments": {
                "operation_id": "operation.multi_step", "operation_version": "v1",
                "target": {"run_id": "run_source", "node_ref": "stage:source", "artifact_id": "source_data"},
                "preconditions": {"context_version": "node-operation-context/v1", "context_fingerprint": FINGERPRINT,
                                  "active_head_run_id": "run_source", "owner_resolution": "single_candidate"},
                "changes": {"steps": [_explore("tab", "region"), _t_test("tt"), {
                    "step_id": "report", "operation_id": "report.compose", "depends_on": ["tab", "tt"],
                    "spec": {"sections": ["descriptives", "tests"]}}]},
                "evidence_refs": ["profile:fixture"], "expected_effect": ["Save analysis and report"], "risks": []}}
        yield ModelStreamEvent.tool_call_delta(request.request_id, call)
        yield ModelStreamEvent.done(request.request_id, "tool_calls")


def _killed_product(root):
    root = Path(root)
    original = JsonlSessionRepository.append_once
    receipts = 0
    def exit_on_third_receipt(self, *args, **kwargs):
        nonlocal receipts
        if kwargs.get("stage") == "tool_result":
            receipts += 1
            if receipts == 3:
                os._exit(73)
        return original(self, *args, **kwargs)
    async def run():
        with patch.object(JsonlSessionRepository, "append_once", exit_on_third_receipt), headless_runtime_scope(
            adapter_factory=lambda config: ProductAnalysis(), config=_config(),
        ):
            await run_headless(root, "Calculate 2 + 3, then 5 - 2; analyze and save the report.",
                               session_id="chain-session", on_event=lambda event: None)
    asyncio.run(run())


def _hashes(directory):
    return {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in directory.rglob("*") if path.is_file()}


def test_product_step_three_process_death_does_not_repeat_analysis_or_report(tmp_path):
    fixture = _Fixture(tmp_path)
    root = fixture.project_root
    run = root / "runs" / "run_source"
    (run / "node_index.json").write_text(json.dumps({"stage:source": {
        "node_hash": hashlib.sha256((run / "data.csv").read_bytes()).hexdigest()}}))
    (run / "run_manifest.json").write_text(json.dumps({"status": "completed", "started_at": "2026-07-15T00:00:00+00:00"}))
    (run / "run_inputs.json").write_text(json.dumps({"rerun_of": None, "form": {}}))
    (root / "workbench" / "agent-permissions.json").write_text(json.dumps({"allow": [{"class": "derive"}]}))
    process = multiprocessing.get_context("spawn").Process(target=_killed_product, args=(str(root),))
    process.start()
    process.join(30)
    try:
        assert process.exitcode == 73
        [interrupted] = TurnStore(root).list_active()
        assert interrupted.status == "running" and interrupted.steps_used == 3
        operations = root / "workbench" / "operation-records"
        records = [json.loads(path.read_text().splitlines()[-1]) for path in operations.glob("oprec_*.jsonl")]
        assert len(records) == 4 and all(record["status"] == "completed" for record in records)
        reports = [path for path in run.rglob("*") if path.suffix in {".pdf", ".html", ".xlsx"}]
        assert {path.suffix for path in reports} == {".pdf", ".html", ".xlsx"}
        assert all(path.stat().st_size > 0 for path in reports)
        run_before, records_before = _hashes(root / "runs"), _hashes(operations)
        ledger_before = (root / "workbench" / "analysis_ledger.jsonl").read_bytes()
        requests = []
        class FinalAnswer:
            async def stream(self, request):
                requests.append(request)
                yield ModelStreamEvent.text_delta(request.request_id, "The analysis and report are saved.")
                yield ModelStreamEvent.done(request.request_id)
        async def resume():
            with headless_runtime_scope(adapter_factory=lambda config: FinalAnswer(), config=_config()):
                return await resume_headless(root, "chain-session", interrupted.turn_id, on_event=lambda event: None)
        result = asyncio.run(resume())
        assert result["status"] == "idle"
        assert len(requests) == 1 and requests[0].messages[-1]["role"] == "tool"
        final = TurnStore(root).get(interrupted.turn_id)
        assert final.command_id == interrupted.command_id and final.steps_used == 4 and final.status == "completed"
        assert _hashes(root / "runs") == run_before
        assert _hashes(operations) == records_before
        assert (root / "workbench" / "analysis_ledger.jsonl").read_bytes() == ledger_before
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
