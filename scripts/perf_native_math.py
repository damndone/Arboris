#!/usr/bin/env python3
"""A/B of single product calls between two checkouts, each with its own native builds.

Each run is a fresh worker in the lane's repository (its backend and its local/ native
libraries). The worker reads the registered fixed CSV, then times one public call and prints
the digest of its full result (floats by repr, so equal digests mean equal bits). Five baseline
calibrations, then five alternating pairs (AB, BA, ...). Free disk is checked before every run;
other heavy processes and any test run are recorded with each observation (--refuse-concurrent
stops instead). Every observation is kept.

A workflow:<family> case is one default run through perf_1m.py's own worker on the family's
registered input. Its run tree is journaled file by file and removed (perf_evidence), and the
files whose bytes are the same in every baseline run must be the same in every candidate run.

    .venv/bin/python -B scripts/perf_native_math.py --baseline-repo <checkout> --out local/perf-evidence/<fresh dir>
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

from perf_host import monitor_host, require_idle

INPUT = Path('local/perf-inputs/ols/source.json')
STATISTIC_COLUMNS = ['wage', 'education', 'experience', 'female', 'hours']
CASES = {
    'summarize_detail': (
        "from workbench.statistical_exploration import ExplorationSpec, execute_exploration",
        "out = execute_exploration(frame, ExplorationSpec('summarize_detail', ('wage', 'hours', 'age')))"),
    'statistical_tests': (
        "from workbench.statistical_tests import run_statistical_tests",
        f"out = run_statistical_tests(frame, analysis_columns={STATISTIC_COLUMNS!r}, "
        "dataset_sha256='0' * 64, lineage_parent='perf')"),
}
WORKER = """
import hashlib, json, resource, sys, time, warnings
warnings.simplefilter('ignore')
import pandas as pd
frame = pd.read_csv(sys.argv[1])
{imports}
started = time.perf_counter()
{call}
elapsed = time.perf_counter() - started
print(json.dumps({{'call_seconds': elapsed, 'rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                   'result_sha256': hashlib.sha256(json.dumps(out, sort_keys=True, default=repr).encode()).hexdigest()}}))
"""
WORKFLOW_FAMILIES = ('ols', 'wide', 'panel', 'did', 'iv', 'cox')


def registered_input():
    payload = json.loads(INPUT.read_text())
    source = Path(payload['source'])
    with source.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != payload['sha256']:
            raise SystemExit('registered input changed')
    return source, payload['sha256']


def checkout_metadata(repo):
    """A source export must not inherit the enclosing worktree's Git claims."""
    top = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=repo,
                         text=True, capture_output=True)
    if top.returncode or Path(top.stdout.strip()).resolve() != repo.resolve():
        return {'kind': 'source_snapshot', 'revision': None, 'tracked_changes': None}
    return {'kind': 'git_checkout',
            'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip(),
            'tracked_changes': subprocess.check_output(
                ['git', 'status', '--porcelain', '--untracked-files=no'], cwd=repo, text=True)}


def case_input(case, out):
    if case.startswith('workflow:'):
        manifest, payload = workflow_manifest(case.split(':', 1)[1], out)
        return {'source': payload['source'], 'sha256': payload['sha256'], 'manifest': str(manifest)}
    source, digest = registered_input()
    return {'source': str(source), 'sha256': digest, 'manifest': str(INPUT.resolve())}


def other_load():
    """Other processes above 20% CPU right now (command shortened), for the record."""
    rows = subprocess.check_output(['ps', '-Ao', 'pid=,pcpu=,rss=,comm='], text=True).splitlines()
    busy = []
    for row in rows:
        pid, cpu, rss, command = row.split(None, 3)
        if int(pid) != os.getpid() and float(cpu) >= 20:
            busy.append({'pid': int(pid), 'cpu': float(cpu), 'rss_kib': int(rss), 'command': command[-80:]})
    return busy


def tests_running():
    rows = subprocess.check_output(['ps', '-Ao', 'pid=,command='], text=True).splitlines()
    return [row for row in rows if ('-m pytest' in row or 'perf_1m.py' in row) and str(os.getpid()) not in row.split()[:1]]


def measurement_identity(repo):
    """Actual source and native artifacts in this lane, including uncommitted inputs."""
    suffixes = {'.py', '.rs', '.cpp', '.c', '.h', '.hpp', '.toml', '.lock'}
    paths = [p for name in ('backend', 'native') for p in (repo / name).rglob('*')
             if p.is_file() and p.suffix in suffixes and not {'target', '__pycache__'}.intersection(p.parts)]
    paths += [p for p in (repo / 'local').glob('native-*/*') if p.is_file()
              and (p.suffix in {'.so', '.dylib', '.dll'} or p.name.startswith('build-manifest'))]
    identity = {}
    for p in sorted(paths):
        with p.open('rb') as stream:
            identity[str(p.relative_to(repo))] = hashlib.file_digest(stream, 'sha256').hexdigest()
    drivers = {str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    for name in ('perf_1m.py', 'perf_host.py', 'perf_evidence.py'):
        p = Path(__file__).with_name(name)
        drivers[str(p.resolve())] = hashlib.sha256(p.read_bytes()).hexdigest()
    return {'files': identity, 'drivers': drivers}


def _measure(case, repo, source, *, out, lane, label, monitor):
    if shutil.disk_usage(repo).free < 5_000_000_000:
        raise SystemExit('less than 5 GB free; not starting a run')
    if case.startswith('workflow:'):
        return measure_workflow(case.split(':', 1)[1], repo, out, lane, label, monitor=monitor)
    imports, call = CASES[case]
    load = other_load()
    started = time.perf_counter()
    done = monitor.popen([sys.executable, '-B', '-c', WORKER.format(imports=imports, call=call), str(source)],
                         cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         env={**os.environ, 'PYTHONPATH': str(repo / 'backend')})
    stdout, stderr = done.communicate()
    wall = time.perf_counter() - started
    if done.returncode:
        (out / f'{case}-{lane}-{label}-stderr.log').write_text(stderr)
        raise SystemExit(f'{case} failed in {repo}: {stderr[-800:]}')
    return {**json.loads(stdout.splitlines()[-1]), 'worker_seconds': wall, 'other_load': load,
            'free_bytes': shutil.disk_usage(repo).free}


def measure(case, repo, source, *, refuse_concurrent, out, lane, label):
    # The legacy flag remains accepted; host exclusivity is mandatory now.
    require_idle()
    before = measurement_identity(repo)
    identity_fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    source_stat = tuple(getattr(source.stat(), field) for field in identity_fields)
    path = out / 'host' / f"{case.replace(':', '-')}-{lane}-{label}.jsonl"
    with monitor_host(path) as monitor:
        value = _measure(case, repo, source, out=out, lane=lane, label=label, monitor=monitor)
    return {**value, 'host_monitor': monitor.summary,
            'source_identity_before': before, 'source_identity_after': measurement_identity(repo),
            'input_identity_unchanged': tuple(getattr(source.stat(), field) for field in identity_fields) == source_stat,
            'concurrent_tests': monitor.summary['overlap']}


def acceptance(case, rows, summary):
    """Fail closed on numeric identity, every occupancy window and resource lane."""
    failures = []
    if not summary['identical_result']:
        failures.append('result_identity')
    if any(len(rows[lane]) < 5 for lane in ('calibration', 'baseline', 'candidate')):
        failures.append('five_calibrations_and_pairs_required')
    for lane, runs in rows.items():
        for run in runs:
            if not run.get('host_monitor', {}).get('valid'):
                failures.append(f'{lane}:host_exclusivity')
            if (not run.get('source_identity_before')
                    or run['source_identity_before'] != run.get('source_identity_after')
                    or run['source_identity_before'] != runs[0].get('source_identity_before')):
                failures.append('source_identity_changed')
            if run.get('input_identity_unchanged') is not True:
                failures.append('input_identity_changed')
        metrics = ('call_seconds', 'worker_seconds', 'rss_bytes') + (('run_bytes',) if case.startswith('workflow:') else ())
        for metric in metrics:
            values = [run[metric] for run in runs]
            if any(not isinstance(value, (int, float)) or not 0 < value < float('inf') for value in values):
                failures.append(f'{lane}:invalid_{metric}')
            elif spread(values)['stdev_over_median'] >= .05:
                failures.append(f'{lane}:noise_{metric}')
    for metric in ('call_seconds', 'worker_seconds', 'rss_bytes'):
        if statistics.median(r[metric] for r in rows['candidate']) > 1.05 * statistics.median(r[metric] for r in rows['baseline']):
            failures.append(f'regression:{metric}')
    if case.startswith('workflow:'):
        if statistics.median(r['run_bytes'] for r in rows['candidate']) > 1.05 * statistics.median(r['run_bytes'] for r in rows['baseline']):
            failures.append('regression:run_bytes')
        if case == 'workflow:ols' and statistics.median(r['call_seconds'] for r in rows['candidate']) > 8:
            failures.append('absolute_ols_seconds')
    return sorted(set(failures))


def workflow_manifest(family, out):
    """The family's registered manifest, digest verified once, with this mount's file identity."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import perf_1m
    canonical = perf_1m.prepare_family(family, Path('local/perf-inputs').resolve() / family)
    payload = json.loads(canonical.read_text())
    payload = {**payload, 'canonical_manifest': str(canonical), 'origin_source_stat': payload['source_stat'],
               'source_stat': perf_1m.source_identity(Path(payload['source']))}
    manifest = out / 'inputs' / f'{family}.json'
    manifest.parent.mkdir(exist_ok=True)
    if not manifest.exists():
        manifest.write_text(json.dumps(payload, indent=2))
    return manifest, payload


def measure_workflow(family, repo, out, lane, label, *, monitor):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from perf_evidence import finalize_active
    manifest, payload = workflow_manifest(family, out)
    active = out / 'active'
    if active.exists():
        raise SystemExit('an unrecorded active run tree exists')
    load = other_load()
    command = [sys.executable, '-B', str(Path(__file__).resolve().with_name('perf_1m.py')), '--case', family,
               '--out', str(active), '--manifest', str(manifest)]
    started = time.perf_counter()
    with (out / f'{family}-{label}.log').open('w') as log:
        done = monitor.popen(command, cwd=repo, stdout=log, stderr=subprocess.STDOUT)
        done.wait()
    wall = time.perf_counter() - started
    metrics = json.loads((active / 'metrics.json').read_text())
    metrics.update(version_commit=checkout_metadata(repo)['revision'],
                   input_source=payload['source'], returncode=done.returncode, label=label)
    retention = finalize_active(active, ledger=out / 'runs.jsonl', record_id=f'{family}-{label}', metadata=metrics,
                                archive_dir=out / 'representatives', version=lane, case=family)
    if done.returncode or metrics['status'] != 'completed':
        raise SystemExit(f'{family} {label} failed; evidence journaled')
    record = [json.loads(line) for line in (out / 'runs.jsonl').open() if json.loads(line)['record_id'] == f'{family}-{label}'][-1]
    run_prefix = Path(metrics['run_root']).relative_to(active)
    files = {str(Path(f['path']).relative_to(run_prefix)): f['sha256'] for f in record['files']
             if Path(f['path']).is_relative_to(run_prefix)}
    return {'call_seconds': metrics['seconds'], 'rss_bytes': metrics['rss_bytes'], 'run_bytes': metrics['run_bytes'],
            'input_source': payload['source'], 'input_sha256': payload['sha256'],
            'result_sha256': hashlib.sha256(json.dumps(metrics['numeric_signature'], sort_keys=True).encode()).hexdigest(),
            'run_files': files, 'worker_seconds': wall, 'other_load': load, 'retention': retention,
            'free_bytes': shutil.disk_usage(repo).free}


def stable_files(rows):
    """Run files with the same bytes in every given run (names that embed run ids drop out)."""
    common = set(rows[0]['run_files'].items())
    for row in rows[1:]:
        common &= set(row['run_files'].items())
    return dict(common)


def spread(values):
    median = statistics.median(values)
    return {'median': median, 'min': min(values), 'max': max(values),
            'stdev_over_median': statistics.stdev(values) / median if len(values) > 1 else 0.0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--calibrations', type=int, default=5)
    parser.add_argument('--pairs', type=int, default=5)
    parser.add_argument('--cases', nargs='+', default=list(CASES),
                        choices=list(CASES) + [f'workflow:{family}' for family in WORKFLOW_FAMILIES])
    parser.add_argument('--refuse-concurrent', action='store_true', help='compatibility flag; exclusivity is always required')
    args = parser.parse_args()
    if args.calibrations < 5 or args.pairs < 5:
        parser.error('at least five calibrations and five pairs are required')
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    lanes = {'baseline': args.baseline_repo.resolve(), 'candidate': Path.cwd().resolve()}
    checkouts = {lane: checkout_metadata(repo) for lane, repo in lanes.items()}
    revisions = {lane: info['revision'] for lane, info in checkouts.items()}
    dirty = {lane: info['tracked_changes'] for lane, info in checkouts.items()}
    report = {'inputs_by_case': {}, 'checkouts': checkouts, 'revisions': revisions, 'tracked_changes': dirty,
              'comparison_scope': 'attribution_against_supplied_baseline_not_v190_release_gate',
              'order': 'calibration A x N, then pairs AB, BA, AB, ...', 'cases': {}}
    log = (args.out / 'measurements.jsonl').open('a')
    for case in args.cases:
        report['inputs_by_case'][case] = case_input(case, args.out)
        source = Path(report['inputs_by_case'][case]['source'])
        rows = {'calibration': [], 'baseline': [], 'candidate': []}

        def run(lane, bucket):
            label = f'{bucket}-{len(rows[bucket]) + 1:02}'
            row = {'case': case, 'lane': lane, 'bucket': bucket, 'at': time.time(), 'revision': revisions[lane],
                   **measure(case, lanes[lane], source, refuse_concurrent=args.refuse_concurrent, out=args.out,
                             lane=lane, label=label)}
            rows[bucket].append(row)
            log.write(json.dumps(row) + '\n')
            log.flush()

        for _ in range(args.calibrations):
            run('baseline', 'calibration')
        for pair in range(args.pairs):
            for lane in (('baseline', 'candidate') if pair % 2 == 0 else ('candidate', 'baseline')):
                run(lane, lane)
        base, cand = rows['baseline'], rows['candidate']
        summary = {
            'identical_result': len({row['result_sha256'] for row in rows['calibration'] + base + cand}) == 1,
            'call_seconds': {'baseline': spread([r['call_seconds'] for r in base]),
                             'candidate': spread([r['call_seconds'] for r in cand]),
                             'calibration': spread([r['call_seconds'] for r in rows['calibration']])},
            'rss_mib': {lane: spread([r['rss_bytes'] / 2**20 for r in runs]) for lane, runs in (('baseline', base), ('candidate', cand))},
            'runs_with_concurrent_tests': sum(bool(r['concurrent_tests']) for r in rows['calibration'] + base + cand),
        }
        if case.startswith('workflow:'):
            stable = stable_files(rows['calibration'] + base)
            summary['run_bytes'] = {lane: spread([r['run_bytes'] for r in runs]) for lane, runs in (('baseline', base), ('candidate', cand))}
            summary['stable_baseline_files'] = len(stable)
            summary['identical_result'] = summary['identical_result'] and all(
                all(row['run_files'].get(path) == digest for path, digest in stable.items()) for row in cand)
        summary['speedup'] = summary['call_seconds']['baseline']['median'] / summary['call_seconds']['candidate']['median']
        summary['failures'] = acceptance(case, rows, summary)
        summary['accepted'] = not summary['failures']
        report['cases'][case] = summary
        (args.out / 'report.json').write_text(json.dumps(report, indent=1))
        b, c = summary['call_seconds']['baseline'], summary['call_seconds']['candidate']
        print(f"{case:18s} {b['median']:7.3f}s [{b['min']:.3f}-{b['max']:.3f}] -> {c['median']:7.3f}s [{c['min']:.3f}-{c['max']:.3f}] "
              f"{summary['speedup']:5.2f}x  RSS {summary['rss_mib']['baseline']['median']:5.0f} -> "
              f"{summary['rss_mib']['candidate']['median']:5.0f} MiB  calibration noise "
              f"{summary['call_seconds']['calibration']['stdev_over_median'] * 100:.1f}%  identical={summary['identical_result']}",
              flush=True)
    if not all(case['accepted'] for case in report['cases'].values()):
        raise SystemExit('acceptance failed; see per-case failures in report.json')


if __name__ == '__main__':
    main()
