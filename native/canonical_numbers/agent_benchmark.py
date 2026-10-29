"""A/B the same frozen offline Agent pipeline using two default source trees.

Each measured observation is a fresh process. No functions/configuration are
patched: worker --source-tree imports the requested backend directly. Model
waiting, runtime handlers and task-quality evaluation are excluded explicitly.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from perf_evidence import digest, require_space, finalize_active
from perf_agent_pipeline import verify_source_snapshot

MODULES = ("agent/compaction.py", "agent/context.py", "agent/model.py", "agent/session.py", "agent/tools.py",
           "agent/tool_receipts.py", "agent/business_identity.py", "jsonl_store.py", "native_canonical.py")


def host_idle_snapshot():
    raw = subprocess.check_output(["ps", "-Ao", "pid=,ppid=,command="], text=True)
    competing = []
    for line in raw.splitlines():
        pid, ppid, command = line.strip().split(maxsplit=2)
        if int(pid) in {os.getpid(), os.getppid()} or "ps -Ao" in command:
            continue
        if any(token in command for token in (
                "-m pytest", "/pytest ", "vitest", "scripts/perf_1m.py", "scripts/agent_eval_run.py",
                "native/kendall_counts/bench.py", "native/ar_exact/bench.py", "bench_families.py",
                "native/canonical_numbers/run_benchmark.py", "native/canonical_numbers/agent_benchmark.py",
                "scripts/perf_agent_pipeline.py worker")):
            competing.append({"pid": int(pid), "ppid": int(ppid)})
    if competing:
        raise RuntimeError("measurement host is not test/evaluation-idle: " + json.dumps(competing))
    return {"processes_checked": len(raw.splitlines()), "competing": competing}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-source", type=Path, required=True)
    parser.add_argument("--candidate-source", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--allow-low-space", action="store_true")
    args = parser.parse_args()
    args.out = args.out.resolve()
    if args.out.exists():
        raise FileExistsError(args.out)
    require_space(ROOT, allow_low_space=args.allow_low_space)
    args.out.mkdir(parents=True)
    source_trees = {"baseline":args.baseline_source.resolve(), "candidate":args.candidate_source.resolve()}
    worker = ROOT / "scripts/perf_agent_pipeline.py"
    files = [worker, Path(__file__).resolve(), ROOT / "scripts/perf_evidence.py", Path(sys.executable).resolve()]
    files.extend(tree / "backend/workbench" / module for tree in source_trees.values() for module in MODULES)
    sources = {str(path):digest(path) for path in files}
    snapshot_manifests = {}
    for role,tree in source_trees.items():
        snapshot_manifests[role] = verify_source_snapshot(tree)["manifest_sha256"]
    if digest(args.fixture / "manifest.json") != args.sha256:
        raise ValueError("frozen pipeline input manifest changed")
    manifest = {"schema_version":1, "scope":"offline_local_pipeline_replay",
        "source_sha256":sources, "snapshot_manifest_sha256":snapshot_manifests,
        "fixture_manifest_sha256":args.sha256, "source_trees":{key:str(value) for key,value in source_trees.items()},
        "worker_environment":"inherited unchanged; --source-tree selects default imported code",
        "low_space_exception":args.allow_low_space, "calibration":5,"alternating_pairs":5,
        "noise_definition":"sample standard deviation / median; max calibration and all baseline; no exclusion",
        "noise_limit":.05,"regression_limit":1.05, "native_kernel_speedup_claim":False,
        "retention":"one active/work tree; per-file SHA journal then one representative per source lane and verified removal",
        "host_idle":"ps before and after every worker; failures retained without claiming host idleness",
        "source_validation":"full backend/runtime registrations plus shared driver/worker/helper/interpreter SHA before/after every worker; pyc excluded",
        "storage_metric":"work_dir_bytes; complete worker work directory, controls/retention outside excluded"}
    (args.out / "source-manifest.json").write_text(json.dumps(manifest,sort_keys=True,indent=2)+"\n")
    manifest_sha = digest(args.out / "source-manifest.json")
    sequence = [("calibration",i,"baseline") for i in range(5)]
    for pair in range(5):
        sequence.extend(("pair",pair,engine) for engine in (
            ("baseline","candidate") if pair%2 == 0 else ("candidate","baseline")))
    rows = []
    for ordinal,(phase,pair,engine) in enumerate(sequence):
        free = require_space(ROOT,allow_low_space=args.allow_low_space)
        if any(digest(path) != checksum for path,checksum in sources.items()):
            raise ValueError("pipeline A/B source changed during measurement")
        for role,tree in source_trees.items():
            verify_source_snapshot(tree,snapshot_manifests[role])
        active = args.out / "active"
        if active.exists() or active.is_symlink():
            raise RuntimeError("an active pipeline tree already exists; refusing another observation")
        active.mkdir()
        run_dir = active / "work"
        command = [sys.executable,str(worker),"worker","--fixture",str(args.fixture.resolve()),
                   "--sha256",args.sha256,"--source-tree",str(source_trees[engine]),"--work-dir",str(run_dir.resolve())]
        row = {"phase":phase,"pair":pair,"engine_role":engine,"benchmark_manifest_sha256":manifest_sha,
               "free_before_bytes":free,"command":command,"status":"failed", "measurement_started":False,
               "run_root":str(run_dir.resolve())}
        try:
            row["processes_before"] = host_idle_snapshot()
            (active / "processes-before.json").write_text(json.dumps(row["processes_before"],sort_keys=True)+"\n")
            row["measurement_started"] = True
            started = perf_counter()
            result = subprocess.run(command,cwd=ROOT,text=True,capture_output=True)
            row["process_seconds"] = perf_counter()-started
            row["returncode"] = result.returncode
            row.update(json.loads(result.stdout) if not result.returncode else {"stdout":result.stdout,"stderr":result.stderr})
            if any(digest(path) != checksum for path,checksum in sources.items()):
                raise ValueError("pipeline A/B source changed during measurement")
            for role,tree in source_trees.items():
                verify_source_snapshot(tree,snapshot_manifests[role])
            row["processes_after"] = host_idle_snapshot()
            (active / "processes-after.json").write_text(json.dumps(row["processes_after"],sort_keys=True)+"\n")
            if result.returncode:
                raise RuntimeError("offline pipeline worker failed")
            if type(row.get("work_dir_bytes")) is not int or row["work_dir_bytes"] <= 0:
                raise ValueError("offline pipeline worker reported missing or invalid storage bytes")
            row["status"] = "completed"
        except BaseException as error:
            row["error"] = type(error).__name__ + ": " + str(error)
            raise
        finally:
            (active / "measurement.json").write_text(json.dumps(row,sort_keys=True)+"\n")
            # The dedicated helper verifies every file SHA and its durable
            # journal, then verifies an archive before removing only active.
            row["retention"] = finalize_active(active, ledger=args.out / "retention.jsonl",
                record_id=f"{ordinal:02d}-{engine}", metadata=row,
                archive_dir=args.out / "representatives", version=engine, case="agent-local-pipeline")
            with (args.out / "runs.jsonl").open("a") as stream:
                stream.write(json.dumps(row,sort_keys=True)+"\n");stream.flush();os.fsync(stream.fileno())
            rows.append(row)
    calibration = [row for row in rows if row["phase"] == "calibration"]
    baseline = [row for row in rows if row["engine_role"] == "baseline"]
    paired = [row for row in rows if row["phase"] == "pair"]
    metrics = ("seconds","process_seconds","local_pipeline_seconds","rss_bytes","work_dir_bytes")
    def noise(data,key):
        return statistics.stdev(row[key] for row in data)/statistics.median(row[key] for row in data)
    noises = {key:max(noise(calibration,key),noise(baseline,key)) for key in metrics}
    ratios = {key:statistics.median(next(row[key] for row in paired if row["pair"] == pair and row["engine_role"] == "candidate") /
                                   next(row[key] for row in paired if row["pair"] == pair and row["engine_role"] == "baseline")
                                   for pair in range(5)) for key in metrics}
    results = {row["result_sha256"] for row in rows}
    failures = ([] if len(results)==1 else ["result_hash_mismatch"])
    failures.extend(key+"_noise" for key,value in noises.items() if value >= .05)
    failures.extend(key+"_regression" for key,value in ratios.items() if value > 1.05)
    stage_medians = {engine:{stage:statistics.median(row["stage_seconds"][stage] for row in paired if row["engine_role"] == engine)
                             for stage in paired[0]["stage_seconds"]} for engine in source_trees}
    report = {"manifest_sha256":manifest_sha,"scope":manifest["scope"],"accepted_local_replay":not failures,
              "failures":failures,"noise":noises,"median_candidate_over_baseline":ratios,
              "stage_seconds_median":stage_medians,"result_sha256":sorted(results),"native_kernel_speedup_claim":False}
    (args.out / "report.json").write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
    print(json.dumps(report,sort_keys=True))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
