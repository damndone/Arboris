#!/usr/bin/env python3
"""Prepared acceptance only: five fresh 1M-row fast-IV workers at the approved 50 ms delay.

Do not run alongside tests/builds. The request is 50 ms after the public
estimation/start hook. A normally completed run is NOT_EXERCISED; the first
failed or unexercised observation stops this campaign after evidence retention.
Only the existing stop_reason requests cancellation. No product/FFI patches,
worker environment overrides, forced GC, providers or protected runner.
The two-second comparison applies only to this fixed input/build/phase/delay;
NumPy preprocessing, cold loading/self-checks and synchronous publication have
checkpoint boundaries, not universal hard preemption or atomic rollback.

Review first, then run ONLY on the root agent's subsequent execution instruction:
  PYTHONPATH=backend .venv/bin/python scripts/perf_fast_iv_cancel.py \
    --out local/perf-evidence/fast-iv-cancel-<fresh> --delay-ms 50 \
    --manifest local/perf-evidence/fast-engine-review-20261104-input/source.json \
    --allow-low-space-this-campaign
"""
from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'backend'))

from perf_1m import registered_source, validate_family_manifest
from perf_evidence import (append_record, archive_verified, read_records, require_space,
                           snapshot, verify_tree_records)
from perf_fast_engine import measurement_identity, retain_worker_logs
from perf_host import monitor_host, require_idle, terminate_bounded

CAP_SECONDS = 2.0
REPETITIONS = 5
PROBE_SECONDS = .1
TARGETS = ('model_results/iv_2sls_1.json', 'model_results/inference_kernels/iv_2sls_1.json')


def input_identity(path):
    stat = path.stat()
    return {key: getattr(stat, 'st_' + key) for key in ('dev', 'ino', 'size', 'mtime_ns', 'ctime_ns')}


def stamps():
    return {'monotonic_ns': time.monotonic_ns(), 'wall_ns': time.time_ns()}


def model_files(project):
    values = {}
    for run in (project / 'runs').glob('*'):
        for relative in TARGETS:
            path = run / relative
            if path.exists():
                stat = path.stat()
                values[str(path.relative_to(project))] = {
                    'mtime_ns': stat.st_mtime_ns, 'bytes': stat.st_size,
                    'birthtime_ns': getattr(stat, 'st_birthtime_ns', None)}
    return values


def exception_evidence(error, *, expected_interruption):
    value = {'type': type(error).__name__, 'reason': getattr(error, 'reason', None),
             'message': str(error), 'io_error': isinstance(error, OSError), 'errno': getattr(error, 'errno', None)}
    if not expected_interruption:
        value['traceback'] = ''.join(traceback.format_exception(error))
    return value



