#!/usr/bin/env python3
"""A/B of the Rust kernels: the same public function before and after, on fixed inputs.

The baseline is the source at --baseline-commit, unpacked once. Nothing is patched and the
library is not switched off in place. Each run is a fresh worker that imports the product,
loads one fixed .npy, makes one call and prints the digest of its full result; a digest that
differs between the two lanes fails the measurement. Five baseline calibrations, then five
alternating pairs; every observation is kept.

    .venv/bin/python -B scripts/perf_native_kernels.py --out local/perf-evidence/<fresh dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time

INPUTS = Path('local/perf-inputs/kernels')
CASES = {
    'bootstrap_mean': ('sample.npy', "from workbench.engine.packs.resampling import run_bootstrap as f\nout = f(data, n_resamples=2000, seed=1)"),
    'bootstrap_median': ('sample.npy', "from workbench.engine.packs.resampling import run_bootstrap as f\nout = f(data, statistic_id='median', n_resamples=2000, seed=1)"),
    'permutation_mean': ('sample.npy', "from workbench.engine.packs.resampling import run_permutation as f\nout = f(data[:50000], data[50000:], n_resamples=2000, seed=1)"),
    'permutation_median': ('sample.npy', "from workbench.engine.packs.resampling import run_permutation as f\nout = f(data[:50000], data[50000:], statistic_id='difference_in_medians', n_resamples=2000, seed=1)"),
    'kmeans': ('matrix.npy', "from workbench.engine.packs.multivariate.clustering import _kmeans as f\nout = f(data, 8, random_state=9, max_iter=300, tol=1e-4)\nout = [out[0].tolist(), out[1].tolist(), out[2], out[3]]"),
    'cox_ph_test': ('cox.npy', "from workbench.engine.packs.survival_analysis.ph_diagnostics import ph_score_test as f\nout = f(data[:, 0], data[:, 1], data[:, 2:], np.array([.1, .1]), ['x1', 'x2'], ties='breslow')"),
}
WORKER = """
import hashlib, json, resource, sys, time
started = time.perf_counter()
import numpy as np
data = np.load(sys.argv[1])
{body_import}
imported = time.perf_counter()
{call}
elapsed = time.perf_counter() - imported
print(json.dumps({{'call_seconds': elapsed, 'rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                   'result_sha256': hashlib.sha256(json.dumps(out, sort_keys=True, default=repr).encode()).hexdigest()}}))
"""


def prepare():
    """Fixed inputs, written once and registered by SHA-256."""
    import numpy as np
    INPUTS.mkdir(parents=True, exist_ok=True)
    registry = INPUTS/'source.json'
    if not registry.exists():
        rng = np.random.default_rng(20261102)
        np.save(INPUTS/'sample.npy', rng.normal(size=100_000))
        np.save(INPUTS/'matrix.npy', rng.normal(size=(200_000, 8)))
        import pandas as pd
        cox = pd.read_csv('local/perf-inputs/cox/cox.csv')
        np.save(INPUTS/'cox.npy', cox[['duration', 'event', 'x1', 'x2']].to_numpy(dtype=float))
        digest = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(INPUTS.glob('*.npy'))}
        registry.write_text(json.dumps(digest, indent=1))
    digest = json.loads(registry.read_text())
    for name, value in digest.items():
        if hashlib.sha256((INPUTS/name).read_bytes()).hexdigest() != value:
            raise SystemExit(f'input changed: {name}')
    return digest


def worker_source(case):
    _, body = CASES[case]
    head, _, call = body.partition('\n')
    return WORKER.format(body_import=head, call=call)


def measure(case, backend, env):
    source = worker_source(case)
    started = time.perf_counter()
    done = subprocess.run([sys.executable, '-B', '-c', source, str(INPUTS/CASES[case][0])], capture_output=True, text=True,
                          env={**env, 'PYTHONPATH': str(backend)}, check=False)
    wall = time.perf_counter()-started
    if done.returncode:
        raise SystemExit(f'{case} failed in {backend}: {done.stderr[-600:]}')
    return {**json.loads(done.stdout.splitlines()[-1]), 'worker_seconds': wall}


def noise(values):
    median = statistics.median(values)
    return max(abs(value-median) for value in values)/median


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--baseline-commit', default='4cd3454b')
    parser.add_argument('--calibrations', type=int, default=5)
    parser.add_argument('--pairs', type=int, default=5)
    parser.add_argument('--cases', nargs='+', choices=list(CASES), default=list(CASES))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    if shutil.disk_usage('.').free < 5_000_000_000:
        raise SystemExit('less than 5 GB free; not starting')
    inputs = prepare()
    baseline = args.out/'baseline-src'
    baseline.mkdir()
    archive = subprocess.run(['git', 'archive', args.baseline_commit, 'backend'], capture_output=True, check=True)
    subprocess.run(['tar', '-x', '-C', str(baseline)], input=archive.stdout, check=True)
    lanes = {'baseline': (baseline/'backend').resolve(), 'candidate': Path('backend').resolve()}
    env = dict(os.environ)
    report = {'inputs': inputs, 'baseline_commit': args.baseline_commit, 'cases': {}}
    log = (args.out/'measurements.jsonl').open('a')
    for case in args.cases:
        rows = {'calibration': [], 'baseline': [], 'candidate': []}
        def run(lane, bucket, backend):
            row = {'case': case, 'lane': lane, 'at': time.time(), **measure(case, backend, env)}
            rows[bucket].append(row)
            log.write(json.dumps(row)+'\n')
            log.flush()
        for _ in range(args.calibrations):
            run('baseline', 'calibration', lanes['baseline'])
        for pair in range(args.pairs):
            order = ('baseline', 'candidate') if pair % 2 == 0 else ('candidate', 'baseline')
            for lane in order:
                run(lane, lane, lanes[lane])
        base, cand = rows['baseline'], rows['candidate']
        digests = {row['result_sha256'] for row in rows['calibration']+base+cand}
        summary = {
            'identical_result': len(digests) == 1,
            'call_seconds': {'baseline': statistics.median(r['call_seconds'] for r in base),
                             'candidate': statistics.median(r['call_seconds'] for r in cand)},
            'worker_seconds': {'baseline': statistics.median(r['worker_seconds'] for r in base),
                               'candidate': statistics.median(r['worker_seconds'] for r in cand)},
            'rss_mib': {'baseline': statistics.median(r['rss_bytes'] for r in base)/2**20,
                        'candidate': statistics.median(r['rss_bytes'] for r in cand)/2**20},
            'calibration_noise': {'call': noise([r['call_seconds'] for r in rows['calibration']]),
                                  'rss': noise([r['rss_bytes'] for r in rows['calibration']])},
        }
        summary['speedup'] = summary['call_seconds']['baseline']/summary['call_seconds']['candidate']
        report['cases'][case] = summary
        (args.out/'report.json').write_text(json.dumps(report, indent=1))
        print(f"{case:20s} {summary['call_seconds']['baseline']:7.3f}s -> {summary['call_seconds']['candidate']:7.3f}s "
              f"{summary['speedup']:6.1f}x  worker {summary['worker_seconds']['baseline']:6.2f} -> {summary['worker_seconds']['candidate']:6.2f}  "
              f"RSS {summary['rss_mib']['baseline']:6.0f} -> {summary['rss_mib']['candidate']:6.0f} MiB  "
              f"noise {summary['calibration_noise']['call']*100:4.1f}%  identical={summary['identical_result']}", flush=True)
    if not all(case['identical_result'] for case in report['cases'].values()):
        raise SystemExit('a result differed between the lanes')


if __name__ == '__main__':
    main()
