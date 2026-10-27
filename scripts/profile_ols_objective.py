"""Observe the default 1M OLS workflow; diagnostic profiling, never a time gate.

Uses the registered fixed CSV, does not wrap/patch product functions, and
journals all outputs before removing the sole active benchmark directory.
"""
from __future__ import annotations

import cProfile
import argparse
import json
from pathlib import Path
import pstats
import resource
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from perf_evidence import digest, finalize_active, require_space
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def main():
    root = Path.cwd()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='Fresh evidence directory; existing evidence is never overwritten')
    area = parser.parse_args().out.resolve()
    require_space(root)
    manifest = json.loads((root / "local/perf-inputs/ols/source.json").read_text())
    source = Path(manifest["source"])
    if digest(source) != manifest["sha256"]:
        raise ValueError("fixed input checksum changed")
    area.mkdir(parents=True, exist_ok=False)
    active = area / "active"
    active.mkdir(exist_ok=False)
    project = create_project(active, "benchmark")
    profiler = cProfile.Profile()
    started = time.perf_counter()
    profiler.enable()
    try:
        result = run_workflow(project.root, [source], mode="auto", **manifest["kwargs"])
    finally:
        profiler.disable()
    elapsed = time.perf_counter() - started
    profiler.dump_stats(str(area / "workflow.pstats"))
    stats = pstats.Stats(profiler)
    entries = [{"file": key[0], "line": key[1], "name": key[2], "primitive_calls": value[0],
                "calls": value[1], "self_s": value[2], "inclusive_s": value[3]}
               for key, value in stats.stats.items()]
    entries.sort(key=lambda item: -item["inclusive_s"])
    metadata = {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "case": "ols", "status": result["status"], "elapsed_s": elapsed,
        "ru_maxrss": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "tracemalloc_peak": None, "measurement": "diagnostic_cProfile_not_gate",
        "input_source": str(source), "input_sha256": manifest["sha256"],
        "run_root": str(project.root / "runs" / result["run_id"])}
    (area / "profile.json").write_text(json.dumps({"metadata": metadata, "functions": entries}, indent=2))
    retention = finalize_active(active, ledger=area / "runs.jsonl", record_id="ols-objective-profile",
        metadata=metadata, archive_dir=root / "local/perf-evidence/representatives",
        version="v1.9.1", case="ols")
    print(json.dumps({"metadata": metadata, "retention": retention}, indent=2))


if __name__ == "__main__":
    main()
