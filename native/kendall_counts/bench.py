"""Component triage only: public SciPy tau/p versus native counts plus tau/p.

Review/freeze this script before measuring. No default product path is connected.
Commands (use the existing .venv interpreter; no environment overrides):

  python native/kendall_counts/bench.py selftest
  python native/kendall_counts/bench.py prepare
  python native/kendall_counts/bench.py freeze --implementation legacy \\
    --source-manifest local/perf-evidence/kendall-source.json
  python native/kendall_counts/bench.py run --implementation legacy \\
    --source-manifest local/perf-evidence/kendall-source.json \\
    --out local/perf-evidence/kendall-component-YYYYMMDD

The explicit --allow-low-space-this-run flag applies only to a human-authorized
comparison and is frozen into its manifest; without it the 5GB floor remains.
Source manifests admit uncommitted code only by exact source/binary hashes and
ABI, versions, flags and input identity, checked before/after every worker.

Only selftest uses 10k temporary data, without timing or RSS observation. Prepare
creates the one fixed 1M CSV and checksum once; workers never generate/copy it.
Run first verifies bit-identical nondegenerate tau/p, then makes exactly five
baseline calibrations and five alternating A/B pairs in fresh processes. Both
workers import the same libraries before timing; timing covers read_csv, array
extraction/conversion, the full calculation and fsynced result output. Process
startup/import time is excluded; terminal wait4 RSS covers the entire worker.
Run exits 2 if baseline noise is not below 5%, retaining all raw evidence.

This is not an independent statistical oracle, general p-value certification,
Workbench default-path acceptance, the 8s gate, or a v1.9.0 resource comparison.

--trace-memory is a separate memory lane, never time acceptance. It adds the
process high-water of C++ owned-vector requested bytes to tracemalloc's peak.
Their sum is conservative even when the peaks occur at different times. Native
allocator metadata/sort stacks are outside this allocation-payload metric; the
reference's untraced C scratch is omitted, making the candidate budget stricter.
Raw RSS and its failed noise evidence remain independent of this memory lane.
--workload ols-pairs reuses the registered 1M OLS CSV and all ten default-auto
Kendall pairs across its five analysis columns, keeping their int64/float64
dtypes and exact zero/one p-values. It does not generate another input.
"""
from __future__ import annotations

import argparse
import importlib
import inspect
from itertools import combinations
import json
import os
from pathlib import Path
import shutil
import statistics
import struct
import subprocess
import sys
import sysconfig
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).resolve()
INPUT_DIR = ROOT / 'local/perf-inputs/kendall-counts'
ROWS = 1_000_000
SEED = 20261027
OLS_COLUMNS = ['wage', 'education', 'experience', 'female', 'hours']
sys.path.insert(0, str(ROOT / 'scripts'))
import perf_evidence as evidence  # noqa: E402


def save(path, value):
    """Exclusive, durable evidence creation; never overwrite an earlier result."""
    with Path(path).open('x', encoding='utf-8') as handle:
        json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())


def libraries(extension_dir):
    import numpy as np
    import pandas as pd
    import scipy
    from scipy import special, stats
    sys.path.insert(0, str(extension_dir))
    native = importlib.import_module('_kendall_counts')
    if scipy.__version__.split('.')[:2] != ['1', '18']:
        raise RuntimeError('this frozen comparison requires public SciPy 1.18.x')
    if Path(native.__file__).resolve().parent != extension_dir.resolve():
        raise RuntimeError('native module did not load from the requested directory')
    return np, pd, scipy, special, stats, native


