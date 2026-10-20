#!/usr/bin/env python3
"""Time everyday operations on a 1,000,000-row dataset against budgets.

Builds a scratch project with a 1M x 10 wage dataset, runs one OLS, then
times what a user does next: open the Data view, read variable metadata,
tabulate and summarize, recode and filter, export, read results and the
report's disclosure. Prints a table and exits non-zero when a budget is
missed. Heavy: run it alone on the machine.

    PYTHONPATH=backend .venv/bin/python scripts/perf_1m.py --out /private/tmp/perf-1m
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path.cwd() / "backend"))

from workbench import analysis_disclosure, analysis_ledger  # noqa: E402
from workbench.data_operation_registry import get_data_operation  # noqa: E402
from workbench.orchestrator import run_workflow  # noqa: E402
from workbench.projects import create_project  # noqa: E402
from workbench.services.data_export import export_dataset, preview_export  # noqa: E402
from workbench.services.dataset_view import dataset_page, dataset_variables, load_dataset  # noqa: E402
from workbench.services.results_service import read_model_results  # noqa: E402
from workbench.statistical_exploration import ExplorationSpec, execute_exploration  # noqa: E402

ROWS = 1_000_000

# Seconds. Interactive reads must feel instant; one-off heavy work may take a
# while but must stay bounded.
BUDGETS = {
    "ingest + OLS run": 24.37 * 1.05,
    "data view: first page (cold)": 10.0,
    "data view: next page (warm)": 1.0,
    "data view: sorted page": 3.0,
    "variable view": 5.0,
    "tabulate region": 2.0,
    "summarize detail (3 vars)": 5.0,
    "recode age": 3.0,
    "subset filter": 3.0,
    "export preview (dta)": 10.0,
    "export dta": 30.0,
    "export csv": 30.0,
    "read model results": 1.0,
    "ledger: disclosure of 5,000 entries": 1.0,
}


def _dataset(path: Path, rows: int = ROWS) -> Path:
    rng = np.random.default_rng(1)
    education = rng.integers(9, 21, rows)
    experience = rng.integers(0, 40, rows)
    female = rng.binomial(1, 0.5, rows)
    region = rng.choice(["north", "south", "east", "west"], rows)
    frame = pd.DataFrame(
        {
            "id": np.arange(rows),
            "wage": np.round(np.exp(1.2 + 0.08 * education + 0.03 * experience - 0.1 * female + rng.normal(0, 0.35, rows)), 2),
            "education": education,
            "experience": experience,
            "age": np.clip(education + experience + 6, 18, 75),
            "female": female,
            "region": region,
            "union": rng.binomial(1, 0.25, rows),
            "hours": np.round(rng.normal(40, 6, rows), 1),
            "tenure": rng.integers(0, 30, rows),
        }
    )
    frame.to_csv(path, index=False)
    return path


def interactive_main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "perf-1m")
    args = parser.parse_args()
    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}

    @contextmanager
    def timed(name: str):
        started = time.perf_counter()
        yield
        timings[name] = time.perf_counter() - started
        print(f"{name:40s} {timings[name]:8.2f}s  (budget {BUDGETS[name]:.1f}s)", flush=True)

    source = _dataset(out / "wages_1m.csv")
    project = create_project(out, f"p{int(time.time())}")
    root = project.root
    with timed("ingest + OLS run"):
        outcome = run_workflow(root, [source], mode="auto", model_type="ols", y="wage",
                               x=["education", "experience", "female", "hours"])
    assert outcome["status"] == "completed", outcome
    run_id = outcome["run_id"]

    with timed("data view: first page (cold)"):
        dataset_page(root, run_id, "stage:raw", offset=0, limit=100)
    with timed("data view: next page (warm)"):
        dataset_page(root, run_id, "stage:raw", offset=500_000, limit=100)
    with timed("data view: sorted page"):
        dataset_page(root, run_id, "stage:raw", offset=0, limit=100, sort_by="wage", descending=True)
    with timed("variable view"):
        dataset_variables(root, run_id, "stage:raw")

    _context, frame = load_dataset(root, run_id, "stage:raw")
    with timed("tabulate region"):
        execute_exploration(frame, ExplorationSpec("tabulate", ("region",)))
    with timed("summarize detail (3 vars)"):
        execute_exploration(frame, ExplorationSpec("summarize_detail", ("wage", "hours", "age")))
    with timed("recode age"):
        get_data_operation("recode").run(frame, {
            "column": "age", "output": "age_group",
            "rules": [{"from": {"low": 18, "high": 29}, "to": 1}, {"from": {"low": 30, "high": 49}, "to": 2},
                      {"from": "else", "to": 3}],
        })
    with timed("subset filter"):
        get_data_operation("subset").run(frame, {
            "columns": ["wage", "education", "region"],
            "filters": [{"column": "age", "op": "between", "value": [25, 55]}, {"column": "region", "op": "eq", "value": "north"}],
        })
    with timed("export preview (dta)"):
        preview_export(root, run_id, "stage:raw", {"format": "dta"})
    with timed("export dta"):
        export_dataset(root, run_id, "stage:raw", {"format": "dta"})
    with timed("export csv"):
        export_dataset(root, run_id, "stage:raw", {"format": "csv"})
    with timed("read model results"):
        read_model_results(root / "runs" / run_id)

    step = analysis_ledger.LedgerStep.of("test.t_tests")
    for index in range(5000):
        analysis_ledger.record(root, analysis_ledger.LedgerEntry(
            actor="agent", authorized_by="read_only_policy", source="operation.multi_step", status="completed",
            steps=(step,), run_id=run_id, source_upload_sha256="x" if index % 2 else None,
        ))
    with timed("ledger: disclosure of 5,000 entries"):
        analysis_disclosure.disclosure(root, run_id)

    missed = {name: value for name, value in timings.items() if value > BUDGETS[name]}
    print()
    print("all within budget" if not missed else f"over budget: {', '.join(missed)}")
    return 1 if missed else 0


# End-to-end regression lane, isolated process per version/case/repetition.
# Run from each repository root; the driver file can belong to the candidate.
FAMILY_ROWS = {'ols': 1_000_000, 'panel': 1_000_000, 'iv': 1_000_000,
               'did': 1_000_000, 'cox': 200_000}


def prepare_family(case, out, *, rows=None):
    import json
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / 'source.json'
    if manifest.exists():
        validate_family_manifest(manifest)
        return manifest
    rng = np.random.default_rng(7)
    n = FAMILY_ROWS[case] if rows is None else rows
    if case == 'ols':
        source = _dataset(out / 'wages.csv', n)
        kwargs = dict(model_type='ols', y='wage', x=['education', 'experience', 'female', 'hours'])
    elif case in {'panel', 'did'}:
        unit = np.repeat(np.arange(n//10), 10)
        year = np.tile(np.arange(2000, 2010), n//10)
        x1, x2 = rng.normal(size=n), rng.normal(size=n)
        y = .5*x1-.2*x2+rng.normal(size=n//10)[unit]+rng.normal(size=n)
        frame = pd.DataFrame({'unit': unit, 'year': year, 'x1': x1, 'x2': x2, 'y': y})
        kwargs = dict(model_type='panel_ols', y='y', x=['x1', 'x2'], entity_col='unit', time_col='year')
        if case == 'did':
            frame['first_treat'] = np.where(unit % 2 == 0, 2005, 0)
            frame['y'] += 2*((unit % 2 == 0) & (year >= 2005))
            kwargs.update(model_type='did', did_mode='cohort', did_cohort_col='first_treat')
        source = out / f'{case}.csv'
        frame.to_csv(source, index=False)
        del frame
    elif case == 'iv':
        z1, z2, u = rng.normal(size=n), rng.normal(size=n), rng.normal(size=n)
        d = .6*z1+.4*z2+.5*u+rng.normal(size=n)
        w = rng.normal(size=n)
        frame = pd.DataFrame({'y': d+.3*w+u+rng.normal(size=n), 'd': d, 'w': w, 'z1': z1, 'z2': z2})
        source = out / 'iv.csv'
        frame.to_csv(source, index=False)
        del frame
        kwargs = dict(model_type='iv_2sls', y='y', x=['w'], iv_endog=['d'], iv_instruments=['z1', 'z2'])
    else:
        x1, x2 = rng.normal(size=n), rng.normal(size=n)
        duration = rng.exponential(np.exp(-.3*x1+.2*x2))
        censor = rng.exponential(2, size=n)
        frame = pd.DataFrame({'duration': np.minimum(duration, censor)+.001,
                              'event': (duration <= censor).astype(int), 'x1': x1, 'x2': x2})
        source = out / 'cox.csv'
        frame.to_csv(source, index=False)
        del frame
        kwargs = dict(model_type='survival_cox', y='duration', x=['x1', 'x2'],
                      model_options={'event_column': 'event', 'ties': 'breslow'})
    payload = {'case': case, 'rows': n, 'source': str(source.resolve()),
               'sha256': source_digest(source),
               'source_stat': source_identity(source),
               'kwargs': kwargs, 'generator': 'perf_1m_fixed_input_v2', 'seed': 7}
    manifest.write_text(json.dumps(payload, indent=2))
    return manifest


def source_digest(source):
    import hashlib
    with source.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_identity(source):
    stat = source.stat()
    return dict(size=stat.st_size, mtime_ns=stat.st_mtime_ns, inode=stat.st_ino, device=stat.st_dev)


def registered_source(payload):
    source = Path(payload['source'])
    if source_identity(source) != payload['source_stat']:
        raise ValueError('registered_source_changed')
    return source


def validate_family_manifest(manifest):
    import json
    payload = json.loads(manifest.read_text())
    digest = source_digest(Path(payload['source']))
    if digest != payload['sha256']:
        raise ValueError('source_digest_mismatch')
    return payload


def current_rss():
    """Current resident bytes, NOT ru_maxrss (whose increments miss releases)."""
    import os
    import platform
    if platform.system() == 'Darwin':
        import ctypes
        class Info(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ('virtual', 'resident', 'resident_max', 'user', 'system',
                         'policy', 'faults', 'pageins', 'cow', 'sent', 'received',
                         'mach', 'unix', 'switches', 'csw', 'priority')]
        info = Info()
        size = ctypes.c_uint32(ctypes.sizeof(info)//4)
        lib = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
        port = lib.mach_task_self()
        if lib.task_info(port, 20, ctypes.byref(info), ctypes.byref(size)):
            raise RuntimeError('task_info_failed')
        return info.resident
    return int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')


def stage_summary(rows):
    return {r['stage']: dict(r, rss_delta_bytes=r['rss_after']-r['rss_before']) for r in rows}


def compare_stages(baseline, candidate):
    differences = {}
    for name in baseline['stages'].keys() | candidate['stages'].keys():
        a, b = baseline['stages'].get(name), candidate['stages'].get(name)
        if a is None or b is None:
            differences[name] = {'reason': 'stage_exists_in_one_version_only', 'over_one_percent': True}
            continue
        dt, dm = b['seconds']-a['seconds'], b['rss_delta_bytes']-a['rss_delta_bytes']
        differences[name] = {
            'baseline': a, 'candidate': b, 'seconds_delta': dt,
            'rss_increment_delta_bytes': dm,
            'time_fraction_of_baseline_workflow': dt/baseline['seconds'],
            'memory_fraction_of_baseline_peak': dm/baseline['rss_bytes'],
            'over_one_percent': abs(dt/baseline['seconds']) > .01 or abs(dm/baseline['rss_bytes']) > .01,
            'cause': 'requires_stage_code/profile_attribution' if abs(dt/baseline['seconds']) > .01 or abs(dm/baseline['rss_bytes']) > .01 else 'below_one_percent',
        }
    # Imports, hashing, publication and run setup outside the pipeline must not
    # disappear merely because stage timings add up to less than the workflow.
    outside_a = baseline['seconds']-sum(r['seconds'] for r in baseline['stages'].values())
    outside_b = candidate['seconds']-sum(r['seconds'] for r in candidate['stages'].values())
    differences['outside_pipeline'] = {'baseline_seconds': outside_a, 'candidate_seconds': outside_b,
                                        'seconds_delta': outside_b-outside_a,
                                        'over_one_percent': abs(outside_b-outside_a)/baseline['seconds'] > .01}
    return differences


def instrument_stages(rows):
    from workbench.engine.stages import PIPELINE
    import resource
    for stage in PIPELINE:
        original = type(stage).run
        def measured(self, ctx, env, _run=original):
            before = current_rss()
            high_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            start = time.perf_counter()
            result = _run(self, ctx, env)
            rows.append(dict(stage=type(self).__name__, seconds=time.perf_counter()-start,
                             rss_before=before, rss_after=current_rss(),
                             high_water_before=high_before,
                             high_water_after=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
            return result
        type(stage).run = measured


def family_run(case, out, *, manifest, stage_profile=False, trace_memory=False):
    import json
    import resource
    import platform
    # Parent validates the file digest before EACH worker. Do not re-read the
    # source or generate any observations in this measured process.
    payload = json.loads(manifest.read_text())
    source, kwargs, n = Path(payload['source']), payload['kwargs'], payload['rows']
    if case != payload['case']:
        raise ValueError('manifest_case_mismatch')
    out.mkdir(parents=True, exist_ok=False)
    stages = []
    if stage_profile:
        instrument_stages(stages)
    if trace_memory:
        import tracemalloc
        tracemalloc.start()
    project = create_project(out, 'benchmark')
    started = time.perf_counter()
    outcome = run_workflow(project.root, [source], mode='auto', **kwargs)
    elapsed = time.perf_counter()-started
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    traced_peak = None
    if trace_memory:
        traced_peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    run = project.root / 'runs' / outcome['run_id']
    primary_id = {'ols': 'ols_1', 'panel': 'panel_ols_1', 'iv': 'iv_2sls_1', 'did': 'did_1', 'cox': 'survival_cox_1'}[case]
    packet_path = run / 'model_results' / f'{primary_id}.json'
    packet = json.loads(packet_path.read_text()) if packet_path.exists() else {}
    def bits(value):
        if isinstance(value, float):
            return {'binary64': value.hex()}
        if isinstance(value, dict):
            return {k: bits(v) for k,v in value.items()}
        if isinstance(value, list):
            return [bits(v) for v in value]
        return value
    signature = bits({k: packet[k] for k in ('coefficients', 'fit_statistics', 'nobs',
                                           'r_squared', 'r_squared_adj', 'df_model',
                                           'df_resid', 'covariance') if k in packet})
    result = {'case': case, 'rows': n, 'status': outcome['status'], 'seconds': elapsed,
              'input_sha256': payload['sha256'], 'measurement_scope': 'fresh_worker_without_input_generation',
              'tracemalloc_peak_bytes': traced_peak, 'stages': stage_summary(stages),
              'ru_maxrss': rss, 'rss_bytes': rss if platform.system() == 'Darwin' else rss*1024,
              'run_bytes': sum(p.stat().st_size for p in run.rglob('*') if p.is_file()),
              'numeric_signature': signature, 'run_root': str(run)}
    (out / 'metrics.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({k:v for k,v in result.items() if k != 'numeric_signature'}), flush=True)
    return 0 if outcome['status'] == 'completed' else 1


RESOURCE_METRICS = ('seconds', 'rss_bytes', 'run_bytes')


def baseline_noise(runs, *, metrics=RESOURCE_METRICS):
    """Sample standard deviation / median; preregistered before measuring.

    Every observation stays in the estimate. More samples estimate the noise
    more accurately; they do NOT divide it by sqrt(n) to conceal variability.
    """
    import statistics
    if len(runs) < 5:
        raise ValueError('at_least_five_calibration_runs_required')
    return {key: statistics.stdev(r[key] for r in runs)/statistics.median(r[key] for r in runs)
            for key in metrics}


def noise_accepted(noise):
    return all(v < .05 for v in noise.values())


def idle_processes(out):
    import os
    import subprocess
    processes = subprocess.check_output(['ps', '-Ao', 'pid=,ppid=,command='], text=True)
    (out / 'processes-before.txt').write_text(processes)
    others = [line for line in processes.splitlines()
              if int(line.split()[0]) not in {os.getpid(), os.getppid()}
              and any(s in line for s in ('-m pytest', '/pytest ', 'bench_families.py', 'scripts/perf_1m.py'))
              and 'ps -Ao' not in line]
    if others:
        raise SystemExit('Other tests/benchmarks active; refusing A/B: '+str(others))


def ab_main(argv):
    import hashlib
    import json
    import os
    import statistics
    import subprocess
    import shutil
    parser = argparse.ArgumentParser(description='Fixed source; A-only noise then five alternating pairs; 5% limits.')
    parser.add_argument('--ab', action='store_true')
    parser.add_argument('--baseline-repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--inputs', type=Path)
    parser.add_argument('--cases', nargs='+', choices=list(FAMILY_ROWS), default=list(FAMILY_ROWS))
    parser.add_argument('--profile-stages', action='store_true', help='Separate instrumented A/B after acceptance runs')
    parser.add_argument('--trace-memory', action='store_true', help='Separate tracemalloc lane; timings are NOT acceptance timings')
    parser.add_argument('--calibration-from', type=Path, help='Reuse completed calibration with the same probe, baseline, threads and source SHA')
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    candidate, baseline = Path.cwd(), args.baseline_repo.resolve()
    if (out/'ab-results.json').exists():
        raise FileExistsError('Do not overwrite previous measurement evidence; use a fresh --out')
    idle_processes(out)
    revisions = {name: subprocess.check_output(['git','rev-parse','HEAD'], cwd=repo, text=True).strip()
                 for name,repo in [('baseline',baseline),('candidate',candidate)]}
    if revisions['baseline'] != subprocess.check_output(['git','rev-parse','v1.9.0^{commit}'], cwd=candidate,text=True).strip():
        raise SystemExit('Baseline must be exact v1.9.0')
    difference = subprocess.check_output(['git','diff','--binary','HEAD'], cwd=candidate)
    (out/'candidate.patch').write_bytes(difference)
    untracked = subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=candidate,text=True).splitlines()
    report = {'measurement_version': 2, 'candidate_diff_sha256': hashlib.sha256(difference).hexdigest(),
              'untracked_source_sha256': {path:source_digest(candidate/path) for path in untracked if (candidate/path).is_file()},
              'thread_environment': {key: os.environ.get(key) for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','VECLIB_MAXIMUM_THREADS','MKL_NUM_THREADS','PYTHONHASHSEED')},
              'revisions': revisions, 'order': [f'{lane}{i}' for i in range(1,6) for lane in 'AB'],
              'noise_definition': 'sample_standard_deviation/median; all observations; no standard_error_substitution',
              'multiplier': 1.05, 'trace_memory': args.trace_memory,
              'time_acceptance_eligible': not args.trace_memory,
              'memory_metric': 'tracemalloc_peak_bytes' if args.trace_memory else 'rss_bytes', 'cases': {}}
    failed = []
    driver = Path(__file__).resolve()
    def save():
        (out/'ab-results.json').write_text(json.dumps(report, indent=2))
    for case in args.cases:
        inputs = (args.inputs or out/'inputs').resolve()/case
        manifest = prepare_family(case, inputs)
        records = {'A': [], 'B': []}
        calibration = []
        input_payload = json.loads(manifest.read_text())
        if args.calibration_from:
            prior = json.loads(args.calibration_from.read_text())
            if (prior['revisions']['baseline'] != revisions['baseline'] or
                    prior['trace_memory'] != args.trace_memory or
                    prior['thread_environment'] != report['thread_environment'] or
                    prior['cases'][case]['input']['sha256'] != input_payload['sha256']):
                raise ValueError('calibration_provenance_mismatch')
            calibration.extend(prior['cases'][case]['calibration'])
        case_report = {'calibration': calibration, 'raw': records,
                       'input': input_payload, 'calibration_origin': str(args.calibration_from) if args.calibration_from else None}
        report['cases'][case] = case_report
        def run(label, *, profile=False):
            repo = baseline if label.startswith('A') else candidate
            destination = out / case / label
            payload = json.loads(manifest.read_text())
            registered_source(payload)
            previous = calibration+records['A']+records['B']
            expected = max([r.get('destination_bytes', 0) for r in previous]+[220*2**20])
            if shutil.disk_usage(out).free < expected+512*2**20:
                save()
                raise SystemExit('Insufficient disk for next run plus 512MiB reserve; evidence preserved')
            command = [str(candidate/'.venv/bin/python'), str(driver), '--case', case,
                       '--out', str(destination), '--manifest', str(manifest)]
            if profile:
                command += ['--profile-stages']
            if args.trace_memory:
                command += ['--trace-memory']
            env = dict(os.environ, PYTHONPATH=str(repo/'backend'), LC_ALL='en_US.UTF-8', LANG='en_US.UTF-8')
            with (out/f'{case}-{label}.log').open('w') as log:
                result = subprocess.run(command,cwd=repo,env=env,stdout=log,stderr=subprocess.STDOUT)
            if result.returncode:
                raise SystemExit(f'{case} {label} failed; see log')
            registered_source(payload)
            value = json.loads((destination/'metrics.json').read_text())
            value['destination_bytes'] = sum(p.stat().st_size for p in destination.rglob('*') if p.is_file())
            if value['input_sha256'] != payload['sha256']:
                raise SystemExit('worker_input_digest_mismatch')
            print(f"{case} {label}: {value['seconds']:.6f}s, RSS {value['rss_bytes']/2**20:.3f} MiB, disk {value['run_bytes']/1e6:.6f} MB", flush=True)
            return value
        noise_metrics = ('tracemalloc_peak_bytes', 'run_bytes') if args.trace_memory else RESOURCE_METRICS
        def calibration_ready():
            if len(calibration) < 5:
                return False
            noise = baseline_noise(calibration, metrics=noise_metrics)
            case_report['noise'] = noise
            # RSS noise does not justify spending on identical RSS repetitions.
            # Complete the uninstrumented TIME lane, flag memory unresolved,
            # and use the separately recorded tracemalloc lane for memory.
            case_report['rss_noise_requires_trace'] = not args.trace_memory and noise['rss_bytes'] >= .05
            valid = {k:v for k,v in noise.items() if k != 'rss_bytes' or args.trace_memory}
            save()
            return noise_accepted(valid)
        while not calibration_ready():
            if len(calibration) >= 30:
                case_report['failed'] = ['measurement_noise']
                save()
                print(f'Noise >=5% after 30 calibration runs: {case_report["noise"]}',flush=True)
                return 2
            calibration.append(run(f'A0_{len(calibration)+1:02}'))
            save()
        for label in report['order']:
            records[label[0]].append(run(label))
            save()
        observed_metrics = RESOURCE_METRICS + (('tracemalloc_peak_bytes',) if args.trace_memory else ())
        medians = {lane:{key:statistics.median(r[key] for r in runs) for key in observed_metrics}
                   for lane,runs in records.items()}
        accepted_metrics = ('tracemalloc_peak_bytes','run_bytes') if args.trace_memory else RESOURCE_METRICS
        budgets = {key:medians['A'][key]*1.05 for key in accepted_metrics}
        misses = [key for key,limit in budgets.items() if medians['B'][key]>limit]
        if case_report['rss_noise_requires_trace']:
            misses.append('rss_noise_requires_trace')
        if not args.trace_memory and case in {'panel','iv'} and medians['B']['seconds']>{'panel':12.2,'iv':15.1}[case]:
            misses.append('absolute_seconds')
        signatures = [r['numeric_signature'] for r in records['A']+records['B']]
        if not signatures[0] or not all(s==signatures[0] for s in signatures):
            misses.append('numeric_bits')
        case_report.update(medians=medians, budgets=budgets, failed=misses)
        if args.profile_stages:
            case_report['stage_profile'] = {lane:run(lane+'_stages',profile=True) for lane in 'AB'}
            case_report['stage_comparison'] = compare_stages(case_report['stage_profile']['A'], case_report['stage_profile']['B'])
            if any(r['over_one_percent'] for r in case_report['stage_comparison'].values()):
                misses.append('stage_attribution_pending')
        save()
        failed.extend(f'{case}:{key}' for key in misses)
    label = 'PASS memory-only (instrumented time is ineligible)' if args.trace_memory else 'PASS'
    print(label if not failed else 'FAIL '+', '.join(failed),flush=True)
    return int(bool(failed))


def main():
    if '--ab' in sys.argv:
        return ab_main(sys.argv[1:])
    if '--case' in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument('--case', choices=list(FAMILY_ROWS), required=True)
        parser.add_argument('--out', type=Path, required=True)
        parser.add_argument('--manifest', type=Path, required=True)
        parser.add_argument('--profile-stages', action='store_true')
        parser.add_argument('--trace-memory', action='store_true')
        args = parser.parse_args()
        return family_run(args.case, args.out.resolve(), manifest=args.manifest,
                          stage_profile=args.profile_stages, trace_memory=args.trace_memory)
    return interactive_main()


if __name__ == '__main__':
    raise SystemExit(main())
