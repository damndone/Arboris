"""Alternating A/B runs of ``perf_agent_turn_replay.py`` on fixed recorded tasks.

Each run is a fresh process on an exported source tree (``git archive <commit> backend``).
Calibration runs of A come first, then strictly alternating A, B pairs. Every raw
summary is kept as one JSON line in ``<out>/runs.jsonl``, including failed runs.
The disk floor is checked before reusing ``<out>/active``. Worker logs and a
verified inventory are retained before the project is removed. Each label and
task keeps one representative project per campaign. Other Python processes and
the load average are recorded with each run, since other sessions may share the machine.

    .venv/bin/python scripts/perf_agent_turn_ab.py --out <folder> --provider <json> \
        --a before=<tree>/backend --b after=<tree>/backend --task 403=<task dir> --pairs 5
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time

from perf_evidence import digest, finalize_active, retain_worker_logs

ROOT = Path(__file__).resolve().parents[1]
FREE_FLOOR_BYTES = 5 * 1024 ** 3


def _other_python_processes() -> list[str]:
    listing = subprocess.run(["ps", "-Ao", "pid,pcpu,command"], capture_output=True, text=True).stdout
    return [line.strip()[:160] for line in listing.splitlines()[1:]
            if "python" in line.lower() and str(os.getpid()) not in line.split()[:1]
            and "perf_agent_turn" not in line]


def _append_run(out: Path, record: dict) -> None:
    with (out / "runs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _one(out: Path, label: str, backend: Path, task: str, task_dir: Path, provider: Path, ordinal: int,
         phase: str) -> dict:
    free = shutil.disk_usage(out).free
    record = {"ordinal": ordinal, "phase": phase, "label": label, "task": task, "backend": str(backend),
              "free_bytes_before": free, "load_average": os.getloadavg(),
              "other_python_processes": _other_python_processes(), "started_at": time.time()}
    if free < FREE_FLOOR_BYTES:
        record["status"] = "not_started_low_disk"
        _append_run(out, record)
        return record
    record_id = f"{ordinal:03d}-{task}-{label}"
    summary_path = out / "summaries" / f"{record_id}.json"
    logs_path = out / "logs" / record_id
    active = out / "active"
    active.mkdir(exist_ok=False)
    for path in (summary_path, logs_path):
        if path.exists() or path.is_symlink():
            active.rmdir()
            raise FileExistsError(path)
    work = active / "worker"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path = active / "stderr.log"
    with (active / "stdout.log").open("xb") as stdout, stderr_path.open("xb") as stderr:
        started = time.perf_counter()
        result = subprocess.run([sys.executable, "-W", "ignore", str(ROOT / "scripts" / "perf_agent_turn_replay.py"),
                                 "--backend", str(backend), "--task-dir", str(task_dir), "--work", str(work),
                                 "--provider", str(provider), "--out", str(summary_path)],
                                stdout=stdout, stderr=stderr, cwd=ROOT, env={**os.environ, "PYTHONPATH": ""})
        record.update(process_wall_s=time.perf_counter() - started, returncode=result.returncode)
    with stderr_path.open("rb") as stderr:
        stderr.seek(-min(stderr_path.stat().st_size, 8000), os.SEEK_END)
        record["stderr_tail"] = stderr.read().decode("utf-8", errors="replace")[-2000:]
    record["status"] = "failed"
    if result.returncode == 0:
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if not isinstance(summary, dict):
                raise ValueError("expected a replay summary object")
            record.update(status="ok", summary=summary)
        except (OSError, ValueError) as exc:
            record["summary_error"] = str(exc)
    project = work / "project"
    sessions = project / "workbench" / "agent-sessions"
    additional_logs = (work / "normalized-journal.json", *sessions.glob("*.jsonl"), *sessions.glob("*.meta.json"))
    record["retained_logs"] = retain_worker_logs(active, logs_path, additional_paths=additional_logs)
    _append_run(out, record)
    record["retention"] = finalize_active(
        active, ledger=out / "retention.jsonl", record_id=record_id, metadata=record | {"run_root": str(project)},
        archive_dir=out / "representatives" / task, version=label, case=task,
    )
    return record


def _campaign_identity(backends, tasks, provider):
    inputs = []
    for name, task in tasks:
        dataset, = task.glob("*.csv")
        paths = (dataset, task / "record.json", task / "provider_tape.jsonl.gz")
        inputs.append({"name": name, "root": str(task), "sha256": {path.name: digest(path) for path in paths}})
    return {"backends": [(name, str(path)) for name, path in backends], "tasks": inputs,
            "provider": {"path": str(provider), "sha256": digest(provider)}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--provider", type=Path, required=True)
    parser.add_argument("--a", required=True, help="label=backend directory (baseline)")
    parser.add_argument("--b", required=True, help="label=backend directory (candidate)")
    parser.add_argument("--task", action="append", required=True, help="name=recorded task directory")
    parser.add_argument("--calibration", type=int, default=5)
    parser.add_argument("--pairs", type=int, default=5)
    args = parser.parse_args()
    (a_label, a_backend), (b_label, b_backend) = [(item.split("=", 1)[0], Path(item.split("=", 1)[1]).resolve())
                                                  for item in (args.a, args.b)]
    tasks = [(item.split("=", 1)[0], Path(item.split("=", 1)[1]).resolve()) for item in args.task]
    if a_label == b_label:
        parser.error("the baseline and candidate need distinct labels")
    for name in (a_label, b_label, *(task for task, _ in tasks)):
        if not name or Path(name).name != name or name in {".", ".."}:
            parser.error("labels and task names must be single path components")
    if len({task for task, _ in tasks}) != len(tasks):
        parser.error("each task needs a distinct name")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    with (out / ".campaign.lock").open("ab") as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("this replay campaign is already running; wait for its lease or use a new --out directory")
        _run_campaign(out, parser, args, (a_label, a_backend), (b_label, b_backend), tasks)


def _run_campaign(out, parser, args, baseline, candidate, tasks):
    journal = out / "runs.jsonl"
    identity_path = out / "campaign.json"
    if journal.exists() and not identity_path.exists():
        parser.error("the existing replay journal has no frozen input identity. Use a new --out directory")
    provider = args.provider.resolve()
    try:
        identity = _campaign_identity((baseline, candidate), tasks, provider)
    except (ValueError, OSError) as exc:
        parser.error(f"cannot identify replay inputs: {exc}")
    encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True)
    if identity_path.exists():
        if identity_path.read_text(encoding="utf-8").strip() != encoded:
            parser.error("the recorded replay inputs or backends differ. Use a new --out directory")
    else:
        with identity_path.open("x", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    ordinal = 0
    if journal.exists():
        with journal.open(encoding="utf-8") as handle:
            ordinal = sum(1 for _ in handle)
    schedule = [("calibration", *baseline)] * args.calibration
    for _ in range(args.pairs):
        schedule += [("pair", *baseline), ("pair", *candidate)]
    for phase, label, backend in schedule:
        for task, task_dir in tasks:
            record = _one(out, label, backend, task, task_dir, provider, ordinal, phase)
            ordinal += 1
            summary = record.get("summary") or {}
            retention = record.get("retention") or {}
            print(f"{record['ordinal']:3d} {phase:11s} {label:8s} {task:5s} {record['status']:8s} "
                  f"step_median_ms={summary.get('step_nonmodel_ms_median')} "
                  f"turn_nonmodel_s={summary.get('turn_nonmodel_s_total')} "
                  f"representative_bytes={retention.get('representative_bytes')}", flush=True)
            if record["status"] == "not_started_low_disk":
                return
    rows = [json.loads(line) for line in journal.open()]
    report = {}
    for task, _ in tasks:
        for label, _ in (baseline, candidate):
            for phase in ("calibration", "pair"):
                done = [row["summary"] for row in rows if row["task"] == task and row["label"] == label
                        and row["phase"] == phase and row["status"] == "ok"]
                if done:
                    step = [item["step_nonmodel_ms_median"] for item in done]
                    turn = [item["turn_nonmodel_s_total"] for item in done]
                    report[f"{task}/{label}/{phase}"] = {
                        "runs": len(done), "step_median_ms": statistics.median(step), "step_min_ms": min(step),
                        "step_max_ms": max(step), "turn_nonmodel_s_median": statistics.median(turn),
                        "turn_nonmodel_s_min": min(turn), "turn_nonmodel_s_max": max(turn)}
    (out / "report.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
