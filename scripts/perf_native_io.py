#!/usr/bin/env python3
"""Compare 1M-row OLS exports through the public ASGI routes.

Run from the candidate checkout on an idle host. The driver verifies the shared
input and both checkout identities, takes five baseline calibrations and five
alternating pairs, and journals each run before removing its active directory.

    .venv/bin/python -B scripts/perf_native_io.py --out local/perf-evidence/<new-round>
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import re
import resource
import shutil
from statistics import median
import subprocess
import sys
import time
import traceback
from urllib.parse import urlencode


DRIVER = Path(__file__).resolve()
ROOT = DRIVER.parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from evidence_identity import evidence_key, source_tree
from perf_1m import (AB_ORDER, GATE_MEMORY, MEMORY_METRICS, REFERENCE_MEMORY, THRESHOLDS, baseline_noise, baseline_source_state, build_identity,
                     family_kwargs, noise_accepted, product_sources, registered_source,
                     source_identity, validate_family_manifest)
from perf_evidence import (BASELINE, MIN_FREE_BYTES, append_record, archive_verified,
                           digest, finalize_active, read_records, require_space,
                           retain_worker_logs, snapshot, verify_tree_records)
from perf_host import monitored_worker, require_idle


CALIBRATION = tuple(f'A0_{index:02d}' for index in range(1, 6))
FORMATS = ('json', 'csv', 'dta')
METRICS = ('seconds', 'export_seconds', 'json_seconds', 'csv_seconds', 'dta_seconds', 'rss_bytes', 'run_bytes')
RATIO_LIMIT = 1.05
TIMEOUT_SECONDS = 120
# The shared A/B rules plus this driver's own; part of the evidence key.
NATIVE_IO_THRESHOLDS = {**THRESHOLDS, 'driver': 'perf_native_io', 'resource_ratio_limit': RATIO_LIMIT,
                        'worker_timeout_seconds': TIMEOUT_SECONDS}
ACTIVE_SPACE_RESERVE = 1_000_000_000
DOWNLOAD_ARTIFACT_TYPE = {'json': 'model_result', 'csv': 'data_export', 'dta': 'data_export'}
DTA_WRITER_REFERENCE = 'https://github.com/WizardMac/ReadStat/blob/master/src/stata/readstat_dta_write.c'
DTA_HEADER = re.compile(
    rb'<stata_dta><header><release>118</release><byteorder>(LSF|MSF)</byteorder>'
    rb'<K>(.{2})</K><N>(.{8})</N><label>(.{2})', re.DOTALL,
)
DTA_TIMESTAMP_OPEN = b'</label><timestamp>\x11'
DTA_TIMESTAMP_CLOSE = b'</timestamp></header><map>'


def durable_json(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


async def request(app, method, path, root, *, payload=None, download=False):
    request_body = b'' if payload is None else json.dumps(payload).encode('utf-8')
    sent_request = False
    status = None
    ended = False
    headers = {}
    content = bytearray()
    body_hash = sha256()
    size = 0

    async def receive():
        nonlocal sent_request
        if sent_request:
            await asyncio.Event().wait()
        sent_request = True
        return {'type': 'http.request', 'body': request_body, 'more_body': False}

    async def send(message):
        nonlocal status, ended, size
        if message['type'] == 'http.response.start' and status is None:
            status = message['status']
            headers.update(message['headers'])
        elif message['type'] == 'http.response.body' and status is not None and not ended:
            chunk = message.get('body', b'')
            size += len(chunk)
            if download and status == 200:
                body_hash.update(chunk)
            elif size <= 1_048_576:
                content.extend(chunk)
            else:
                raise ValueError(f'oversized response from {method} {path}')
            ended = not message.get('more_body', False)
        else:
            raise ValueError(f'unexpected ASGI response from {method} {path}')

    await app({
        'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.4'},
        'http_version': '1.1', 'method': method, 'scheme': 'http', 'path': path,
        'raw_path': path.encode('ascii'), 'root_path': '',
        'client': ('127.0.0.1', 49152), 'server': ('127.0.0.1', 8000),
        'query_string': urlencode({'project_root': str(root)}).encode('ascii'),
        'headers': [(b'host', b'127.0.0.1:8000'), (b'content-type', b'application/json'),
                    (b'content-length', str(len(request_body)).encode('ascii'))],
    }, receive, send)
    if status != 200 or not ended:
        raise ValueError(f'{method} {path} returned {status}: {bytes(content[:2000])!r}')
    if download:
        if not headers.get(b'content-disposition', b'').startswith(b'attachment') or size <= 0:
            raise ValueError(f'expected a nonempty attachment from {path}')
        if int(headers[b'content-length']) != size:
            raise ValueError(f'incomplete download from {path}')
        return {'bytes': size, 'sha256': body_hash.hexdigest(),
                'content_type': headers[b'content-type'].decode('ascii'),
                'content_disposition': headers[b'content-disposition'].decode('latin-1')}
    return json.loads(content)


async def export_from_app(app, project, run_id, rows, result):
    base = f'/runs/{run_id}'
    for format in FORMATS:
        started = time.perf_counter()
        if format == 'json':
            artifact_id = 'ols_1'
            download_url = f'{base}/artifacts/{artifact_id}'
        else:
            options = {'node_id': 'stage:raw', 'format': format}
            if format == 'dta':
                options['dta_version'] = 14
            exported = await request(app, 'POST', f'{base}/datasets/export', project, payload=options)
            artifact_id, download_url = exported['artifact_id'], exported['download_url']
            if download_url != f'{base}/artifacts/{artifact_id}' or exported['report']['rows'] != rows:
                raise ValueError(f'{format} export returned an unexpected artifact or row count')
            result['columns'][format] = exported['report']['column_names']
        delivered = await request(app, 'GET', download_url, project, download=True)
        result[f'{format}_seconds'] = time.perf_counter() - started
        result['downloads'][format] = delivered | {'artifact_id': artifact_id}


def worker(active, manifest):
    from workbench import __file__ as backend_file
    from workbench.app import app
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project

    if not Path(backend_file).resolve().is_relative_to(Path.cwd() / 'backend'):
        raise ValueError('worker imported a different Workbench checkout')
    payload = json.loads(manifest.read_text())
    source = registered_source(payload)
    require_space(active.parent)
    active.mkdir(exist_ok=False)
    result = {'status': 'failed', 'run_root': str(active / 'uncompleted'), 'downloads': {}, 'columns': {},
              'input_sha256': payload['sha256'], 'rows': payload['rows'], 'worker_repo': str(Path.cwd())}
    try:
        project = create_project(active, 'benchmark')
        started = time.perf_counter()
        outcome = run_workflow(project.root, [source], mode='auto', **payload['kwargs'])
        result['workflow_seconds'] = time.perf_counter() - started
        run_id = outcome['run_id']
        run = project.root / 'runs' / run_id
        result['run_root'] = str(run)
        if outcome['status'] != 'completed':
            raise ValueError(f'OLS workflow returned {outcome["status"]}')

        export_started = time.perf_counter()
        asyncio.run(export_from_app(app, project.root, run_id, payload['rows'], result))
        ended = time.perf_counter()
        result['export_seconds'] = ended - export_started
        result['seconds'] = ended - started
        result['status'] = 'completed'
    except Exception as error:
        traceback.print_exc()
        result['worker_error'] = f'{type(error).__name__}: {error}'
    result['ru_maxrss'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result['ru_maxrss_unit'] = 'bytes' if platform.system() == 'Darwin' else 'KiB'
    result['rss_bytes'] = result['ru_maxrss'] * (1 if result['ru_maxrss_unit'] == 'bytes' else 1024)
    from perf_footprint import memory_accounting
    result.update(memory_accounting())
    registered_source(payload)
    durable_json(active / 'metrics.json', result)
    return int(result['status'] != 'completed')


def dta_identity(stream):
    prefix = stream.read(131_072)
    header = DTA_HEADER.match(prefix)
    if not header:
        raise ValueError('expected a Stata release 118 header')
    byteorder, columns, rows, label_length = header.groups()
    order = 'little' if byteorder == b'LSF' else 'big'
    tag = header.end() + int.from_bytes(label_length, order)
    start = tag + len(DTA_TIMESTAMP_OPEN)
    end = start + 17
    if prefix[tag:start] != DTA_TIMESTAMP_OPEN or not prefix.startswith(DTA_TIMESTAMP_CLOSE, end):
        raise ValueError('unexpected Stata timestamp field')
    timestamp = prefix[start:end].decode('ascii')
    parsed = datetime.strptime(timestamp, '%d %b %Y %H:%M')
    if parsed.strftime('%d %b %Y %H:%M') != timestamp:
        raise ValueError('unexpected Stata timestamp value')

    raw = sha256(prefix)
    normalized = sha256(prefix[:start] + bytes(17) + prefix[end:])
    for block in iter(lambda: stream.read(1_048_576), b''):
        raw.update(block)
        normalized.update(block)
    return {'sha256': raw.hexdigest(), 'without_header_timestamp_sha256': normalized.hexdigest(),
            'timestamp': timestamp, 'timestamp_byte_offset': start, 'rows': int.from_bytes(rows, order),
            'columns': int.from_bytes(columns, order), 'release': 118}


def audit_downloads(active, result, payload):
    run = Path(result['run_root'])
    if run.resolve(strict=True) != run or run.parent != active / 'benchmark' / 'runs':
        raise ValueError('worker reported a run outside the active benchmark project')
    entries = json.loads((run / 'artifacts_index.json').read_bytes())['artifacts']
    for format, item in result['downloads'].items():
        matches = [entry for entry in entries if entry['artifact_id'] == item['artifact_id']]
        if len(matches) != 1 or matches[0]['artifact_type'] != DOWNLOAD_ARTIFACT_TYPE[format]:
            raise ValueError(f'{format} download has no unique artifact registration')
        entry = matches[0]
        path = run / entry['path']
        if path.resolve(strict=True) != path or not path.is_relative_to(run) or path.suffix != f'.{format}':
            raise ValueError(f'{format} download has an invalid registered path')
        if item['sha256'] != entry['sha256'] or item['bytes'] != path.stat().st_size:
            raise ValueError(f'{format} download bytes differ from the registered artifact')
        item['path'] = entry['path']
        if format == 'dta':
            with path.open('rb') as stream:
                info = dta_identity(stream)
            if (info['sha256'] != item['sha256'] or info['rows'] != payload['rows']
                    or info['columns'] != len(result['columns']['dta'])):
                raise ValueError('DTA bytes or dimensions differ from the downloaded artifact and export receipt')
            item.update(info)
    if set(result['downloads']) != set(FORMATS) or result['downloads']['csv']['sha256'] != payload['sha256']:
        raise ValueError('missing download or CSV download differs from the fixed CSV')
    if result['columns']['csv'] != result['columns']['dta']:
        raise ValueError('CSV and DTA column receipts disagree')
    result['run_bytes'] = sum(path.stat().st_size for path in run.rglob('*') if path.is_file())
    result['export_bytes'] = sum(item['bytes'] for item in result['downloads'].values())


def preserve_failed(active, out, label, result):
    ledger = out / 'measurements.jsonl'
    record = snapshot(active, record_id=label, metadata=result, kind='failed_export_measurement')
    append_record(ledger, record)
    saved = [entry for entry in read_records(ledger) if entry['record_id'] == label]
    if len(saved) != 1:
        raise ValueError('failed measurement journal entry missing')
    verify_tree_records(active, saved)
    archive = out / 'failed' / f'{label}.tar.gz'
    archive_info = archive_verified(active, archive, record['files'])
    with archive.open('rb') as stream:
        os.fsync(stream.fileno())
    shutil.rmtree(active)
    return archive_info


def evaluate(calibration, pairs, memory=GATE_MEMORY):
    metrics = tuple(MEMORY_METRICS[memory] if key == 'rss_bytes' else key for key in METRICS)
    lanes = {'calibration': calibration, 'baseline': pairs['A'], 'candidate': pairs['B']}
    noise = {name: baseline_noise(records, metrics=metrics) for name, records in lanes.items()}
    resources = {}
    for key in metrics:
        baseline = median(row[key] for row in pairs['A'])
        candidate = median(row[key] for row in pairs['B'])
        resources[key] = {'baseline_median': baseline, 'candidate_median': candidate, 'ratio': candidate / baseline}
    samples = calibration + pairs['A'] + pairs['B']
    content_fields = {'json': 'sha256', 'csv': 'sha256', 'dta': 'without_header_timestamp_sha256'}
    equal = {format: len({row['downloads'][format][key] for row in samples}) == 1
             for format, key in content_fields.items()}
    equal['export_receipt_columns'] = all(row['columns'] == samples[0]['columns'] for row in samples)
    failed = [f'noise:{lane}' for lane, values in noise.items() if not noise_accepted(values)]
    failed.extend(f'resource:{key}' for key, values in resources.items() if values['ratio'] > RATIO_LIMIT)
    failed.extend(f'content:{key}' for key, agrees in equal.items() if not agrees)
    return {'noise': noise, 'medians': resources, 'content_agreement': equal, 'failed': failed,
            'memory_metric': memory}


def revision(repo):
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()


def driver(out, baseline):
    from perf_fast_engine import verify_host_trace

    if Path.cwd() != ROOT:
        raise ValueError(f'launch the driver from {ROOT}')
    require_space(out)
    require_idle()
    out.mkdir(parents=True, exist_ok=False)
    report = {'status': 'running', 'calibration': [], 'pairs': {'A': [], 'B': []}, 'failed_samples': []}

    def save():
        durable_json(out / 'report.json', report)

    try:
        repos = {'A': baseline, 'B': ROOT}
        revisions = {lane: revision(repo) for lane, repo in repos.items()}
        if revisions['A'] != BASELINE:
            raise ValueError('baseline must be exact v1.9.0')
        baseline_state = baseline_source_state(baseline)
        sources = {lane: product_sources(repo) for lane, repo in repos.items()}
        builds = {lane: build_identity(repo) for lane, repo in repos.items()}
        driver_paths = [DRIVER, *(ROOT / 'scripts' / name for name in (
            'perf_1m.py', 'perf_evidence.py', 'perf_host.py', 'perf_fast_engine.py'))]
        drivers = {str(path): digest(path) for path in driver_paths}

        original_manifest = ROOT / 'local/perf-inputs/ols/source.json'
        original_manifest_sha = digest(original_manifest)
        payload = validate_family_manifest(original_manifest)
        source = Path(payload['source'])
        if (source != original_manifest.with_name('wages.csv') or payload['rows'] != 1_000_000
                or payload['case'] != 'ols' or payload['kwargs'] != family_kwargs('ols')):
            raise ValueError('expected the pre-registered 1M OLS workload')
        input_identity = source_identity(source) | {'ctime_ns': source.stat().st_ctime_ns}
        manifest = out / 'input.json'
        payload = payload | {'source_stat': source_identity(source), 'origin_source_stat': payload['source_stat'],
                             'origin_manifest': str(original_manifest), 'origin_manifest_sha256': original_manifest_sha}
        durable_json(manifest, payload)
        manifest_sha = digest(manifest)
        report.update(revisions=revisions, repositories={lane: str(repo) for lane, repo in repos.items()},
                      source_sha256=sources, builds=builds, driver_sha256=drivers, input=payload,
                      input_identity=input_identity, input_manifest_sha256=manifest_sha,
                      order=list(CALIBRATION) + AB_ORDER, noise_definition='sample standard deviation / median < 0.05',
                      resource_ratio_limit=RATIO_LIMIT, minimum_free_bytes=MIN_FREE_BYTES,
                      active_space_reserve_bytes=ACTIVE_SPACE_RESERVE, worker_timeout_seconds=TIMEOUT_SECONDS,
                      scope='full OLS worker, public ASGI attachment deliveries, one bounded SHA-256 sink; no network',
                      export_wall_definition='JSON GET; CSV and DTA each POST export plus GET attachment',
                      model_json_policy='exact response SHA-256 across all samples, including scientific fields',
                      csv_policy='exact response SHA-256 equal to the registered input CSV',
                      dta_policy='only the 17-byte ReadStat release-118 header write timestamp is masked; all other bytes exact',
                      dta_writer_reference=DTA_WRITER_REFERENCE, thresholds=NATIVE_IO_THRESHOLDS,
                      evidence_key={lane: evidence_key(repo, python=sys.executable, scope=f'perf:native-io:{lane}',
                                                       inputs={'manifest_sha256': manifest_sha, 'source_sha256': payload['sha256']},
                                                       thresholds=NATIVE_IO_THRESHOLDS)
                                    for lane, repo in repos.items()})
        save()

        def check_frozen():
            if baseline_source_state(baseline) != baseline_state:
                raise ValueError('baseline product state changed')
            if any(digest(path) != drivers[str(path)] for path in driver_paths):
                raise ValueError('benchmark driver changed')
            for lane, repo in repos.items():
                if revision(repo) != revisions[lane] or product_sources(repo) != sources[lane]:
                    raise ValueError(f'product or native binary changed in lane {lane}')
            if (source_identity(source) | {'ctime_ns': source.stat().st_ctime_ns}) != input_identity:
                raise ValueError('registered input identity changed')
            if digest(manifest) != manifest_sha or digest(original_manifest) != original_manifest_sha:
                raise ValueError('input manifest changed')

        for label in report['order']:
            active = out / 'active'
            if active.exists() or active.is_symlink():
                raise FileExistsError('previous active measurement requires review')
            check_frozen()
            require_idle()
            free = require_space(out)
            if free < MIN_FREE_BYTES + ACTIVE_SPACE_RESERVE:
                raise ValueError('insufficient disk for one active measurement above the 5 GB floor')
            lane = label[0]
            trace = out / 'host' / f'{label}.jsonl'
            code, stdout, stderr, host = monitored_worker(
                [str(ROOT / '.venv/bin/python'), str(DRIVER), '--worker', str(active), str(manifest)],
                trace, cwd=repos[lane], timeout=TIMEOUT_SECONDS,
            )
            active.mkdir(exist_ok=True)
            (active / 'stdout.log').write_text(stdout)
            (active / 'stderr.log').write_text(stderr)
            result = {'run_root': str(active / 'uncompleted')}
            try:
                result.update(json.loads((active / 'metrics.json').read_text()))
                verify_host_trace(host, trace)
                check_frozen()
                if (code or not host['valid'] or result['status'] != 'completed'
                        or result['input_sha256'] != payload['sha256'] or result['worker_repo'] != str(repos[lane])):
                    raise ValueError('worker execution, repository binding, or host verification failed')
                audit_downloads(active, result, payload)
            except Exception as error:
                result.update(status='failed', measurement_error=f'{type(error).__name__}: {error}')
            result.update(label=label, host=host, returncode=code, free_before_bytes=free,
                          version_commit=revisions[lane], input_source=str(source), input_sha256=payload['sha256'])
            result['retained_logs'] = retain_worker_logs(active, out / 'logs' / label)
            if result['status'] == 'failed':
                result['failure_archive'] = preserve_failed(active, out, label, result)
                report['failed_samples'].append(result)
                raise ValueError(f'{label} failed; see the preserved sample')
            result['retention'] = finalize_active(
                active, ledger=out / 'measurements.jsonl', record_id=label, metadata=result,
                archive_dir=out / 'representatives', version='v1.9.0' if lane == 'A' else 'v1.9.1',
                case='ols-export',
            )
            destination = report['calibration'] if label in CALIBRATION else report['pairs'][lane]
            destination.append(result)
            save()
            print(f'{label}: export {result["export_seconds"]:.4f}s; RSS {result["rss_bytes"]:,} bytes', flush=True)

        report.update(evaluate(report['calibration'], report['pairs'], memory=GATE_MEMORY))
        report['reference_memory'] = evaluate(report['calibration'], report['pairs'], memory=REFERENCE_MEMORY)
        if source_tree(ROOT)['sha256'] != report['evidence_key']['B']['source_tree']['sha256']:
            report['failed'].append('evidence:source_tree_changed_during_run')
        report['status'] = 'failed' if report['failed'] else 'passed'
    except (Exception, KeyboardInterrupt, SystemExit) as error:
        report.update(status='failed', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        save()
    return int(report['status'] != 'passed')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--baseline-repo', type=Path, default=ROOT.parent / 'eval-v190-baseline')
    parser.add_argument('--worker', nargs=2, type=Path, metavar=('ACTIVE', 'MANIFEST'), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker is not None:
        return worker(*args.worker)
    if args.out is None:
        parser.error('--out is required')
    return driver(args.out.resolve(), args.baseline_repo.resolve())


if __name__ == '__main__':
    raise SystemExit(main())