def worker(args):
    from workbench.engine.context import RunInterruptionRequested
    from workbench.estimation_engine import native
    from workbench.native_build import verify_build
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project
    if 'on_step' not in inspect.signature(run_workflow).parameters:
        raise RuntimeError('public_run_workflow_on_step_hook_required')
    payload = json.loads(args.manifest.read_text())
    source = registered_source(payload)
    if payload['case'] != 'iv' or payload['rows'] != 1_000_000:
        raise ValueError('registered_original_1M_IV_required')
    before_input = input_identity(source)
    project = create_project(args.out, 'benchmark')
    before_threads = {t.ident for t in threading.enumerate()}
    # Verify files without loading the library early: cold loading remains inside the observed product path.
    verified_build = verify_build(ROOT / 'native/engine', native.library_directory())
    cancelled, audit_stop = threading.Event(), threading.Event()
    lock = threading.Lock()
    events, first_seen, request, timer, audit_errors = [], {}, {}, None, []

    def audit_once():
        now = stamps()
        current = model_files(project.root)
        with lock:
            for path, value in current.items():
                first_seen.setdefault(path, {**now, **value})
        return current

    def audit():
        while not audit_stop.wait(.005):
            try:
                audit_once()
            except OSError as error:
                with lock:
                    audit_errors.append({'type': type(error).__name__, 'errno': error.errno, 'message': str(error)})
                return

    def request_cancel():
        # Both clock domains and the signal emission are retained; no second stop source.
        with lock:
            visible = model_files(project.root)
            request.update(stamps())
            request['visible_files'] = visible
            cancelled.set()

    def on_step(stage, state, message):
        nonlocal timer
        event = {**stamps(), 'stage': stage, 'state': state, 'message': message}
        with lock:
            events.append(event)
        if stage == 'estimation' and state == 'start' and timer is None:
            timer = threading.Timer(args.delay_ms / 1000., request_cancel)
            timer.name = 'iv-cancel-request-timer'
            timer.start()

    observer = threading.Thread(target=audit, name='iv-cancel-file-observer', daemon=True)
    observer.start()
    started = stamps()
    exception, outcome = None, None
    try:
        outcome = run_workflow(project.root, [source], mode='auto', **payload['kwargs'],
                               estimation_engine='fast', on_step=on_step,
                               stop_reason=lambda: 'cancelled' if cancelled.is_set() else None)
    except BaseException as error:
        expected_interruption = isinstance(error, RunInterruptionRequested)
        exception = exception_evidence(error, expected_interruption=expected_interruption)
    else:
        expected_interruption = False
    returned = stamps()  # actual public-call return, before observer teardown/evidence hashing
    threads_at_return = [{'name': t.name, 'ident': t.ident, 'daemon': t.daemon}
                         for t in threading.enumerate()
                         if t.ident not in before_threads and t is not observer and t is not timer]
    if timer is not None:
        timer.cancel()
        timer.join()
    at_return = audit_once()
    time.sleep(PROBE_SECONDS)  # external observation only; no GC or computation intervention
    after_probe = audit_once()
    audit_stop.set()
    observer.join()
    publication = {}
    for path, value in after_probe.items():
        seen = first_seen.get(path, {})
        if not request:
            category = 'no_cancel_request'
        elif (path in request['visible_files'] or seen.get('monotonic_ns', returned['monotonic_ns']) < request['monotonic_ns']) and value['mtime_ns'] <= request['wall_ns']:
            category = 'before_cancel'
        elif value['birthtime_ns'] is not None and value['birthtime_ns'] <= request['wall_ns'] < value['mtime_ns']:
            category = 'synchronous_write_boundary_unresolved'
        elif value['mtime_ns'] > request['wall_ns']:
            category = 'after_cancel'
        else:
            category = 'publication_boundary_unresolved'
        publication[path] = {'category': category, 'first_seen': seen, 'final': value}
    not_exercised = outcome is not None and outcome.get('status') == 'completed'
    latency = ((returned['monotonic_ns'] - request['monotonic_ns']) / 1e9) if request else None
    failures = []
    if audit_errors:
        failures.append('file_observation_failed')
    if not not_exercised:
        if not request:
            failures.append('estimation_deadline_not_reached_before_failure')
        if not expected_interruption or (exception or {}).get('reason') != 'cancelled':
            failures.append('wrong_owner_exception')
        if latency is None or latency > CAP_SECONDS:
            failures.append('fixed_workload_cancel_return_above_2_seconds')
        if threads_at_return:
            failures.append('python_worker_threads_still_alive_at_public_return')
        if at_return != after_probe:
            failures.append('model_or_kernel_changed_after_public_return')
        if any(v['category'] == 'after_cancel' for v in publication.values()):
            failures.append('new_publication_after_cancel')
        if any('unresolved' in v['category'] for v in publication.values()):
            failures.append('publication_boundary_requires_review')
    runs = list((project.root / 'runs').iterdir())
    if len(runs) != 1:
        raise RuntimeError('exactly_one_product_run_required')
    value = {'status': 'interrupted' if expected_interruption else 'completed' if outcome else 'failed',
             'exercise_status': 'failed' if failures else 'not_exercised' if not_exercised else 'passed',
             'failures': failures, 'delay_ms': args.delay_ms, 'started': started, 'cancel_request': request,
             'returned': returned, 'cancel_to_public_return_seconds': latency,
             'exception': exception, 'outcome': outcome, 'threads_at_return': threads_at_return,
             'publication': publication, 'events': events, 'audit_errors': audit_errors,
             'post_return_probe_seconds': PROBE_SECONDS,
             'run_root': str(runs[0]), 'input_source': str(source), 'input_sha256': payload['sha256'],
             'input_identity_before': before_input, 'input_identity_after': input_identity(source),
             'verified_worker_build': verified_build,
             'actual_loaded_worker_build': native.build_record() if native._loaded.cache_info().currsize else None,
             'native_entry_exercised': 'not established by a stage-relative timer; actual small-FFI cancellation is a separate gate',
             'thread_scope': 'Python owned-worker census; Rust native scoped join separately proven by actual native test',
             'scope': 'fixed registered 1M IV only; preprocessing/cold self-check/publication retain checkpoint boundaries'}
    (args.out / 'worker-result.json').write_text(json.dumps(value, indent=2, allow_nan=False))
    return 0 if value['exercise_status'] == 'passed' else 1


def journal_then_cleanup(active, out, label, metadata):
    """Only this campaign's designated active tree, after complete SHA registration/verification."""
    record = snapshot(active, record_id=label, metadata=metadata,
                      registered_input=(Path(metadata['input_source']), metadata['input_sha256']))
    ledger = out / 'journal.jsonl'
    append_record(ledger, record)
    saved = [row for row in read_records(ledger) if row['record_id'] == label]
    if len(saved) != 1:
        raise ValueError('journal_record_count')
    verify_tree_records(active, saved)
    archive = out / 'representatives' / f'fast-iv-cancel-{metadata["delay_ms"]}ms.tar.gz'
    if not archive.exists():
        archive_verified(active, archive, record['files'])  # failed exercises also retain their actual products/logs
    shutil.rmtree(active)
    return {'journal_record_id': label, 'file_count': record['file_count'], 'tree_bytes': record['tree_bytes'],
            'representative': str(archive)}


