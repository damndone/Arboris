"""A task's wall-clock limit measures the Agent, not the waits the harness inserts between requests."""
from types import SimpleNamespace

from tests.test_agent_eval_headless_transport import runner  # noqa: F401 - fixture


class Client:
    def post(self, *args, **kwargs):
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"session_id": "s"})


def _conversation(runner, monkeypatch, paced_per_turn):  # noqa: F811
    clock, paced = [0.0], [0.0]

    def turn(*args, **kwargs):
        clock[0] += 100.0
        paced[0] += paced_per_turn
        return {"reply": "still working", "status": "ok"}

    monkeypatch.setattr(runner.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(runner, "pacing_wait_s", lambda: paced[0])
    monkeypatch.setattr(runner, "_turn", turn)
    monkeypatch.setattr(runner, "_pending_proposals", lambda *args: [])
    monkeypatch.setattr(runner, "_session_entries", lambda *args: [])
    return runner.run_conversation(Client(), "root", "run", "Analyze",
                                   runner.Policy(mode="ask", max_wall_s=300.0, max_nudges=8))


def test_pacing_waits_do_not_spend_the_wall_limit(runner, monkeypatch):  # noqa: F811
    result = _conversation(runner, monkeypatch, paced_per_turn=90.0)
    assert result["stop_reason"] == "nudge_budget" and result["nudges"] == 8
    assert result["pacing_wait_s"] == 810.0 and result["wall_s"] == 900.0


def test_without_pacing_the_wall_limit_is_unchanged(runner, monkeypatch):  # noqa: F811
    result = _conversation(runner, monkeypatch, paced_per_turn=0.0)
    assert result["stop_reason"] == "wall_clock" and result["wall_s"] == 300.0


def test_the_pace_counts_each_wait_it_sleeps(tmp_path, monkeypatch):
    from agent_eval import nvidia_serial

    clock = [1000.0]
    monkeypatch.setattr(nvidia_serial.time, "time", lambda: clock[0])
    monkeypatch.setattr(nvidia_serial.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    pace = nvidia_serial.SharedStartPace(tmp_path / "pace", 75)
    before = nvidia_serial.pacing_wait_s()
    for _ in range(3):
        pace.wait_turn()
    assert round(nvidia_serial.pacing_wait_s() - before, 6) == 150.0


def test_the_agent_turn_budget_reads_the_same_pacing_waits(runner, monkeypatch):  # noqa: F811
    from workbench.agent import turn_clock

    seen = []
    monkeypatch.setattr(runner, "pacing_wait_s", lambda: 42.0)
    monkeypatch.setattr(runner, "_turn", lambda *a, **k: seen.append(turn_clock.excluded_s()) or
                        {"reply": "ANALYSIS COMPLETE", "status": "ok"})
    monkeypatch.setattr(runner, "_session_entries", lambda *args: [])
    runner.run_conversation(Client(), "root", "run", "Analyze", runner.Policy(mode="ask"))
    assert seen == [42.0] and turn_clock.excluded_s() == 0.0
