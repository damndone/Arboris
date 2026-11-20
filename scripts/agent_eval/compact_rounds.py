"""Lossless space recovery for finished evaluation rounds, used from 2026-10-31.

Usage: compact_rounds.py local/agent-eval [running_round ...]

Tapes: gzip, verify by streaming decompression against the original SHA-256, then replace.
CSVs: APFS clone over byte-identical duplicates (same path, same content, shared blocks).
JSON records (2026-11-03): APFS transparent compression (ditto --hfsCompression), same path and bytes, so every
reader is unchanged; records and progress files were 12 GB of the finished rounds and compress to about 20%.
Every change is journaled before the original goes away. The running round is never touched.
"""
import collections, gzip, hashlib, json, os, pathlib, shutil, stat, subprocess, sys, tempfile, time

ROOT = pathlib.Path(sys.argv[1]).resolve()
SKIP = set(sys.argv[2:])  # rounds still running or still needing plain tapes
JOURNAL = ROOT / f"compaction-{time.strftime('%Y%m%d')}.jsonl"


def digest(path, opener=open):
    h = hashlib.sha256()
    with opener(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def note(**record):
    with open(JOURNAL, 'a') as out:
        out.write(json.dumps(record, ensure_ascii=False) + '\n')
        out.flush()
        os.fsync(out.fileno())


def active(path):
    return path.relative_to(ROOT).parts[0] in SKIP


saved_gz = saved_clone = 0
for path in sorted(ROOT.rglob('provider_tape.jsonl')):
    if active(path) or path.stat().st_size < 1 << 16:
        continue
    before = path.stat()
    sha = digest(path)
    target = path.with_name(path.name + '.gz')
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix='.gz.tmp')
    with os.fdopen(fd, 'wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', compresslevel=6, mtime=0) as out, open(path, 'rb') as src:
        shutil.copyfileobj(src, out, 1 << 20)
    if digest(tmp, gzip.open) != sha:
        os.unlink(tmp)
        note(kind='tape', path=str(path), status='verify_failed_kept')
        continue
    os.utime(tmp, ns=(before.st_atime_ns, before.st_mtime_ns))
    os.chmod(tmp, before.st_mode & 0o777)
    os.replace(tmp, target)
    note(kind='tape', path=str(path.relative_to(ROOT)), sha256=sha, size=before.st_size, gz_size=target.stat().st_size)
    path.unlink()
    saved_gz += before.st_size - target.stat().st_size

groups = collections.defaultdict(list)
for path in ROOT.rglob('*.csv'):
    if not active(path) and not path.is_symlink() and path.stat().st_size >= 1 << 18:
        groups[path.stat().st_size].append(path)
for size, paths in groups.items():
    if len(paths) < 2:
        continue
    by_sha = collections.defaultdict(list)
    for path in paths:
        by_sha[digest(path)].append(path)
    for sha, same in by_sha.items():
        master = same[0]
        for path in same[1:]:
            before = path.stat()
            tmp = path.with_name(path.name + '.clone.tmp')
            subprocess.run(['cp', '-c', '-p', str(master), str(tmp)], check=True)
            if digest(tmp) != sha:
                tmp.unlink()
                note(kind='csv', path=str(path), status='verify_failed_kept')
                continue
            os.utime(tmp, ns=(before.st_atime_ns, before.st_mtime_ns))
            os.chmod(tmp, before.st_mode & 0o777)
            os.replace(tmp, path)
            note(kind='csv', path=str(path.relative_to(ROOT)), sha256=sha, size=size, clone_of=str(master.relative_to(ROOT)))
            saved_clone += size
saved_json = 0
for path in sorted([*ROOT.rglob('*.json'), *ROOT.rglob('*.jsonl')]):
    if active(path) or path.is_symlink() or path == JOURNAL:
        continue
    before = path.stat()
    if before.st_size < 1 << 20 or before.st_flags & stat.UF_COMPRESSED:
        continue
    sha = digest(path)
    tmp = path.with_name(path.name + '.tc.tmp')
    subprocess.run(['ditto', '--hfsCompression', str(path), str(tmp)], check=True)
    after = tmp.stat()
    if digest(tmp) != sha or not after.st_flags & stat.UF_COMPRESSED:
        tmp.unlink()
        note(kind='json', path=str(path), status='verify_failed_or_uncompressed_kept')
        continue
    os.utime(tmp, ns=(before.st_atime_ns, before.st_mtime_ns))
    os.chmod(tmp, before.st_mode & 0o777)
    os.replace(tmp, path)
    note(kind='json', path=str(path.relative_to(ROOT)), sha256=sha, size=before.st_size,
         blocks_before=before.st_blocks * 512, blocks_after=after.st_blocks * 512)
    saved_json += (before.st_blocks - after.st_blocks) * 512
print(json.dumps({'tape_bytes_saved': saved_gz, 'csv_bytes_cloned': saved_clone, 'json_bytes_saved': saved_json,
                  'at': time.time()}))
