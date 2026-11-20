"""Stdlib-only durable gate timings and evidence key; does not choose or omit any tests.

The summary binds its verdict to the tree that was tested (2026-11-06 risk review, finding 11):
``init`` digests the working tree, ``finish`` digests it again and records the full evidence key
(scripts/evidence_identity.py). A tree that changed during the run fails the gate; an identity
that could not be read leaves the verdict alone and marks the evidence incomplete.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence_identity  # noqa: E402


def _write(path: Path, value: dict | list) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def collect_tests(directory: Path) -> tuple[list[dict], list[str]]:
    tests, errors = [], []
    for path in sorted(directory.glob("*.junit.xml")):
        try:
            root = ET.parse(path).getroot()
            for case in root.iter("testcase"):
                tests.append({"runner": "pytest", "name": case.get("classname", "") + "::" + case.get("name", ""),
                              "duration_seconds": float(case.get("time", 0)), "report": path.name,
                              "status": "failed" if case.find("failure") is not None or case.find("error") is not None
                              else "skipped" if case.find("skipped") is not None else "passed"})
        except (OSError, ValueError, ET.ParseError) as exc:
            errors.append(f"{path.name}: {exc}")
    for path in sorted(directory.glob("*.vitest.json")):
        try:
            report = json.loads(path.read_text())
            for suite in report.get("testResults", []):
                for case in suite.get("assertionResults", []):
                    if case.get("duration") is not None:
                        tests.append({"runner": "vitest", "name": case["fullName"],
                                      "duration_seconds": float(case["duration"]) / 1000,
                                      "status": case["status"], "report": path.name})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{path.name}: {exc}")
    return tests, errors


#: Passed gate runs kept in local/gate (the user's evidence rule, 2026-10-07:
#: keep the last 3 of each kind, always keep a failed one).
KEEP_PASSED = 3
GATE_OUTPUT = ("local/gate/",)  # the gate's own logs never count as the tested tree
_RUN_NAME = re.compile(r"^\d{8}T\d{6}-[A-Za-z0-9_]+$")


def prune(parent: Path, keep: int = KEEP_PASSED) -> list[Path]:
    """Remove passed runs beyond the newest ``keep``. A failed, running or
    unreadable run, one marked ``.keep``, and anything that is not a run
    directory directly in ``parent`` are left alone."""
    passed = []
    for path in parent.iterdir() if parent.is_dir() else ():
        if path.is_symlink() or not path.is_dir() or not _RUN_NAME.match(path.name) or (path / ".keep").exists():
            continue
        try:
            status = json.loads((path / "summary.json").read_text()).get("status")
        except (OSError, ValueError):
            continue
        if status == "passed":
            passed.append(path)
    removed = sorted(passed, key=lambda path: path.name, reverse=True)[keep:]
    for path in removed:
        shutil.rmtree(path)
    return removed


def main(arguments: list[str]) -> None:
    operation, *args = arguments
    if operation == "clock":
        print(time.monotonic())
        return
    if operation == "init":
        parent = Path.cwd() / "local" / "gate"
        parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        directory = Path(tempfile.mkdtemp(prefix=now.strftime("%Y%m%dT%H%M%S-"), dir=parent))
        git = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
        try:
            tree = evidence_identity.source_tree(Path.cwd(), GATE_OUTPUT)
        except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
            tree = {"error": f"{type(exc).__name__}: {exc}"}
        _write(directory / "summary.json", {
            "schema_version": "workbench.gate-timing/v1", "mode": args[0], "status": "running",
            "started_at": now.isoformat(), "started_monotonic": time.monotonic(),
            "cwd": str(Path.cwd()), "head": git.stdout.strip() if git.returncode == 0 else None,
            "source_tree_at_start": tree, "stages": [],
        })
        print(directory)
        return
    directory = Path(args[0])
    path = directory / "summary.json"
    summary = json.loads(path.read_text())
    if operation == "stage":
        _, label, started, exit_code, log = args
        summary["stages"].append({"label": label, "duration_seconds": time.monotonic() - float(started),
                                  "exit_code": int(exit_code), "log": log,
                                  "stderr_log": log.removesuffix(".log") + ".stderr.log"})
    elif operation == "finish":
        exit_code = int(args[1])
        summary.update(status="passed" if exit_code == 0 else "failed", exit_code=exit_code,
                       finished_at=datetime.now(timezone.utc).isoformat(),
                       duration_seconds=time.monotonic() - summary["started_monotonic"])
        tests, errors = collect_tests(directory)
        _write(directory / "test-timings.json", tests)
        summary["test_count"] = len(tests)
        summary["slow_tests"] = sorted(tests, key=lambda test: test["duration_seconds"], reverse=True)[:25]
        summary["slow_stages"] = sorted(summary["stages"], key=lambda stage: stage["duration_seconds"], reverse=True)
        summary["report_errors"] = errors
        record_evidence(summary, tests, python=args[2] if len(args) > 2 else None)
    else:
        raise ValueError(f"unknown timing operation: {operation}")
    _write(path, summary)
    if operation == "finish":
        prune(directory.parent)
        if summary.get("evidence_status") == "invalidated":
            raise SystemExit("gate evidence invalidated: the source tree changed during the run")


def record_evidence(summary: dict, tests: list[dict], *, python: str | None) -> None:
    """Attach the evidence key; a tree changed since ``init`` invalidates the run."""
    names = sorted(f"{test['runner']}:{test['name']}" for test in tests)
    selection = {"mode": summary["mode"], "stages": [stage["label"] for stage in summary["stages"]],
                 "tests": len(names), "tests_sha256": evidence_identity.canonical_sha256(names)}
    try:
        key = evidence_identity.evidence_key(Path(summary["cwd"]), python=python or None,
                                             scope=f"gate:{summary['mode']}", test_selection=selection,
                                             exclude=GATE_OUTPUT)
    except (OSError, ValueError, subprocess.CalledProcessError, UnicodeError) as exc:
        summary.update(evidence_status="incomplete", evidence_key={"error": f"{type(exc).__name__}: {exc}"})
        return
    summary["evidence_key"] = key
    start = summary.get("source_tree_at_start", {})
    if start.get("sha256") != key["source_tree"]["sha256"] or "error" in start:
        summary.update(evidence_status="invalidated" if "error" not in start else "incomplete")
        if "error" not in start:
            summary.update(status="failed", exit_code=summary["exit_code"] or 1,
                           invalidated_reason="source_tree_changed_during_run")
        return
    parts = (key["environment"], key["native_builds"])
    complete = not any("error" in part for part in parts) and key["environment"]["lock"].get("matches")
    summary["evidence_status"] = "complete" if complete else "incomplete"


if __name__ == "__main__":
    main(sys.argv[1:])
