#!/usr/bin/env python3
"""Time everyday operations on a 1,000,000-row dataset against budgets.

Builds a scratch project with a 1M x 10 wage dataset, runs one OLS, then
times what a user does next: open the Data view, read variable metadata,
tabulate and summarize, recode and filter, export, read results and the
report's disclosure. Prints a table and exits non-zero when a budget is
missed. Each run journals the full timings and keeps one representative
project under the output directory. Heavy: run it alone on the machine.

    PYTHONPATH=backend .venv/bin/python scripts/perf_1m.py --out /private/tmp/perf-1m
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
import traceback
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path.cwd() / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence_identity import evidence_key, source_tree  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))

from perf_evidence import (MIN_FREE_BYTES, create_active_project, finalize_active, require_space,
                           retain_worker_logs)  # noqa: E402
from perf_host import monitored_worker, require_idle  # noqa: E402

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


def _measure_interactive(active: Path, timings: dict[str, float]) -> Path:
    from workbench import analysis_disclosure, analysis_ledger
    from workbench.data_operation_registry import get_data_operation
    from workbench.services.data_export import export_dataset, preview_export
    from workbench.services.dataset_view import dataset_page, dataset_variables, load_dataset
    from workbench.services.results_service import read_model_results
    from workbench.statistical_exploration import ExplorationSpec, execute_exploration

    @contextmanager
    def timed(name: str):
        started = time.perf_counter()
        yield
        timings[name] = time.perf_counter() - started
        print(f"{name:40s} {timings[name]:8.2f}s  (budget {BUDGETS[name]:.1f}s)", flush=True)

    source = _dataset(active / "wages_1m.csv")
    project = create_active_project(active)
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
    return root / "runs" / run_id


def interactive_main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "perf-1m")
    args = parser.parse_args()
    out = args.out.expanduser().resolve()
    require_space(out)
    active = out / "active"
    active.mkdir(parents=True, exist_ok=False)
    record_id = f"interactive-{time.time_ns()}"
    timings: dict[str, float] = {}
    failure = None
    try:
        run = _measure_interactive(active, timings)
    except Exception as exc:
        failure = exc
        manifests = list((active / "benchmark/runs").glob("*/run_manifest.json"))
        run = manifests[0].parent if len(manifests) == 1 else active / "uncompleted"
        (active / "failure.log").write_text(traceback.format_exc(), encoding="utf-8")

    missed = {name: value for name, value in timings.items() if value > BUDGETS[name]}
    metadata = {"run_root": str(run), "status": "failed" if failure else "completed", "timings": timings,
                "budgets": BUDGETS, "missed": missed,
                "retained_logs": retain_worker_logs(active, out / "logs" / record_id)}
    retention = finalize_active(active, ledger=out / "runs.jsonl", record_id=record_id, metadata=metadata,
                                archive_dir=out / "representatives", version="v1.9.1", case="interactive-ols")
    print(f"Evidence: {out / 'runs.jsonl'} ({retention['representative_bytes']} representative bytes)", flush=True)
    if failure is not None:
        raise failure
    print()
    print("all within budget" if not missed else f"over budget: {', '.join(missed)}")
    return 1 if missed else 0


# End-to-end regression lane, isolated process per version/case/repetition.
# Run from each repository root; the driver file can belong to the candidate.
FAMILY_ROWS = {'ols': 1_000_000, 'panel': 1_000_000, 'iv': 1_000_000,
               'did': 1_000_000, 'cox': 200_000, 'wide': 750}


def family_kwargs(case):
    if case == 'ols':
        return dict(model_type='ols', y='wage', x=['education', 'experience', 'female', 'hours'])
    if case in {'panel', 'did'}:
        kwargs = dict(model_type='panel_ols', y='y', x=['x1', 'x2'], entity_col='unit', time_col='year')
        if case == 'did':
            kwargs.update(model_type='did', did_mode='cohort', did_cohort_col='first_treat')
        return kwargs
    if case == 'wide':
        return dict(model_type='ols', y='y', x=['treatment', *(f'x{i}' for i in range(1, 26))])
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
        elif case == 'wide':
            # A small survey-shaped table: the statistics stage dominates, not the fit.
            frame = pd.DataFrame({'treatment': rng.integers(0, 2, n)})
            for i in range(1, 26):
                frame[f'x{i}'] = rng.normal(size=n) if i <= 6 else rng.integers(0, 2 + i % 6, n)
            frame['y'] = frame['treatment'] + .2*frame['x1'] + rng.normal(size=n)
            source = out / 'wide.csv'
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


def numeric_bits(value):
    """Small persisted numerical evidence only; never observation arrays."""
    if isinstance(value, float):
        return {'binary64': value.hex()}
    if isinstance(value, dict):
        return {k: numeric_bits(v) for k, v in value.items()}
    if isinstance(value, list):
        return [numeric_bits(v) for v in value]
    return value


INFERENCE_FIELDS = ('param_names', 'params', 'vcov', 'vcov_param_names', 'vcov_scope',
                    'reference_distribution', 'df_resid', 'df_method', 'n_clusters', 'loglik',
                    'nobs', 'covariance_estimator', 'estimation_sample_fingerprint', 'weights',
                    'interfaces', 'unavailable')


def primary_inference_signature(run, model_id):
    """Exact persisted small kernel, including definitions; never observation arrays/refits."""
    import json
    kernel = json.loads((run/'model_results/inference_kernels'/f'{model_id}.json').read_text())
    return {key: kernel[key] for key in INFERENCE_FIELDS}


STATISTICAL_FILES = frozenset(('anova.json', 'chi_square.json', 'correlations.json', 'evidence.json',
                               'fisher_exact.json', 'nonparametric.json', 'rank_correlations.json', 't_tests.json'))


# These registered workloads produce advanced tests. Other workloads may
# legitimately omit the unregistered optional evidence file when its rows are empty.
ADVANCED_STATISTICAL_CASES = frozenset(('ols', 'wide'))


def statistical_signature_payloads(payloads, *, case):
    """Keep every field; only reviewed rank provenance text is not a statistical difference."""
    import copy
    required = STATISTICAL_FILES if case in ADVANCED_STATISTICAL_CASES else STATISTICAL_FILES - {'evidence.json'}
    if (not isinstance(payloads, dict) or not required <= payloads.keys()
            or any(not isinstance(v, dict) or not isinstance(v.get('results'), list) for v in payloads.values())
            or any(not isinstance(row, dict) or not {'statistic', 'p_value'} <= row.keys()
                   for payload in payloads.values() for row in payload['results'])
            or not any(v['results'] for v in payloads.values())
            or ('evidence.json' in payloads and not payloads['evidence.json']['results'])):
        raise ValueError('complete_nonempty_statistical_payloads_required')
    value = copy.deepcopy(payloads)
    for row in value['rank_correlations.json']['results']:
        metadata = row.get('computation')
        if (isinstance(metadata, dict) and metadata.keys() == {'engine', 'reason'}
                and metadata['engine'] in ('native-average-rank', 'native-counts')
                and (metadata['reason'] is None or isinstance(metadata['reason'], str))):
            del row['computation']
    return value


def statistical_tests_signature(run, *, case):
    """Read already persisted small test payloads, without fitting or observation arrays."""
    import json
    payloads = {path.name: json.loads(path.read_text())
                for path in sorted((run/'statistical_tests').glob('*.json'))}
    if case not in ADVANCED_STATISTICAL_CASES and 'evidence.json' not in payloads:
        entries = json.loads((run/'artifacts_index.json').read_text())['artifacts']
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            raise ValueError('statistical_artifact_index_malformed')
        if any(entry.get('artifact_id') == 'statistical_tests_evidence'
               or entry.get('path') == 'statistical_tests/evidence.json' for entry in entries):
            raise ValueError('registered_statistical_evidence_missing')
    return statistical_signature_payloads(payloads, case=case)


def iv_acceptance_signature(run, packet):
    """Read the already persisted fit; no refit, product hook or source reread."""
    import json
    from scipy import stats
    kernel = json.loads((run / 'model_results/inference_kernels/iv_2sls_1.json').read_text())
    diagnostics = json.loads((run / 'iv_diagnostics.json').read_text())
    completion = json.loads((run / 'model_results/iv_2sls_1.completion.json').read_text())
    # Explanatory prose embeds rounded values; retain its statistical facts and definitions.
    def facts(value):
        if isinstance(value, dict):
            return {k: facts(v) for k, v in value.items() if k != 'message'}
        if isinstance(value, list):
            return [facts(v) for v in value]
        return value
    inference = {}
    for index, name in enumerate(kernel['param_names']):
        statistic = kernel['params'][index] / kernel['vcov'][index][index] ** .5
        distribution = stats.t(kernel['df_resid']) if kernel['reference_distribution'] == 't' else stats.norm
        inference[name] = {'statistic': statistic, 'p_value': float(2 * distribution.sf(abs(statistic)))}
    return numeric_bits({
        'packet': {key: packet[key] for key in ('coefficients', 'nobs', 'df_model', 'df_resid',
                                               'r_squared', 'r_squared_adj')},
        'kernel': kernel, 'coefficient_inference': inference, 'diagnostics': facts(diagnostics),
        'sample': completion['sample'], 'point_definition': completion['point_definition'],
    })


def requested_figure_delivery(run, *, started, requested, analysis_ready=None):
    """Time the same public materialization service a user's figure request uses."""
    if not requested:
        return {'status': 'not_requested', 'requirements': 'analysis only; figures and extra report export not requested'}
    import json
    import platform
    import resource
    planned = (run / 'figures/plan.json').exists()
    if planned:
        # v1.9.0 generated figures eagerly and has no figure_plans module.
        # A declared plan, however, must use the real public service or fail.
        from workbench.figure_plans import ensure_figures
        ensure_figures(run)
    if not planned and analysis_ready is not None:
        ready = dict(analysis_ready)
    else:
        from perf_footprint import memory_accounting
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        ready = {'seconds': time.perf_counter() - started,
                 'rss_bytes': rss if platform.system() == 'Darwin' else rss * 1024,
                 **memory_accounting(),
                 'run_bytes': sum(p.stat().st_size for p in run.rglob('*') if p.is_file())}
    rendered = run / 'figures/rendered.json'
    rendering = json.loads(rendered.read_text()) if rendered.exists() else {}
    index = json.loads((run / 'artifacts_index.json').read_text())
    records = [row for row in index['artifacts'] if row.get('artifact_type') == 'figure']
    figures = sorted(str(row['artifact_id']) for row in records)
    error = rendering.get('error')
    if planned and not rendered.exists():
        error = 'planned_figures_not_materialized'
    if not figures:
        error = error or 'no_registered_figures'
    if rendered.exists() and sorted(rendering.get('figures', [])) != figures:
        error = error or 'rendered_and_registered_figures_differ'
    for record in records:
        path = run / str(record.get('path', ''))
        if (not path.resolve().is_relative_to(run.resolve()) or path.is_symlink()
                or not path.is_file() or path.stat().st_size <= 0):
            error = error or 'figure_file_missing_or_empty'
        elif not record.get('sha256') or source_digest(path) != record['sha256']:
            error = error or 'figure_file_digest_mismatch'
    return {'status': 'failed' if error else 'completed', 'error': error,
            'mode': 'deferred_materialized' if planned else 'eager_registered',
            'requirements': 'standard analysis outputs plus all planned figures; extra report export not requested',
            **ready,
            'figure_count': len(figures), 'figure_artifact_ids': figures}


