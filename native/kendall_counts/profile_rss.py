"""Five fresh reference workers for stage RSS attribution; never acceptance.

freeze --source-manifest local/perf-evidence/kendall-rss-source.json
run --source-manifest local/perf-evidence/kendall-rss-source.json \
    --out local/perf-evidence/kendall-rss-attribution

Add --allow-low-space-this-run to both commands only for an authorized run.
No elapsed times, input generation, product patching, or environment changes.
The exact existing perf_1m.current_rss function is loaded without importing that
script's product/CLI dependencies. Observer allocations affect these readings:
this is causal evidence, not an uninstrumented RSS or performance certificate.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import resource
import subprocess
import sys

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[2]
spec = importlib.util.spec_from_file_location('kendall_component', SCRIPT.with_name('bench.py'))
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)
RSS_SOURCE = ROOT / 'scripts/perf_1m.py'


def resident_reader():
    """Reuse only the existing observer, without importing the product driver."""
    tree = ast.parse(RSS_SOURCE.read_text())
    node, = (item for item in tree.body if isinstance(item, ast.FunctionDef)
             and item.name == 'current_rss')
    namespace = {'Path': Path}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(RSS_SOURCE), 'exec'), namespace)
    return namespace['current_rss']


def frozen_request(args, *, verified_input=None):
    csv, sha, registration = bench.fixed_input() if verified_input is None else verified_input
    return {'schema_version': 1, 'kind': 'kendall-stage-rss-diagnostic', 'workers': 5,
        'lane': 'public-reference-only', 'acceptance': False,
        'observer_sha256': bench.evidence.digest(SCRIPT),
        'resident_helper_sha256': bench.evidence.digest(RSS_SOURCE),
        'provenance': bench.provenance(args.extension_dir),
        'input': {'path': str(csv), 'sha256': sha, 'registration': registration},
        'allow_low_space_this_run': args.allow_low_space_this_run,
        'observer_environment': {name: os.environ.get(name) for name in
            ['SCIPY_ARRAY_API', 'PYTHONMALLOC', 'MallocNanoZone']}}


def worker(args):
    current_rss = resident_reader()
    marks = []
    def mark(stage):
        resident = current_rss()
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        marks.append({'stage': stage, 'resident_bytes': resident,
                      'ru_maxrss_bytes': peak if sys.platform == 'darwin' else peak * 1024})

    mark('before_libraries')
    np, pd, _, special, stats, native = bench.libraries(args.extension_dir)
    sys.path.insert(0, str(ROOT / 'backend'))
    from workbench import native_kendall
    native_kendall._load_native()
    mark('after_libraries_and_candidate_load')
    frame = pd.read_csv(args.input, usecols=['x', 'y'], dtype=np.float64,
                        float_precision='round_trip')
    if len(frame) != bench.ROWS:
        raise ValueError('fixed row count changed')
    mark('after_read_csv')
    x = np.ascontiguousarray(frame['x'].to_numpy(dtype=np.float64, copy=False))
    y = np.ascontiguousarray(frame['y'].to_numpy(dtype=np.float64, copy=False))
    # Match bench.arrays: its local DataFrame goes out of scope on return.
    del frame
    mark('after_contiguous_arrays')
    result = bench.calculate('A', x, y, np, special, stats, native, implementation='product')
    mark('after_public_kendall_tau_p')
    bench.save(args.output / 'result.json', result)
    mark('after_result_output')
    bench.save(args.output / 'stage-rss.json', {'scope': 'instrumented_attribution_only',
        'marks': marks, 'result': result, 'elapsed_time_measured': False})


def run(args):
    if sys.platform not in ('darwin', 'linux') or not hasattr(os, 'wait4'):
        raise RuntimeError('stage RSS observer requires macOS/Linux wait4')
    manifest_path = args.source_manifest.resolve()
    manifest = json.loads(manifest_path.read_text())
    manifest_id, manifest_sha = bench.identity(manifest_path), bench.evidence.digest(manifest_path)
    registered = bench.fixed_input()
    if manifest != frozen_request(args, verified_input=registered):
        raise ValueError('frozen observer/source/input/options differ')
    csv = Path(manifest['input']['path'])
    input_id = bench.identity(csv)
    parent = ROOT / 'local/perf-evidence'
    out = args.out.resolve()
    if not out.is_relative_to(parent) or out == parent or out.exists():
        raise ValueError('use a fresh output directory below local/perf-evidence')
    bench.evidence.require_space(parent, allow_low_space=args.allow_low_space_this_run)

    def check():
        if (bench.identity(manifest_path) != manifest_id
                or bench.evidence.digest(manifest_path) != manifest_sha
                or bench.identity(csv) != input_id
                or frozen_request(args, verified_input=registered) != manifest):
            raise ValueError('frozen observer/source/input changed')

    out.mkdir(parents=True)
    report = {'scope': 'stage_rss_attribution_only', 'acceptance': False,
              'manifest': manifest, 'manifest_sha256': manifest_sha, 'workers': [], 'status': 'incomplete'}
    try:
        expected = None
        for index in range(1, 6):
            check()
            free = bench.evidence.require_space(out, allow_low_space=args.allow_low_space_this_run)
            if any(parent.rglob('active')):
                raise RuntimeError('an active benchmark tree already exists')
            active = out / 'active'
            active.mkdir()
            metadata = {'label': f'profile-A{index}', 'lane': 'A', 'status': 'failed',
                        'scope': 'instrumented_stage_rss_only', 'free_before_bytes': free}
            try:
                bench.idle_snapshot(active / 'processes-before.json')
                command = [sys.executable, str(SCRIPT), '_worker', '--input', str(csv),
                    '--output', str(active), '--extension-dir', str(args.extension_dir)]
                with (active / 'worker.log').open('x') as log:
                    child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
                    _, status, usage = os.wait4(child.pid, 0)
                    code = os.waitstatus_to_exitcode(status)
                    child.returncode = code
                metadata.update(returncode=code, command=command,
                    terminal_peak_rss_bytes=usage.ru_maxrss if sys.platform == 'darwin' else usage.ru_maxrss * 1024)
                bench.idle_snapshot(active / 'processes-after.json')
                check()
                if code:
                    raise RuntimeError('stage RSS worker failed')
                observed = json.loads((active / 'stage-rss.json').read_text())
                if expected is not None and observed['result'] != expected:
                    raise ValueError('reference result changed across workers')
                expected = observed['result']
                metadata.update(status='completed', **observed)
            except BaseException as error:
                metadata.update(status='failed', error=f'{type(error).__name__}: {error}')
                raise
            finally:
                metadata['retention'] = bench.retain(active, out, metadata['label'], metadata)
                report['workers'].append(metadata)
        report['status'] = 'diagnostic_completed'
    except BaseException as error:
        report.update(status='failed', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        bench.save(out / 'summary.json', report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    freeze = sub.add_parser('freeze')
    diagnose = sub.add_parser('run')
    diagnose.add_argument('--out', type=Path, required=True)
    for item in (freeze, diagnose):
        item.add_argument('--source-manifest', type=Path, required=True)
        item.add_argument('--allow-low-space-this-run', action='store_true')
    internal = sub.add_parser('_worker')
    internal.add_argument('--input', type=Path, required=True)
    internal.add_argument('--output', type=Path, required=True)
    for item in (freeze, diagnose, internal):
        item.add_argument('--extension-dir', type=Path, default=ROOT / 'local/native-kendall')
    args = parser.parse_args()
    args.extension_dir = args.extension_dir.resolve()
    if args.mode == '_worker':
        worker(args)
    elif args.mode == 'freeze':
        target = args.source_manifest.resolve()
        if not target.is_relative_to(ROOT / 'local'):
            raise ValueError('source manifest must be below local/')
        target.parent.mkdir(parents=True, exist_ok=True)
        bench.save(target, frozen_request(args))
        print(json.dumps({'path': str(target), 'sha256': bench.evidence.digest(target)}))
    else:
        run(args)


if __name__ == '__main__':
    main()