def generate(directory, rows, *, allow_low_space=False):
    """Parent-only, fixed seed; ties fail rather than causing seed selection."""
    evidence.require_space(directory, allow_low_space=allow_low_space)
    import numpy as np
    import pandas as pd
    directory.mkdir(parents=True, exist_ok=True)
    csv, checksum, registration = (directory / name for name in ['input.csv', 'input.sha256', 'input.json'])
    if any(path.exists() for path in (csv, checksum, registration)):
        if not all(path.is_file() for path in (csv, checksum, registration)):
            raise RuntimeError('incomplete fixed input; preserve it for inspection')
        saved = json.loads(registration.read_text())
        if (saved['rows'] != rows or saved['seed'] != SEED
                or saved['sha256'] != checksum.read_text().strip()
                or saved['sha256'] != evidence.digest(csv)):
            raise RuntimeError('fixed input checksum mismatch')
        return csv
    rng = np.random.default_rng(SEED)
    x, y = rng.standard_normal((2, rows))
    if np.unique(x).size != rows or np.unique(y).size != rows:
        raise RuntimeError('fixed generated input has ties; do not tune the seed')
    with csv.open('x') as handle:
        pd.DataFrame({'x': x, 'y': y}).to_csv(handle, index=False, float_format='%.17g')
        handle.flush()
        os.fsync(handle.fileno())
    with checksum.open('x') as handle:
        handle.write(evidence.digest(csv) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    save(registration, {'rows': rows, 'seed': SEED, 'generator': 'numpy.default_rng.standard_normal',
                        'numpy': np.__version__, 'columns': ['x', 'y'], 'dtype': 'float64',
                        'generator_script_sha256': evidence.digest(SCRIPT), 'sha256': checksum.read_text().strip()})
    return csv


def arrays(csv, rows, np, pd, *, workload='random-pair'):
    columns = OLS_COLUMNS if workload == 'ols-pairs' else ['x', 'y']
    frame = pd.read_csv(csv, usecols=columns,
                        dtype=None if workload == 'ols-pairs' else np.float64,
                        float_precision='round_trip')
    if len(frame) != rows:
        raise ValueError(f'expected exactly {rows} rows')
    if workload == 'ols-pairs':
        if any(frame[name].dtype != (np.dtype('float64') if name in ('wage', 'hours')
                                    else np.dtype('int64')) for name in columns):
            raise ValueError('registered OLS column dtypes differ')
        return {name: np.ascontiguousarray(frame[name].to_numpy(copy=False)) for name in columns}
    return (np.ascontiguousarray(frame['x'].to_numpy(dtype=np.float64, copy=False)),
            np.ascontiguousarray(frame['y'].to_numpy(dtype=np.float64, copy=False)))


def numeric_result(tau, p, *, allow_boundary=False):
    tau, p = float(tau), float(p)
    valid_p = 0 <= p <= 1 if allow_boundary else 0 < p < 1
    if not (-1 <= tau <= 1 and valid_p):
        raise ValueError('tau/p outside the finite, nondegenerate comparison boundary')
    return {'tau': tau, 'p': p, 'binary64_hex': struct.pack('!dd', tau, p).hex()}


def calculate(lane, x, y, np, special, stats, native, *, implementation='legacy'):
    if lane == 'A':
        result = stats.kendalltau(x, y, variant='b', method='asymptotic',
                                  alternative='two-sided', nan_policy='raise')
        return numeric_result(result.statistic, result.pvalue)
    if implementation == 'product':
        # Import before timing in worker(), including the reference lane.
        from workbench import native_kendall
        result = native_kendall.evaluate(x, y, method='asymptotic', engine='native',
                                         alternative='two-sided', nan_policy='raise')
        return numeric_result(result.statistic, result.pvalue)
    counts = native.count(x, y)
    n = counts['n']
    if n != x.size or n < 10_000 or any(value for key, value in counts.items()
                                      if key not in {'n', 'discordant'}):
        raise ValueError('native tau/p reconstruction supports large no-tie data only')
    total = n * (n - 1) // 2
    if min(counts['discordant'], total - counts['discordant']) <= 1:
        raise ValueError('extreme ordering is outside this asymptotic triage case')
    score = total - 2 * counts['discordant']
    # Preserve the public SciPy 1.18 arithmetic order; do not replace the two
    # divisions by score/total, which can change the last binary64 bit.
    tau = np.minimum(1., max(-1., score / np.sqrt(total) / np.sqrt(total)))
    m = n * (n - 1.)
    variance = m * (2 * n + 5) / 18
    p = 2 * special.ndtr(-np.abs(score / np.sqrt(variance)))
    return numeric_result(tau, p)


def calculate_ols(lane, columns, stats):
    from workbench import native_kendall
    output = {}
    for left, right in combinations(OLS_COLUMNS, 2):
        if lane == 'A':
            result = stats.kendalltau(columns[left], columns[right])
        else:
            result = native_kendall.evaluate(columns[left], columns[right], engine='native')
        output[left + ':' + right] = numeric_result(result.statistic, result.pvalue,
                                                   allow_boundary=True)
    return output


def worker(args):
    np, pd, _, special, stats, native = libraries(args.extension_dir)
    if args.implementation == 'product':
        sys.path.insert(0, str(ROOT / 'backend'))
        importlib.import_module('workbench.native_kendall')._load_native()
    def get_arrays():
        return arrays(args.input, args.rows, np, pd, workload=args.workload)
    def evaluate(lane, inputs):
        if args.workload == 'ols-pairs':
            return calculate_ols(lane, inputs, stats)
        return calculate(lane, *inputs, np, special, stats, native,
                         implementation=args.implementation)
    if not args.measure:
        inputs = get_arrays()
        values = inputs.values() if args.workload == 'ols-pairs' else inputs
        if any(not np.isfinite(value).all() for value in values):
            raise ValueError('fixed input must be finite')
        if args.workload == 'random-pair' and any(np.unique(value).size != args.rows for value in inputs):
            raise ValueError('parsed CSV contains ties')
        a, b = evaluate('A', inputs), evaluate('B', inputs)
        save(args.output / 'verification.json', {'A': a, 'B': b, 'rows': args.rows})
        if a != b:
            raise ValueError('tau/p are not bit-identical; measurement is forbidden')
        return
    evidence.require_space(args.output, allow_low_space=args.allow_low_space_this_run)
    tracing = args.trace_memory
    if tracing:
        import tracemalloc
        tracemalloc.start()
    started = time.perf_counter()
    try:
        inputs = get_arrays()
        result = evaluate(args.lane, inputs)
        save(args.output / 'result.json', result)  # Same bytes/work for A and B.
    except Exception as error:
        elapsed = time.perf_counter() - started
        save(args.output / 'measurement.json', {'status': 'failed', 'seconds': elapsed,
                                               'error': f'{type(error).__name__}: {error}'})
        raise
    elapsed = time.perf_counter() - started
    workspace, traced_peak = None, None
    if tracing:
        workspace = native.workspace_bytes()
        traced_peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    save(args.output / 'measurement.json', {'status': 'completed', 'seconds': elapsed,
        'time_acceptance_eligible': not tracing, 'workspace_bytes': workspace,
        'tracemalloc_peak_bytes': traced_peak,
        'conservative_allocation_peak_bytes': traced_peak + workspace if tracing else None})


def launch(directory, csv, rows, extension_dir, *, lane=None, implementation='legacy',
           allow_low_space=False, trace_memory=False, workload='random-pair'):
    command = [sys.executable, str(SCRIPT), '_worker', '--input', str(csv), '--rows', str(rows),
               '--extension-dir', str(extension_dir), '--output', str(directory),
               '--implementation', implementation, '--workload', workload]
    if allow_low_space:
        command += ['--allow-low-space-this-run']
    if trace_memory:
        command += ['--trace-memory']
    if lane:
        command += ['--measure', '--lane', lane]
    with (directory / 'worker.log').open('x') as log:
        if lane:
            child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            _, status, usage = os.wait4(child.pid, 0)
            child.returncode = os.waitstatus_to_exitcode(status)
            return child.returncode, usage.ru_maxrss, command
        completed = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=False)
        return completed.returncode, None, command


