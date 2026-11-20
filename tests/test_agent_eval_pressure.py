import asyncio
import json
import signal

import pytest

from scripts.agent_eval import offline_pressure


def test_pressure_preview_owns_its_recovery_and_egress_stores(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_AGENT_RECOVERY_DIR", "/user/recovery")
    monkeypatch.setenv("WORKBENCH_EGRESS_AUDIT_DIR", "/user/egress")
    harness = offline_pressure.Pressure(tmp_path, 4096)
    assert harness.env["WORKBENCH_AGENT_RECOVERY_DIR"] == str(tmp_path / "agent-recovery")
    assert harness.env["WORKBENCH_EGRESS_AUDIT_DIR"] == str(tmp_path / "egress-audit")


def test_interrupt_keeps_the_failure_and_unfinished_task(tmp_path, monkeypatch):
    harness = offline_pressure.Pressure(tmp_path, 4096)

    async def interrupt():
        started = asyncio.Event()

        async def exercise():
            row = harness.task("fake", "replay")
            harness.event(row, status="running")
            started.set()
            await asyncio.Future()

        async def monitor():
            await asyncio.Future()

        monkeypatch.setattr(harness, "exercise", exercise)
        monkeypatch.setattr(harness, "monitor", monitor)
        supervisor = asyncio.create_task(harness.run(0))
        await started.wait()
        supervisor.cancel()
        with pytest.raises(asyncio.CancelledError):
            await supervisor

    asyncio.run(interrupt())
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["result"] == "interrupted"
    assert summary["tasks"][0]["status"] == "interrupted"
    assert "取消" in summary["tasks"][0]["detail"]


def test_child_has_its_own_process_group_and_cleanup_signals_the_group(tmp_path, monkeypatch):
    harness = offline_pressure.Pressure(tmp_path, 4096)
    observed = {}

    class Child:
        pid = 23456
        def poll(self):
            return None
        def wait(self, timeout):
            return 0
        def terminate(self):
            observed["direct_child_only"] = True

    def launch(*args, **kwargs):
        observed.update(kwargs)
        return Child()

    signals = []
    monkeypatch.setattr(offline_pressure.subprocess, "Popen", launch)
    monkeypatch.setattr(offline_pressure.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    harness.child("test", ["test-only"])
    harness.close()
    assert observed.get("start_new_session") is True
    assert (Child.pid, signal.SIGTERM) in signals
    assert "direct_child_only" not in observed