def campaign(args):
    from workbench.orchestrator import run_workflow
    if 'on_step' not in inspect.signature(run_workflow).parameters:
        raise RuntimeError('public_on_step_hook_missing; do not patch or bypass admission')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    payload = validate_family_manifest(args.manifest)
    source = registered_source(payload)
    if payload['case'] != 'iv' or payload['rows'] != 1_000_000:
        raise ValueError('registered_original_1M_IV_required')
    identity, input_stat = measurement_identity(), input_identity(source)
    report = {'scope': __doc__, 'source_identity': identity, 'input_identity': input_stat,
              'input_sha256': payload['sha256'],
              'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'allow_low_space_this_campaign': args.allow_low_space_this_campaign,
              'low_space_authority': 'existing explicit native-campaign exception; never bypass actual IO/ENOSPC failures',
              'runs': []}
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False))
    save()
    for delay in (args.delay_ms,):
        for index in range(REPETITIONS):
            require_idle()
            free = require_space(out, allow_low_space=args.allow_low_space_this_campaign)
            if measurement_identity() != identity or input_identity(source) != input_stat:
                raise RuntimeError('frozen_source_build_or_input_changed')
            active = out / 'active'
            active.mkdir(exist_ok=False)
            label = f'{delay}ms-{index}'
            command = [sys.executable, '-B', str(Path(__file__).resolve()), '--worker', '--out', str(active),
                       '--manifest', str(args.manifest.resolve()), '--delay-ms', str(delay)]
            with monitor_host(out / 'host' / f'{label}.jsonl') as monitor:
                process = monitor.popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    stdout, stderr = process.communicate(timeout=120)
                except subprocess.TimeoutExpired:
                    (active / 'watchdog-failed.txt').write_text('external 120s watchdog; terminate/kill waits each bounded at 2s; never cooperative pass')
                    try:
                        stdout, stderr = terminate_bounded(process)
                    except subprocess.TimeoutExpired as error:
                        for name, partial in (('stdout', error.output), ('stderr', error.stderr)):
                            (active / f'{name}.log').write_bytes(partial if isinstance(partial, bytes) else (partial or '').encode())
                        (out / 'watchdog-stop-unconfirmed.json').write_text(json.dumps({
                            'label': label, 'pid': process.pid, 'status': 'failed',
                            'active_preserved': str(active), 'reason': 'kill did not drain within 2s'}))
                        raise RuntimeError('worker stop unconfirmed after bounded kill wait; active evidence preserved') from error
            (active / 'stdout.log').write_text(stdout)
            (active / 'stderr.log').write_text(stderr)
            result_path = active / 'worker-result.json'
            value = json.loads(result_path.read_text()) if result_path.exists() else {
                'status': 'failed', 'exercise_status': 'failed', 'failures': ['missing_worker_result'], 'delay_ms': delay}
            if (active / 'watchdog-failed.txt').exists():
                value['failures'].append('external_watchdog_not_cooperative_stop')
                value['exercise_status'] = 'failed'
            value.update(label=label, returncode=process.returncode, host_monitor=monitor.summary,
                         free_bytes_before=free, source_identity_after=measurement_identity(),
                         input_source=str(source), input_sha256=payload['sha256'])
            if (not monitor.summary['valid'] or value['source_identity_after'] != identity
                    or input_identity(source) != input_stat
                    or value.get('verified_worker_build', {}).get('build_identity_sha256') != identity['native_build']['build_identity_sha256']
                    or (value.get('actual_loaded_worker_build') is not None and
                        value['actual_loaded_worker_build']['build_identity_sha256'] != identity['native_build']['build_identity_sha256'])):
                value['failures'].append('host_source_build_or_input_integrity')
                value['exercise_status'] = 'failed'
            value['retained_logs'] = retain_worker_logs(active, out / 'logs' / f'{label}.logs')
            value['retention'] = journal_then_cleanup(active, out, label, value)
            report['runs'].append(value)
            save()
            print(json.dumps({k: value.get(k) for k in ('label', 'exercise_status', 'cancel_to_public_return_seconds', 'failures')}), flush=True)
            io_or_crash = (process.returncode not in (0, 1) or (value.get('exception') or {}).get('io_error')
                           or value.get('audit_errors') or 'No space left on device' in stderr or 'ENOSPC' in stderr)
            if io_or_crash or value['exercise_status'] != 'passed' or process.returncode != 0:
                report['passed'] = False
                report['stopped_reason'] = 'worker_io_or_crash' if io_or_crash else value['exercise_status']
                save()
                return 1  # this observation is already journaled/archived; do not repeat a known failure
    report['passed'] = all(value['exercise_status'] == 'passed' and value['returncode'] == 0 for value in report['runs'])
    save()
    return int(not report['passed'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'local/perf-inputs/iv/source.json')
    parser.add_argument('--delay-ms', type=int, choices=(50,), default=50)
    parser.add_argument('--allow-low-space-this-campaign', action='store_true')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return worker(args)
    return campaign(args)


if __name__ == '__main__':
    raise SystemExit(main())