def identity(path):
    value = path.stat()
    return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns]


def provenance(extension_dir):
    _, _, scipy, _, stats, native = libraries(extension_dir)
    sources = [SCRIPT, SCRIPT.with_name('kendall_counts.cpp'), SCRIPT.with_name('build.py'),
               SCRIPT.with_name('candidate.py'), SCRIPT.with_name('SCIPY_LICENSE.txt'),
               ROOT / 'backend/workbench/native_kendall.py',
               ROOT / 'scripts/perf_evidence.py', Path(native.__file__).resolve(),
               Path(importlib.import_module('scipy.stats._stats').__file__).resolve(),
               Path(importlib.import_module('scipy.special._ufuncs').__file__).resolve(),
               Path(inspect.getsourcefile(inspect.unwrap(stats.kendalltau))).resolve()]
    import numpy, pandas
    return {'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'native_module': str(Path(native.__file__).resolve()),
            'source_sha256': {str(path): evidence.digest(path) for path in sources},
            'python': sys.version, 'executable': sys.executable,
            'build_abi': {key: sysconfig.get_config_var(key) for key in
                          ['SOABI', 'EXT_SUFFIX', 'LDCXXSHARED', 'CC', 'CXX']},
            'build_flags': ['-std=c++17', '-O3', '-Wall', '-Wextra', '-Werror', '-fPIC'],
            'build_flags_scope': 'declared by the frozen build.py; binary SHA identifies the actual artifact',
            'versions': {'scipy': scipy.__version__, 'numpy': numpy.__version__, 'pandas': pandas.__version__},
            'thread_environment': {key: os.environ.get(key) for key in
                ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'MKL_NUM_THREADS', 'PYTHONHASHSEED']}}


