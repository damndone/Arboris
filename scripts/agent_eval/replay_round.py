"""Replay a recorded QRData round on the current code, with no model or network request.

Each task's answered model replies are served in recorded order (scripts/agent_eval/recorder.py,
answered_only) and the current code judges the same tool calls. Identifiers the new run mints
afresh are mapped to the recorded ones by lining up the requests. The output folder has the
same layout as a live round, so refusal-audit-20261102/round_tools.py reads it unchanged.

What a replay measures: how the current code treats the calls the model actually made --
refusals that disappear, and refusals the change adds. What it cannot measure: what the model
would do differently after a different reply (a better refusal message, a new step it never
saw). Once the replies diverge from the recording the rest of that task is not evidence, so the
report counts calls up to each task's first divergent tool result separately.

Run: .venv/bin/python scripts/agent_eval/replay_round.py <recorded round>/qr55 <out folder> [--workers N]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _recorded_tasks(round_folder: Path) -> list[str]:
    return sorted({path.parts[-4] for path in round_folder.glob("qrdata40/ask/*/tasks/*/record.json")
                   if "attempt0" not in str(path)})


def _replay_one(task: str, round_folder: Path, out: Path) -> tuple[str, int]:
    folder = out / "qrdata40" / "ask" / task
    folder.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend"), "LC_ALL": "en_US.UTF-8", "LANG": "en_US.UTF-8",
           "WORKBENCH_AGENT_MODEL": "nvidia/nemotron-3-ultra-550b-a55b", "WORKBENCH_REASONING_EFFORT": "high",
           "WORKBENCH_EVAL_RETRY_DELAYS_S": "0"}
    command = [sys.executable, str(ROOT / "scripts/agent_eval_run.py"), "--out", str(folder), "--suite", "external",
               "--tasks", task, "--repeat", "1", "--mode", "ask", "--transport", "headless", "--max-nudges", "8",
               "--max-wall-s", "1800", "--replay-round", str(round_folder)]
    with open(folder / "run.log", "w") as log:
        code = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    return task, code


def _tool_results(record: dict) -> list[dict]:
    results = []
    for entry in (record.get("conversation") or {}).get("entries") or []:
        payload = entry["payload"]
        if entry["entry_type"] == "message" and payload.get("role") == "tool":
            try:
                results.append(json.loads(payload["content"]))
            except (TypeError, ValueError):
                results.append({"unparsed": True})
    return results


def _outcome(result: dict) -> tuple[bool, str | None]:
    return bool(result.get("ok")), result.get("error")


def compare(round_folder: Path, out: Path) -> dict:
    """Refusals per task up to the first tool result whose outcome differs from the recording."""
    rows = []
    for replayed_path in sorted(out.glob("qrdata40/ask/*/tasks/*/record.json")):
        task_folder = replayed_path.parts[-4]
        recorded_path = next((path for path in round_folder.glob(f"qrdata40/ask/{task_folder}/tasks/*/record.json")
                              if "attempt0" not in str(path)), None)
        if recorded_path is None:
            continue
        recorded = _tool_results(json.loads(recorded_path.read_text()))
        replayed_record = json.loads(replayed_path.read_text())
        replayed = _tool_results(replayed_record)
        aligned = 0
        for old, new in zip(recorded, replayed):
            if _outcome(old) != _outcome(new):
                break
            aligned += 1
        first_change = None
        if aligned < min(len(recorded), len(replayed)):
            first_change = {"recorded": _outcome(recorded[aligned]), "replayed": _outcome(replayed[aligned]),
                            "message": str((replayed[aligned].get("error_details") or [{}])[0].get("message")
                                           or replayed[aligned].get("output"))[:300]}
        rows.append({
            "task": task_folder, "status": replayed_record.get("status"), "replay": replayed_record.get("replay"),
            "recorded_refusals": sum(not ok for ok, _ in map(_outcome, recorded)),
            "replayed_refusals": sum(not ok for ok, _ in map(_outcome, replayed)),
            "aligned_results": aligned, "recorded_results": len(recorded), "replayed_results": len(replayed),
            "first_change": first_change,
        })
    return {"tasks": rows,
            "recorded_refusals": sum(row["recorded_refusals"] for row in rows),
            "replayed_refusals": sum(row["replayed_refusals"] for row in rows),
            "tasks_diverged": sum(row["first_change"] is not None for row in rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("round_folder", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--tasks", default="", help="comma-separated task ids; empty = every recorded task")
    args = parser.parse_args()
    round_folder, out = args.round_folder.resolve(), args.out.resolve()
    tasks = [task for task in args.tasks.split(",") if task] or _recorded_tasks(round_folder)
    out.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for task, code in pool.map(lambda task: _replay_one(task, round_folder, out), tasks):
            print(f"{task} exit {code}", flush=True)
    report = compare(round_folder, out)
    (out / "replay_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"recorded refusals {report['recorded_refusals']}, replayed {report['replayed_refusals']}, "
          f"tasks diverged {report['tasks_diverged']} of {len(report['tasks'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
