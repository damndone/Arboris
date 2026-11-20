"""Five fixed-input baseline calibrations and five alternating fresh-process pairs.

Component results include input I/O, numeric validation, full encoding, Python /
C++ crossings, allocation/copy, UTF8 and SHA256. They cannot establish Agent or
OLS end-to-end acceptance. Retains JSONL evidence only; never deletes data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from perf_evidence import digest, require_space
from agent_benchmark import host_idle_snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--allow-low-space", action="store_true")
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(args.out)
    require_space(ROOT, allow_low_space=args.allow_low_space)
    args.out.mkdir(parents=True)
    inputs = json.loads(args.inputs.read_text())["inputs"]
    worker = Path(__file__).with_name("benchmark.py")
    from sysconfig import get_config_var
    binary = ROOT / "local/native-canonical" / ("_canonical_numbers" + get_config_var("EXT_SUFFIX"))
    sources = [worker, Path(__file__), ROOT / "scripts/perf_evidence.py", Path(__file__).with_name("canonical_numbers.cpp"),
               Path(__file__).with_name("agent_benchmark.py"), ROOT / "backend/workbench/canonical.py", ROOT / "backend/workbench/native_canonical.py", binary]
    manifest = {"schema_version": 1, "scope": "canonical_numeric_component",
        "input_manifest_sha256": digest(args.inputs), "inputs": inputs,
        "source_sha256": {str(path.relative_to(ROOT)): digest(path) for path in sources},
        "python": {"executable": sys.executable, "version": sys.version, "platform": platform.platform()},
        "thread_environment": {key:os.environ.get(key) for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")},
        "worker_environment": "inherited unchanged", "fresh_process_per_observation": True,
        "low_space_exception": args.allow_low_space, "calibrations": 5, "alternating_pairs": 5,
        "noise_definition": "sample standard deviation / median; calibration and all-reference max; no exclusion",
        "noise_limit": .05, "default_regression_limit": 1.05,
        "memory_metric": "process ru_maxrss bytes; no tracemalloc substitution",
        "kernel_threads": 1, "kernel_gil": "held; no signal polling in numeric loop",
        "acceptance_boundary": "component only; no full Agent or OLS claim",
        "host_idle": "ps before and after each worker; failed probes retained explicitly"}
    raw_manifest = json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n"
    (args.out / "source-manifest.json").write_bytes(raw_manifest)
    manifest_sha256 = hashlib.sha256(raw_manifest).hexdigest()
    ledger = args.out / "runs.jsonl"
    rows = []
    def idle_or_record(stage):
        try:
            return host_idle_snapshot()
        except Exception as error:
            (args.out / "host-check-failure.json").write_text(json.dumps({
                "stage":stage,"completed_measurements":len(rows),
                "error":type(error).__name__ + ": " + str(error),
                "manifest_sha256":manifest_sha256},sort_keys=True)+"\n")
            raise
    idle_or_record("preflight")
    for fixture in inputs:
        if digest(fixture["path"]) != fixture["sha256"]:
            raise ValueError("frozen numeric input changed")
        sequence = [("calibration", i, "reference") for i in range(5)]
        for pair in range(5):
            sequence.extend(("pair", pair, engine) for engine in (
                ("reference", "native") if pair % 2 == 0 else ("native", "reference")))
        for phase, pair, engine in sequence:
            free = require_space(ROOT, allow_low_space=args.allow_low_space)
            for path in sources:
                if digest(path) != manifest["source_sha256"][str(path.relative_to(ROOT))]:
                    raise ValueError("frozen canonical source/binary changed during A/B")
            command = [sys.executable, str(worker), "--input", fixture["path"],
                       "--sha256", fixture["sha256"], "--engine", engine]
            processes_before = idle_or_record("before_worker")
            started = perf_counter()
            result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
            process_seconds = perf_counter() - started
            row = {"phase":phase, "pair":pair, "selected_engine":engine,
                   "fixture":Path(fixture["path"]).stem, "manifest_sha256":manifest_sha256,
                   "free_before_bytes":free, "command":command, "process_seconds":process_seconds,
                   "returncode":result.returncode, "processes_before":processes_before,
                   "processes_after":None}
            if result.returncode:
                row.update(stderr=result.stderr, stdout=result.stdout)
            else:
                row.update(json.loads(result.stdout))
            try:
                row["processes_after"] = idle_or_record("after_worker")
            except Exception as error:
                row["host_check_error"] = type(error).__name__ + ": " + str(error)
                with ledger.open("a") as stream:
                    stream.write(json.dumps(row,sort_keys=True) + "\n")
                    stream.flush(); os.fsync(stream.fileno())
                raise
            with ledger.open("a") as stream:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            rows.append(row)
            if result.returncode:
                raise RuntimeError("component worker failed; raw evidence retained")
    report = {"manifest_sha256":manifest_sha256, "scope":"component_only", "fixtures":{}}
    for fixture in inputs:
        name = Path(fixture["path"]).stem
        data = [r for r in rows if r["fixture"] == name]
        calibration = [r for r in data if r["phase"] == "calibration"]
        paired = [r for r in data if r["phase"] == "pair"]
        reference = [r for r in data if r["selected_engine"] == "reference"]
        output_hashes = {r["output_sha256"] for r in data}
        def noise(values, key):
            return statistics.stdev(r[key] for r in values) / statistics.median(r[key] for r in values)
        noises = {key:max(noise(calibration,key),noise(reference,key))
                  for key in ("seconds", "process_seconds", "encoding_seconds", "rss_bytes")}
        ratios = {key:statistics.median(next(r[key] for r in paired if r["pair"] == i and r["selected_engine"] == "native") /
                                        next(r[key] for r in paired if r["pair"] == i and r["selected_engine"] == "reference")
                                        for i in range(5))
                  for key in ("seconds", "process_seconds", "encoding_seconds", "rss_bytes")}
        failures = []
        if len(output_hashes) != 1:
            failures.append("canonical_output_hash_mismatch")
        failures.extend(key + "_noise" for key,value in noises.items() if value >= .05)
        failures.extend(key + "_regression" for key,value in ratios.items() if value > 1.05)
        report["fixtures"][name] = {"noise":noises,"median_native_over_reference":ratios,
            "output_sha256":sorted(output_hashes), "accepted_component":not failures,"failures":failures}
    (args.out / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