def fixed_input():
    csv = INPUT_DIR / 'input.csv'
    sha = (INPUT_DIR / 'input.sha256').read_text().strip()
    registration = json.loads((INPUT_DIR / 'input.json').read_text())
    # The stored generator SHA is historical provenance, not the current
    # measurement-driver SHA. Never rewrite/regenerate the registered input
    # merely because measurement/retention code was changed.
    if (registration['rows'] != ROWS or registration['seed'] != SEED
            or registration['generator'] != 'numpy.default_rng.standard_normal'
            or registration['columns'] != ['x', 'y'] or registration['dtype'] != 'float64'
            or registration['sha256'] != sha or evidence.digest(csv) != sha):
        raise ValueError('fixed input checksum or registration mismatch')
    return csv, sha, registration


def workload_input(workload):
    if workload == 'random-pair':
        return fixed_input()
    registration = json.loads((ROOT / 'local/perf-inputs/ols/source.json').read_text())
    csv = Path(registration['source'])
    sha = registration['sha256']
    if (registration['case'] != 'ols' or registration['rows'] != ROWS
            or sha != 'd7b25e65fa1875e205a31354feba22f5a9988a2647fb20fd232825ce2e9e595d'
            or registration['kwargs']['y'] != OLS_COLUMNS[0]
            or registration['kwargs']['x'] != OLS_COLUMNS[1:]
            or evidence.digest(csv) != sha):
        raise ValueError('registered OLS input differs; do not regenerate/copy it')
    return csv, sha, registration


def freeze(args):
    workload = getattr(args, 'workload', 'random-pair')
    csv, sha, registration = workload_input(workload)
    target = args.source_manifest.resolve()
    if not target.is_relative_to(ROOT / 'local'):
        raise ValueError('source manifest must be below local/')
    target.parent.mkdir(parents=True, exist_ok=True)
    save(target, {'schema_version': 1, 'kind': 'native-kendall-component',
        'implementation': args.implementation,
        'workload': workload,
        'trace_memory': getattr(args, 'trace_memory', False),
        'allow_low_space_this_run': args.allow_low_space_this_run,
        'input': {'path': str(csv), 'sha256': sha, 'registration': registration},
        'provenance': provenance(args.extension_dir)})
    print(json.dumps({'source_manifest': str(target), 'sha256': evidence.digest(target)}, sort_keys=True))


def idle_snapshot(path):
    text = subprocess.check_output(['ps', '-Ao', 'pid=,ppid=,command='], text=True)
    competing, checked = [], 0
    for line in text.splitlines():
        pid, ppid, command = line.strip().split(maxsplit=2)
        checked += 1
        if int(pid) in {os.getpid(), os.getppid()} or 'ps -Ao' in command:
            continue
        category = ('test' if any(token in command for token in ['-m pytest', '/pytest ', 'vitest'])
                    else 'benchmark' if any(token in command for token in
                        ['scripts/perf_1m.py', 'bench_families.py', str(SCRIPT),
                         'native/kendall_counts/bench.py']) else None)
        if category:
            competing.append({'pid': int(pid), 'ppid': int(ppid), 'category': category})
    # Inspect command lines in memory only: arguments can contain credentials.
    save(path, {'checked_count': checked, 'processes': competing})
    if competing:
        raise RuntimeError('other tests/benchmarks active; inspect the sanitized process snapshot')


