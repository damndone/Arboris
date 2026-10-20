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


def _dataset(path: Path) -> Path:
    rng = np.random.default_rng(1)
    education = rng.integers(9, 21, ROWS)
    experience = rng.integers(0, 40, ROWS)
    female = rng.binomial(1, 0.5, ROWS)
    region = rng.choice(["north", "south", "east", "west"], ROWS)
    frame = pd.DataFrame(
        {
            "id": np.arange(ROWS),
            "wage": np.round(np.exp(1.2 + 0.08 * education + 0.03 * experience - 0.1 * female + rng.normal(0, 0.35, ROWS)), 2),
            "education": education,
            "experience": experience,
            "age": np.clip(education + experience + 6, 18, 75),
            "female": female,
            "region": region,
            "union": rng.binomial(1, 0.25, ROWS),
            "hours": np.round(rng.normal(40, 6, ROWS), 1),
            "tenure": rng.integers(0, 30, ROWS),
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


def family_run(case, out):
    import json
    import resource
    import platform
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    n = FAMILY_ROWS[case]
    if case == 'ols':
        source = _dataset(out.parent / 'wages.csv')
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
        source = out.parent / f'{case}.csv'
        frame.to_csv(source, index=False)
        del frame
    elif case == 'iv':
        z1, z2, u = rng.normal(size=n), rng.normal(size=n), rng.normal(size=n)
        d = .6*z1+.4*z2+.5*u+rng.normal(size=n)
        w = rng.normal(size=n)
        frame = pd.DataFrame({'y': d+.3*w+u+rng.normal(size=n), 'd': d, 'w': w, 'z1': z1, 'z2': z2})
        source = out.parent / 'iv.csv'
        frame.to_csv(source, index=False)
        del frame
        kwargs = dict(model_type='iv_2sls', y='y', x=['w'], iv_endog=['d'], iv_instruments=['z1', 'z2'])
    else:
        x1, x2 = rng.normal(size=n), rng.normal(size=n)
        duration = rng.exponential(np.exp(-.3*x1+.2*x2))
        censor = rng.exponential(2, size=n)
        frame = pd.DataFrame({'duration': np.minimum(duration, censor)+.001,
                              'event': (duration <= censor).astype(int), 'x1': x1, 'x2': x2})
        source = out.parent / 'cox.csv'
        frame.to_csv(source, index=False)
        del frame
        kwargs = dict(model_type='survival_cox', y='duration', x=['x1', 'x2'],
                      model_options={'event_column': 'event', 'ties': 'breslow'})
    project = create_project(out, 'benchmark')
    started = time.perf_counter()
    outcome = run_workflow(project.root, [source], mode='auto', **kwargs)
    elapsed = time.perf_counter()-started
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
    signature = bits({k: packet[k] for k in ('coefficients', 'fit_statistics') if k in packet})
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result = {'case': case, 'rows': n, 'status': outcome['status'], 'seconds': elapsed,
              'ru_maxrss': rss, 'rss_bytes': rss if platform.system() == 'Darwin' else rss*1024,
              'run_bytes': sum(p.stat().st_size for p in run.rglob('*') if p.is_file()),
              'numeric_signature': signature, 'run_root': str(run)}
    (out / 'metrics.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({k:v for k,v in result.items() if k != 'numeric_signature'}), flush=True)
    return 0 if outcome['status'] == 'completed' else 1


def ab_main(argv):
    import json
    import os
    import statistics
    import subprocess
    parser = argparse.ArgumentParser(description='Alternating A/B: baseline, candidate, baseline, candidate; 5% limits.')
    parser.add_argument('--ab', action='store_true')
    parser.add_argument('--baseline-repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', choices=list(FAMILY_ROWS), default=list(FAMILY_ROWS))
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    candidate, baseline = Path.cwd(), args.baseline_repo.resolve()
    # Preserve the complete process inventory used to establish a clean slot.
    processes = subprocess.check_output(['ps', '-Ao', 'pid=,command='], text=True)
    (out / 'processes-before.txt').write_text(processes)
    others = [line for line in processes.splitlines() if any(s in line for s in ('-m pytest', '/pytest ', 'bench_families.py'))
              and 'ps -Ao' not in line]
    if others:
        raise SystemExit('Other tests/benchmarks active; refusing A/B: '+str(others))
    revisions = {name: subprocess.check_output(['git','rev-parse','HEAD'], cwd=repo, text=True).strip()
                 for name,repo in [('baseline',baseline),('candidate',candidate)]}
    if revisions['baseline'] != subprocess.check_output(['git','rev-parse','v1.9.0^{commit}'], cwd=candidate,text=True).strip():
        raise SystemExit('Baseline must be exact v1.9.0')
    import hashlib
    difference = subprocess.check_output(['git','diff','--binary','HEAD'], cwd=candidate)
    report = {'candidate_diff_sha256': hashlib.sha256(difference).hexdigest(),
              'thread_environment': {key: os.environ.get(key) for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','VECLIB_MAXIMUM_THREADS','MKL_NUM_THREADS','PYTHONHASHSEED')},
              'revisions': revisions, 'order': ['A1','B1','A2','B2'], 'multiplier': 1.05, 'cases': {}}
    failed = []
    driver = Path(__file__).resolve()
    for case in args.cases:
        records = {'A': [], 'B': []}
        for label in report['order']:
            repo = baseline if label.startswith('A') else candidate
            destination = out / case / label
            command = [str(candidate/'.venv/bin/python'), str(driver), '--case', case, '--out', str(destination)]
            env = dict(os.environ, PYTHONPATH=str(repo/'backend'), LC_ALL='en_US.UTF-8', LANG='en_US.UTF-8')
            with (out/f'{case}-{label}.log').open('w') as log:
                result = subprocess.run(command,cwd=repo,env=env,stdout=log,stderr=subprocess.STDOUT)
            if result.returncode:
                raise SystemExit(f'{case} {label} failed; see log')
            value = json.loads((destination/'metrics.json').read_text())
            records[label[0]].append(value)
            print(f"{case} {label}: {value['seconds']:.3f}s, RSS {value['rss_bytes']/2**20:.1f} MiB, disk {value['run_bytes']/1e6:.3f} MB", flush=True)
        medians = {lane:{key:statistics.median(r[key] for r in runs) for key in ('seconds','rss_bytes','run_bytes')}
                   for lane,runs in records.items()}
        budgets = {key:value*1.05 for key,value in medians['A'].items()}
        misses = [key for key,limit in budgets.items() if medians['B'][key]>limit]
        if case in {'panel','iv'}:
            absolute = {'panel':12.2,'iv':15.1}[case]
            if medians['B']['seconds']>absolute:
                misses.append('absolute_seconds')
        signatures = [r['numeric_signature'] for runs in records.values() for r in runs]
        # JSON floats have round-trip binary64 precision; exact equality here
        # includes coefficients, standard errors, tests and reported fit stats.
        if not signatures[0] or not all(s==signatures[0] for s in signatures):
            misses.append('numeric_bits')
        report['cases'][case] = {'raw':records,'medians':medians,'budgets':budgets,'failed':misses}
        (out/'ab-results.json').write_text(json.dumps(report,indent=2))
        failed.extend(f'{case}:{key}' for key in misses)
    print('PASS' if not failed else 'FAIL '+', '.join(failed),flush=True)
    return int(bool(failed))


def main():
    if '--ab' in sys.argv:
        return ab_main(sys.argv[1:])
    if '--case' in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument('--case', choices=list(FAMILY_ROWS), required=True)
        parser.add_argument('--out', type=Path, required=True)
        args = parser.parse_args()
        return family_run(args.case, args.out.resolve())
    return interactive_main()


if __name__ == '__main__':
    raise SystemExit(main())
