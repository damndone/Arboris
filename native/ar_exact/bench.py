"""Exact AR component A/B on the registered, shared 1M IV CSV.

Run only in a coordinator-assigned exclusive measurement window. No product
function patches, dependency installation, dataset generation, input copies,
environment changes or removal of earlier evidence. A is the retained original
Python exact algorithm; B is the product-selected native exact algorithm. Both
include the unchanged global polynomial root certification. This measures the
exact fallback component, not default IV, the verified NumPy path, end-to-end
Workbench, coverage or a release gate. Primary elapsed time covers the entire
fresh worker, including imports, parsing, validation, cross-language calls,
certification and output. Algorithm and input stages are also reported. RSS
is the entire fresh worker, observed by wait4. All outputs remain in one
fresh directory; the journal retains hashes, bytes and complete exact results.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import sysconfig
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).resolve()
MANIFEST = ROOT / 'local/perf-inputs/iv/source.json'
EXPECTED_SHA256 = '4f18e7f8f28c324e0383952e1a1d4e8b6402dcabb2dbcf8f10acfb758981c6ef'
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'scripts'))
import perf_evidence as evidence  # noqa: E402


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def save(path, value):
    with path.open('xb') as stream:
        stream.write(encoded(value) + b'\n')
        stream.flush()
        os.fsync(stream.fileno())


def identity(path):
    stat = path.stat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]


def provenance():
    import numpy, pandas, scipy
    from workbench import native_ar
    if native_ar.engine_status()['engine'] != 'native_cpp_exact':
        raise RuntimeError('build the exact native AR extension first')
    paths = [SCRIPT, SCRIPT.with_name('ar_exact.cpp'), SCRIPT.with_name('build.py'),
             ROOT / 'backend/workbench/native_ar.py', ROOT / 'backend/workbench/checks/ar_confidence.py',
             ROOT / 'backend/workbench/checks/ar_polynomials.py', ROOT / 'backend/workbench/checks/ar_cancellation.py',
             ROOT / 'backend/workbench/agent/execution.py', ROOT / 'backend/workbench/agent/workflow.py',
             ROOT / 'backend/workbench/agent/workflow_runtime.py',
             ROOT / 'backend/workbench/agent/orchestration_operation_handler.py',
             ROOT / 'backend/workbench/agent/orchestration_workflows.py', ROOT / 'backend/workbench/services/iv_ar.py',
             ROOT / 'backend/workbench/exploration_log.py', ROOT / 'backend/workbench/agent/core_parts/commands.py',
             ROOT / 'backend/workbench/http/agent_turn_routes.py',
             ROOT / 'tests/test_native_ar_exact.py', ROOT / 'tests/test_native_ar_cancellation.py',
             ROOT / 'scripts/perf_evidence.py',
             native_ar._BINARY]
    return {'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'source_sha256': {str(path.relative_to(ROOT)): evidence.digest(path) for path in paths},
            'engine': native_ar.engine_status(), 'python': sys.version, 'executable': sys.executable,
            'ext_suffix': sysconfig.get_config_var('EXT_SUFFIX'),
            'libraries': {'numpy': numpy.__version__, 'pandas': pandas.__version__, 'scipy': scipy.__version__},
            'worker_environment': {key: os.environ.get(key) for key in
                ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'MKL_NUM_THREADS', 'PYTHONHASHSEED']}}


def process_snapshot():
    raw = subprocess.check_output(['ps', '-Ao', 'pid=,ppid=,command='], text=True)
    competing = []
    for line in raw.splitlines():
        pid, ppid, command = line.strip().split(maxsplit=2)
        if int(pid) in {os.getpid(), os.getppid()} or 'ps -Ao' in command:
            continue
        if any(token in command for token in ['-m pytest', '/pytest ', 'vitest', 'scripts/perf_1m.py',
                    'native/kendall_counts/bench.py', 'native/ar_exact/bench.py', 'bench_families.py']):
            competing.append({'pid': int(pid), 'ppid': int(ppid)})
    if competing:
        raise RuntimeError('measurement host is not test-idle: ' + json.dumps(competing))
    return {'processes_checked': len(raw.splitlines()), 'competing': competing}


def worker(args):
    case_started = time.perf_counter()
    import numpy as np
    import pandas as pd
    from scipy import stats
    from workbench.checks import ar_confidence as ar
    from workbench.checks.ar_polynomials import certify_set
    before = provenance()
    source = json.loads(MANIFEST.read_text())
    csv = Path(source['source'])
    if source['sha256'] != EXPECTED_SHA256 or identity(csv) != args.input_identity:
        raise ValueError('fixed_input_identity_changed')
    input_started = time.perf_counter()
    frame = pd.read_csv(csv)
    if len(frame) != 1_000_000:
        raise ValueError('expected_exactly_1M_rows')
    y, x, z = frame.y.to_numpy(), frame[['d']].to_numpy(), frame[['z1', 'z2']].to_numpy()
    w = np.column_stack([np.ones(len(frame)), frame.w])
    critical = float(stats.chi2.ppf(.95, z.shape[1]))
    input_finished = time.perf_counter()
    calculate = ar.robust_polynomials_reference if args.lane == 'A' else ar.robust_polynomials
    started = time.perf_counter()
    numerator, denominator = calculate(y, x, z, w, critical)
    polynomial_finished = time.perf_counter()
    result = certify_set(numerator, denominator)
    elapsed = time.perf_counter()-started
    numerical = {'critical_binary64_hex': critical.hex(), 'numerator': numerator,
                 'denominator': denominator, 'global_result': result}
    if before != provenance() or identity(csv) != args.input_identity:
        raise ValueError('source_or_input_identity_changed')
    save(args.output, {'lane': args.lane, 'algorithm_seconds': elapsed,
                       'polynomial_seconds': polynomial_finished-started,
                       'certification_seconds': elapsed-(polynomial_finished-started),
                       'input_seconds': input_finished-input_started,
                       'imports_and_initial_validation_seconds': input_started-case_started,
                       'total_case_seconds': time.perf_counter()-case_started, 'numerical': numerical,
                       'numerical_sha256': hashlib.sha256(encoded(numerical)).hexdigest(),
                       'numerical_payload_bytes': len(encoded(numerical)), 'provenance': before})


def run(args):
    if not hasattr(os, 'wait4'):
        raise RuntimeError('fresh-worker RSS requires wait4')
    out = args.out.resolve()
    parent = ROOT / 'local/perf-evidence'
    if out.exists() or out == parent or not out.is_relative_to(parent):
        raise ValueError('use a fresh directory below local/perf-evidence')
    run_started = time.perf_counter()
    before = provenance()
    digest_started = time.perf_counter()
    manifest = json.loads(MANIFEST.read_text())
    csv = Path(manifest['source'])
    if manifest['sha256'] != EXPECTED_SHA256 or evidence.digest(csv) != EXPECTED_SHA256:
        raise ValueError('registered_fixed_input_sha256_mismatch')
    registered_digest_validation_seconds = time.perf_counter()-digest_started
    source_identity = identity(csv)
    out.mkdir(parents=True)
    # Preserve the exact measured uncommitted sources and ABI binary, so a
    # subsequent candidate remains reproducible without relying on Git HEAD.
    frozen = out / 'frozen-candidate-sources.tar.gz'
    with frozen.open('xb') as raw:
        with tarfile.open(fileobj=raw, mode='w:gz') as archive:
            for path, digest in sorted(before['source_sha256'].items()):
                if evidence.digest(ROOT / path) != digest:
                    raise ValueError('source_changed_before_freeze')
                archive.add(ROOT / path, arcname=path, recursive=False)
        raw.flush()
        os.fsync(raw.fileno())
    with tarfile.open(frozen, 'r:gz') as archive:
        archived = {member.name: hashlib.file_digest(archive.extractfile(member), 'sha256').hexdigest()
                    for member in archive.getmembers()}
    if archived != before['source_sha256']:
        raise ValueError('frozen_source_archive_verification_failed')
    save(out / 'frozen-candidate-sources.json', {'sha256': evidence.digest(frozen), 'files': archived})
    report = {'scope': 'exact_fallback_component_only', 'measurement_window': args.measurement_window,
              'input': {'path': str(csv), 'sha256': EXPECTED_SHA256, 'rows': 1_000_000, 'identity': source_identity},
              'provenance': before, 'elapsed_scope': 'entire_fresh_worker_startup_imports_read_validate_exact_calculation_certification_output',
              'algorithm_elapsed_scope': 'exact Gram/projection/covariance including bridge calls + determinants + global certification',
              'registered_digest_validation_seconds_once': registered_digest_validation_seconds,
              'rss_scope': 'whole_fresh_worker_wait4', 'unmodified_inherited_worker_environment': True,
              'low_disk_waiver_explicit': args.allow_low_disk, 'runs': [], 'status': 'incomplete',
              'noise_definition': 'sample_standard_deviation/median; every sample retained'}
    expected = None
    try:
        order = [(f'calibration-A{i}', 'A') for i in range(1, 6)]
        order += [(f'{lane}{i}', lane) for i in range(1, 6) for lane in 'AB']
        for label, lane in order:
            free = evidence.require_space(out, allow_low_space=args.allow_low_disk)
            process_check = process_snapshot()
            if provenance() != before or identity(csv) != source_identity:
                raise ValueError('benchmark_identity_changed')
            output = out / f'{label}.json'
            command = [sys.executable, str(SCRIPT), '_worker', '--lane', lane, '--output', str(output),
                       '--input-identity', *map(str, source_identity)]
            worker_started = time.perf_counter()
            child = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _, status, usage = os.wait4(child.pid, 0)
            child.returncode = os.waitstatus_to_exitcode(status)
            stdout, stderr = child.communicate()
            worker_elapsed = time.perf_counter()-worker_started
            # Small logs and every successful numerical result are retained.
            save(out / f'{label}-worker.json', {'returncode': child.returncode,
                 'stdout': stdout.decode(errors='replace'), 'stderr': stderr.decode(errors='replace')})
            metadata = {'label': label, 'lane': lane, 'returncode': child.returncode,
                        'seconds': worker_elapsed,
                        'free_before_bytes': free, 'processes_before': process_check,
                        'ru_maxrss': usage.ru_maxrss,
                        'rss_bytes': usage.ru_maxrss if sys.platform == 'darwin' else usage.ru_maxrss*1024}
            if output.exists():
                value = json.loads(output.read_text())
                metadata.update({key: value[key] for key in ['algorithm_seconds', 'polynomial_seconds', 'certification_seconds',
                    'input_seconds', 'imports_and_initial_validation_seconds', 'total_case_seconds',
                    'numerical_sha256', 'numerical_payload_bytes']})
                if expected is None:
                    expected = value['numerical']
                    report['exact_reference_result'] = expected
                metadata['all_exact_integers_and_certificates_equal'] = value['numerical'] == expected
            record = evidence.snapshot(out, record_id=label, metadata=metadata,
                                       exclude=[out / 'measurements.jsonl'], kind='exact_ar_component')
            evidence.append_record(out / 'measurements.jsonl', record)
            if len(evidence.read_records(out / 'measurements.jsonl')) != len(report['runs'])+1:
                raise ValueError('journal_verification_failed')
            metadata['directory_bytes'] = record['tree_bytes']
            metadata['file_count'] = record['file_count']
            report['runs'].append(metadata)
            print(json.dumps(metadata, sort_keys=True), flush=True)
            if child.returncode or not metadata.get('all_exact_integers_and_certificates_equal'):
                raise RuntimeError('worker_failure_or_exact_numerical_mismatch')
            process_snapshot()
            if provenance() != before or identity(csv) != source_identity:
                raise ValueError('benchmark_identity_changed_after_worker')
        a = report['runs'][5::2]
        b = report['runs'][6::2]
        calibration = report['runs'][:5]
        def noise(rows):
            return {key: statistics.stdev(row[key] for row in rows) / statistics.median(row[key] for row in rows)
                    for key in ['seconds', 'algorithm_seconds', 'rss_bytes']}
        report['calibration_noise'] = noise(calibration)
        report['all_baseline_noise'] = noise(calibration+a)
        report['noise_below_five_percent'] = all(value < .05 for values in
            [report['calibration_noise'], report['all_baseline_noise']] for value in values.values())
        report['paired_medians'] = {lane: {key: statistics.median(row[key] for row in rows)
            for key in ['seconds', 'total_case_seconds', 'algorithm_seconds', 'input_seconds',
                        'polynomial_seconds', 'certification_seconds', 'rss_bytes', 'numerical_payload_bytes']}
            for lane, rows in [('A', a), ('B', b)]}
        report['candidate_over_baseline_median_ratio'] = {key:
            report['paired_medians']['B'][key] / report['paired_medians']['A'][key]
            for key in report['paired_medians']['A']}
        report['status'] = 'component_comparison_only' if report['noise_below_five_percent'] else 'uncertified_noise'
    except BaseException as error:
        report.update(status='failed', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        report['total_run_seconds_including_initial_validation_and_all_workers'] = time.perf_counter()-run_started
        save(out / 'summary.json', report)
    return 0 if report['status'] == 'component_comparison_only' else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    benchmark = sub.add_parser('run')
    benchmark.add_argument('--out', type=Path, required=True)
    benchmark.add_argument('--measurement-window', required=True)
    benchmark.add_argument('--allow-low-disk', action='store_true', help='Only for the explicit 2026-10-29 user waiver')
    internal = sub.add_parser('_worker')
    internal.add_argument('--lane', choices=['A', 'B'], required=True)
    internal.add_argument('--output', type=Path, required=True)
    internal.add_argument('--input-identity', nargs=4, type=int, required=True)
    args = parser.parse_args()
    return worker(args) if args.mode == '_worker' else run(args)


if __name__ == '__main__':
    raise SystemExit(main())