def retain(active, out, label, metadata):
    """Reuse the authorized journal-before-remove primitives, not workflow fakes."""
    if active != out / 'active' or active.is_symlink():
        raise ValueError('only this component active tree may be finalized')
    ledger = out / 'measurements.jsonl'
    record = evidence.snapshot(active, record_id=label, metadata=metadata, kind='component_run')
    evidence.append_record(ledger, record)
    saved = [row for row in evidence.read_records(ledger) if row['record_id'] == label]
    if len(saved) != 1:
        raise ValueError('component journal record missing')
    evidence.verify_tree_records(active, saved)
    archive = out / 'representatives' / f"{metadata['lane']}.tar.gz"
    archive_manifest = archive.parent / f"{metadata['lane']}.json"
    archived = None
    if metadata['status'] == 'completed':
        if not archive.exists():
            archived = evidence.archive_verified(active, archive, record['files'])
            save(archive_manifest, {**archived, 'origin_record_id': label})
        else:
            archived = json.loads(archive_manifest.read_text())
            if archived['sha256'] != evidence.digest(archive):
                raise ValueError('representative archive changed')
        shutil.rmtree(active)
    # Failed active trees stay intact; no automatic retry or evidence deletion.
    return {'record_id': label, 'file_count': record['file_count'], 'tree_bytes': record['tree_bytes'],
            'archive': archived}


