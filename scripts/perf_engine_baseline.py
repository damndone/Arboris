#!/usr/bin/env python3
"""Where a default run's time and memory go: cold start, package size, per-area CPU.

Fixed inputs from local/perf-inputs, fresh processes, nothing in the product changed. Profiled
times carry cProfile overhead, so they rank costs and do not certify them; perf_1m.py certifies.

    PYTHONPATH=backend:scripts .venv/bin/python -B scripts/perf_engine_baseline.py --out local/perf-evidence/<dir>
"""
from __future__ import annotations

import argparse
import json
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

IMPORTS = {'python alone': 'pass', 'numpy': 'import numpy', 'pandas': 'import pandas', 'pyarrow': 'import pyarrow',
           'scipy.stats': 'import scipy.stats', 'statsmodels.api': 'import statsmodels.api',
           'linearmodels': 'import linearmodels', 'matplotlib.pyplot': 'import matplotlib.pyplot',
           'sklearn': 'import sklearn.linear_model',
           'workbench.orchestrator': 'import workbench.orchestrator', 'workbench.api': 'import workbench.api'}

AREAS = (('read source', ('read_csv', 'read_parquet', 'read_table', 'pyarrow/csv')),
         ('write parquet/csv', ('to_parquet', 'write_table', 'to_csv')),
         ('hash', ('sha256', 'hashlib', 'openssl_', 'file_digest')),
         ('json', ('json/encoder', 'json/decoder', "of '_json", 'iterencode', 'canonical')),
         ('figures', ('matplotlib', 'savefig', 'print_figure', 'PIL/')),
         ('linear algebra', ('linalg', 'lapack', 'blas', 'method \'dot\'', 'matmul')),
         ('pandas', ('pandas/',)), ('statsmodels', ('statsmodels/',)), ('scipy', ('scipy/',)),
         ('import', ('importlib', "'exec'", 'marshal')))


def peak_child_rss():
    return resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss


def timed_import(code, repeats, env):
    wall, rss = [], []
    for _ in range(repeats):
        probe = (f'import resource,time;s=time.perf_counter();{code};'
                 'print(time.perf_counter()-s,resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)')
        started = time.perf_counter()
        out = subprocess.run([sys.executable, '-c', probe], capture_output=True, text=True, env=env, check=True).stdout.split()
        wall.append(time.perf_counter()-started)
        rss.append(int(out[-1]))
    return {'process_seconds': statistics.median(wall), 'rss_mib': statistics.median(rss)/2**20, 'raw_seconds': wall}


WORKER = r'''
import cProfile, json, pstats, resource, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, 'scripts')
import perf_1m
from workbench.orchestrator import run_workflow
from workbench.projects import create_project
case, source, out = sys.argv[1:4]
kwargs = perf_1m.family_kwargs(case)
project = create_project(Path(out), 'benchmark')
profile = cProfile.Profile()
started = time.perf_counter()
profile.enable()
outcome = run_workflow(project.root, [Path(source)], mode='auto', **kwargs)
profile.disable()
elapsed = time.perf_counter() - started
rows = []
for (path, line, name), (calls, total_calls, own, cumulative, _) in pstats.Stats(profile).stats.items():
    rows.append({'where': f'{path}:{line} {name}', 'calls': total_calls, 'own': own, 'cumulative': cumulative})
print(json.dumps({'status': outcome['status'], 'seconds': elapsed, 'rss': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, 'rows': rows}))
'''


def profile_case(case, source, env):
    with tempfile.TemporaryDirectory() as out:
        done = subprocess.run([sys.executable, '-c', WORKER, case, str(source), out], capture_output=True, text=True, env=env)
    if done.returncode:
        return {'status': 'failed', 'stderr': done.stderr[-800:]}
    data = json.loads(done.stdout.splitlines()[-1])
    rows = data.pop('rows')
    areas = {}
    for row in rows:
        area = next((name for name, keys in AREAS if any(key in row['where'] for key in keys)), 'everything else')
        areas[area] = areas.get(area, 0.0)+row['own']
    data['areas_own_seconds'] = {k: round(v, 3) for k, v in sorted(areas.items(), key=lambda kv: -kv[1])}
    keep = sorted(rows, key=lambda row: -row['cumulative'])[:60]
    data['top_cumulative'] = [{**row, 'where': row['where'][-90:]} for row in keep]
    data['top_own'] = [{**row, 'where': row['where'][-90:]} for row in sorted(rows, key=lambda row: -row['own'])[:30]]
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--cases', nargs='+', default=['ols', 'panel', 'iv', 'did', 'cox', 'wide'])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    env = {**__import__('os').environ, 'PYTHONPATH': 'backend:scripts'}
    report = {'imports': {name: timed_import(code, args.repeats, env) for name, code in IMPORTS.items()}}
    site = Path(sys.prefix)/'lib'/f'python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages'
    sizes = {path.name: sum(item.stat().st_size for item in path.rglob('*') if item.is_file()) for path in site.iterdir() if path.is_dir()}
    report['site_packages_mib'] = {k: round(v/2**20, 1) for k, v in sorted(sizes.items(), key=lambda kv: -kv[1])[:24]}
    report['site_packages_total_mib'] = round(sum(sizes.values())/2**20, 1)
    inputs = Path('local/perf-inputs')
    report['cases'] = {}
    for case in args.cases:
        source = json.loads((inputs/case/'source.json').read_text())['source'] if (inputs/case/'source.json').exists() else None
        report['cases'][case] = profile_case(case, source, env) if source else {'status': 'no input'}
    (args.out/'report.json').write_text(json.dumps(report, indent=1))
    for name, row in report['imports'].items():
        print(f"{name:26s} {row['process_seconds']:6.3f} s {row['rss_mib']:7.1f} MiB")
    print('site-packages', report['site_packages_total_mib'], 'MiB')
    for case, row in report['cases'].items():
        print(case, row.get('status'), round(row.get('seconds', 0), 2), 's', round(row.get('rss', 0)/2**20), 'MiB', row.get('areas_own_seconds'))


if __name__ == '__main__':
    main()