def family_run(case, out, *, manifest, trace_memory=False, allow_low_space=False, estimation_engine='', request_figures=False):
    import json
    import resource
    import platform
    # Parent validates the file digest once, then checks identity per worker. Do not re-read the
    # source or generate any observations in this measured process.
    payload = json.loads(manifest.read_text())
    source, kwargs, n = registered_source(payload), payload['kwargs'], payload['rows']
    if case != payload['case']:
        raise ValueError('manifest_case_mismatch')
    require_space(out.parent, allow_low_space=allow_low_space)
    out.mkdir(parents=True, exist_ok=False)
    if trace_memory:
        import tracemalloc
        tracemalloc.start()
    project = create_project(out, 'benchmark')
    if estimation_engine:
        kwargs = {**kwargs, 'estimation_engine': estimation_engine}
    started = time.perf_counter()
    outcome = run_workflow(project.root, [source], mode='auto', **kwargs)
    elapsed = time.perf_counter()-started
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    from perf_footprint import memory_accounting
    accounting = memory_accounting()
    traced_peak = None
    if trace_memory:
        traced_peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    run = project.root / 'runs' / outcome['run_id']
    primary_id = {'ols': 'ols_1', 'panel': 'panel_ols_1', 'iv': 'iv_2sls_1', 'did': 'did_1', 'wide': 'ols_1', 'cox': 'survival_cox_1'}[case]
    packet_path = run / 'model_results' / f'{primary_id}.json'
    packet = json.loads(packet_path.read_text()) if packet_path.exists() else {}
    analysis_bytes = sum(p.stat().st_size for p in run.rglob('*') if p.is_file())
    analysis_ready = {'seconds': elapsed, 'rss_bytes': rss if platform.system() == 'Darwin' else rss*1024,
                      **accounting, 'run_bytes': analysis_bytes}
    delivery = requested_figure_delivery(run, started=started, requested=request_figures,
                                        analysis_ready=analysis_ready)
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
    signature_errors = []
    for section, capture in (
        ('inference_kernel', lambda: primary_inference_signature(run, primary_id)),
        ('statistical_tests', lambda: statistical_tests_signature(run, case=case)),
    ):
        try:
            signature[section] = bits(capture())
        except (OSError, ValueError, KeyError, TypeError) as error:
            signature_errors.append(f'{section}: {type(error).__name__}: {error}')
    signature_error = 'not_comparable: ' + '; '.join(signature_errors) if signature_errors else None
    result = {'case': case, 'rows': n, 'status': outcome['status'], 'seconds': elapsed,
              'allow_low_space_this_run': allow_low_space,
              'input_sha256': payload['sha256'],
              'measurement_scope': 'fresh_worker_opt_in_fast_engine' if estimation_engine else 'fresh_worker_default_product_path',
              'default_product_path': not estimation_engine, 'estimation_engine': estimation_engine or 'reference',
              'input_io': 'unmodified_product_writes', 'timing_instrumentation': 'tracemalloc' if trace_memory else 'none',
              'time_acceptance_eligible': not trace_memory,
              'tracemalloc_peak_bytes': traced_peak,
              'ru_maxrss': rss, 'rss_bytes': rss if platform.system() == 'Darwin' else rss*1024,
              **accounting, 'run_bytes': analysis_bytes,
              'analysis_ready': analysis_ready,
              'requested_delivery': delivery,
              'numeric_signature': signature, 'numeric_signature_error': signature_error, 'run_root': str(run)}
    if case == 'iv':
        result['engine_used'] = packet.get('engine')
        try:
            result['acceptance_signature'] = iv_acceptance_signature(run, packet)
        except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
            result['acceptance_signature_error'] = f'{type(exc).__name__}: {exc}'
    (out / 'metrics.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({k:v for k,v in result.items() if k not in {'numeric_signature', 'acceptance_signature'}}), flush=True)
    return 0 if outcome['status'] == 'completed' and delivery['status'] != 'failed' else 1


RESOURCE_METRICS = ('seconds', 'rss_bytes', 'run_bytes')
COMPARISON_METRICS = RESOURCE_METRICS + tuple('delivery_'+key for key in RESOURCE_METRICS)
# footprint: kernel peak phys_footprint (perf_footprint.py), the gate's memory metric since the
# user's 2026-11-09 decision. rss: ru_maxrss, recorded and evaluated beside it as a reference.
MEMORY_METRICS = {'rss': 'rss_bytes', 'footprint': 'footprint_bytes'}
GATE_MEMORY, REFERENCE_MEMORY = 'footprint', 'rss'
# Bump the version whenever a rule below changes; it is part of every A/B evidence key.
# 1: ru_maxrss gate. 2: footprint gate, RSS reference (2026-11-09).
THRESHOLDS = {'version': 2, 'memory_metric': GATE_MEMORY, 'reference_memory_metric': REFERENCE_MEMORY,
              'resource_ratio_limit': 1.05, 'noise_limit': .05, 'calibration_runs': 5, 'pairs': 5}


def resource_metrics(memory='rss'):
    resource = ('seconds', MEMORY_METRICS[memory], 'run_bytes')
    return resource + tuple('delivery_'+key for key in resource)
AB_ORDER = ['A1', 'B1', 'B2', 'A2', 'A3', 'B3', 'B4', 'A4', 'A5', 'B5']


def product_sources(repo):
    """Freeze untracked native/product code too; a Git patch alone misses it."""
    import json
    suffixes = {'.py', '.rs', '.cpp', '.cc', '.c', '.h', '.hpp', '.toml', '.lock',
                '.j2', '.jinja2', '.html', '.css', '.json'}
    paths = {path for directory in ('backend', 'native') for path in (repo/directory).rglob('*')
             if path.is_file() and path.suffix in suffixes
             and not {'target', '__pycache__'}.intersection(path.relative_to(repo).parts)}
    for output in (repo/'local').glob('native-*'):
        paths.update(path for path in output.glob('*') if path.is_file()
                     and (path.suffix in {'.so', '.dylib', '.dll'} or path.match('build-manifest*.json')))
        paths.update(path for path in (output/'target/release').glob('arboris-engine*') if path.is_file())
        for manifest in output.glob('build-manifest*.json'):
            for name in json.loads(manifest.read_text()).get('artifacts', {}):
                path = output/name
                if not path.resolve().is_relative_to(output.resolve()) or not path.is_file():
                    raise ValueError('native_manifest_artifact_missing_or_outside_output')
                paths.add(path)
    return {str(path.relative_to(repo)): source_digest(path) for path in sorted(paths)}


def build_identity(repo):
    """Current builds must verify all variants; legacy is only hash evidence."""
    if not (repo/'backend/workbench/native_build.py').exists():
        return {'kind': 'legacy_source_and_artifact_hash_only'}
    from workbench.native_build import MODULES, variants, verify_build
    records = {f'{name}:{variant}': verify_build(repo/'native'/name, repo/'local'/output, variant=variant)
               for name, (output, *_) in MODULES.items() for variant in variants(repo/'native'/name)}
    return {'kind': 'verified_native_manifests', 'variants': records}


def baseline_source_state(repo):
    """HEAD identifies v1.9.0 only when its actual product/native tree is clean."""
    import subprocess
    state = subprocess.check_output(['git', 'status', '--porcelain=v1', '--untracked-files=all',
                                     '--', 'backend', 'native'], cwd=repo, text=True)
    if state.strip():
        raise SystemExit('Baseline backend/native must be clean at the pinned revision: '+state)
    return {'git_status': state}


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
    import math
    return bool(noise) and all(math.isfinite(v) and 0 <= v < .05 for v in noise.values())


def evaluate_ab_case(case, calibration, records, *, trace_memory=False, memory=GATE_MEMORY):
    """Fixed acceptance rules; invalid/missing observations cannot enter a median."""
    import math
    import statistics
    misses, medians, budgets, noise = [], {}, {}, {}
    groups = {'calibration': calibration, 'baseline_pairs': records['A'],
              'all_baseline': calibration+records['A'], 'candidate': records['B']}
    rows = calibration+records['A']+records['B']
    comparison = resource_metrics(memory)
    keys = comparison+(('tracemalloc_peak_bytes',) if trace_memory else ())
    def positive(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0
    def finite(value):
        if isinstance(value, dict):
            if 'nonfinite' in value:
                return False
            if 'binary64' in value:
                try:
                    return len(value) == 1 and math.isfinite(float.fromhex(value['binary64']))
                except (ValueError, TypeError):
                    return False
            return all(finite(v) for v in value.values())
        if isinstance(value, list):
            return all(finite(v) for v in value)
        return not isinstance(value, float) or math.isfinite(value)
    def number(value):
        try:
            return float.fromhex(value['binary64']) if isinstance(value, dict) else float(value)
        except (KeyError, TypeError, ValueError):
            return math.nan
    signatures, figure_sets = [], []
    for row in rows:
        delivery = row.get('requested_delivery')
        delivery = delivery if isinstance(delivery, dict) else {}
        row_metrics = {**{k: (delivery.get(k[len('delivery_'):]) if k.startswith('delivery_') else row.get(k))
                          for k in comparison},
                       'tracemalloc_peak_bytes': row.get('tracemalloc_peak_bytes')}
        row['_comparison_metrics'] = row_metrics
        if any(not positive(row_metrics[k]) for k in keys):
            misses.append('invalid_resource_metrics')
        if row.get('status') != 'completed' or row.get('returncode') != 0:
            misses.append('worker_failed')
        if not isinstance(row.get('host_monitor'), dict) or row['host_monitor'].get('valid') is not True:
            misses.append('host_monitor')
        figures = delivery.get('figure_artifact_ids')
        if (delivery.get('status') != 'completed' or not isinstance(figures, list) or not figures
                or not all(isinstance(v, str) and v for v in figures)
                or len(set(figures)) != len(figures) or delivery.get('figure_count') != len(figures)):
            misses.append('requested_delivery')
        else:
            figure_sets.append(sorted(figures))
        sig = row.get('numeric_signature', {})
        try:
            statistical_signature_payloads(sig.get('statistical_tests'), case=case)
        except (AttributeError, ValueError, TypeError):
            misses.append('invalid_statistical_tests_signature')
        coeff = sig.get('coefficients') if isinstance(sig, dict) else None
        if (not isinstance(coeff, dict) or not coeff or not finite(sig)
                or not positive(number(sig.get('nobs')))
                or any(not isinstance(v, dict) or not math.isfinite(number(v.get('estimate')))
                       or not positive(number(v.get('std_error')))
                       or any(k not in v or not math.isfinite(number(v[k])) for k in ('p_value', 'ci_lower', 'ci_upper'))
                       or not 0 <= number(v['p_value']) <= 1 for v in coeff.values())):
            misses.append('invalid_numeric_signature')
        kernel = sig.get('inference_kernel', {}) if isinstance(sig, dict) else {}
        try:
            names, params, cov = kernel['param_names'], kernel['params'], kernel['vcov']
            if (not set(INFERENCE_FIELDS) <= kernel.keys() or kernel['vcov_scope'] != 'full'
                    or not names or len(set(names)) != len(names) or set(names) != set(coeff)
                    or kernel['vcov_param_names'] != names or len(params) != len(names)
                    or not all(math.isfinite(number(v)) for v in params)
                    or len(cov) != len(names) or any(len(r) != len(names) for r in cov)
                    or not all(math.isfinite(number(v)) for r in cov for v in r)
                    or any(not positive(number(cov[i][i])) for i in range(len(names)))
                    or number(kernel['nobs']) != number(sig['nobs'])
                    or kernel['reference_distribution'] not in {'t', 'z'}
                    or kernel['df_method'] not in {'residual', 'clusters_minus_one', 'design', 'design_minus_p', 'asymptotic'}
                    or kernel['weights'] not in {'none', 'frequency', 'analysis', 'sampling'}
                    or (kernel['reference_distribution'] == 't' and not positive(number(kernel['df_resid'])))
                    or not isinstance(kernel['unavailable'], dict)):
                misses.append('invalid_inference_kernel')
        except (KeyError, TypeError, ValueError):
            misses.append('invalid_inference_kernel')
        if row.get('numeric_signature_error'):
            misses.append('numeric_signature_capture')
        signatures.append(sig)
    if len(calibration) != 5 or any(len(records[k]) != 5 for k in 'AB'):
        misses.append('fixed_five_calibration_and_pairs_required')
    if not signatures or not signatures[0] or any(sig != signatures[0] for sig in signatures):
        misses.append('numeric_bits')
    if len(figure_sets) != len(rows) or any(figures != figure_sets[0] for figures in figure_sets):
        misses.append('figure_requirements_differ')
    if 'invalid_resource_metrics' not in misses and all(len(runs) >= 5 for runs in groups.values()):
        for name, runs in groups.items():
            noise[name] = baseline_noise([r['_comparison_metrics'] for r in runs], metrics=keys)
            # Traced seconds remain diagnostic; memory is mandatory in both modes.
            accepted = {k: v for k, v in noise[name].items() if not (trace_memory and k.endswith('seconds'))}
            if not noise_accepted(accepted):
                misses.append('measurement_noise:'+name)
        medians = {lane: {key: statistics.median(r['_comparison_metrics'][key] for r in runs) for key in keys}
                   for lane, runs in records.items()}
        budgets = {key: medians['A'][key]*1.05 for key in keys if not (trace_memory and key.endswith('seconds'))}
        cap = None if trace_memory else {'ols': OLS_SECONDS_CAP, 'panel': 12.2, 'iv': 15.1}.get(case)
        if cap is not None:
            budgets['seconds'] = min(budgets['seconds'], cap)
            budgets['delivery_seconds'] = min(budgets['delivery_seconds'], cap)
        misses.extend(key for key, limit in budgets.items() if medians['B'][key] > limit)
    for row in rows:
        row.pop('_comparison_metrics', None)
    return {'failed': sorted(set(misses)), 'noise': noise, 'medians': medians, 'budgets': budgets,
            'ratios': {key: medians['B'][key]/medians['A'][key] for key in keys} if medians else {},
            'absolute_seconds_cap': None if trace_memory else {'ols': OLS_SECONDS_CAP, 'panel': 12.2, 'iv': 15.1}.get(case),
            'memory_metric': f'{memory}_and_tracemalloc' if trace_memory else memory}


def idle_processes(out):
    require_idle()


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
    parser.add_argument('--attribution-baseline-sha',
                        help='explicit exact pre-native baseline SHA; labels attribution separately from the v1.9.0 regression gate')
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
    v190_sha = subprocess.check_output(['git','rev-parse','v1.9.0^{commit}'], cwd=candidate,text=True).strip()
    expected_baseline = args.attribution_baseline_sha or v190_sha
    if revisions['baseline'] != expected_baseline:
        raise SystemExit('Baseline must match the exact attribution SHA' if args.attribution_baseline_sha else 'Baseline must be exact v1.9.0')
    comparison_kind = 'pre_native_attribution' if args.attribution_baseline_sha else 'v1.9.0_regression'
    baseline_state = baseline_source_state(baseline)
    repos = {'baseline': baseline, 'candidate': candidate}
    sources = {name: product_sources(repo) for name, repo in repos.items()}
    builds = {name: build_identity(repo) for name, repo in repos.items()}
    difference = subprocess.check_output(['git','diff','--binary','HEAD'], cwd=candidate)
    (out/'candidate.patch').write_bytes(difference)
    shared_sources = {str(path): source_digest(path) for path in
                      (Path(__file__).resolve(), Path(__file__).with_name('perf_evidence.py').resolve(),
                       Path(__file__).with_name('perf_host.py').resolve())}
    report = {'measurement_version': 7, 'comparison_kind':comparison_kind,
              'v1.9.0_regression_gate':not bool(args.attribution_baseline_sha),
              'expected_baseline_sha':expected_baseline, 'v1.9.0_sha':v190_sha,
              'baseline_product_git_state':baseline_state,
              'candidate_diff_sha256': hashlib.sha256(difference).hexdigest(),
              'driver_sha256': source_digest(Path(__file__)),
              'thread_environment': {key: os.environ.get(key) for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','VECLIB_MAXIMUM_THREADS','MKL_NUM_THREADS','PYTHONHASHSEED')},
              'revisions': revisions, 'order': AB_ORDER, 'calibration_count': 5, 'pair_count': 5,
              'noise_definition': 'sample_standard_deviation/median < 0.05 for every lane/metric; all observations',
              'multiplier':1.05, 'worker_timeout_seconds':120,
              'delivery_scope':'same registered figures verified by IDs, nonempty files and SHA256; public materialization when planned',
              'trace_memory':args.trace_memory, 'time_acceptance_eligible':not args.trace_memory,
              'default_product_path':True, 'worker_environment':'inherited unchanged',
              'inputs_policy':'one_fixed_CSV_per_case; product snapshots/uploads written normally',
              'numeric_comparison_scope':'exact primary coefficient/SE/p/CI/fit, complete small persisted kernel and all published statistical_tests JSON fields; seven required packets, advanced evidence mandatory for ols/wide or when registered; only reviewed rank computation engine/reason text omitted; all 15 workers',
              'retention':'one_active_tree; durable_verified_JSONL_then_removal; one_archive_per_case_release',
              'minimum_free_bytes':MIN_FREE_BYTES, 'allow_low_space_this_run':args.allow_low_space_this_run,
              'source_sha256':sources, 'native_build':builds, 'shared_source_sha256':shared_sources, 'cases':{},
              'thresholds': THRESHOLDS,
              'evidence_key': {name: evidence_key(repo, python=sys.executable, scope=f'perf:1m-ab:{name}',
                                                  test_selection={'cases': args.cases, 'trace_memory': args.trace_memory},
                                                  thresholds=THRESHOLDS)
                               for name, repo in repos.items()}}
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
        input_guard = dict(source_identity(Path(payload['source'])), ctime_ns=Path(payload['source']).stat().st_ctime_ns)
        manifest_sha = source_digest(manifest)
        records, calibration = {'A':[], 'B':[]}, []
        case_report = {'calibration':calibration, 'raw':records, 'input':payload,
                       'input_guard':input_guard, 'measurement_manifest_sha256':manifest_sha}
        report['cases'][case] = case_report
        save()
        def frozen():
            if baseline_source_state(baseline) != baseline_state:
                raise SystemExit('Baseline product Git state changed; retain active evidence')
            if any(source_digest(Path(path)) != digest for path, digest in shared_sources.items()):
                raise SystemExit('Shared measurement source changed; retain active evidence')
            for name, repo in repos.items():
                if subprocess.check_output(['git','rev-parse','HEAD'], cwd=repo, text=True).strip() != revisions[name]:
                    raise SystemExit('Repository changed; retain active evidence')
                if product_sources(repo) != sources[name] or build_identity(repo) != builds[name]:
                    raise SystemExit('Product/native source, manifest or binary changed; retain active evidence')
            source = registered_source(payload)
            current = dict(source_identity(source), ctime_ns=source.stat().st_ctime_ns)
            if (current != input_guard or source_digest(manifest) != manifest_sha
                    or source_digest(canonical_manifest) != payload['canonical_manifest_sha256']):
                raise SystemExit('Registered input/manifest changed; retain active evidence')
        def run(label):
            free = require_space(out, allow_low_space=args.allow_low_space_this_run)
            idle_processes(out)
            frozen()
            if active.exists():
                raise SystemExit('Unrecorded active tree exists; refusing a second run')
            lane = 'baseline' if label.startswith('A') else 'candidate'
            command = [str(candidate/'.venv/bin/python'), str(driver), '--case',case,
                       '--out',str(active),'--manifest',str(manifest), '--request-figures']
            if args.trace_memory:
                command.append('--trace-memory')
            if args.allow_low_space_this_run:
                command.append('--allow-low-space-this-run')
            code, stdout, stderr, host = monitored_worker(command, out/'host'/f'{case}-{label}.jsonl',
                                                          cwd=repos[lane], timeout=120)
            active.mkdir(parents=True, exist_ok=True)
            (active/'stdout.log').write_text(stdout)
            (active/'stderr.log').write_text(stderr)
            frozen()
            try:
                value = json.loads((active/'metrics.json').read_text(), parse_constant=lambda v: {'nonfinite':v})
                if not isinstance(value, dict):
                    raise ValueError('metrics_object_required')
            except (OSError, ValueError) as error:
                value = dict(case=case, status='failed', run_root=str(active/'uncompleted'),
                             measurement_error=f'{type(error).__name__}: {error}')
            if value.get('status') == 'completed' and value.get('input_sha256') != payload['sha256']:
                value.update(status='failed', worker_input_sha256=value.get('input_sha256'),
                             measurement_error='worker_input_digest_mismatch')
            value.update(version_commit=revisions[lane], driver_sha256=report['driver_sha256'],
                         measurement_version=7, input_source=payload['source'], input_sha256=payload['sha256'],
                         free_before_bytes=free, returncode=code, label=label, host_monitor=host)
            value['retained_logs'] = retain_worker_logs(active, out/'logs'/f'{case}-{label}.logs')
            value['retention'] = finalize_active(active,ledger=ledger,record_id=f'{case}-{label}',metadata=value,
                                        archive_dir=out/'representatives',
                                        version=(('pre-native-'+expected_baseline[:12] if args.attribution_baseline_sha else 'v1.9.0')
                                                 if lane=='baseline' else 'v1.9.1'),case=case)
            if code or value.get('status') != 'completed' or not host.get('valid'):
                case_report.setdefault('failed_runs',[]).append(value)
                save()
                raise SystemExit(f'{case} {label} failed; evidence retained and active tree removed')
            print(f"{case} {label}: analysis={value.get('seconds')}s, delivery={value.get('requested_delivery', {}).get('seconds')}s; recorded then removed",flush=True)
            return value
        for index in range(1, 6):
            calibration.append(run(f'A0_{index:02}'))
            save()
        for label in AB_ORDER:
            records[label[0]].append(run(label))
            save()
        case_report.update(evaluate_ab_case(case, calibration, records, trace_memory=args.trace_memory,
                                            memory=GATE_MEMORY))
        case_report['reference_memory'] = evaluate_ab_case(case, calibration, records, memory=REFERENCE_MEMORY)
        gate_key = MEMORY_METRICS[GATE_MEMORY]
        if args.trace_memory and any(values.get(gate_key, 0) >= .05 for values in case_report['noise'].values()):
            if any(Path(path).suffix in {'.so', '.dylib', '.dll'} for inventory in sources.values() for path in inventory):
                case_report['failed'].append('native_workspace_unaccounted')
                case_report['memory_metric'] = 'unaccepted_native_workspace'
        save()
        failed.extend(f'{case}:{key}' for key in case_report['failed'])
    if source_tree(candidate)['sha256'] != report['evidence_key']['candidate']['source_tree']['sha256']:
        failed.append('evidence:source_tree_changed_during_run')
    report['failed'] = failed
    save()
    print(comparison_kind+': '+(('DEFAULT PATH MEMORY CHECKS PASS; traced time is diagnostic' if args.trace_memory else 'DEFAULT PATH CHECKS PASS') if not failed else 'FAIL '+', '.join(failed)),flush=True)
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
        parser.add_argument('--estimation-engine', default='', choices=['', 'reference', 'fast'])
        parser.add_argument('--request-figures', action='store_true', help='also measure delivery after the public figure request')
        args = parser.parse_args()
        return family_run(args.case, args.out.resolve(), manifest=args.manifest,
                          trace_memory=args.trace_memory, allow_low_space=args.allow_low_space_this_run,
                          estimation_engine='' if args.estimation_engine == 'reference' else args.estimation_engine,
                          request_figures=args.request_figures)
    return interactive_main()


if __name__ == '__main__':
    raise SystemExit(main())