def run(args):
    if sys.platform not in {'darwin', 'linux'} or not hasattr(os, 'wait4'):
        raise RuntimeError('whole-worker RSS observation requires macOS/Linux wait4')
    out = args.out.resolve()
    parent = ROOT / 'local/perf-evidence'
    if not out.is_relative_to(parent) or out == parent or out.exists():
        raise ValueError('use a fresh output directory below local/perf-evidence')
    evidence.require_space(parent, allow_low_space=args.allow_low_space_this_run)
    original = provenance(args.extension_dir)
    tracing = getattr(args, 'trace_memory', False)
    workload = getattr(args, 'workload', 'random-pair')
    if args.frozen_commit and original['git_commit'] != args.frozen_commit:
        raise ValueError('HEAD differs from the explicitly frozen commit')
    native_file = Path(original['native_module'])
    if args.native_sha256 and evidence.digest(native_file) != args.native_sha256:
        raise ValueError('native binary differs from the explicitly frozen SHA256')
    csv, sha, registration = workload_input(workload)
    manifest_path = args.source_manifest.resolve()
    manifest = json.loads(manifest_path.read_text())
    manifest_identity = identity(manifest_path)
    manifest_sha = evidence.digest(manifest_path)
    if manifest != {'schema_version': 1, 'kind': 'native-kendall-component',
            'implementation': args.implementation,
            'workload': workload,
            'trace_memory': tracing,
            'allow_low_space_this_run': args.allow_low_space_this_run,
            'input': {'path': str(csv), 'sha256': sha, 'registration': registration},
            'provenance': original}:
        raise ValueError('explicit frozen source manifest differs from current sources/ABI/input/options')

    def check_manifest():
        if (identity(manifest_path) != manifest_identity or evidence.digest(manifest_path) != manifest_sha):
            raise ValueError('frozen source manifest changed during the comparison')

    input_identity = identity(csv)
    out.mkdir(parents=True)
    report = {'scope': 'component_triage_only', 'default_product_path': False,
        'statistical_oracle': False,
        'p_value_scope': 'registered_ols_all_ten_auto_tau_b_pairs' if workload == 'ols-pairs'
                         else 'large_finite_no_tie_asymptotic_only',
        'lanes': ({'A': 'public scipy.stats.kendalltau; all ten registered OLS auto tau-b pairs',
                   'B': 'typed native counts + SciPy-order tied tau-b/p; all ten pairs'}
                  if workload == 'ols-pairs' else {
                   'A': 'public scipy.stats.kendalltau; asymptotic tau-b, two-sided, nan_policy=raise',
                   'B': 'native counts + no-tie tau-b/variance + public scipy.special.ndtr'}),
        'input': {**registration, 'path': str(csv), 'sha256': sha,
                  'columns': OLS_COLUMNS if workload == 'ols-pairs' else ['x', 'y'],
                  'independent_columns': workload != 'ols-pairs'},
        'provenance': original, 'startup_and_imports_timed': False,
        'source_manifest': {'path': str(manifest_path), 'sha256': manifest_sha, 'document': manifest},
        'implementation': args.implementation,
        'workload': workload,
        'trace_memory': tracing, 'time_acceptance_eligible': not tracing,
        'memory_metric': 'traced_peak_plus_native_vector_peak' if tracing else 'whole_worker_rss',
        'memory_omissions': ['allocator_metadata', 'std_sort_stack', 'reference_untraced_c_scratch'],
        'allow_low_space_this_run': args.allow_low_space_this_run,
        'elapsed_scope': 'read_csv + original_dtype_contiguous_arrays + full_tau_p + fsynced_identical_result_output',
        'pair_count': 10 if workload == 'ols-pairs' else 1,
        'rss_scope': 'entire_fresh_worker_from_terminal_wait4', 'worker_environment': 'inherited unchanged',
        'retention': 'component files only; verified journal before cleanup; one representative per lane',
        'noise_definition': 'sample_standard_deviation/median; no sample exclusion or tolerance widening',
        'minimum_free_bytes': evidence.MIN_FREE_BYTES, 'runs': [], 'status': 'incomplete'}
    try:
        if any(parent.rglob('active')):
            raise RuntimeError('an active benchmark tree already exists; verification not started')
        idle_snapshot(out / 'processes-preflight.json')
        verification = out / 'verification'
        verification.mkdir()
        check_manifest()
        code, _, _ = launch(verification, csv, ROWS, args.extension_dir,
            implementation=args.implementation, allow_low_space=args.allow_low_space_this_run,
            trace_memory=tracing, workload=workload)
        check_manifest()
        if code:
            raise RuntimeError('functional verification failed; no measurements started')
        expected = json.loads((verification / 'verification.json').read_text())['A']
        report['verified_result'] = expected
        order = [(f'calibration-A{i}', 'A') for i in range(1, 6)]
        order += [(f'{lane}{i}', lane) for i in range(1, 6) for lane in 'AB']
        for label, lane in order:
            free = evidence.require_space(out, allow_low_space=args.allow_low_space_this_run)
            if any(parent.rglob('active')):
                raise RuntimeError('an active benchmark tree already exists; refusing another')
            active = out / 'active'
            active.mkdir()
            metadata = {'label': label, 'lane': lane, 'status': 'failed', 'seconds': None,
                        'free_before_bytes': free, 'provenance': original, 'input_sha256': sha}
            try:
                idle_snapshot(active / 'processes-before.json')
                check_manifest()
                if provenance(args.extension_dir) != original or identity(csv) != input_identity:
                    raise ValueError('source, binary, environment or fixed input identity changed')
                code, rss, command = launch(active, csv, ROWS, args.extension_dir, lane=lane,
                    implementation=args.implementation, allow_low_space=args.allow_low_space_this_run,
                    trace_memory=tracing, workload=workload)
                metadata.update(command=command, returncode=code, ru_maxrss=rss,
                    rss_bytes=rss if sys.platform == 'darwin' else rss * 1024)
                if (active / 'measurement.json').is_file():
                    metadata.update(json.loads((active / 'measurement.json').read_text()))
                idle_snapshot(active / 'processes-after.json')
                check_manifest()
                if provenance(args.extension_dir) != original or identity(csv) != input_identity:
                    raise ValueError('measurement identities changed')
                actual = json.loads((active / 'result.json').read_text()) if code == 0 else None
                metadata['result'] = actual
                if code or actual != expected:
                    raise ValueError('worker failed or tau/p bits changed; do not continue')
            except BaseException as error:
                metadata.update(status='failed', error=f'{type(error).__name__}: {error}')
                raise
            finally:
                metadata['retention'] = retain(active, out, label, metadata)
                report['runs'].append(metadata)
        calibration = report['runs'][:5]
        paired = report['runs'][5:]
        baseline = [row for row in paired if row['lane'] == 'A']
        candidate = [row for row in paired if row['lane'] == 'B']
        def noise(rows):
            return {key: statistics.stdev(row[key] for row in rows) / statistics.median(row[key] for row in rows)
                    for key in ['seconds', 'rss_bytes'] +
                    (['tracemalloc_peak_bytes', 'conservative_allocation_peak_bytes'] if tracing else [])}
        report['calibration_noise'] = noise(calibration)
        report['all_baseline_noise'] = noise(calibration + baseline)
        acceptance_noise_keys = ['conservative_allocation_peak_bytes'] if tracing else ['seconds', 'rss_bytes']
        report['noise_below_five_percent'] = all(values[key] < .05 for values in
            [report['calibration_noise'], report['all_baseline_noise']] for key in acceptance_noise_keys)
        report['native_rss_noise_below_five_percent'] = all(values['rss_bytes'] < .05 for values in
            [report['calibration_noise'], report['all_baseline_noise']])
        report['candidate_over_baseline_median_ratio'] = {key:
            statistics.median(row[key] for row in candidate) / statistics.median(row[key] for row in baseline)
            for key in ['seconds', 'rss_bytes'] +
                (['tracemalloc_peak_bytes', 'conservative_allocation_peak_bytes'] if tracing else [])}
        report['paired_time_ratios'] = [b['seconds'] / a['seconds']
                                       for a, b in zip(baseline, candidate)]
        report['positive_untraced_time_evidence'] = (
            not tracing
            and all(values['seconds'] < .05 for values in
                    [report['calibration_noise'], report['all_baseline_noise']])
            and all(ratio < 1 for ratio in report['paired_time_ratios'])
            and report['candidate_over_baseline_median_ratio']['seconds']
                < 1 - report['calibration_noise']['seconds'])
        report['stable_component_time_benefit'] = (
            not tracing and report['noise_below_five_percent']
            and all(ratio < 1 for ratio in report['paired_time_ratios'])
            and report['candidate_over_baseline_median_ratio']['seconds']
                < 1 - report['calibration_noise']['seconds'])
        report['component_rss_within_105_percent'] = (
            report['candidate_over_baseline_median_ratio']['rss_bytes'] <= 1.05)
        if tracing:
            report['workspace_bytes_by_lane'] = {
                'A': [row['workspace_bytes'] for row in baseline],
                'B': [row['workspace_bytes'] for row in candidate]}
            within = report['candidate_over_baseline_median_ratio']['conservative_allocation_peak_bytes'] <= 1.05
            report['status'] = ('memory_component_comparison_only' if within else 'component_memory_regression') \
                if report['noise_below_five_percent'] else 'uncertified_memory_noise'
        else:
            report['status'] = 'component_comparison_only' if report['noise_below_five_percent'] else 'uncertified_noise'
    except BaseException as error:
        report.update(status='failed', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        save(out / 'summary.json', report)
    return 0 if report['status'] in ('component_comparison_only', 'memory_component_comparison_only') else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--allow-low-space-this-run', action='store_true')
    sub.add_parser('selftest')
    benchmark = sub.add_parser('run')
    benchmark.add_argument('--frozen-commit')
    benchmark.add_argument('--native-sha256')
    benchmark.add_argument('--out', type=Path, required=True)
    frozen = sub.add_parser('freeze')
    internal = sub.add_parser('_worker')
    internal.add_argument('--input', type=Path, required=True)
    internal.add_argument('--rows', type=int, required=True)
    internal.add_argument('--output', type=Path, required=True)
    internal.add_argument('--measure', action='store_true')
    internal.add_argument('--lane', choices=['A', 'B'])
    for item in (benchmark, internal, frozen):
        item.add_argument('--extension-dir', type=Path, default=ROOT / 'local/native-kendall')
        item.add_argument('--implementation', choices=['legacy', 'product'], default='legacy')
        item.add_argument('--workload', choices=['random-pair', 'ols-pairs'], default='random-pair')
        item.add_argument('--allow-low-space-this-run', action='store_true')
        item.add_argument('--trace-memory', action='store_true')
    for item in (benchmark, frozen):
        item.add_argument('--source-manifest', type=Path, required=True)
    args = parser.parse_args()
    if getattr(args, 'trace_memory', False) and args.implementation != 'product':
        parser.error('--trace-memory requires --implementation product')
    if getattr(args, 'workload', 'random-pair') == 'ols-pairs' and args.implementation != 'product':
        parser.error('--workload ols-pairs requires --implementation product')
    if hasattr(args, 'extension_dir'):
        args.extension_dir = args.extension_dir.resolve()
    if args.mode == '_worker':
        worker(args)
    elif args.mode == 'prepare':
        print(generate(INPUT_DIR, ROWS, allow_low_space=args.allow_low_space_this_run))
    elif args.mode == 'freeze':
        freeze(args)
    elif args.mode == 'run':
        return run(args)
    else:
        with tempfile.TemporaryDirectory(prefix='kendall-functional-') as folder:
            directory = Path(folder)
            csv = generate(directory, 10_000)
            code, _, _ = launch(directory, csv, 10_000, ROOT / 'local/native-kendall')
            if code:
                raise RuntimeError((directory / 'worker.log').read_text())
            result = json.loads((directory / 'verification.json').read_text())
            assert result['A'] == result['B'] and 0 < result['A']['p'] < 1
            print(json.dumps({'functional_only': True, 'rows': 10_000, 'tau_p_bit_identical': True,
                              'result': result['A'], 'timing_or_rss_observed': False}, sort_keys=True))


if __name__ == '__main__':
    raise SystemExit(main())
