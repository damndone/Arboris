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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from perf_evidence import MIN_FREE_BYTES, finalize_active, require_space  # noqa: E402

from workbench.orchestrator import run_workflow  # noqa: E402
from workbench.projects import create_project  # noqa: E402

ROWS = 1_000_000
OLS_SECONDS_CAP = 8.0

# Seconds. Interactive reads must feel instant; one-off heavy work may take a
# while but must stay bounded.
BUDGETS = {
    "ingest + OLS run": OLS_SECONDS_CAP,
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
    from workbench import analysis_disclosure, analysis_ledger
    from workbench.data_operation_registry import get_data_operation
    from workbench.services.data_export import export_dataset, preview_export
    from workbench.services.dataset_view import dataset_page, dataset_variables, load_dataset
    from workbench.services.results_service import read_model_results
    from workbench.statistical_exploration import ExplorationSpec, execute_exploration

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

    require_space(out)
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


def family_kwargs(case):
    if case == 'ols':
        return dict(model_type='ols', y='wage', x=['education', 'experience', 'female', 'hours'])
    if case in {'panel', 'did'}:
        kwargs = dict(model_type='panel_ols', y='y', x=['x1', 'x2'], entity_col='unit', time_col='year')
        if case == 'did':
            kwargs.update(model_type='did', did_mode='cohort', did_cohort_col='first_treat')
        return kwargs
    if case == 'iv':
        return dict(model_type='iv_2sls', y='y', x=['w'], iv_endog=['d'], iv_instruments=['z1', 'z2'])
    return dict(model_type='survival_cox', y='duration', x=['x1', 'x2'],
                model_options={'event_column': 'event', 'ties': 'breslow'})


def prepare_family(case, out, *, rows=None):
    import json
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / 'source.json'
    if manifest.exists():
        validate_family_manifest(manifest)
        return manifest
    n = FAMILY_ROWS[case] if rows is None else rows
    source = out / ('wages.csv' if case == 'ols' else f'{case}.csv')
    if not source.exists():
        require_space(out)
        rng = np.random.default_rng(7)
        if case == 'ols':
            source = _dataset(out / 'wages.csv', n)
        elif case in {'panel', 'did'}:
            unit = np.repeat(np.arange(n//10), 10)
            year = np.tile(np.arange(2000, 2010), n//10)
            x1, x2 = rng.normal(size=n), rng.normal(size=n)
            y = .5*x1-.2*x2+rng.normal(size=n//10)[unit]+rng.normal(size=n)
            frame = pd.DataFrame({'unit': unit, 'year': year, 'x1': x1, 'x2': x2, 'y': y})
            if case == 'did':
                frame['first_treat'] = np.where(unit % 2 == 0, 2005, 0)
                frame['y'] += 2*((unit % 2 == 0) & (year >= 2005))
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
        else:
            x1, x2 = rng.normal(size=n), rng.normal(size=n)
            duration = rng.exponential(np.exp(-.3*x1+.2*x2))
            censor = rng.exponential(2, size=n)
            frame = pd.DataFrame({'duration': np.minimum(duration, censor)+.001,
                                  'event': (duration <= censor).astype(int), 'x1': x1, 'x2': x2})
            source = out / 'cox.csv'
            frame.to_csv(source, index=False)
            del frame
    payload = {'case': case, 'rows': n, 'source': str(source.resolve()),
               'sha256': source_digest(source), 'source_stat': source_identity(source),
               'kwargs': family_kwargs(case), 'generator': 'perf_1m_fixed_input_v2',
               'seed': 1 if case == 'ols' else 7}
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
    return {r['stage']: dict(r, rss_delta_bytes=r['rss_after']-r['rss_before'],
                            **({'traced_delta_bytes':r['traced_after']-r['traced_before']}
                               if 'traced_before' in r else {})) for r in rows}


def compare_stages(baseline, candidate):
    differences = {}
    for name in baseline['stages'].keys() | candidate['stages'].keys():
        a, b = baseline['stages'].get(name), candidate['stages'].get(name)
        if a is None or b is None:
            differences[name] = {'reason': 'stage_exists_in_one_version_only', 'over_one_percent': True}
            continue
        dt, dm = b['seconds']-a['seconds'], b['rss_delta_bytes']-a['rss_delta_bytes']
        traced = b.get('traced_delta_bytes',0)-a.get('traced_delta_bytes',0)
        traced_fraction = traced/baseline.get('tracemalloc_peak_bytes',1)
        over = abs(dt/baseline['seconds']) > .01 or abs(dm/baseline['rss_bytes']) > .01 or abs(traced_fraction) > .01
        differences[name] = {
            'baseline': a, 'candidate': b, 'seconds_delta': dt,
            'rss_increment_delta_bytes': dm,
            'time_fraction_of_baseline_workflow': dt/baseline['seconds'],
            'memory_fraction_of_baseline_peak': dm/baseline['rss_bytes'],
            'traced_increment_delta_bytes':traced,
            'traced_fraction_of_baseline_peak':traced_fraction,
            'over_one_percent':over,
            'cause': 'requires_stage_code/profile_attribution' if over else 'below_one_percent',
        }
    # Imports, hashing, publication and run setup outside the pipeline must not
    # disappear merely because stage timings add up to less than the workflow.
    outside_a = baseline['seconds']-sum(r['seconds'] for r in baseline['stages'].values())
    outside_b = candidate['seconds']-sum(r['seconds'] for r in candidate['stages'].values())
    differences['outside_pipeline'] = {'baseline_seconds': outside_a, 'candidate_seconds': outside_b,
                                        'seconds_delta': outside_b-outside_a,
                                        'over_one_percent': abs(outside_b-outside_a)/baseline['seconds'] > .01}
    return differences


def family_run(case, out, *, manifest, trace_memory=False, allow_low_space=False):
    import json
    import resource
    import platform
    # Parent validates the file digest once, then checks identity per worker. Do not re-read the
    # source or generate any observations in this measured process.
    payload = json.loads(manifest.read_text())
    source, kwargs, n = Path(payload['source']), payload['kwargs'], payload['rows']
    if case != payload['case']:
        raise ValueError('manifest_case_mismatch')
    require_space(out.parent, allow_low_space=allow_low_space)
    out.mkdir(parents=True, exist_ok=False)
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
              'allow_low_space_this_run': allow_low_space,
              'input_sha256': payload['sha256'], 'measurement_scope': 'fresh_worker_default_product_path', 'default_product_path': True,
              'input_io': 'unmodified_product_writes', 'timing_instrumentation': 'tracemalloc' if trace_memory else 'none',
              'time_acceptance_eligible': not trace_memory,
              'tracemalloc_peak_bytes': traced_peak,
              'ru_maxrss': rss, 'rss_bytes': rss if platform.system() == 'Darwin' else rss*1024,
              'run_bytes': sum(p.stat().st_size for p in run.rglob('*') if p.is_file()),
              'numeric_signature': signature, 'run_root': str(run)}
    (out / 'metrics.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({k:v for k,v in result.items() if k != 'numeric_signature'}), flush=True)
    return 0 if outcome['status'] == 'completed' else 1


RESOURCE_METRICS = ('seconds', 'rss_bytes', 'run_bytes')


def product_sources(repo):
    """Freeze untracked native/product code too; a Git patch alone misses it."""
    paths = [path for directory in ('backend', 'native') for path in (repo/directory).rglob('*')
             if path.is_file() and path.suffix in {'.py', '.cpp', '.h', '.hpp'}]
    paths.extend(path for name in ('native-ar', 'native-kendall', 'native-canonical')
                 for path in (repo/'local'/name).glob('*.so') if path.is_file())
    return {str(path.relative_to(repo)): source_digest(path) for path in sorted(paths)}


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


def median_stages(runs):
    import statistics
    names = {name for run in runs for name in run['stages']}
    stages = {}
    for name in names:
        values = [run['stages'][name] for run in runs if name in run['stages']]
        stages[name] = {key:statistics.median(value[key] for value in values)
                        for key in values[0] if key != 'stage' and values[0][key] is not None}
    return stages


def ab_main(argv):
    import hashlib
    import json
    import os
    import statistics
    import subprocess
    parser = argparse.ArgumentParser(description='One active tree; journal then remove; fixed inputs and five alternating pairs.')
    parser.add_argument('--ab', action='store_true')
    parser.add_argument('--baseline-repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--inputs', type=Path)
    parser.add_argument('--cases', nargs='+', choices=list(FAMILY_ROWS), default=list(FAMILY_ROWS))
    parser.add_argument('--trace-memory', action='store_true', help='Same-run allocation tracing; memory lane only, no absolute time acceptance')
    parser.add_argument('--allow-low-space-this-run', action='store_true',
                        help='explicit user exception for this native AB; all numerical/resource gates remain')
    args = parser.parse_args(argv)
    out = args.out.resolve()
    require_space(out, allow_low_space=args.allow_low_space_this_run)
    out.mkdir(parents=True, exist_ok=True)
    candidate, baseline = Path.cwd(), args.baseline_repo.resolve()
    if (out/'ab-results.json').exists() or (out/'active').exists():
        raise FileExistsError('Preserve previous evidence; use a fresh --out')
    idle_processes(out)
    revisions = {name: subprocess.check_output(['git','rev-parse','HEAD'], cwd=repo, text=True).strip()
                 for name,repo in [('baseline',baseline),('candidate',candidate)]}
    sources = {name: product_sources(repo) for name, repo in [('baseline', baseline), ('candidate', candidate)]}
    if revisions['baseline'] != subprocess.check_output(['git','rev-parse','v1.9.0^{commit}'], cwd=candidate,text=True).strip():
        raise SystemExit('Baseline must be exact v1.9.0')
    difference = subprocess.check_output(['git','diff','--binary','HEAD'], cwd=candidate)
    (out/'candidate.patch').write_bytes(difference)
    shared_sources = {str(path): source_digest(path) for path in
                      (Path(__file__).resolve(), Path(__file__).with_name('perf_evidence.py').resolve())}
    report = {'measurement_version': 4, 'candidate_diff_sha256': hashlib.sha256(difference).hexdigest(),
              'driver_sha256': source_digest(Path(__file__)),
              'thread_environment': {key: os.environ.get(key) for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','VECLIB_MAXIMUM_THREADS','MKL_NUM_THREADS','PYTHONHASHSEED')},
              'revisions': revisions, 'order': [f'{lane}{i}' for i in range(1,6) for lane in 'AB'],
              'noise_definition': 'sample_standard_deviation/median; all observations', 'multiplier':1.05,
              'trace_memory':args.trace_memory, 'time_acceptance_eligible':not args.trace_memory,
              'default_product_path':True, 'worker_environment':'inherited unchanged',
              'inputs_policy':'one_fixed_CSV_per_case; product snapshots/uploads written normally',
              'retention':'one_active_tree; durable_verified_JSONL_then_removal; one_archive_per_case_release',
              'minimum_free_bytes':MIN_FREE_BYTES, 'allow_low_space_this_run':args.allow_low_space_this_run,
              'source_sha256':sources, 'shared_source_sha256':shared_sources, 'cases':{}}
    failed = []
    driver = Path(__file__).resolve()
    ledger = out/'measurements.jsonl'
    active = out/'active'
    def save():
        (out/'ab-results.json').write_text(json.dumps(report,indent=2))
    (out/'inputs').mkdir()
    for case in args.cases:
        canonical_manifest = prepare_family(case, (args.inputs or candidate/'local/perf-inputs').resolve()/case)
        payload = json.loads(canonical_manifest.read_text())
        # The canonical content digest was just verified by prepare_family.
        # Device/inode identities belong to this measurement, not a prior
        # filesystem mount. Keep the original registration immutable.
        payload = {**payload, 'canonical_manifest': str(canonical_manifest),
                   'canonical_manifest_sha256': source_digest(canonical_manifest),
                   'origin_source_stat': payload['source_stat'],
                   'source_stat': source_identity(Path(payload['source']))}
        manifest = out/'inputs'/f'{case}.json'
        with manifest.open('x') as stream:
            json.dump(payload, stream, indent=2)
        records, calibration = {'A':[], 'B':[]}, []
        case_report = {'calibration':calibration, 'raw':records, 'input':payload}
        report['cases'][case] = case_report
        save()
        def run(label):
            free = require_space(out, allow_low_space=args.allow_low_space_this_run)
            idle_processes(out)
            if any(source_digest(Path(path)) != digest for path, digest in shared_sources.items()):
                raise SystemExit('Shared measurement source changed before worker')
            if active.exists():
                raise SystemExit('Unrecorded active tree exists; refusing a second run')
            lane = 'baseline' if label.startswith('A') else 'candidate'
            repo = baseline if lane == 'baseline' else candidate
            commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
            if commit != revisions[lane]:
                raise SystemExit('Repository changed during measurement')
            if product_sources(repo) != sources[lane]:
                raise SystemExit('Product/native source or binary changed during measurement')
            registered_source(payload)
            command = [str(candidate/'.venv/bin/python'), str(driver), '--case',case,
                       '--out',str(active),'--manifest',str(manifest)]
            if args.trace_memory:
                command.append('--trace-memory')
            if args.allow_low_space_this_run:
                command.append('--allow-low-space-this-run')
            with (out/f'{case}-{label}.log').open('w') as log:
                result = subprocess.run(command,cwd=repo,stdout=log,stderr=subprocess.STDOUT)
            overlap = None
            try:
                idle_processes(out)
            except SystemExit as error:
                overlap = str(error)
            registered_source(payload)
            if any(source_digest(Path(path)) != digest for path, digest in shared_sources.items()):
                raise SystemExit('Shared measurement source changed during worker; retain active evidence')
            if product_sources(repo) != sources[lane]:
                raise SystemExit('Product/native source or binary changed during worker; retain active evidence')
            metrics = active/'metrics.json'
            if metrics.exists():
                value = json.loads(metrics.read_text())
            else:
                active.mkdir(parents=True,exist_ok=True)
                value = dict(case=case,status='failed',seconds=None,ru_maxrss=None,tracemalloc_peak_bytes=None,
                             run_root=str(active/'uncompleted'),numeric_signature={},input_sha256=payload['sha256'])
            value.update(version_commit=commit, driver_sha256=report['driver_sha256'],
                         measurement_version=4,input_source=payload['source'],free_before_bytes=free,
                         returncode=result.returncode,label=label,host_overlap=overlap)
            retention = finalize_active(active,ledger=ledger,record_id=f'{case}-{label}',metadata=value,
                                        archive_dir=out.parent/'representatives',
                                        version='v1.9.0' if lane=='baseline' else 'v1.9.1',case=case)
            value['retention'] = retention
            if result.returncode or overlap:
                case_report.setdefault('failed_runs',[]).append(value)
                save()
                raise SystemExit(f'{case} {label} failed; evidence retained and active tree removed')
            print(f"{case} {label}: {value['seconds']:.6f}s, trace={args.trace_memory}, RSS {value['rss_bytes']/2**20:.3f} MiB, traced peak {value['tracemalloc_peak_bytes']}, disk {value['run_bytes']}; recorded then removed",flush=True)
            return value
        noise_keys = ('tracemalloc_peak_bytes','run_bytes') if args.trace_memory else ('seconds','run_bytes')
        while True:
            calibration.append(run(f'A0_{len(calibration)+1:02}'))
            save()
            if len(calibration) >= 5:
                case_report['noise'] = baseline_noise(calibration,metrics=noise_keys)
                case_report['native_rss_noise'] = baseline_noise(calibration,metrics=('rss_bytes',))['rss_bytes']
                if noise_accepted(case_report['noise']):
                    break
                if len(calibration) >= 30:
                    case_report['failed'] = ['measurement_noise']
                    save()
                    return 2
        for label in report['order']:
            records[label[0]].append(run(label))
            save()
        case_report['all_baseline_noise'] = baseline_noise(calibration+records['A'],metrics=noise_keys)
        case_report['calibration_native_rss_noise'] = case_report['native_rss_noise']
        case_report['all_baseline_native_rss_noise'] = baseline_noise(calibration+records['A'],metrics=('rss_bytes',))['rss_bytes']
        case_report['native_rss_noise'] = max(case_report['calibration_native_rss_noise'],case_report['all_baseline_native_rss_noise'])
        keys = RESOURCE_METRICS+(('tracemalloc_peak_bytes',) if args.trace_memory else ())
        medians = {lane:{key:statistics.median(r[key] for r in runs) for key in keys} for lane,runs in records.items()}
        accepted = noise_keys+(('rss_bytes',) if case_report['native_rss_noise'] < .05 else ())
        budgets = {key:medians['A'][key]*1.05 for key in accepted}
        absolute_cap = None if args.trace_memory else {'ols':OLS_SECONDS_CAP,'panel':12.2,'iv':15.1}.get(case)
        if absolute_cap is not None:
            budgets['seconds'] = min(budgets['seconds'],absolute_cap)
        misses = [key for key,limit in budgets.items() if medians['B'][key]>limit]
        if not noise_accepted(case_report['all_baseline_noise']):
            misses.append('measurement_noise')
        if not args.trace_memory and case_report['native_rss_noise'] >= .05:
            misses.append('native_rss_noise_requires_tracemalloc')
        signatures = [r['numeric_signature'] for runs in records.values() for r in runs]
        if not signatures[0] or not all(value==signatures[0] for value in signatures):
            misses.append('numeric_bits')
        case_report.update(medians=medians,budgets=budgets,failed=misses,
                           absolute_seconds_cap=absolute_cap,
                           memory_metric=('rss_and_tracemalloc' if args.trace_memory else 'rss') if 'rss_bytes' in accepted else ('tracemalloc_due_to_native_rss_noise' if args.trace_memory else 'unaccepted_rss_noise'))
        save()
        failed.extend(f'{case}:{key}' for key in misses)
    print(('DEFAULT PATH MEMORY CHECKS PASS; traced time is diagnostic' if args.trace_memory else 'DEFAULT PATH CHECKS PASS') if not failed else 'FAIL '+', '.join(failed),flush=True)
    return int(bool(failed))


def main():
    if '--ab' in sys.argv:
        return ab_main(sys.argv[1:])
    if '--case' in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument('--case', choices=list(FAMILY_ROWS), required=True)
        parser.add_argument('--out', type=Path, required=True)
        parser.add_argument('--manifest', type=Path, required=True)
        parser.add_argument('--trace-memory', action='store_true')
        parser.add_argument('--allow-low-space-this-run', action='store_true')
        args = parser.parse_args()
        return family_run(args.case, args.out.resolve(), manifest=args.manifest,
                          trace_memory=args.trace_memory, allow_low_space=args.allow_low_space_this_run)
    return interactive_main()


if __name__ == '__main__':
    raise SystemExit(main())
