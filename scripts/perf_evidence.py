"""Bounded benchmark retention: durable numbers/manifests, then authorized cleanup."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile

BASELINE = '402d2d3eac3695d836255a424372930850b73a95'
MIN_FREE_BYTES = 10_000_000_000
PRIMARY_MODELS = {'ols_1', 'panel_ols_1', 'iv_2sls_1', 'did_1', 'survival_cox_1'}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(tree, *, exclude=(), hashes=True, registered_input=None):
    result = []
    known = {}
    if registered_input:
        source, sha = registered_input
        stat = source.stat()
        known[(stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)] = sha
    for path in sorted(tree.rglob('*')):
        if any(path == p or p in path.parents for p in exclude):
            continue
        if path.is_symlink():
            raise ValueError(f'symlink in evidence tree: {path}')
        if path.is_file():
            stat = path.stat()
            item = dict(path=str(path.relative_to(tree)), size=stat.st_size,
                        mtime_ns=stat.st_mtime_ns, inode=stat.st_ino, device=stat.st_dev)
            if hashes:
                identity = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
                if identity not in known:
                    known[identity] = digest(path)
                item['sha256'] = known[identity]
                if path.stat().st_mtime_ns != stat.st_mtime_ns:
                    raise ValueError(f'file changed during hashing: {path}')
            result.append(item)
    return result


def snapshot(tree, *, record_id, metadata, kind='tree', exclude=(), registered_input=None):
    tree = tree.absolute()
    files = inventory(tree, exclude=exclude, registered_input=registered_input)
    return dict(schema_version=1, record_id=record_id, kind=kind, tree=str(tree),
                observed_at=datetime.now(timezone.utc).isoformat(), metadata=metadata,
                file_count=len(files), tree_bytes=sum(f['size'] for f in files), files=files)


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def append_record(ledger, record):
    ledger.parent.mkdir(parents=True, exist_ok=True)
    if any(r['record_id'] == record['record_id'] for r in read_records(ledger)):
        raise ValueError(f'duplicate record id: {record["record_id"]}')
    value = dict(record, record_sha256=hashlib.sha256(_encoded(record)).hexdigest())
    with ledger.open('ab') as stream:
        stream.write(_encoded(value)+b'\n')
        stream.flush()
        os.fsync(stream.fileno())
    return value


def read_records(ledger):
    if not ledger.exists():
        return []
    records, seen = [], set()
    with ledger.open() as stream:
        for line in stream:
            value = json.loads(line)
            checksum = value.pop('record_sha256')
            if checksum != hashlib.sha256(_encoded(value)).hexdigest():
                raise ValueError('journal checksum mismatch')
            if value['record_id'] in seen or value['file_count'] != len(value['files']):
                raise ValueError('journal count mismatch')
            seen.add(value['record_id'])
            value['record_sha256'] = checksum
            records.append(value)
    return records


def archive_verified(tree, archive, files):
    expected = {f['path']: f for f in files}
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        raise FileExistsError(archive)
    with tarfile.open(archive, 'w:gz', compresslevel=1, dereference=True) as tar:
        for item in files:
            tar.add(tree/item['path'], arcname=item['path'], recursive=False)
    actual = {}
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar:
            if not member.isfile() or member.name not in expected:
                raise ValueError('unexpected archive member')
            with tar.extractfile(member) as stream:
                sha = hashlib.file_digest(stream, 'sha256').hexdigest()
            actual[member.name] = (member.size, sha)
    if actual != {name:(f['size'], f['sha256']) for name, f in expected.items()}:
        raise ValueError('archive verification failed')
    return dict(path=str(archive), sha256=digest(archive), verified_files=len(actual), bytes=archive.stat().st_size)


def check_legacy_root(root, parent):
    if root.is_symlink():
        raise ValueError('symlink cleanup root')
    allowed = (root.name.startswith(('fixed-ab-', 'isolated-', 'profile-')) or
               (root.name.startswith('panel-') and root.name.endswith('-trace')) or
               root.name in {'panel-evidence-profile', 'ar-verified-1m'})
    if root.parent.absolute() != parent.absolute() or not allowed or not root.is_dir():
        raise ValueError(f'root is not authorized for cleanup: {root}')


def verify_tree_records(root, records):
    expected = {}
    for record in records:
        for item in record['files']:
            path = Path(record['tree'])/item['path']
            key = str(path.relative_to(root))
            if key in expected:
                raise ValueError('duplicate file coverage')
            expected[key] = {k:v for k,v in item.items() if k != 'sha256'} | {'path': key}
    actual = {f['path']:f for f in inventory(root, hashes=False)}
    if actual != expected:
        raise ValueError(f'files changed or missing from journal: {root}')
    return len(actual)


def remove_recorded_tree(root, *, parent, ledger, expected_ids):
    check_legacy_root(root, parent)
    ids = set(expected_ids)
    records = [r for r in read_records(ledger) if r['record_id'] in ids]
    if {r['record_id'] for r in records} != ids:
        raise ValueError('journal record count mismatch before removal')
    count = verify_tree_records(root.absolute(), records)
    shutil.rmtree(root)
    return count


def aggregate_summary(value):
    if isinstance(value, (dict, list)) and len(value) > 256:
        return dict(omitted_observation_items=len(value),
                    retained_identity='original file SHA256 in files manifest')
    if isinstance(value, dict):
        return {k:aggregate_summary(v) for k,v in value.items()}
    if isinstance(value, list):
        return [aggregate_summary(v) for v in value]
    return value


def major_results(run):
    models, tests = {}, {}
    native = {path.stem:aggregate_summary(json.loads(path.read_text()))
              for path in sorted((run/'model_results').glob('checks_*.json'))}
    if native:
        tests['native_checks'] = native
    for path in sorted((run/'model_results').glob('*.json')):
        if path.stem not in PRIMARY_MODELS:
            continue
        packet = json.loads(path.read_text())
        models[path.stem] = aggregate_summary(packet)
        coefficients = packet.get('coefficients', {})
        if isinstance(coefficients, dict):
            tests[path.stem] = {term:dict(estimate_over_se=c['estimate']/c['std_error'],
                                         definition='derived from reported estimate / std_error')
                                for term, c in coefficients.items()
                                if isinstance(c, dict) and c.get('estimate') is not None and c.get('std_error')}
    return models, tests


def _version(root, project, report):
    label = project.parent.name
    lane = label[0] if label.startswith(('A', 'B')) else None
    if lane and report.get('revisions'):
        role = 'baseline' if lane == 'A' else 'candidate'
        return ('v1.9.0' if lane == 'A' else 'v1.9.1', report['revisions'][role], 'ab_report')
    if root.name == 'profile-baseline':
        return 'v1.9.0', BASELINE, 'historical_baseline_profile'
    return 'v1.9.1', None, 'historical_commit_not_recorded'


def migrate_legacy(parent, destination):
    """Only the human-authorized direct children; untouched siblings stay put."""
    parent, destination = parent.absolute(), destination.absolute()
    destination.mkdir(parents=True, exist_ok=True)
    ledger = destination/'legacy-measurements.jsonl'
    if ledger.exists():
        raise FileExistsError('Preserve the previous migration; inspect its completion report before resuming')
    free_before = shutil.disk_usage(parent).free
    roots = []
    for root in sorted(parent.iterdir()):
        if root.is_dir() or root.is_symlink():
            try:
                check_legacy_root(root, parent)
            except ValueError:
                if root.is_symlink() and root.name.startswith(('fixed-ab-', 'isolated-', 'profile-')):
                    raise
                continue
            roots.append(root)
    groups, all_records, representatives = {}, [], {}
    for root in roots:
        summary = root/'ab-results.json'
        report = json.loads(summary.read_text()) if summary.exists() else {}
        projects = sorted({p.parent.parent for p in root.glob('**/runs/*') if p.is_dir()})
        group = []
        for project in projects:
            runs = sorted(p for p in (project/'runs').iterdir() if p.is_dir())
            if len(runs) != 1:
                raise ValueError('legacy project must contain exactly one benchmark run')
            run = runs[0]
            metrics = project.parent/'metrics.json'
            metadata = json.loads(metrics.read_text()) if metrics.exists() else {}
            manifest = run/'run_manifest.json'
            manifest = json.loads(manifest.read_text()) if manifest.exists() else {}
            case = metadata.get('case') or {'panel_ols':'panel','iv_2sls':'iv','survival_cox':'cox'}.get(manifest.get('requested_model_type'), manifest.get('requested_model_type'))
            if case is None and project.relative_to(root).parts[0] in {'panel','iv','did','cox','ols'}:
                case = project.relative_to(root).parts[0]
            release, commit, origin = _version(root, project, report)
            models, tests = major_results(run)
            metadata.update(case=case, version=release, version_commit=commit, commit_source=origin,
                            seconds=metadata.get('seconds'), ru_maxrss=metadata.get('ru_maxrss'),
                            tracemalloc_peak_bytes=metadata.get('tracemalloc_peak_bytes'),
                            candidate_diff_sha256=report.get('candidate_diff_sha256'),
                            status=metadata.get('status',manifest.get('status','interrupted_or_unrecorded')),
                            run_root=str(run), major_results=models, test_statistics=tests,
                            historical_rss_acceptance='invalid; retained only as raw measurement',
                            run_bytes=sum(p.stat().st_size for p in run.rglob('*') if p.is_file()))
            record = snapshot(project, record_id=str(project.relative_to(parent)), metadata=metadata, kind='workflow_run')
            append_record(ledger, record)
            group.append(record)
            if case and metadata['status'] == 'completed':
                key = (case, release)
                rank = (3 if root.name == 'isolated-v2-panel-time' else 2 if root.name == 'fixed-ab-3' else 1)
                if key not in representatives or rank > representatives[key][0]:
                    representatives[key] = (rank, record, run)
        if root.name == 'ar-verified-1m':
            for path in sorted(root.glob('*.json')):
                value = json.loads(path.read_text())
                if 'seconds' in value and 'result' in value:
                    record = dict(schema_version=1, record_id=str(path.relative_to(parent)), kind='ar_timing',
                                  tree=str(root), observed_at=datetime.now(timezone.utc).isoformat(),
                                  metadata=value | {'version_commit':None, 'commit_source':'historical_commit_not_recorded'},
                                  file_count=0, tree_bytes=0, files=[])
                    append_record(ledger, record)
                    group.append(record)
        control = snapshot(root, record_id=root.name+'/controls', metadata=report,
                           kind='legacy_controls', exclude=projects)
        append_record(ledger, control)
        group.append(control)
        # Preserve logs, scripts, small control JSON and profiler data separately
        # from the journal so all original reproduction commands remain usable.
        for item in control['files']:
            source = root/item['path']
            if source.suffix == '.csv':
                continue  # fixed input is retained separately before cleanup
            target = destination/'controls'/root.name/item['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if digest(target) != item['sha256']:
                raise ValueError('retained control digest mismatch')
        verify_tree_records(root, group)
        groups[root] = [r['record_id'] for r in group]
        all_records.extend(group)
    saved = read_records(ledger)
    if len(saved) != len(all_records):
        raise ValueError('global journal count mismatch')
    verified_files = sum(r['file_count'] for r in saved)
    archives = {}
    for (case, release), (_, record, run) in sorted(representatives.items()):
        files = [dict(f, path=str(Path(f['path']).relative_to(run.relative_to(Path(record['tree'])))))
                 for f in record['files'] if (Path(record['tree'])/f['path']).is_relative_to(run)]
        archive = destination/'representatives'/f'{release}-{case}.tar.gz'
        archives[f'{release}:{case}'] = archive_verified(run, archive, files) | {'record_id':record['record_id']}
    # Every CSV outside run/project trees must have its fixed source preserved.
    # The caller creates canonical inputs before entering this destructive step.
    canonical = parent.parent/'perf-inputs'
    input_digests = {digest(p) for p in canonical.rglob('*.csv')} if canonical.exists() else set()
    for record in saved:
        if record['kind'] == 'legacy_controls':
            for item in record['files']:
                if item['path'].endswith('.csv') and item['sha256'] not in input_digests:
                    raise ValueError(f'unpreserved fixed input: {item["path"]}')
    report = dict(jsonl=str(ledger), records=len(saved), workflow_runs=sum(r['kind']=='workflow_run' for r in saved),
                  ar_timings=sum(r['kind']=='ar_timing' for r in saved), verified_file_count=verified_files,
                  logical_bytes=sum(r['tree_bytes'] for r in saved), roots=[str(p) for p in roots],
                  representative_archives=archives, free_before_bytes=free_before)
    (destination/'cleanup-preflight.json').write_text(json.dumps(report, indent=2))
    for root, ids in groups.items():
        remove_recorded_tree(root, parent=parent, ledger=ledger, expected_ids=ids)
    report.update(free_after_bytes=shutil.disk_usage(parent).free, deleted_roots=len(roots))
    report['free_space_increase_bytes'] = report['free_after_bytes']-free_before
    (destination/'cleanup-result.json').write_text(json.dumps(report, indent=2))
    return report


def require_space(path):
    while not path.exists():
        path = path.parent
    free = shutil.disk_usage(path).free
    if free < MIN_FREE_BYTES:
        raise SystemExit(f'Only {free/1e9:.3f} GB free; 10 GB minimum. Measurement not started.')
    return free


def finalize_active(active, *, ledger, record_id, metadata, archive_dir, version, case):
    if active.name != 'active' or active.is_symlink():
        raise ValueError('only the designated active benchmark tree can be removed')
    run = Path(metadata['run_root'])
    if not run.is_relative_to(active):
        raise ValueError('run root outside active benchmark tree')
    models, tests = major_results(run)
    metadata = metadata | {'version':version, 'case':case, 'major_results':models, 'test_statistics':tests}
    registered_input = ((Path(metadata['input_source']), metadata['input_sha256'])
                        if metadata.get('input_source') else None)
    record = snapshot(active, record_id=record_id, metadata=metadata, kind='workflow_run',
                      registered_input=registered_input)
    append_record(ledger, record)
    saved = [r for r in read_records(ledger) if r['record_id'] == record_id]
    if len(saved) != 1:
        raise ValueError('active journal count mismatch')
    verify_tree_records(active, saved)
    archive = archive_dir/f'{version}-{case}.tar.gz'
    existing = archive.exists()
    if metadata.get('status') != 'failed' and not archive.exists():
        run_files = [dict(f, path=str(Path(f['path']).relative_to(run.relative_to(active))))
                     for f in record['files'] if (active/f['path']).is_relative_to(run)]
        archive_verified(run, archive, run_files)
    shutil.rmtree(active)
    return dict(journal_record_id=record_id, recorded_files=record['file_count'],
                recorded_tree_bytes=record['tree_bytes'], representative=str(archive),
                representative_origin='existing_release_sample' if existing else 'this_run')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--migrate-20261020', action='store_true', required=True)
    args = parser.parse_args()
    base = Path.cwd()/'local/perf-regression-2026-10-20'
    print(json.dumps(migrate_legacy(base, Path.cwd()/'local/perf-evidence'), indent=2))


if __name__ == '__main__':
    main()
