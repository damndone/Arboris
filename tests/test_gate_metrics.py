"""Gate instrumentation consumes real runner reports without filtering tests."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


HELPER = Path(__file__).resolve().parents[1] / "scripts/gate_metrics.py"


def test_timing_summary_keeps_all_real_pytest_results_and_vitest_durations(tmp_path):
    def metrics(*args):
        return subprocess.run([sys.executable, str(HELPER), *map(str, args)], cwd=tmp_path,
                              text=True, capture_output=True, check=True).stdout.strip()

    directory = Path(metrics("init", "full"))
    test_file = tmp_path / "test_fixture.py"
    test_file.write_text("def test_pass():\n    assert True\n\ndef test_fail():\n    assert False\n")
    started = metrics("clock")
    completed = subprocess.run([sys.executable, "-m", "pytest", str(test_file), "-q", "--durations=25",
                               f"--junitxml={directory / 'stage-1.junit.xml'}"], cwd=tmp_path,
                              env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}, capture_output=True, text=True)
    assert completed.returncode == 1
    (directory / "stage-1.log").write_text(completed.stdout + completed.stderr)
    metrics("stage", directory, "backend", started, 1, "stage-1.log")
    (directory / "stage-2.vitest.json").write_text(json.dumps({"testResults": [{"assertionResults": [
        {"fullName": "slow frontend fixture", "status": "passed", "duration": 750}]}]}))
    metrics("finish", directory, 1)
    summary = json.loads((directory / "summary.json").read_text())
    cases = json.loads((directory / "test-timings.json").read_text())
    assert summary["status"] == "failed" and summary["stages"][0]["exit_code"] == 1
    assert summary["duration_seconds"] >= summary["stages"][0]["duration_seconds"] >= 0
    assert summary["test_count"] == len(cases) == 3
    assert {case["status"] for case in cases if case["runner"] == "pytest"} == {"passed", "failed"}
    assert summary["slow_tests"][0]["name"] == "slow frontend fixture"
    assert summary["slow_tests"][0]["duration_seconds"] == .75
    assert summary["report_errors"] == []


def test_malformed_timing_reports_are_visible(tmp_path):
    specification = importlib.util.spec_from_file_location("gate_metrics", HELPER)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    (tmp_path / "broken.junit.xml").write_text("not XML")
    (tmp_path / "broken.vitest.json").write_text("not JSON")
    cases, errors = module.collect_tests(tmp_path)
    assert cases == []
    assert len(errors) == 2


def test_finished_gates_keep_the_newest_passed_runs_and_every_failed_one(tmp_path):
    spec = importlib.util.spec_from_file_location("gate_metrics", HELPER)
    metrics = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(metrics)

    def run(name, status, keep=False):
        path = tmp_path / name
        path.mkdir()
        (path / "summary.json").write_text(json.dumps({"status": status}))
        if keep:
            (path / ".keep").write_text("")
        return path

    passed = [run(f"2026100{day}T120000-p{day}", "passed") for day in range(1, 6)]
    failed = run("20261001T090000-f1", "failed")
    running = run("20261002T090000-r1", "running")
    pinned = run("20261001T080000-k1", "passed", keep=True)
    other = tmp_path / "notes"
    other.mkdir()
    removed = metrics.prune(tmp_path)
    assert sorted(path.name for path in removed) == [passed[0].name, passed[1].name]
    assert all(path.exists() for path in (*passed[2:], failed, running, pinned, other))
